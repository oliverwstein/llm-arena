#!/usr/bin/env python3
"""Run 1v1 battles between two LLM players."""

import asyncio
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from poke_env import AccountConfiguration

from src.config import ModelConfig, load_models_from_yaml, find_model
from src.llm_player import LLMPlayer, CUSTOM_SERVER_CONFIG
from src.conversational_llm_player import ConversationalLLMPlayer
from src.team_pool import get_team_pool
from src.env_manager import load_env_file, has_api_key

# Player mode mapping
PLAYER_MODES = {
    "tools": LLMPlayer,
    "conversational": ConversationalLLMPlayer,
}
from src.battle_logger import BattleLogger

# Load environment
load_env_file()

BATTLE_FORMAT = "gen4ou"


def resolve_team(team_path: Optional[str], team_pool):
    """Resolve a team path to a packed team string or return the pool."""
    if not team_path:
        # Get a specific random team so we can log its name
        packed, name = team_pool.get_random_team()
        return packed, name
    
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
    
    # Fallback also gets specific random team
    packed, name = team_pool.get_random_team()
    return packed, name


def _make_player_label(model_name: str, mode: str, suffix: str, is_mirror: bool) -> str:
    """Generate a clean, human-readable player label that fits Showdown's 18-char limit.

    For mirror matches (same model), includes a mode tag (tool/conv).
    For non-mirror matches, just uses the model name + suffix.
    """
    mode_tag = "tool" if mode == "tools" else "conv"
    if is_mirror:
        # e.g. "Gemini-3-Fl-tool-A" -- reserve room for "-{tag}-{suffix}"
        max_name = 18 - len(mode_tag) - len(suffix) - 2  # 2 dashes
        base = model_name[:max_name].rstrip(".-_")
        return f"{base}-{mode_tag}-{suffix}"
    else:
        # e.g. "Gemini-3-Flash-A"
        max_name = 18 - len(suffix) - 1  # 1 dash
        base = model_name[:max_name].rstrip(".-_")
        return f"{base}-{suffix}"


async def run_battle(
    model_a: ModelConfig,
    model_b: ModelConfig,
    team_pool,
    n_battles: int = 5,
    verbose: bool = False,
    battle_logger: BattleLogger = None,
    player_class_a = LLMPlayer,
    player_class_b = LLMPlayer,
    mode_a: str = "tools",
    mode_b: str = "tools",
    session_dir: Optional[Path] = None,
) -> dict:
    """Run battles between two LLM players."""

    print(f"\n{'='*60}")
    print(f"LLM vs LLM Battle")
    print(f"{'='*60}")
    print(f"  Player A: {model_a.name} ({model_a.model}) [{mode_a}]")
    print(f"  Player B: {model_b.name} ({model_b.model}) [{mode_b}]")
    print(f"  Battles: {n_battles}")
    print(f"{'='*60}")

    # Check API keys
    if not has_api_key(model_a.model):
        print(f"  ERROR: No API key available for {model_a.model}")
        return {"status": "error", "reason": f"no_api_key for {model_a.name}"}

    if not has_api_key(model_b.model):
        print(f"  ERROR: No API key available for {model_b.model}")
        return {"status": "error", "reason": f"no_api_key for {model_b.name}"}

    # Generate clean player labels (used as both Showdown username and player_id)
    is_mirror = model_a.name == model_b.name
    label_a = _make_player_label(model_a.name, mode_a, "A", is_mirror)
    label_b = _make_player_label(model_b.name, mode_b, "B", is_mirror)

    # Resolve teams
    team_a, team_a_name = resolve_team(model_a.team, team_pool)
    team_b, team_b_name = resolve_team(model_b.team, team_pool)

    print(f"  {label_a} Team: {team_a_name}")
    print(f"  {label_b} Team: {team_b_name}")

    # Create players (using specified player classes)
    player_a = player_class_a(
        account_configuration=AccountConfiguration(label_a, None),
        model=model_a.model,
        temperature=model_a.temperature,
        max_tokens=model_a.max_tokens,
        timeout=model_a.timeout,
        reasoning_effort=model_a.reasoning_effort,
        battle_format=BATTLE_FORMAT,
        team=team_a,
        server_configuration=CUSTOM_SERVER_CONFIG,
        verbose=verbose,
        battle_logger=battle_logger,
        team_name=team_a_name,
        player_id=label_a,
        player_mode=mode_a,
    )

    player_b = player_class_b(
        account_configuration=AccountConfiguration(label_b, None),
        model=model_b.model,
        temperature=model_b.temperature,
        max_tokens=model_b.max_tokens,
        timeout=model_b.timeout,
        reasoning_effort=model_b.reasoning_effort,
        battle_format=BATTLE_FORMAT,
        team=team_b,
        server_configuration=CUSTOM_SERVER_CONFIG,
        verbose=verbose,
        battle_logger=battle_logger,
        team_name=team_b_name,
        player_id=label_b,
        player_mode=mode_b,
    )

    # Register opponents so they can log the enemy model name correctly
    player_a.register_opponent(label_b, model_b.model, player_id=label_b)
    player_b.register_opponent(label_a, model_a.model, player_id=label_a)

    print(f"\n  Running {n_battles} battles...")

    try:
        await player_a.battle_against(player_b, n_battles=n_battles)

        wins_a = player_a.n_won_battles
        wins_b = player_b.n_won_battles

        print(f"\n  Results:")
        print(f"    {label_a}: {wins_a}/{n_battles} ({wins_a/n_battles*100:.1f}%)")
        print(f"    {label_b}: {wins_b}/{n_battles} ({wins_b/n_battles*100:.1f}%)")

        result = {
            "status": "completed",
            "player_a": {
                "label": label_a,
                "name": model_a.name,
                "model": model_a.model,
                "mode": mode_a,
                "player_class": player_class_a.__name__,
                "team": team_a_name,
                "wins": wins_a,
            },
            "player_b": {
                "label": label_b,
                "name": model_b.name,
                "model": model_b.model,
                "mode": mode_b,
                "player_class": player_class_b.__name__,
                "team": team_b_name,
                "wins": wins_b,
            },
            "total_battles": n_battles,
        }

        # Write session manifest
        if session_dir:
            _write_session_manifest(session_dir, result)

        return result

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "reason": str(e)}


def _write_session_manifest(session_dir: Path, result: dict) -> None:
    """Write session.json manifest with full player details and results."""
    manifest = {
        "created_at": datetime.now().isoformat(),
        "format": BATTLE_FORMAT,
        "players": {
            result["player_a"]["label"]: {
                "name": result["player_a"]["name"],
                "model": result["player_a"]["model"],
                "mode": result["player_a"]["mode"],
                "player_class": result["player_a"]["player_class"],
                "team": result["player_a"]["team"],
            },
            result["player_b"]["label"]: {
                "name": result["player_b"]["name"],
                "model": result["player_b"]["model"],
                "mode": result["player_b"]["mode"],
                "player_class": result["player_b"]["player_class"],
                "team": result["player_b"]["team"],
            },
        },
        "results": {
            "total_battles": result["total_battles"],
            result["player_a"]["label"]: result["player_a"]["wins"],
            result["player_b"]["label"]: result["player_b"]["wins"],
        },
    }
    manifest_path = session_dir / "session.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Session manifest: {manifest_path}")


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
    parser.add_argument("--team-a", help="Override team file for Player A")
    parser.add_argument("--team-b", help="Override team file for Player B")
    parser.add_argument("--random-teams", action="store_true", help="Force random team selection for both players")
    parser.add_argument("--teams-dir", default="Raw-Teams", help="Directory containing team files")
    parser.add_argument("--models", default="config/models.yaml", help="Path to models YAML config")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full LLM responses")
    parser.add_argument("--timeout", type=int, help="Override timeout for both models (seconds)")
    parser.add_argument("--max-tokens", type=int, help="Override max tokens for both models")
    parser.add_argument("--no-log", action="store_true", help="Disable battle logging")
    parser.add_argument(
        "--mode", 
        choices=["tools", "conversational"], 
        default="tools",
        help="Default player mode for both players (can be overridden per-player)"
    )
    parser.add_argument(
        "--mode-a", 
        choices=["tools", "conversational"], 
        help="Player A mode (overrides --mode)"
    )
    parser.add_argument(
        "--mode-b", 
        choices=["tools", "conversational"], 
        help="Player B mode (overrides --mode)"
    )

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

    # Apply team overrides
    # Priority:
    # 1. Explicit team argument (--team-a/--team-b)
    # 2. Random teams flag (--random-teams)
    # 3. Model config (already loaded)
    
    if args.random_teams:
        model_a.team = None
        model_b.team = None
        print("  Team Override: Force Random")

    if args.team_a:
        model_a.team = args.team_a
        print(f"  Team A Override: {args.team_a}")
    
    if args.team_b:
        model_b.team = args.team_b
        print(f"  Team B Override: {args.team_b}")

    # Resolve player modes (per-player overrides default)
    mode_a = args.mode_a or args.mode
    mode_b = args.mode_b or args.mode
    player_class_a = PLAYER_MODES[mode_a]
    player_class_b = PLAYER_MODES[mode_b]
    print(f"Player A mode: {mode_a} ({player_class_a.__name__})")
    print(f"Player B mode: {mode_b} ({player_class_b.__name__})")

    # Create session directory and battle logger
    session_dir = None
    logger = None
    if not args.no_log:
        session_name = f"llm-vs-llm-{datetime.now().strftime('%Y-%m-%d-%H%M')}"
        session_dir = Path("logs") / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        logger = BattleLogger(log_dir=str(session_dir), enabled=True)
        print(f"Logging battles to: {session_dir}/")

    # Run battles
    result = await run_battle(
        model_a=model_a,
        model_b=model_b,
        team_pool=team_pool,
        n_battles=args.battles,
        verbose=args.verbose,
        battle_logger=logger,
        player_class_a=player_class_a,
        player_class_b=player_class_b,
        mode_a=mode_a,
        mode_b=mode_b,
        session_dir=session_dir,
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
