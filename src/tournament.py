"""Tournament management for LLM battles."""

import asyncio
from datetime import datetime
from typing import Optional, Union, TYPE_CHECKING
from dataclasses import dataclass, field
from poke_env.player import cross_evaluate, Player

from .llm_player import CUSTOM_SERVER_CONFIG
from .team_pool import get_team_pool
from .results import ResultsDB
from .player_factory import PlayerFactory
from .env_manager import print_api_key_status

if TYPE_CHECKING:
    from .battle_logger import BattleLogger


@dataclass
class TournamentConfig:
    """Configuration for a tournament."""
    name: str
    format: str = "gen4ou"
    n_battles: int = 10  # Battles per matchup
    save_replays: bool = True
    replay_dir: str = "results/replays"
    teams_dir: str = "Raw-Teams"  # Directory containing team files
    fallback_type: str = "random"  # "random" or "heuristic" for missing API keys


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""
    name: str           # Display name
    model: str          # LiteLLM model ID
    temperature: float = 0.7
    max_tokens: int = 4096        # Tool-calling needs more tokens
    timeout: float = 60.0         # LLM timeout in seconds
    force_fallback: bool = False  # Force use of fallback bot
    team: Optional[str] = None    # Specific team path (optional)


@dataclass
class PlayerInfo:
    """Information about a created player."""
    player: Player
    config: ModelConfig
    is_llm: bool  # True if using LLM, False if using fallback bot


def create_players(
    models: list[ModelConfig],
    battle_format: str,
    teams_dir: str = "Raw-Teams",
    save_replays: bool = False,
    replay_dir: str = "replays",
    fallback_type: str = "random",
    battle_logger: Optional["BattleLogger"] = None,
) -> list[PlayerInfo]:
    """
    Create players for each model, with automatic fallback for missing API keys.

    Returns list of PlayerInfo objects containing player and metadata.
    """
    # Load the team pool (shared by all players)
    team_pool = get_team_pool(teams_dir)

    # Create player factory
    factory = PlayerFactory(
        team_pool=team_pool,
        server_config=CUSTOM_SERVER_CONFIG,
        battle_format=battle_format,
        fallback_type=fallback_type,
        battle_logger=battle_logger,
    )
    
    player_infos = []
    for config in models:
        player, is_llm = factory.create_player(
            name=config.name,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
            force_fallback=config.force_fallback,
            team_path=config.team,
        )
        player_infos.append(PlayerInfo(player=player, config=config, is_llm=is_llm))
    
    return player_infos


async def run_tournament(
    config: TournamentConfig,
    models: list[ModelConfig],
    results_db: Optional[ResultsDB] = None,
    show_api_status: bool = True,
    battle_logger: Optional["BattleLogger"] = None,
) -> dict:
    """
    Run a round-robin tournament between all models.

    Args:
        config: Tournament configuration
        models: List of model configurations
        results_db: Optional database for persisting results
        show_api_status: If True, print API key status at start
        battle_logger: Optional BattleLogger for comprehensive output logging

    Returns:
        Dictionary with win rates for each matchup
    """
    print(f"\n{'='*60}")
    print(f"Tournament: {config.name}")
    print(f"Format: {config.format}")
    print(f"Battles per matchup: {config.n_battles}")
    print(f"Models: {[m.name for m in models]}")
    print(f"{'='*60}\n")

    if show_api_status:
        print_api_key_status()

    # Create players
    player_infos = create_players(
        models=models,
        battle_format=config.format,
        teams_dir=config.teams_dir,
        save_replays=config.save_replays,
        replay_dir=config.replay_dir,
        fallback_type=config.fallback_type,
        battle_logger=battle_logger,
    )
    
    # Report player types
    print("Player Status:")
    for info in player_infos:
        status = "LLM" if info.is_llm else f"Fallback ({config.fallback_type})"
        print(f"  • {info.config.name}: {status}")
    print()
    
    players = [info.player for info in player_infos]

    # Run cross-evaluation
    # This runs all pairwise matchups
    start_time = datetime.now()

    results = await cross_evaluate(players, n_challenges=config.n_battles)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Process results
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}\n")

    # Print win rate matrix
    model_names = [m.name for m in models]
    print(f"{'':15}", end="")
    for name in model_names:
        print(f"{name:15}", end="")
    print()

    for i, p1 in enumerate(players):
        print(f"{model_names[i]:15}", end="")
        for j, p2 in enumerate(players):
            if i == j:
                print(f"{'---':15}", end="")
            else:
                win_rate = results[p1.username][p2.username]
                print(f"{win_rate*100:5.1f}%{'':<9}", end="")
        print()

    print(f"\nTotal time: {duration:.1f}s")

    # Calculate overall rankings
    rankings = []
    for i, player in enumerate(players):
        wins = sum(
            results[player.username][opp.username] * config.n_battles
            for j, opp in enumerate(players) if i != j
        )
        total = (len(players) - 1) * config.n_battles
        is_llm = player_infos[i].is_llm
        rankings.append((model_names[i], wins, total, is_llm))

    rankings.sort(key=lambda x: x[1], reverse=True)

    print("\nOVERALL RANKINGS:")
    for rank, (name, wins, total, is_llm) in enumerate(rankings, 1):
        marker = "" if is_llm else " (bot)"
        print(f"  {rank}. {name}{marker}: {wins:.0f}/{total} ({wins/total*100:.1f}%)")

    # Save to database if provided
    if results_db:
        await results_db.save_tournament(config, models, results)

    return results


async def run_single_battle(
    player1: Player,
    player2: Player,
    n_battles: int = 1
) -> dict:
    """
    Run battles between two specific players.

    Returns dict with win counts.
    """
    await player1.battle_against(player2, n_battles=n_battles)

    return {
        player1.username: player1.n_won_battles,
        player2.username: player2.n_won_battles,
    }
