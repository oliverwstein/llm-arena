#!/usr/bin/env python3
"""
Manifest-based round-robin tournament runner.

Three subcommands:
  generate  - Create match manifest from model list
  run       - Execute matches from manifest (resumable)
  status    - Show tournament progress

Examples:
  # Generate a tournament manifest
  python3 scripts/run_round_robin.py generate --models Grok-4 DeepSeek-Reasoner Gemini-3-Flash GPT-5-Mini --games-per-pair 3

  # Run the tournament (resumable)
  python3 scripts/run_round_robin.py run --manifest logs/{tournament-name}/manifest.json --concurrent 6 --per-model-concurrent 3

  # Check status
  python3 scripts/run_round_robin.py status --manifest logs/{tournament-name}/manifest.json

  # Run with mock players (for testing)
  python3 scripts/run_round_robin.py run --manifest logs/{tournament-name}/manifest.json --mock

PLAN FOR REFACTORING:
 Refactor run_round_robin.py: Player Pool Reuse                                                                                                  
                                                                                                                                                 
 Problem                                                                                                                                         
                                                                                                                                                 
 run_round_robin.py creates new LLMPlayer/MockPlayer instances for every match. This is wasteful (repeated websocket connections, no cross-match 
  state) and diverges from the pattern in tournament.py which creates players once.                                                              
                                                                                                                                                 
 Approach: Player Pool per Model                                                                                                                 
                                                                                                                                                 
 Create a pool of per_model_concurrent player instances per model using asyncio.Queue. Workers acquire a player from the pool, prepare it for    
 the specific match (set team, logger, opponents), run the battle, then return it.                                                               
                                                                                                                                                 
 This preserves the existing concurrency model while eliminating per-match player construction.                                                  
                                                                                                                                                 
 ---                                                                                                                                             
 Changes                                                                                                                                         
                                                                                                                                                 
 1. src/agent_player.py - Add two methods to AgentPlayer                                                                                         
                                                                                                                                                 
 prepare_for_battle(team, team_name, battle_logger) (after register_opponent, ~line 49):                                                         
 - Calls self.update_team(team) (inherited from poke-env Player)                                                                                 
 - Sets self.team_name and optionally self.battle_logger                                                                                         
                                                                                                                                                 
 clear_opponent_registry():                                                                                                                      
 - Clears self.known_opponents and self.known_opponent_ids                                                                                       
 - Needed because pool players face different opponents each match                                                                               
                                                                                                                                                 
 2. scripts/run_round_robin.py - Four changes                                                                                                    
                                                                                                                                                 
 a) Add create_player_pools() function (after load_manifest):                                                                                    
 - For each model, create per_model_concurrent player instances                                                                                  
 - Players constructed with team=None (safe - poke-env stores self._team = None)                                                                 
 - Usernames: {model_name[:max]}-{i} where i = pool index (0 to N-1)                                                                             
 - Store in asyncio.Queue per model name                                                                                                         
 - Returns dict[str, asyncio.Queue]                                                                                                              
                                                                                                                                                 
 b) Refactor run_match() to accept pre-created players:                                                                                          
 - New params: player_a, player_b (replace internal player creation)                                                                             
 - Call prepare_for_battle() and clear_opponent_registry() + register_opponent() on each                                                         
 - Determine winner via battle.won/battle.lost on the battle object (not n_won_battles)                                                          
 - Call player_a.reset_battles() / player_b.reset_battles() after extracting winner                                                              
 - Remove all LLMPlayer(...) / MockPlayer(...) construction from this function                                                                   
                                                                                                                                                 
 c) Refactor worker() inside run_tournament():                                                                                                   
 - Acquire players: player_a = await player_pools[model_a_name].get()                                                                            
 - Pass them to run_match()                                                                                                                      
 - In finally block: return both players to their pools via pool.put_nowait(player)                                                              
 - On error: try reset_battles() on both players before returning to pool                                                                        
                                                                                                                                                 
 d) Create pools at start of run_tournament() (after team_pool load, ~line 360):                                                                 
 - player_pools = create_player_pools(models_by_name, per_model_concurrent, use_mock, mock_error_rate)                                           
                                                                                                                                                 
 ---                                                                                                                                             
 Key Design Details                                                                                                                              
                                                                                                                                                 
 - Winner detection: Check battle.won/battle.lost on the battle object BEFORE calling reset_battles(). The current n_won_battles approach would  
 accumulate across reuses.                                                                                                                       
 - team=None at construction: Safe. prepare_for_battle() always sets the team before the first match. poke-env's update_team() accepts packed    
 team strings.                                                                                                                                   
 - Concurrency safety: The existing scheduler (get_best_match) already enforces per-model concurrency via current_load. The pool acts as a       
 safety net - await pool.get() blocks if exhausted.                                                                                              
 - WebSocket reuse: Pool players keep their websocket connections alive across matches - a performance win.                                      
 - Logging: Each match still creates its own MatchLogger. It's set on the player via prepare_for_battle() before each match. Since each pool     
 player handles one battle at a time, there's no conflict.                                                                                       
                                                                                                                                                 
 Files Modified                                                                                                                                  
                                                                                                                                                 
 - src/agent_player.py - Add prepare_for_battle() and clear_opponent_registry()                                                                  
 - scripts/run_round_robin.py - Add create_player_pools(), refactor run_match(), worker(), and run_tournament()                                  
                                                                                                                                                 
 Verification                                                                                                                                    
                                                                                                                                                 
 1. Run python3 scripts/run_round_robin.py generate --models <2+ models> --games-per-pair 2                                                      
 2. Run python3 scripts/run_round_robin.py run --manifest <path> --mock to test with mock players                                                
 3. Verify matches complete, manifest updates correctly, logs are written per match                                                              
 4. Verify --mock --concurrent 4 --per-model-concurrent 2 works (concurrent execution)  
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


async def run_match(
    match: dict,
    models_by_name: dict[str, ModelConfig],
    team_pool,
    match_dir: Path,
    use_mock: bool = False,
    mock_error_rate: float = 0.0,
) -> dict:
    """
    Run a single match and return updated match dict.
    """
    model_a = models_by_name[match["model_a"]]
    model_b = models_by_name[match["model_b"]]
    
    # Username format: truncate model name to fit -A/-B suffix within 18 chars
    max_name = 18 - 2  # room for "-A" / "-B"
    username_a = f"{model_a.name[:max_name]}-A"
    username_b = f"{model_b.name[:max_name]}-B"
    
    # Player ID = username (makes JSONL files named {username}.jsonl)
    player_id_a = username_a
    player_id_b = username_b
    
    # Create per-match logger
    logger = MatchLogger(match_dir=str(match_dir), enabled=True)
    
    # Get teams
    team_a_idx = team_pool.team_names.index(match["team_a"])
    team_b_idx = team_pool.team_names.index(match["team_b"])
    team_a = team_pool.teams[team_a_idx]
    team_b = team_pool.teams[team_b_idx]
    
    # Create players
    if use_mock:
        player_a = MockPlayer(
            account_configuration=AccountConfiguration(username_a, None),
            battle_format=BATTLE_FORMAT,
            team=team_a,
            server_configuration=CUSTOM_SERVER_CONFIG,
            battle_logger=logger,
            team_name=match["team_a"],
            player_id=player_id_a,
            error_rate=mock_error_rate,
        )
        player_b = MockPlayer(
            account_configuration=AccountConfiguration(username_b, None),
            battle_format=BATTLE_FORMAT,
            team=team_b,
            server_configuration=CUSTOM_SERVER_CONFIG,
            battle_logger=logger,
            team_name=match["team_b"],
            player_id=player_id_b,
            error_rate=mock_error_rate,
        )
    else:
        player_a = LLMPlayer(
            account_configuration=AccountConfiguration(username_a, None),
            model=model_a.model,
            temperature=model_a.temperature,
            max_tokens=model_a.max_tokens,
            timeout=model_a.timeout,
            battle_format=BATTLE_FORMAT,
            team=team_a,
            server_configuration=CUSTOM_SERVER_CONFIG,
            battle_logger=logger,
            team_name=match["team_a"],
            player_id=player_id_a,
        )
        player_b = LLMPlayer(
            account_configuration=AccountConfiguration(username_b, None),
            model=model_b.model,
            temperature=model_b.temperature,
            max_tokens=model_b.max_tokens,
            timeout=model_b.timeout,
            battle_format=BATTLE_FORMAT,
            team=team_b,
            server_configuration=CUSTOM_SERVER_CONFIG,
            battle_logger=logger,
            team_name=match["team_b"],
            player_id=player_id_b,
        )
    
    # Register opponents
    player_a.register_opponent(username_b, model_b.model, player_id=player_id_b)
    player_b.register_opponent(username_a, model_a.model, player_id=player_id_a)
    
    # Run battle
    await player_a.battle_against(player_b, n_battles=1)
    
    # Get battle tag from player for debugging reference
    battle_tag = None
    if player_a.battles:
        battle_tag = list(player_a.battles.keys())[0]
    
    # Determine winner
    if player_a.n_won_battles > 0:
        winner = model_a.name
    elif player_b.n_won_battles > 0:
        winner = model_b.name
    else:
        winner = None
    
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
    
    # Reset any 'running' matches to 'pending' (crash recovery)
    for match in manifest["matches"]:
        if match["status"] == "running":
            match["status"] = "pending"
    write_manifest(manifest, manifest_path)
    
    # Filter to pending/failed matches
    pending_matches = [
        m for m in manifest["matches"]
        if m["status"] in ("pending", "failed") and m["attempts"] < max_retries
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
        
        match_desc = f"#{match['id']}: {model_a} vs {model_b}"
        print(f"[START] {match_desc}")
        
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
            
            result = await run_match(
                match, models_by_name, team_pool, match_dir,
                use_mock=use_mock, mock_error_rate=mock_error_rate
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
            
        finally:
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
