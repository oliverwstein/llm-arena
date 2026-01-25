#!/usr/bin/env python3
"""
Run a round-robin tournament where every team plays every other team
using the SimpleHeuristicsPlayer.
"""

import asyncio
import argparse
import sys
import itertools
from pathlib import Path
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from poke_env.player import SimpleHeuristicsPlayer
from poke_env import ServerConfiguration, AccountConfiguration
from src.team_pool import get_team_pool
from src.env_manager import load_env_file

# Load environment variables
load_env_file()

SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8000/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?"
)

BATTLE_FORMAT = "gen4ou"

async def battle_pair(
    team_a_name: str,
    team_a_packed: str,
    team_b_name: str,
    team_b_packed: str,
    n_battles: int
) -> dict:
    """
    Run N battles between Team A and Team B.
    Returns dictionary with results.
    """
    # Append random suffix to ensure unique names per matchup
    import random
    import string
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
    p1_name = f"H-{team_a_name}"[:12] + "-" + suffix
    p2_name = f"H-{team_b_name}"[:12] + "-" + suffix
    
    # Ensure unique names if playing mirror match
    if p1_name == p2_name:
        p2_name = p2_name[:-1] + "2"

    player_1 = SimpleHeuristicsPlayer(
        account_configuration=AccountConfiguration(p1_name, None),
        battle_format=BATTLE_FORMAT,
        server_configuration=SERVER_CONFIG,
        team=team_a_packed,
        max_concurrent_battles=n_battles
    )
    
    player_2 = SimpleHeuristicsPlayer(
        account_configuration=AccountConfiguration(p2_name, None),
        battle_format=BATTLE_FORMAT,
        server_configuration=SERVER_CONFIG,
        team=team_b_packed,
        max_concurrent_battles=n_battles
    )

    await player_1.battle_against(player_2, n_battles=n_battles)

    return {
        "team_a": team_a_name,
        "team_b": team_b_name,
        "team_a_wins": player_1.n_won_battles,
        "team_b_wins": player_2.n_won_battles,
        "battles": n_battles
    }

async def main():
    parser = argparse.ArgumentParser(description="Run round-robin heuristic tournament")
    parser.add_argument("--teams-dir", default="Raw-Teams", help="Directory with team files")
    parser.add_argument("--battles", type=int, default=5, help="Battles per matchup")
    parser.add_argument("--filter", help="Filter particular teams by name")
    
    parser.add_argument("--concurrent", type=int, default=10, help="Max concurrent matchups")
    
    args = parser.parse_args()

    # Load all teams
    print(f"Loading teams from {args.teams_dir}...")
    full_pool = get_team_pool(args.teams_dir)
    
    # Extract teams into a list of (name, packed_str) tuples
    teams = list(zip(full_pool.team_names, full_pool.teams))
    
    # Filter if requested
    if args.filter:
        teams = [t for t in teams if args.filter.lower() in t[0].lower()]
        print(f"Filtered to {len(teams)} teams matching '{args.filter}'")
    
    if len(teams) < 2:
        print("Error: Need at least 2 teams to run a tournament.")
        return

    print(f"Starting Round Robin for {len(teams)} teams.")
    print(f"Battles per matchup: {args.battles}")
    print(f"Max concurrent matchups: {args.concurrent}")
    print("=" * 60)

    # Dictionary to track total stats per team
    stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'matches': 0})
    
    pairs = list(itertools.combinations(teams, 2))
    total_matchups = len(pairs)
    
    print(f"Total Matchups: {total_matchups}")
    print("-" * 60)

    sem = asyncio.Semaphore(args.concurrent)

    async def run_matchup(index: int, pair: tuple) -> dict:
        async with sem:
            (name_a, packed_a), (name_b, packed_b) = pair
            res = await battle_pair(name_a, packed_a, name_b, packed_b, args.battles)
            return {"index": index, "result": res}

    # Create tasks
    tasks = [run_matchup(i, pair) for i, pair in enumerate(pairs, 1)]
    
    completed_count = 0
    for future in asyncio.as_completed(tasks):
        data = await future
        res = data["result"]
        idx = data["index"]
        
        name_a = res["team_a"]
        name_b = res["team_b"]
        wins_a = res["team_a_wins"]
        wins_b = res["team_b_wins"]
        
        print(f"Matchup {idx}/{total_matchups} finished: {name_a} {wins_a} - {wins_b} {name_b}")
        
        stats[name_a]['wins'] += wins_a
        stats[name_a]['losses'] += wins_b
        stats[name_a]['matches'] += 1
        
        stats[name_b]['wins'] += wins_b
        stats[name_b]['losses'] += wins_a
        stats[name_b]['matches'] += 1
        
        completed_count += 1

    print("\n" + "=" * 60)
    print("TOURNAMENT RESULTS")
    print("=" * 60)
    print(f"{'Team Name':<30} {'Wins':<8} {'Losses':<8} {'Win Rate':<10}")
    print("-" * 60)

    # Sort by win rate
    sorted_stats = sorted(
        stats.items(), 
        key=lambda x: x[1]['wins'] / (x[1]['wins'] + x[1]['losses']) if (x[1]['wins'] + x[1]['losses']) > 0 else 0, 
        reverse=True
    )

    for name, s in sorted_stats:
        total_games = s['wins'] + s['losses']
        win_rate = (s['wins'] / total_games * 100) if total_games > 0 else 0.0
        print(f"{name:<30} {s['wins']:<8} {s['losses']:<8} {win_rate:.1f}%")

if __name__ == "__main__":
    asyncio.run(main())
