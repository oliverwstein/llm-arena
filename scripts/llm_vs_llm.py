#!/usr/bin/env python3
"""Run 1v1 battles between two LLM players."""

import asyncio
import argparse
import yaml
import sys
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from poke_env import AccountConfiguration

from src.llm_player import LLMPlayer, CUSTOM_SERVER_CONFIG
from src.team_pool import get_team_pool
from src.env_manager import load_env_file, has_api_key
from src.battle_logger import BattleLogger

# Load environment
load_env_file()

BATTLE_FORMAT = "gen4ou"


@dataclass
class ModelConfig:
    name: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 60
    team: str = None


def load_models_from_yaml(path: str) -> list[ModelConfig]:
    """Load model configurations from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    models = []
    for m in data["models"]:
        models.append(ModelConfig(
            name=m["name"],
            model=m["model"],
            temperature=m.get("temperature", 0.7),
            max_tokens=m.get("max_tokens", 4096),
            timeout=m.get("timeout", 60),
            team=m.get("team"),
        ))
    return models


def find_model(query: str, model_list: list[ModelConfig]) -> Optional[ModelConfig]:
    """Find a model by name or model ID."""
    # Exact match first
    for m in model_list:
        if m.name == query or m.model == query:
            return m
    # Partial match
    for m in model_list:
        if query.lower() in m.name.lower() or query.lower() in m.model.lower():
            return m
    return None


def resolve_team(team_path: Optional[str], team_pool):
    """Resolve a team path to a packed team string or return the pool."""
    if not team_path:
        return team_pool, "Random (Pool)"
    
    path = Path(team_path)
    if path.exists():
        try:
            content = path.read_text()
            packed = team_pool.join_team(team_pool.parse_showdown_team(content))
            return packed, team_path
        except Exception as e:
            print(f"  WARNING: Failed to parse team file {team_path}: {e}")
            print(f"  Falling back to team pool.")
    else:
        print(f"  WARNING: Team file not found: {team_path}")
        print(f"  Falling back to team pool.")
    
    return team_pool, "Random (Pool)"


async def run_battle(
    model_a: ModelConfig,
    model_b: ModelConfig,
    team_pool,
    n_battles: int = 5,
    verbose: bool = False,
    battle_logger: BattleLogger = None,
) -> dict:
    """Run battles between two LLM players."""

    print(f"\n{'='*60}")
    print(f"LLM vs LLM Battle")
    print(f"{'='*60}")
    print(f"  Player A: {model_a.name} ({model_a.model})")
    print(f"  Player B: {model_b.name} ({model_b.model})")
    print(f"  Battles: {n_battles}")
    print(f"{'='*60}")

    # Check API keys
    if not has_api_key(model_a.model):
        print(f"  ERROR: No API key available for {model_a.model}")
        return {"status": "error", "reason": f"no_api_key for {model_a.name}"}
    
    if not has_api_key(model_b.model):
        print(f"  ERROR: No API key available for {model_b.model}")
        return {"status": "error", "reason": f"no_api_key for {model_b.name}"}

    # Create unique usernames
    session_id = str(uuid.uuid4())[:8]
    username_a = f"L-{session_id}-{model_a.name}"[:18]
    username_b = f"L-{session_id}-{model_b.name}"[:18]
    
    # Ensure unique if same model
    if username_a == username_b:
        username_b = username_b[:-1] + "2"

    # Resolve teams
    team_a, team_a_name = resolve_team(model_a.team, team_pool)
    team_b, team_b_name = resolve_team(model_b.team, team_pool)

    print(f"  {model_a.name} Team: {team_a_name}")
    print(f"  {model_b.name} Team: {team_b_name}")

    # Create players
    player_a = LLMPlayer(
        account_configuration=AccountConfiguration(username_a, None),
        model=model_a.model,
        temperature=model_a.temperature,
        max_tokens=model_a.max_tokens,
        timeout=model_a.timeout,
        battle_format=BATTLE_FORMAT,
        team=team_a,
        server_configuration=CUSTOM_SERVER_CONFIG,
        verbose=verbose,
        battle_logger=battle_logger,
        team_name=team_a_name,
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
        verbose=verbose,
        battle_logger=battle_logger,
        team_name=team_b_name,
    )

    # Register opponents so they can log the enemy model name correctly
    player_a.register_opponent(username_b, model_b.model)
    player_b.register_opponent(username_a, model_a.model)

    print(f"\n  Running {n_battles} battles...")

    try:
        await player_a.battle_against(player_b, n_battles=n_battles)

        wins_a = player_a.n_won_battles
        wins_b = player_b.n_won_battles

        print(f"\n  Results:")
        print(f"    {model_a.name}: {wins_a}/{n_battles} ({wins_a/n_battles*100:.1f}%)")
        print(f"    {model_b.name}: {wins_b}/{n_battles} ({wins_b/n_battles*100:.1f}%)")

        return {
            "status": "completed",
            "player_a": {
                "name": model_a.name,
                "model": model_a.model,
                "wins": wins_a,
            },
            "player_b": {
                "name": model_b.name,
                "model": model_b.model,
                "wins": wins_b,
            },
            "total_battles": n_battles,
        }

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "reason": str(e)}


async def main():
    parser = argparse.ArgumentParser(
        description="Run 1v1 battles between two LLM players",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Battle two models by name (from config/models.yaml)
  python scripts/llm_vs_llm.py --a Claude-Sonnet-4.5 --b GPT-5.1

  # Battle using raw model IDs
  python scripts/llm_vs_llm.py --a claude-sonnet-4-5-20251101 --b gpt-5.1

  # Override settings
  python scripts/llm_vs_llm.py --a Claude-Sonnet-4.5 --b DeepSeek-Reasoner --battles 10 --timeout 120

  # With verbose output for debugging
  python scripts/llm_vs_llm.py --a Claude-Sonnet-4.5 --b GPT-5.1 -v
        """
    )

    parser.add_argument("--a", required=True, help="Player A: model name or ID")
    parser.add_argument("--b", required=True, help="Player B: model name or ID")
    parser.add_argument("--battles", type=int, default=5, help="Number of battles (default: 5)")
    parser.add_argument("--teams-dir", default="Raw-Teams", help="Directory containing team files")
    parser.add_argument("--models", default="config/models.yaml", help="Path to models YAML config")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full LLM responses")
    parser.add_argument("--timeout", type=int, help="Override timeout for both models (seconds)")
    parser.add_argument("--max-tokens", type=int, help="Override max tokens for both models")
    parser.add_argument("--no-log", action="store_true", help="Disable battle logging")

    args = parser.parse_args()

    # Load team pool
    team_pool = get_team_pool(args.teams_dir)
    print(f"Loaded {len(team_pool.teams)} teams")

    # Try to load model configs from YAML
    try:
        all_models = load_models_from_yaml(args.models)
    except Exception as e:
        print(f"Warning: Could not load {args.models}: {e}")
        all_models = []

    # Resolve model A
    model_a = find_model(args.a, all_models)
    if model_a:
        print(f"Model A: Found '{model_a.name}' in config")
    else:
        print(f"Model A: Using raw model ID '{args.a}'")
        model_a = ModelConfig(name=args.a, model=args.a)

    # Resolve model B
    model_b = find_model(args.b, all_models)
    if model_b:
        print(f"Model B: Found '{model_b.name}' in config")
    else:
        print(f"Model B: Using raw model ID '{args.b}'")
        model_b = ModelConfig(name=args.b, model=args.b)

    # Apply overrides
    if args.timeout:
        model_a.timeout = args.timeout
        model_b.timeout = args.timeout
    if args.max_tokens:
        model_a.max_tokens = args.max_tokens
        model_b.max_tokens = args.max_tokens

    # Create battle logger
    logger = None if args.no_log else BattleLogger(log_dir="logs", enabled=True)
    if logger:
        print(f"Logging battles to: logs/")

    # Run battles
    result = await run_battle(
        model_a=model_a,
        model_b=model_b,
        team_pool=team_pool,
        n_battles=args.battles,
        verbose=args.verbose,
        battle_logger=logger,
    )

    # Summary
    print("\n" + "="*60)
    if result["status"] == "completed":
        a = result["player_a"]
        b = result["player_b"]
        if a["wins"] > b["wins"]:
            print(f"WINNER: {a['name']} ({a['wins']}-{b['wins']})")
        elif b["wins"] > a["wins"]:
            print(f"WINNER: {b['name']} ({b['wins']}-{a['wins']})")
        else:
            print(f"TIE: {a['name']} {a['wins']} - {b['wins']} {b['name']}")
    else:
        print(f"FAILED: {result.get('reason', 'Unknown error')}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
