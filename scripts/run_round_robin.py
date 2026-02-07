#!/usr/bin/env python3
"""
Manifest-based round-robin tournament runner.

Three subcommands:
  generate  - Create match manifest from model list
  run       - Execute matches from manifest (resumable)
  status    - Show tournament progress

Examples:
  # Generate a tournament manifest
  python3 scripts/run_round_robin.py generate --models DeepSeek-Reasoner Gemini-3-Flash GPT-5-Mini --games-per-pair 3

  # Run the tournament (resumable)
  python3 scripts/run_round_robin.py run --manifest logs/{tournament-name}/manifest.json --concurrent 6 --per-model-concurrent 3

  # Check status
  python3 scripts/run_round_robin.py status --manifest logs/{tournament-name}/manifest.json

  # Run with mock players (for testing)
  python3 scripts/run_round_robin.py run --manifest logs/{tournament-name}/manifest.json --mock

Architecture:
  - Player Pool: Creates `per_model_concurrent` reusable player instances per model
  - Workers acquire players from pools, run matches, then return them
  - WebSocket connections are reused across matches for efficiency
  - Each match gets its own MatchLogger set via prepare_for_battle()
"""

import asyncio
import argparse
import itertools
import json
import os
import random
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from poke_env import AccountConfiguration

from src.config import ModelConfig, load_models_from_yaml, find_model
from src.env_manager import load_env_file, has_api_key
from src.team_pool import get_team_pool
from src.llm_player import LLMPlayer, CUSTOM_SERVER_CONFIG
from src.mock_player import MockPlayer
from src.battle_logger import BattleLogger

load_env_file()

BATTLE_FORMAT = "gen4ou"


class MatchLogger(BattleLogger):
    """
    BattleLogger subclass that writes files flat into a match directory.
    One instance per match, pointed at match-XXXX/.
    """

    def __init__(self, match_dir: str, enabled: bool = True):
        self.enabled = enabled
        self.log_dir = Path(match_dir)
        self.battles_dir = self.log_dir  # Not used, but required by parent
        self._battle_state: dict[str, dict] = {}

        if self.enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True)

    def _battle_dir(self, battle_id: str) -> Path:
        """Write all files directly to log_dir (the match directory)."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        return self.log_dir

    def log_action(
        self,
        battle_id: str,
        player_id: str,
        turn: int,
        observation: str,
        state: str,
        raw_response: str,
        tool_calls: list[dict],
        parsed: dict,
        tokens: dict,
        latency_ms: int,
        confidence: str = "",
    ) -> None:
        """Append action and update metadata with current_turn."""
        super().log_action(
            battle_id, player_id, turn, observation, state,
            raw_response, tool_calls, parsed, tokens, latency_ms, confidence
        )

        if not self.enabled:
            return

        # Update metadata with current turn for live tracking
        meta_path = self.log_dir / "metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path) as f:
                    metadata = json.load(f)
                metadata["current_turn"] = turn
                with open(meta_path, "w") as f:
                    json.dump(metadata, f, indent=2)
            except Exception:
                pass


def generate_manifest(
    models: list[ModelConfig],
    games_per_pair: int,
    team_pool,
    log_dir: str = "logs",
    tournament_name: Optional[str] = None,
) -> tuple[dict, str]:
    """Generate a tournament manifest with all matches.
    
    Returns (manifest, manifest_path).
    """
    
    if tournament_name is None:
        tournament_name = f"round-robin-{datetime.now().strftime('%Y-%m-%d-%H%M')}"
    
    # Create tournament directory
    tournament_dir = Path(log_dir) / tournament_name
    tournament_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate all pairings
    pairs = list(itertools.combinations(models, 2))
    
    matches = []
    match_id = 0
    
    # Track team assignments per model to ensure rotation
    model_team_idx = {m.name: 0 for m in models}
    team_names = team_pool.team_names
    num_teams = len(team_names)
    
    for model_a, model_b in pairs:
        for game_num in range(games_per_pair):
            match_id += 1

            # Team rotation: each model advances through teams across all its matches.
            # When both models land on the same team (counters are equal mod num_teams),
            # shift model_b by 1 for this match only — model_b's counter still advances
            # normally, so its rotation stays clean for future matches.
            team_a_idx = model_team_idx[model_a.name] % num_teams
            team_b_idx = model_team_idx[model_b.name] % num_teams

            if team_a_idx == team_b_idx:
                team_b_idx = (team_b_idx + 1) % num_teams
            
            team_a_name = team_names[team_a_idx]
            team_b_name = team_names[team_b_idx]
            
            # Advance rotation
            model_team_idx[model_a.name] += 1
            model_team_idx[model_b.name] += 1
            
            # Create match directory
            match_dir_name = f"match-{match_id:04d}"
            match_dir = tournament_dir / match_dir_name
            match_dir.mkdir(parents=True, exist_ok=True)
            
            matches.append({
                "id": match_id,
                "model_a": model_a.name,
                "model_b": model_b.name,
                "team_a": team_a_name,
                "team_b": team_b_name,
                "status": "pending",
                "winner": None,
                "error": None,
                "attempts": 0,
                "battle_tag": None,
            })
    
    manifest = {
        "tournament": {
            "name": tournament_name,
            "format": BATTLE_FORMAT,
            "models": [m.name for m in models],
            "games_per_pair": games_per_pair,
            "created_at": datetime.now().isoformat(),
        },
        "matches": matches,
    }
    
    # Write manifest inside tournament directory
    manifest_path = str(tournament_dir / "manifest.json")
    write_manifest(manifest, manifest_path)
    
    return manifest, manifest_path


def write_manifest(manifest: dict, path: str) -> None:
    """Write manifest atomically (write to .tmp then rename)."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(manifest, f, indent=2)
    os.replace(tmp_path, path)


def load_manifest(path: str) -> dict:
    """Load manifest from file."""
    with open(path) as f:
        return json.load(f)


def create_player_pools(
    models_by_name: dict[str, ModelConfig],
    per_model_concurrent: int,
    use_mock: bool = False,
    mock_error_rate: float = 0.0,
) -> dict[str, asyncio.Queue]:
    """
    Create a pool of reusable player instances per model.
    
    Each model gets `per_model_concurrent` player instances stored in an asyncio.Queue.
    Players are created with team=None (set later via prepare_for_battle()).
    
    Returns dict mapping model name -> Queue of player instances.
    """
    pools = {}
    max_name = 18 - 3  # room for "-{i}" suffix (e.g., "-0", "-1")
    
    for model_name, model_config in models_by_name.items():
        pool = asyncio.Queue()
        
        for i in range(per_model_concurrent):
            # Truncate and strip trailing punctuation that confuses showdown
            base_name = model_name[:max_name].rstrip(".-_")
            username = f"{base_name}-{i}"
            
            if use_mock:
                player = MockPlayer(
                    account_configuration=AccountConfiguration(username, None),
                    battle_format=BATTLE_FORMAT,
                    team=None,
                    server_configuration=CUSTOM_SERVER_CONFIG,
                    error_rate=mock_error_rate,
                    verbose=True,
                )
            else:
                player = LLMPlayer(
                    account_configuration=AccountConfiguration(username, None),
                    model=model_config.model,
                    temperature=model_config.temperature,
                    max_tokens=model_config.max_tokens,
                    timeout=model_config.timeout,
                    battle_format=BATTLE_FORMAT,
                    team=None,
                    server_configuration=CUSTOM_SERVER_CONFIG,
                )
            
            pool.put_nowait(player)
        
        pools[model_name] = pool
    
    return pools


async def cleanup_player(player, expected_opponent_username: Optional[str] = None):
    """
    Ensure player is in a clean state (not stuck in old battles).
    If expected_opponent_username is provided, preserve battles against that opponent (resume).
    Forfeit and delete all others.
    """
    # Wait for server to sync battle state to this player
    # This is important because when a player connects, the server sends info about
    # their active battles, but this happens asynchronously
    await asyncio.sleep(1.5)
    
    # We need to access player.battles safely
    # If the player hasn't connected yet, this might be empty, but that's fine 
    # (if not connected, no battles on server could be tracked by this instance yet).
    if not hasattr(player, "battles"):
        return

    # Debug: show what battles this player has
    if player.battles:
        print(f"[{player.username}] Has {len(player.battles)} tracked battles: {list(player.battles.keys())}")
    else:
        print(f"[{player.username}] No tracked battles (battles dict is empty)")

    battles_to_cleanup = []

    for battle_tag, battle in list(player.battles.items()):
        if battle.finished:
            # Clean up finished battles (just delete locally)
            battles_to_cleanup.append((battle_tag, False))  # (tag, needs_forfeit)
            continue
            
        opponent = battle.opponent_username
        
        # If this is our expected match, preserve it for resumption
        if expected_opponent_username and opponent == expected_opponent_username:
            continue
            
        print(f"[{player.username}] Forfeiting orphan battle {battle_tag} vs {opponent}")
        battles_to_cleanup.append((battle_tag, True))  # (tag, needs_forfeit)
    
    # Forfeit active battles on the server, then delete from local tracking
    for battle_tag, needs_forfeit in battles_to_cleanup:
        try:
            if needs_forfeit:
                # Send forfeit to server
                await player.forfeit(battle_tag)
                # Brief wait for server to process
                await asyncio.sleep(0.5)
            # Delete from local tracking
            del player.battles[battle_tag]
        except Exception as e:
            print(f"[{player.username}] Error cleaning up {battle_tag}: {e}")
            # Still try to delete locally
            try:
                del player.battles[battle_tag]
            except KeyError:
                pass


async def run_match(
    match: dict,
    models_by_name: dict[str, ModelConfig],
    team_pool,
    match_dir: Path,
    player_a,
    player_b,
    force_new: bool = False,
) -> dict:
    """
    Run a single match using pre-created players and return updated match dict.
    
    Players are prepared for this match via prepare_for_battle() before calling.
    Winner is determined via battle.won/battle.lost BEFORE reset_battles().
    
    Args:
        force_new: If True, forfeit any existing battle vs opponent and start fresh.
                   Use True when resuming from "pending" status (fresh start).
                   Use False when resuming from "running" status (continue existing).
    """
    model_a = models_by_name[match["model_a"]]
    model_b = models_by_name[match["model_b"]]
    
    # Create per-match logger
    logger = MatchLogger(match_dir=str(match_dir), enabled=True)
    
    # Get teams
    team_a_idx = team_pool.team_names.index(match["team_a"])
    team_b_idx = team_pool.team_names.index(match["team_b"])
    team_a = team_pool.teams[team_a_idx]
    team_b = team_pool.teams[team_b_idx]
    
    # Prepare players for this match
    player_a.prepare_for_battle(team_a, match["team_a"], logger)
    player_b.prepare_for_battle(team_b, match["team_b"], logger)
    
    if force_new:
        # Forfeit ALL existing battles (including vs the opponent) to start fresh
        await cleanup_player(player_a, expected_opponent_username=None)
        await cleanup_player(player_b, expected_opponent_username=None)
    else:
        # Cleanup orphan battles, but allow resuming battle vs each other
        await cleanup_player(player_a, expected_opponent_username=player_b.username)
        await cleanup_player(player_b, expected_opponent_username=player_a.username)
    
    # Clear and re-register opponents
    player_a.clear_opponent_registry()
    player_b.clear_opponent_registry()
    player_a.register_opponent(player_b.username, model_b.model, player_id=player_b.player_id)
    player_b.register_opponent(player_a.username, model_a.model, player_id=player_a.player_id)
    
    # Check if we are ALREADY battling each other (only possible if force_new=False)
    existing_battle_tag = None
    if not force_new:
        for tag, battle in player_a.battles.items():
            if battle.opponent_username == player_b.username and not battle.finished:
                existing_battle_tag = tag
                break
            
    if existing_battle_tag:
        print(f"[{player_a.username}] Resuming existing battle {existing_battle_tag} vs {player_b.username}")
        # Wait for this battle to finish
        # We assume the agent loop is running implicitly because poke-env dispatches messages
        # to choose_move() as long as the player is connected.
        battle = player_a.battles[existing_battle_tag]
        while not battle.finished:
            await asyncio.sleep(1.0)
    else:
        # Run new battle
        await player_a.battle_against(player_b, n_battles=1)
    
    # Get battle tag and determine winner BEFORE reset_battles()
    
    # Get battle tag and determine winner BEFORE reset_battles()
    battle_tag = None
    winner = None
    
    if player_a.battles:
        battle_tag = list(player_a.battles.keys())[0]
        battle = player_a.battles[battle_tag]
        if battle.won:
            winner = model_a.name
        elif battle.lost:
            winner = model_b.name
    
    # Reset battles for reuse (clears battle history)
    player_a.reset_battles()
    player_b.reset_battles()
    
    return {
        **match,
        "status": "completed",
        "winner": winner,
        "battle_tag": battle_tag,
    }


async def run_tournament(
    manifest_path: str,
    concurrent: int = 6,
    per_model_concurrent: int = 3,
    use_mock: bool = False,
    mock_error_rate: float = 0.0,
    max_retries: int = 3,
    models_config: str = "config/models.yaml",
) -> None:
    """
    Run tournament from manifest with dynamic load balancing.
    """
    manifest = load_manifest(manifest_path)

    # Load models
    try:
        all_models = load_models_from_yaml(models_config)
    except Exception as e:
        print(f"Error loading models.yaml: {e}")
        return
    
    models_by_name = {}
    for model_name in manifest["tournament"]["models"]:
        model = find_model(model_name, all_models)
        if model:
            models_by_name[model_name] = model
        else:
            print(f"Error: Model '{model_name}' not found in config/models.yaml")
            return
    
    # Validate API keys (unless using mock)
    if not use_mock:
        for name, model in models_by_name.items():
            if not has_api_key(model.model):
                print(f"Error: No API key for {name} ({model.model})")
                return
    
    # Derive tournament directory from manifest path
    tournament_dir = Path(manifest_path).parent
    
    # Load teams
    team_pool = get_team_pool("Raw-Teams")
    
    # Create player pools (reusable player instances per model)
    player_pools = create_player_pools(
        models_by_name, per_model_concurrent, use_mock, mock_error_rate
    )
    
    # Filter to matches that need processing:
    # - "pending": new match, start fresh
    # - "running": interrupted match, try to resume
    # - "failed": retry (start fresh)
    pending_matches = [
        m for m in manifest["matches"]
        if m["status"] in ("pending", "running", "failed") and m["attempts"] < max_retries
    ]
    
    if not pending_matches:
        print("No matches to run. All completed or max retries exceeded.")
        return
    
    print(f"\n{'='*60}")
    print(f"Tournament: {manifest['tournament']['name']}")
    print(f"Models: {', '.join(manifest['tournament']['models'])}")
    print(f"Matches to run: {len(pending_matches)}")
    print(f"Concurrency: {concurrent} global, {per_model_concurrent} per model")
    if use_mock:
        print(f"Mode: MOCK (error_rate={mock_error_rate})")
    print(f"{'='*60}\n")
    
    # --- Dynamic Scheduler State ---
    active_tasks = set()
    current_load = {name: 0 for name in models_by_name}
    manifest_lock = asyncio.Lock()
    shutdown_requested = False
    
    def handle_sigint(signum, frame):
        nonlocal shutdown_requested
        print("\n\nShutdown requested. Saving state...")
        shutdown_requested = True
    
    signal.signal(signal.SIGINT, handle_sigint)

    def get_best_match(candidates: list[dict], load: dict[str, int]) -> Optional[dict]:
        """
        Select the match that minimizes the maximum load on any single model.
        Returns None if no match can be scheduled within limits.
        """
        best_match = None
        min_max_load = float('inf')
        
        # We only consider matches where BOTH models are under the limit
        valid_candidates = []
        for match in candidates:
            a, b = match["model_a"], match["model_b"]
            if load[a] < per_model_concurrent and load[b] < per_model_concurrent:
                valid_candidates.append(match)
        
        if not valid_candidates:
            return None
            
        # Optimization: Sort by sum of loads (prefer busier models if under limit? 
        # Actually we want to balance load, so we prefer models with LOWER current load)
        # Strategy: Pick match where max(load_a, load_b) is minimized.
        
        candidates_with_scores = []
        for match in valid_candidates:
            a, b = match["model_a"], match["model_b"]
            # Projected load if we pick this match
            score = max(load[a], load[b])
            candidates_with_scores.append((score, match))
        
        # Sort by score (asc), then randomize for tie-breaking
        random.shuffle(candidates_with_scores)
        candidates_with_scores.sort(key=lambda x: x[0])
        
        return candidates_with_scores[0][1]

    async def worker(match: dict):
        nonlocal manifest
        
        model_a = match["model_a"]
        model_b = match["model_b"]
        original_status = match["status"]  # Track if this was pending vs failed/running
        
        match_desc = f"#{match['id']}: {model_a} vs {model_b}"
        print(f"[START] {match_desc}")
        
        # Acquire players from pools
        player_a = await player_pools[model_a].get()
        player_b = await player_pools[model_b].get()
        
        # Mark as running
        async with manifest_lock:
            for m in manifest["matches"]:
                if m["id"] == match["id"]:
                    m["status"] = "running"
                    m["attempts"] += 1
                    break
            write_manifest(manifest, manifest_path)

        try:
            # Compute match directory path
            match_dir = tournament_dir / f"match-{match['id']:04d}"
            
            # "pending" or "failed" = start fresh, "running" = try to resume
            force_new = (original_status != "running")
            
            result = await run_match(
                match, models_by_name, team_pool, match_dir,
                player_a, player_b, force_new=force_new
            )
            
            async with manifest_lock:
                for i, m in enumerate(manifest["matches"]):
                    if m["id"] == match["id"]:
                        manifest["matches"][i] = result
                        break
                write_manifest(manifest, manifest_path)
            
            print(f"[DONE]  {match_desc} -> {result['winner'] or 'draw'}")
            
        except Exception as e:
            async with manifest_lock:
                for m in manifest["matches"]:
                    if m["id"] == match["id"]:
                        m["status"] = "failed"
                        m["error"] = str(e)[:200]
                        break
                write_manifest(manifest, manifest_path)
            
            print(f"[FAIL]  {match_desc}: {e}")
            
            # Try to reset battles before returning to pool
            try:
                player_a.reset_battles()
            except Exception:
                pass
            try:
                player_b.reset_battles()
            except Exception:
                pass
            
        finally:
            # Return players to their pools
            player_pools[model_a].put_nowait(player_a)
            player_pools[model_b].put_nowait(player_b)
            
            # Update load tracking
            current_load[model_a] -= 1
            current_load[model_b] -= 1

    # Main Supervisor Loop
    while (pending_matches or active_tasks) and not shutdown_requested:
        # Spawn new tasks if slots are available
        while len(active_tasks) < concurrent and pending_matches:
            match = get_best_match(pending_matches, current_load)
            
            if match:
                pending_matches.remove(match)
                
                # Update load immediately
                current_load[match["model_a"]] += 1
                current_load[match["model_b"]] += 1
                
                task = asyncio.create_task(worker(match))
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)
            else:
                # No valid match found (all pending blocked by per-model limits)
                break
        
        if not active_tasks and not pending_matches:
            break
            
        # Wait for at least one task to finish before checking again
        # OR wait a short interval to check for shutdown
        if active_tasks:
            done, pending = await asyncio.wait(
                active_tasks, 
                return_when=asyncio.FIRST_COMPLETED,
                timeout=1.0
            )
            
    # Wait for remaining tasks if shutting down
    if active_tasks:
        print(f"\nWaiting for {len(active_tasks)} active matches to finish...")
        await asyncio.gather(*active_tasks, return_exceptions=True)
    
    # Print summary
    manifest = load_manifest(manifest_path)
    print_status(manifest)


def print_status(manifest: dict) -> None:
    """Print tournament status summary."""
    matches = manifest["matches"]
    
    completed = [m for m in matches if m["status"] == "completed"]
    pending = [m for m in matches if m["status"] == "pending"]
    failed = [m for m in matches if m["status"] == "failed"]
    running = [m for m in matches if m["status"] == "running"]
    
    print(f"\n{'='*60}")
    print(f"Tournament: {manifest['tournament']['name']}")
    print(f"{'='*60}")
    print(f"Completed: {len(completed)}/{len(matches)}")
    print(f"Pending:   {len(pending)}")
    print(f"Failed:    {len(failed)}")
    print(f"Running:   {len(running)}")
    
    # Win rates per model
    if completed:
        print(f"\n{'Model':<25} {'Wins':<8} {'Losses':<8} {'Win Rate':<10}")
        print("-" * 55)
        
        model_stats = {}
        for m in completed:
            if m["model_a"] not in model_stats:
                model_stats[m["model_a"]] = {"wins": 0, "losses": 0}
            if m["model_b"] not in model_stats:
                model_stats[m["model_b"]] = {"wins": 0, "losses": 0}
            
            if m["winner"] == m["model_a"]:
                model_stats[m["model_a"]]["wins"] += 1
                model_stats[m["model_b"]]["losses"] += 1
            elif m["winner"] == m["model_b"]:
                model_stats[m["model_b"]]["wins"] += 1
                model_stats[m["model_a"]]["losses"] += 1
        
        sorted_stats = sorted(
            model_stats.items(),
            key=lambda x: x[1]["wins"] / (x[1]["wins"] + x[1]["losses"]) if (x[1]["wins"] + x[1]["losses"]) > 0 else 0,
            reverse=True
        )
        
        for name, stats in sorted_stats:
            total = stats["wins"] + stats["losses"]
            wr = (stats["wins"] / total * 100) if total > 0 else 0
            print(f"{name:<25} {stats['wins']:<8} {stats['losses']:<8} {wr:.1f}%")
    
    # List failed matches
    if failed:
        print(f"\nFailed matches:")
        for m in failed:
            print(f"  #{m['id']}: {m['model_a']} vs {m['model_b']} - {m.get('error', 'unknown error')[:50]}")
    
    print("=" * 60)


def cmd_generate(args):
    """Handle 'generate' subcommand."""
    # Load models config
    try:
        all_models = load_models_from_yaml(args.models_config)
    except Exception as e:
        print(f"Error loading {args.models_config}: {e}")
        sys.exit(1)
    
    # Resolve requested models
    models = []
    for name in args.model_names:
        model = find_model(name, all_models)
        if model:
            models.append(model)
        else:
            print(f"Warning: Model '{name}' not found in config, skipping")
    
    if len(models) < 2:
        print("Error: Need at least 2 models for a tournament")
        sys.exit(1)
    
    # Validate API keys
    print("\nValidating API keys:")
    valid_models = []
    for m in models:
        if has_api_key(m.model):
            print(f"  ✓ {m.name}")
            valid_models.append(m)
        else:
            print(f"  ✗ {m.name} (no API key)")
    
    if len(valid_models) < 2:
        print("\nError: Need at least 2 models with valid API keys")
        sys.exit(1)
    
    # Load team pool
    team_pool = get_team_pool(args.teams_dir)
    
    # Check if tournament directory already exists
    tournament_name = args.name or f"round-robin-{datetime.now().strftime('%Y-%m-%d-%H%M')}"
    tournament_dir = Path(args.log_dir) / tournament_name
    if tournament_dir.exists() and not args.force:
        print(f"\nError: {tournament_dir} already exists. Use --force to overwrite.")
        sys.exit(1)
    
    # Generate manifest
    manifest, manifest_path = generate_manifest(
        models=valid_models,
        games_per_pair=args.games_per_pair,
        team_pool=team_pool,
        log_dir=args.log_dir,
        tournament_name=args.name,
    )
    
    n_matches = len(manifest["matches"])
    n_models = len(valid_models)
    
    print(f"\nGenerated tournament manifest:")
    print(f"  Models: {n_models}")
    print(f"  Games per pair: {args.games_per_pair}")
    print(f"  Total matches: {n_matches}")
    print(f"  Manifest: {manifest_path}")


def cmd_run(args):
    """Handle 'run' subcommand."""
    if not Path(args.manifest).exists():
        print(f"Error: Manifest not found: {args.manifest}")
        sys.exit(1)
    
    asyncio.run(run_tournament(
        manifest_path=args.manifest,
        concurrent=args.concurrent,
        per_model_concurrent=args.per_model_concurrent,
        use_mock=args.mock,
        mock_error_rate=args.error_rate,
        max_retries=args.max_retries,
        models_config=args.models_config,
    ))


def cmd_status(args):
    """Handle 'status' subcommand."""
    if not Path(args.manifest).exists():
        print(f"Error: Manifest not found: {args.manifest}")
        sys.exit(1)
    
    manifest = load_manifest(args.manifest)
    print_status(manifest)


def main():
    parser = argparse.ArgumentParser(
        description="Manifest-based round-robin tournament runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")
    
    # generate subcommand
    gen_parser = subparsers.add_parser("generate", help="Generate tournament manifest")
    gen_parser.add_argument("--models", dest="model_names", nargs="+", required=True,
                           help="Model names to include")
    gen_parser.add_argument("--games-per-pair", type=int, default=3,
                           help="Number of games per model pair (default: 3)")
    gen_parser.add_argument("--log-dir", default="logs",
                           help="Base log directory (default: logs)")
    gen_parser.add_argument("--name", help="Tournament name (default: auto-generated)")
    gen_parser.add_argument("--models-config", default="config/models.yaml",
                           help="Path to models YAML config")
    gen_parser.add_argument("--teams-dir", default="Raw-Teams",
                           help="Directory containing team files")
    gen_parser.add_argument("--force", "-f", action="store_true",
                           help="Overwrite existing tournament directory")
    gen_parser.set_defaults(func=cmd_generate)
    
    # run subcommand
    run_parser = subparsers.add_parser("run", help="Run tournament from manifest")
    run_parser.add_argument("--manifest", "-m", default="tournament.json",
                           help="Path to tournament manifest")
    run_parser.add_argument("--concurrent", "-c", type=int, default=6,
                           help="Max concurrent matches (default: 6)")
    run_parser.add_argument("--per-model-concurrent", type=int, default=3,
                           help="Max concurrent matches per model (default: 3)")
    run_parser.add_argument("--mock", action="store_true",
                           help="Use mock players (no API calls)")
    run_parser.add_argument("--error-rate", type=float, default=0.0,
                           help="Mock error injection rate (0-1, default: 0)")
    run_parser.add_argument("--max-retries", type=int, default=3,
                           help="Max retries for failed matches (default: 3)")
    run_parser.add_argument("--models-config", default="config/models.yaml",
                           help="Path to models YAML config")
    run_parser.set_defaults(func=cmd_run)
    
    # status subcommand
    status_parser = subparsers.add_parser("status", help="Show tournament status")
    status_parser.add_argument("--manifest", "-m", default="tournament.json",
                              help="Path to tournament manifest")
    status_parser.set_defaults(func=cmd_status)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
