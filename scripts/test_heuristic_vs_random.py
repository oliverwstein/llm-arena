#!/usr/bin/env python3
"""Test SimpleHeuristicsPlayer vs RandomPlayer to verify heuristic bot is working."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from poke_env.player import RandomPlayer, SimpleHeuristicsPlayer
from poke_env import ServerConfiguration

from src.team_pool import get_team_pool

# Server configuration
SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8000/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?"
)

BATTLE_FORMAT = "gen4ou"
N_BATTLES = 20


async def main():
    print("=" * 60)
    print("Heuristic Bot vs Random Bot Test")
    print("=" * 60)
    print(f"Format: {BATTLE_FORMAT}")
    print(f"Battles: {N_BATTLES}")
    print()

    # Load team pool
    team_pool = get_team_pool("Raw-Teams")
    print(f"Loaded {len(team_pool.teams)} teams")
    print()

    # Create players
    heuristic_player = SimpleHeuristicsPlayer(
        battle_format=BATTLE_FORMAT,
        team=team_pool,
        server_configuration=SERVER_CONFIG,
        max_concurrent_battles=5,
    )

    random_player = RandomPlayer(
        battle_format=BATTLE_FORMAT,
        team=team_pool,
        server_configuration=SERVER_CONFIG,
        max_concurrent_battles=5,
    )

    print("Running battles...")
    print()

    # Run battles
    await heuristic_player.battle_against(random_player, n_battles=N_BATTLES)

    # Results
    heuristic_wins = heuristic_player.n_won_battles
    random_wins = random_player.n_won_battles

    heuristic_pct = (heuristic_wins / N_BATTLES) * 100
    random_pct = (random_wins / N_BATTLES) * 100

    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Heuristic Bot: {heuristic_wins}/{N_BATTLES} wins ({heuristic_pct:.1f}%)")
    print(f"Random Bot:    {random_wins}/{N_BATTLES} wins ({random_pct:.1f}%)")
    print()

    if heuristic_wins > random_wins:
        ratio = heuristic_wins / max(random_wins, 1)
        print(f"Heuristic bot won {ratio:.1f}x more battles!")
        print("SUCCESS: Heuristic bot dramatically outperforms random bot.")
    elif heuristic_wins == random_wins:
        print("WARNING: Tie - unexpected result. Check if bots are working correctly.")
    else:
        print("FAILURE: Random bot won more - something is wrong!")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
