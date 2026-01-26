#!/usr/bin/env python3
"""
Run a round-robin tournament between LLM players.
Supports parallel execution, cost tracking, and automatic model filtering.
"""

import asyncio
import argparse
import sys
import itertools
import yaml
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from poke_env import AccountConfiguration, ServerConfiguration
from src.llm_player import LLMPlayer, CUSTOM_SERVER_CONFIG
from src.team_pool import get_team_pool
from src.env_manager import load_env_file, get_available_models, has_api_key
from src.battle_logger import BattleLogger

# Load environment variables
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
    api_price_input: float = 0.0
    api_price_output: float = 0.0
    
    # Stats
    battles_played: int = 0
    wins: int = 0
    losses: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    
    @property
    def total_cost(self) -> float:
        return (
            (self.total_input_tokens / 1_000_000) * self.api_price_input +
            (self.total_output_tokens / 1_000_000) * self.api_price_output
        )

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
            api_price_input=float(m.get("api_price_input", 0.0)),
            api_price_output=float(m.get("api_price_output", 0.0)),
        ))
    return models

async def battle_pair(
    model_a: ModelConfig,
    model_b: ModelConfig,
    team_pool,
    n_battles: int,
    logger: BattleLogger
) -> dict:
    """Run N battles between Model A and Model B."""
    
    # Create unique usernames
    import uuid
    session_id = str(uuid.uuid4())[:6]
    
    # Random suffix for usernames to avoid collisions
    import random
    import string
    
    results = {
        "model_a": model_a.name,
        "model_b": model_b.name,
        "a_wins": 0,
        "b_wins": 0,
        "tokens": {
            "a_input": 0, "a_output": 0,
            "b_input": 0, "b_output": 0
        }
    }

    # To respect global concurrency, we should run these sequentially 
    # or let the global semaphore handle it. 
    # For now, run sequentially to avoid overloading a single pair match.
    
    for i in range(n_battles):
        await run_single_battle(model_a, model_b, team_pool, session_id, i, results, logger)
        
    return results

async def run_single_battle(model_a, model_b, team_pool, session_id, idx, results, logger):
    """Run a single battle and update stats."""
    
    # Truncate to 18 chars for Showdown
    # Format: T-XXXX-Model (try to keep unique part and model identifier)
    import hashlib
    h_a = hashlib.md5(f"{session_id}{model_a.name}{idx}".encode()).hexdigest()[:4]
    h_b = hashlib.md5(f"{session_id}{model_b.name}{idx}".encode()).hexdigest()[:4]
    
    # 2 chars prefix, 5 chars hash, 10 chars model name (total 17 chars safe)
    username_a = f"T-{h_a}-{model_a.name}"[:18]
    username_b = f"T-{h_b}-{model_b.name}"[:18]
    
    # Ensure they are different if playing self
    if username_a == username_b:
        username_b = f"{username_b[:17]}2"
    
    # Always use random teams
    team_a_packed, team_a_name = team_pool.get_random_team()
    team_b_packed, team_b_name = team_pool.get_random_team()
    
    player_id_a = f"{model_a.model}-{uuid.uuid4().hex[:8]}"
    player_id_b = f"{model_b.model}-{uuid.uuid4().hex[:8]}"

    player_a = LLMPlayer(
        account_configuration=AccountConfiguration(username_a, None),
        model=model_a.model,
        temperature=model_a.temperature,
        max_tokens=model_a.max_tokens,
        battle_format=BATTLE_FORMAT,
        team=team_a_packed,
        server_configuration=CUSTOM_SERVER_CONFIG,
        verbose=False, # Reduce excessive logging
        battle_logger=logger,
        team_name=team_a_name,
        player_id=player_id_a
    )
    
    player_b = LLMPlayer(
        account_configuration=AccountConfiguration(username_b, None),
        model=model_b.model,
        temperature=model_b.temperature,
        max_tokens=model_b.max_tokens,
        battle_format=BATTLE_FORMAT,
        team=team_b_packed,
        server_configuration=CUSTOM_SERVER_CONFIG,
        verbose=False,
        battle_logger=logger,
        team_name=team_b_name,
        player_id=player_id_b
    )
    
    player_a.register_opponent(username_b, model_b.model, player_id_b)
    player_b.register_opponent(username_a, model_a.model, player_id_a)
    
    # Run the battle
    await player_a.battle_against(player_b, n_battles=1)
    
    if player_a.n_won_battles > 0:
        results["a_wins"] += 1
    elif player_b.n_won_battles > 0:
        results["b_wins"] += 1

import uuid

async def main():
    parser = argparse.ArgumentParser(description="Run LLM Round Robin Tournament")
    parser.add_argument("--battles", type=int, default=10, help="Battles per matchup")
    parser.add_argument("--concurrent", type=int, default=2, help="Max concurrent matchups")
    parser.add_argument("--filter", nargs="+", help="Filter models by name (case-insensitive)")
    parser.add_argument("--models", default="config/models.yaml", help="Path to models config")
    parser.add_argument("--teams-dir", default="Raw-Teams", help="Directory with team files")
    
    args = parser.parse_args()
    
    # Load team pool
    team_pool = get_team_pool(args.teams_dir)
    print(f"Loaded {len(team_pool.teams)} teams")
    
    # Load models
    all_models = load_models_from_yaml(args.models)
    
    # Filter models
    target_models = []
    
    # 1. Filter by args if provided
    if args.filter:
        for m in all_models:
            if any(f.lower() in m.name.lower() for f in args.filter):
                target_models.append(m)
    else:
        # Default Mini League set
        defaults = ["DeepSeek-Reasoner", "Grok-4", "Gemini-3-Flash", "GPT-5-Mini"]
        for m in all_models:
            if m.name in defaults:
                target_models.append(m)
    
    # 2. Filter by API key availability
    available_models = []
    print("\nValidating API capabilities:")
    for m in target_models:
        if has_api_key(m.model):
            print(f"  ✓ {m.name} ready")
            available_models.append(m)
        else:
            print(f"  ✗ {m.name} skipped (missing API key)")
            
    if len(available_models) < 2:
        print("Error: Need at least 2 models to run a tournament.")
        return

    # Create logger
    log_dir = Path("logs/tournament")
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = BattleLogger(log_dir=str(log_dir), enabled=True)
    
    
    # Setup tournament
    print(f"\nStarting Tournament!")
    print(f"Models: {', '.join(m.name for m in available_models)}")
    print(f"Battles per pair: {args.battles}")
    print(f"Max Concurrent per Model: 3")
    print("=" * 60)
    
    # Create per-model semaphores (limit 3 concurrency per provider)
    model_semaphores = {m.name: asyncio.Semaphore(3) for m in available_models}
    
    pairs = list(itertools.combinations(available_models, 2))
    
    stats = defaultdict(lambda: {"wins": 0, "losses": 0, "matches": 0})
    
    # Flatten all battles into a single list of tasks
    # We create a unique session ID for the tournament
    import uuid
    session_id = str(uuid.uuid4())[:6]
    
    battle_tasks = []
    
    for ma, mb in pairs:
        for i in range(args.battles):
            battle_tasks.append(
                run_safe_battle(ma, mb, team_pool, session_id, i, logger, stats, model_semaphores)
            )
            
    # Run all battles
    await asyncio.gather(*battle_tasks)
    
    # Results
    print("\n" + "=" * 60)
    print("TOURNAMENT RESULTS")
    print("=" * 60)
    print(f"{'Model':<20} {'Wins':<8} {'Losses':<8} {'Win Rate':<10}")
    print("-" * 60)
    
    sorted_stats = sorted(
        stats.items(),
        key=lambda x: x[1]["wins"] / x[1]["matches"] if x[1]["matches"] > 0 else 0,
        reverse=True
    )
    
    for name, s in sorted_stats:
        total = s["matches"]
        wr = (s["wins"] / total * 100) if total > 0 else 0
        print(f"{name:<20} {s['wins']:<8} {s['losses']:<8} {wr:.1f}%")
        
    print("=" * 60)
    print(f"Detailed logs saved to: {log_dir}")


async def run_safe_battle(ma, mb, team_pool, session_id, idx, logger, stats, semaphores):
    """
    Run a single battle with resource locks and retries.
    Acquires locks for BOTH models involved to ensure per-model limits are respected.
    """
    
    # Sort names to prevent deadlocks (Always acquire locks in same order)
    # e.g., if we hold Lock A and want Lock B, and another task holds B wanting A -> Deadlock.
    # By sorting, everyone acquires lowest alphabetical first.
    first, second = sorted([ma.name, mb.name])
    
    sem_1 = semaphores[first]
    sem_2 = semaphores[second]
    
    while True:
        try:
            async with sem_1:
                async with sem_2:
                    print(f"[Queue] Starting {ma.name} vs {mb.name} (#{idx+1})")
                    
                    # We create a temp results dict just for this one battle
                    # to keep the signature similar, or just update stats directly
                    # run_single_battle updates a 'results' dict. Let's make one.
                    results = {"a_wins": 0, "b_wins": 0}
                    
                    await run_single_battle(ma, mb, team_pool, session_id, idx, results, logger)
                    
                    # Update global stats
                    if results["a_wins"] > 0:
                        stats[ma.name]["wins"] += 1
                        stats[mb.name]["losses"] += 1
                        print(f"Result: {ma.name} WINS vs {mb.name}")
                    elif results["b_wins"] > 0:
                        stats[mb.name]["wins"] += 1
                        stats[ma.name]["losses"] += 1
                        print(f"Result: {mb.name} WINS vs {ma.name}")
                    else:
                        print(f"Result: DRAW/ERROR in {ma.name} vs {mb.name}")
                        
                    stats[ma.name]["matches"] += 1
                    stats[mb.name]["matches"] += 1
                    
                    return # Success, exit loop

        except Exception as e:
            print(f"Error in {ma.name} vs {mb.name}: {e}. Retrying in 60s...")
            await asyncio.sleep(60)



if __name__ == "__main__":
    asyncio.run(main())

