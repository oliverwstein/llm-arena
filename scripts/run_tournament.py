#!/usr/bin/env python3
"""Run an LLM Pokemon tournament."""

import asyncio
import argparse
import yaml
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables before other imports
from src.env_manager import load_env_file
load_env_file()

from src.tournament import run_tournament, TournamentConfig, ModelConfig
from src.results import ResultsDB
from src.battle_logger import BattleLogger


# Default models to test
DEFAULT_MODELS = [
    ModelConfig(name="Claude-Sonnet-4.5", model="claude-sonnet-4-5-20251101"),
    ModelConfig(name="GPT-5.1", model="gpt-5.1"),
    ModelConfig(name="Gemini-3.0-Flash", model="gemini/gemini-3.0-flash"),
    ModelConfig(name="DeepSeek-Reasoner", model="deepseek/deepseek-reasoner"),
    ModelConfig(name="Grok-4", model="xai/grok-4"),
]


def load_models_from_yaml(path: str) -> list[ModelConfig]:
    """Load model configurations from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    models = []
    for m in data["models"]:
        # Handle the force_fallback field if present
        models.append(ModelConfig(
            name=m["name"],
            model=m["model"],
            temperature=m.get("temperature", 0.7),
            max_tokens=m.get("max_tokens", 150),
            force_fallback=m.get("force_fallback", False),
        ))
    return models


async def main():
    parser = argparse.ArgumentParser(
        description="Run LLM Pokemon Tournament",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default models (uses random bots if API keys missing)
  python scripts/run_tournament.py --battles 5
  
  # Run with custom models file
  python scripts/run_tournament.py --models config/models.yaml --battles 10
  
  # Run with heuristic fallback instead of random
  python scripts/run_tournament.py --fallback heuristic --battles 5
  
  # Specify custom .env file location
  python scripts/run_tournament.py --env-file /path/to/.env --battles 5

Environment:
  API keys can be set via:
  1. Environment variables (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
  2. A .env file in env/.env, ./.env, or ~/.llm-arena/.env
  
  See env/.env.example for all supported keys.
  Models without API keys will use random-move bots.
        """
    )
    parser.add_argument("--name", default="LLM Battle Tournament", help="Tournament name")
    parser.add_argument("--format", default="gen4ou", help="Battle format")
    parser.add_argument("--battles", type=int, default=10, help="Battles per matchup")
    parser.add_argument("--models", help="Path to models YAML config")
    parser.add_argument("--teams-dir", default="Raw-Teams", help="Directory containing team files")
    parser.add_argument("--no-replays", action="store_true", help="Don't save replays")
    parser.add_argument("--db", default="results/battles.db", help="Results database path")
    parser.add_argument("--env-file", help="Path to .env file with API keys")
    parser.add_argument("--fallback", choices=["random", "heuristic"], default="random",
                        help="Bot type to use when API key is missing (default: random)")
    parser.add_argument("--no-log", action="store_true", help="Disable battle logging")

    args = parser.parse_args()
    
    # Load custom env file if specified
    if args.env_file:
        if not load_env_file(args.env_file):
            print(f"Warning: Could not load env file: {args.env_file}")

    # Load models
    if args.models:
        models = load_models_from_yaml(args.models)
    else:
        models = DEFAULT_MODELS

    # Initialize database
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    db = ResultsDB(args.db)
    await db.initialize()

    # Create tournament config
    config = TournamentConfig(
        name=args.name,
        format=args.format,
        n_battles=args.battles,
        teams_dir=args.teams_dir,
        save_replays=not args.no_replays,
        fallback_type=args.fallback,
    )

    # Create battle logger
    logger = None if args.no_log else BattleLogger(log_dir="logs", enabled=True)
    if logger:
        print(f"Logging battles to: logs/battles.jsonl")

    # Run tournament
    results = await run_tournament(config, models, db, battle_logger=logger)

    print("\nTournament complete!")


if __name__ == "__main__":
    asyncio.run(main())
