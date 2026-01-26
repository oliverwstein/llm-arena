#!/usr/bin/env python3
"""Benchmark LLM players against the SimpleHeuristicsPlayer baseline."""

import asyncio
import argparse
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from poke_env.player import SimpleHeuristicsPlayer
from poke_env import ServerConfiguration, AccountConfiguration

from src.config import ModelConfig, load_models_from_yaml
from src.llm_player import LLMPlayer
from src.team_pool import get_team_pool
from src.env_manager import load_env_file, has_api_key
from src.battle_logger import BattleLogger

# Load environment
load_env_file()

SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8000/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?"
)

BATTLE_FORMAT = "gen4ou"


async def benchmark_model(
    model_config: ModelConfig,
    team_pool,
    n_battles: int = 10,
    verbose: bool = False,
    timeout: int = 30,
    battle_logger: BattleLogger = None,
) -> dict:
    """Run a single model against the heuristic baseline."""

    print(f"\n{'='*60}")
    print(f"Benchmarking: {model_config.name}")
    print(f"Model ID: {model_config.model}")
    print(f"Battles: {n_battles}")
    print(f"Max tokens: {model_config.max_tokens}")
    print(f"{'='*60}")

    # Check API key
    if not has_api_key(model_config.model):
        print(f"  SKIPPED: No API key available for {model_config.model}")
        return {
            "name": model_config.name,
            "model": model_config.model,
            "status": "skipped",
            "reason": "no_api_key",
        }

    # Create unique usernames for this session
    session_id = str(uuid.uuid4())[:8]
    llm_username = f"L-{session_id}-{model_config.name}"[:18]  # Limit length for Showdown
    heuristic_username = f"Heuristic-{session_id}"

    # Determine team for LLM
    llm_team = team_pool
    if model_config.team:
        team_path = Path(model_config.team)
        if team_path.exists():
            print(f"  Using specific team: {model_config.team}")
            try:
                team_content = team_path.read_text()
                llm_team = team_pool.join_team(team_pool.parse_showdown_team(team_content))
            except Exception as e:
                print(f"  WARNING: Failed to parse team file {model_config.team}: {e}")
                print(f"  Falling back to team pool.")
        else:
            print(f"  WARNING: Team file not found: {model_config.team}")
            print(f"  Falling back to team pool.")
            llm_team_name = "Random (Pool)"

    if llm_team == team_pool:
        llm_team_name = "Random (Pool)"
    else:
        llm_team_name = model_config.team

    print(f"  LLM Team: {llm_team_name}")
    print(f"  Heuristic Team: Random (Pool)")

    # Generate player_id for the LLM player
    player_id = f"{model_config.model}-{uuid.uuid4().hex[:8]}"

    # Create players
    llm_player = LLMPlayer(
        account_configuration=AccountConfiguration(llm_username, None),
        model=model_config.model,
        temperature=model_config.temperature,
        max_tokens=model_config.max_tokens,
        timeout=timeout,
        battle_format=BATTLE_FORMAT,
        team=llm_team,
        server_configuration=SERVER_CONFIG,
        verbose=verbose,
        battle_logger=battle_logger,
        team_name=llm_team_name,
        player_id=player_id,
    )

    heuristic_player = SimpleHeuristicsPlayer(
        account_configuration=AccountConfiguration(heuristic_username, None),
        battle_format=BATTLE_FORMAT,
        team=team_pool,
        server_configuration=SERVER_CONFIG,
    )

    print(f"  Running {n_battles} battles...")

    try:
        await llm_player.battle_against(heuristic_player, n_battles=n_battles)

        llm_wins = llm_player.n_won_battles
        heuristic_wins = heuristic_player.n_won_battles

        win_rate = llm_wins / n_battles * 100

        print(f"\n  Results:")
        print(f"    {model_config.name}: {llm_wins}/{n_battles} ({win_rate:.1f}%)")
        print(f"    Heuristic Bot: {heuristic_wins}/{n_battles} ({100-win_rate:.1f}%)")

        return {
            "name": model_config.name,
            "model": model_config.model,
            "status": "completed",
            "wins": llm_wins,
            "losses": heuristic_wins,
            "total": n_battles,
            "win_rate": win_rate,
        }

    except Exception as e:
        print(f"  ERROR: {e}")
        return {
            "name": model_config.name,
            "model": model_config.model,
            "status": "error",
            "reason": str(e),
        }


async def main():
    parser = argparse.ArgumentParser(
        description="Benchmark LLM players against heuristic baseline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark a single model
  python scripts/benchmark_vs_heuristic.py --model claude-sonnet-4-5-20251101 --name "Claude-Sonnet"

  # Benchmark all models from config
  python scripts/benchmark_vs_heuristic.py --all

  # Benchmark specific models from config
  python scripts/benchmark_vs_heuristic.py --models config/models.yaml --filter "Claude"
        """
    )

    parser.add_argument("--model", help="Single model ID to benchmark")
    parser.add_argument("--name", help="Display name for single model (default: model ID)")
    parser.add_argument("--models", default="config/models.yaml", help="Path to models YAML config")
    parser.add_argument("--all", action="store_true", help="Benchmark all models from config")
    parser.add_argument("--filter", help="Only benchmark models whose name contains this string")
    parser.add_argument("--battles", type=int, default=10, help="Number of battles per model")
    parser.add_argument("--teams-dir", default="Raw-Teams", help="Directory containing team files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full LLM responses")
    parser.add_argument("--max-tokens", type=int, help="Override max tokens (default: 150, use 1000+ for reasoning models)")
    parser.add_argument("--timeout", type=int, default=30, help="LLM timeout in seconds (default: 30, use 120+ for reasoning models)")
    parser.add_argument("--no-log", action="store_true", help="Disable battle logging")

    args = parser.parse_args()

    # Load team pool
    team_pool = get_team_pool(args.teams_dir)
    print(f"Loaded {len(team_pool.teams)} teams")

    # Determine which models to benchmark
    models_to_run = []

    if args.model:
        # Check if model exists in config first to get team/settings
        try:
            all_models = load_models_from_yaml(args.models)
            matching_model = next((m for m in all_models if m.model == args.model or m.name == args.model), None)
            
            if matching_model:
                # Use config but override CLI args
                matching_model.max_tokens = args.max_tokens or matching_model.max_tokens
                if args.name:
                    matching_model.name = args.name
                models_to_run.append(matching_model)
            else:
                # Fallback to raw config
                models_to_run.append(ModelConfig(
                    name=args.name or args.model,
                    model=args.model,
                    max_tokens=args.max_tokens or 150,
                ))
        except Exception as e:
            print(f"Warning: Could not load config/models.yaml: {e}")
            models_to_run.append(ModelConfig(
                name=args.name or args.model,
                model=args.model,
                max_tokens=args.max_tokens or 150,
            ))
    elif args.all or args.filter:
        # Load from config
        all_models = load_models_from_yaml(args.models)

        if args.filter:
            models_to_run = [m for m in all_models if args.filter.lower() in m.name.lower()]
        else:
            models_to_run = all_models
    else:
        parser.print_help()
        print("\nError: Specify --model, --all, or --filter")
        sys.exit(1)

    if not models_to_run:
        print("No models to benchmark!")
        sys.exit(1)

    # Override max_tokens if specified
    if args.max_tokens:
        for m in models_to_run:
            m.max_tokens = args.max_tokens

    print(f"\nModels to benchmark: {[m.name for m in models_to_run]}")

    # Create battle logger
    logger = None if args.no_log else BattleLogger(log_dir="logs", enabled=True)
    if logger:
        print(f"Logging battles to: logs/battles/")

    # Run benchmarks
    results = []
    for model_config in models_to_run:
        result = await benchmark_model(model_config, team_pool, args.battles, verbose=args.verbose, timeout=args.timeout, battle_logger=logger)
        results.append(result)

    # Summary
    print("\n" + "="*60)
    print("BENCHMARK SUMMARY")
    print("="*60)
    print(f"{'Model':<25} {'Status':<12} {'Win Rate':<10}")
    print("-"*60)

    completed = [r for r in results if r["status"] == "completed"]
    completed.sort(key=lambda x: x["win_rate"], reverse=True)

    for r in completed:
        print(f"{r['name']:<25} {'completed':<12} {r['win_rate']:.1f}%")

    for r in results:
        if r["status"] == "skipped":
            print(f"{r['name']:<25} {'skipped':<12} (no API key)")
        elif r["status"] == "error":
            print(f"{r['name']:<25} {'error':<12} {r.get('reason', '')[:20]}")

    print("="*60)

    if completed:
        avg_win_rate = sum(r["win_rate"] for r in completed) / len(completed)
        print(f"Average LLM win rate vs Heuristic: {avg_win_rate:.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
