#!/usr/bin/env python3
"""
Manifest-based round-robin tournament runner.

Three subcommands:
  generate  - Create match manifest from model list
  run       - Execute matches from manifest (resumable)
  status    - Show tournament progress

Examples:
  # Generate a tournament manifest
  python scripts/run_round_robin.py generate \\
    --models Claude-Haiku-4.5 GPT-5-Mini Gemini-3-Flash \\
    --games-per-pair 3 \\
    --output tournament.json

  # Run the tournament (resumable)
  python scripts/run_round_robin.py run \\
    --manifest tournament.json \\
    --concurrent 6 \\
    --per-model-concurrent 3

  # Check status
  python scripts/run_round_robin.py status --manifest tournament.json

  # Run with mock players (for testing)
  python scripts/run_round_robin.py run --manifest tournament.json --mock
"""

import asyncio
import argparse
import itertools
import json
import os
import signal
import sys
import uuid
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


def generate_manifest(
    models: list[ModelConfig],
    games_per_pair: int,
    team_pool,
    output_path: str,
    tournament_name: Optional[str] = None,
) -> dict:
    """Generate a tournament manifest with all matches."""
    
    if tournament_name is None:
        tournament_name = f"round-robin-{datetime.now().strftime('%Y-%m-%d-%H%M')}"
    
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
            
            # Assign teams with rotation
            # Each model gets a different team each game (when possible)
            team_a_idx = model_team_idx[model_a.name] % num_teams
            team_b_idx = model_team_idx[model_b.name] % num_teams
            
            # Ensure teams are different for this match
            if team_a_idx == team_b_idx:
                team_b_idx = (team_b_idx + 1) % num_teams
            
            team_a_name = team_names[team_a_idx]
            team_b_name = team_names[team_b_idx]
            
            # Advance rotation
            model_team_idx[model_a.name] += 1
            model_team_idx[model_b.name] += 1
            
            matches.append({
                "id": match_id,
                "model_a": model_a.name,
                "model_b": model_b.name,
                "team_a": team_a_name,
                "team_b": team_b_name,
                "status": "pending",
                "result": None,
                "winner": None,
                "error": None,
                "attempts": 0,
                "battle_id": None,
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
    
    # Write atomically
    write_manifest(manifest, output_path)
    
    return manifest


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
    logger: BattleLogger,
    use_mock: bool = False,
    mock_error_rate: float = 0.0,
) -> dict:
    """
    Run a single match and return updated match dict.
    """
    model_a = models_by_name[match["model_a"]]
    model_b = models_by_name[match["model_b"]]
    
    # Generate unique identifiers
    session_id = str(uuid.uuid4())[:8]
    username_a = f"R-{session_id}-{model_a.name}"[:18]
    username_b = f"R-{session_id}-{model_b.name}"[:18]
    
    if username_a == username_b:
        username_b = username_b[:-1] + "2"
    
    player_id_a = f"{model_a.model}-{uuid.uuid4().hex[:8]}"
    player_id_b = f"{model_b.model}-{uuid.uuid4().hex[:8]}"
    
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
    
    # Determine winner
    if player_a.n_won_battles > 0:
        winner = model_a.name
        result = f"{model_a.name} wins"
    elif player_b.n_won_battles > 0:
        winner = model_b.name
        result = f"{model_b.name} wins"
    else:
        winner = None
        result = "draw"
    
    return {
        **match,
        "status": "completed",
        "result": result,
        "winner": winner,
        "battle_id": f"{session_id}",
    }


async def run_tournament(
    manifest_path: str,
    concurrent: int = 6,
    per_model_concurrent: int = 3,
    use_mock: bool = False,
    mock_error_rate: float = 0.0,
    max_retries: int = 3,
) -> None:
    """
    Run tournament from manifest with concurrency controls.
    """
    manifest = load_manifest(manifest_path)
    
    # Load models
    try:
        all_models = load_models_from_yaml("config/models.yaml")
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
    
    # Load teams
    team_pool = get_team_pool("Raw-Teams")
    
    # Create logger
    log_dir = Path("logs/tournament")
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = BattleLogger(log_dir=str(log_dir), enabled=True)
    
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
    
    # Setup semaphores
    global_sem = asyncio.Semaphore(concurrent)
    model_sems = {name: asyncio.Semaphore(per_model_concurrent) for name in models_by_name}
    
    # Shared state for manifest updates
    manifest_lock = asyncio.Lock()
    shutdown_requested = False
    
    def handle_sigint(signum, frame):
        nonlocal shutdown_requested
        print("\n\nShutdown requested. Saving state...")
        shutdown_requested = True
    
    signal.signal(signal.SIGINT, handle_sigint)
    
    async def run_with_semaphores(match: dict) -> None:
        nonlocal manifest
        
        if shutdown_requested:
            return
        
        # Sorted lock acquisition to prevent deadlocks
        model_names = sorted([match["model_a"], match["model_b"]])
        sem_1 = model_sems[model_names[0]]
        sem_2 = model_sems[model_names[1]]
        
        async with global_sem:
            async with sem_1:
                async with sem_2:
                    if shutdown_requested:
                        return
                    
                    # Mark as running
                    async with manifest_lock:
                        for m in manifest["matches"]:
                            if m["id"] == match["id"]:
                                m["status"] = "running"
                                m["attempts"] += 1
                                break
                        write_manifest(manifest, manifest_path)
                    
                    match_desc = f"#{match['id']}: {match['model_a']} vs {match['model_b']}"
                    print(f"[START] {match_desc}")
                    
                    try:
                        result = await run_match(
                            match, models_by_name, team_pool, logger,
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
    
    # Run all matches
    tasks = [run_with_semaphores(m) for m in pending_matches]
    await asyncio.gather(*tasks, return_exceptions=True)
    
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
    
    # Check if output exists
    if Path(args.output).exists() and not args.force:
        print(f"\nError: {args.output} already exists. Use --force to overwrite.")
        sys.exit(1)
    
    # Generate manifest
    manifest = generate_manifest(
        models=valid_models,
        games_per_pair=args.games_per_pair,
        team_pool=team_pool,
        output_path=args.output,
        tournament_name=args.name,
    )
    
    n_matches = len(manifest["matches"])
    n_models = len(valid_models)
    
    print(f"\nGenerated tournament manifest:")
    print(f"  Models: {n_models}")
    print(f"  Games per pair: {args.games_per_pair}")
    print(f"  Total matches: {n_matches}")
    print(f"  Output: {args.output}")


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
    gen_parser.add_argument("--output", "-o", default="tournament.json",
                           help="Output manifest path (default: tournament.json)")
    gen_parser.add_argument("--name", help="Tournament name (default: auto-generated)")
    gen_parser.add_argument("--models-config", default="config/models.yaml",
                           help="Path to models YAML config")
    gen_parser.add_argument("--teams-dir", default="Raw-Teams",
                           help="Directory containing team files")
    gen_parser.add_argument("--force", "-f", action="store_true",
                           help="Overwrite existing manifest")
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
