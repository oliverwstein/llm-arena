#!/usr/bin/env python3
"""Play as a human against the SimpleHeuristicsPlayer baseline."""

import asyncio
import argparse
import sys
import random
import string
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from poke_env.player import SimpleHeuristicsPlayer
from poke_env import ServerConfiguration, AccountConfiguration

from src.human_player import HumanPlayer
from src.team_pool import get_team_pool
from src.env_manager import load_env_file

# Load environment
load_env_file()

SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8000/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?"
)

BATTLE_FORMAT = "gen4ou"


async def main():
    parser = argparse.ArgumentParser(
        description="Play as a human against heuristic baseline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script lets you experience exactly what the LLM sees and interact
with the same tools available to the LLM player.

Use 'help' during battle to see available commands and tools.

Examples:
  python scripts/human_vs_heuristic.py
  python scripts/human_vs_heuristic.py --battles 3
        """
    )

    parser.add_argument("--battles", type=int, default=1, help="Number of battles to play")
    parser.add_argument("--teams-dir", default="Raw-Teams", help="Directory containing team files")
    parser.add_argument("--name", default="Human", help="Your player name")
    parser.add_argument("--resume", action="store_true", help="Resume existing battle (use exact name)")

    args = parser.parse_args()

    # Generate unique names by default to ensure fresh battles
    # With --resume, use exact names to potentially reconnect
    if args.resume:
        human_name = args.name
        bot_name = "Bot_" + args.name
    else:
        suffix = ''.join(random.choices(string.digits, k=4))
        human_name = f"{args.name}_{suffix}"
        bot_name = f"Bot_{suffix}"

    # Load team pool
    team_pool = get_team_pool(args.teams_dir)
    print(f"Loaded {len(team_pool.teams)} teams")

    # Create players
    human_player = HumanPlayer(
        account_configuration=AccountConfiguration(human_name, None),
        battle_format=BATTLE_FORMAT,
        team=team_pool,
        server_configuration=SERVER_CONFIG,
    )

    heuristic_player = SimpleHeuristicsPlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        battle_format=BATTLE_FORMAT,
        team=team_pool,
        server_configuration=SERVER_CONFIG,
    )

    print(f"\nPlaying as: {human_name}")
    print(f"Starting {args.battles} battle(s) against {bot_name}...")
    print("Type 'help' during battle to see available commands.\n")

    await human_player.battle_against(heuristic_player, n_battles=args.battles)

    # Results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Human wins: {human_player.n_won_battles}/{args.battles}")
    print(f"Bot wins: {heuristic_player.n_won_battles}/{args.battles}")


if __name__ == "__main__":
    asyncio.run(main())
