"""Tool harness for LLM Pokemon players.

Provides tools for type analysis, damage calculation, matchup evaluation,
team information, and battle history queries.
"""

from .type_tools import get_type_effectiveness, get_all_type_matchups
from .damage_tools import calculate_damage, calculate_all_damages
from .matchup_tools import evaluate_matchup, evaluate_all_matchups, should_switch
from .team_tools import (
    get_team_summary,
    get_team_pokemon,
    get_opponent_team_summary,
    get_opponent_pokemon,
)
from .battle_log_tools import get_battle_log, get_turn_details
from .plan_tools import get_battle_plan, update_battle_plan
from .field_tools import get_field_analysis
from .info_tools import get_move_details, get_pokemon_info
from .speed_tools import get_speed_comparison
from .executor import execute_tool
from .definitions import TOOL_DEFINITIONS

__all__ = [
    # Type tools
    "get_type_effectiveness",
    "get_all_type_matchups",
    # Damage tools
    "calculate_damage",
    "calculate_all_damages",
    # Matchup tools
    "evaluate_matchup",
    "evaluate_all_matchups",
    "should_switch",
    # Team tools
    "get_team_summary",
    "get_team_pokemon",
    "get_opponent_team_summary",
    "get_opponent_pokemon",
    # Battle log tools
    "get_battle_log",
    "get_turn_details",
    # Plan tools
    "get_battle_plan",
    "update_battle_plan",
    # Field tools
    "get_field_analysis",
    # Info tools
    "get_move_details",
    "get_pokemon_info",
    # Speed tools
    "get_speed_comparison",
    # Infrastructure
    "execute_tool",
    "TOOL_DEFINITIONS",
]
