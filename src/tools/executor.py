"""Tool execution dispatcher."""

import json
from typing import Any

from poke_env.player.player import AbstractBattle

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


def execute_tool(
    name: str,
    arguments: str | dict,
    battle: AbstractBattle,
    context: dict = None
) -> str:
    """
    Execute a tool and return JSON result string.
    
    Args:
        name: Tool name
        arguments: Tool arguments (JSON string or dict)
        battle: Current battle state
        context: Additional context (battle_plans, etc.)
    
    Returns:
        JSON string with tool result
    """
    # Parse arguments if string
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            args = {}
    else:
        args = arguments or {}
    
    context = context or {}
    
    try:
        result = _dispatch_tool(name, args, battle, context)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _dispatch_tool(
    name: str,
    args: dict,
    battle: AbstractBattle,
    context: dict
) -> Any:
    """Dispatch tool call to appropriate function."""
    
    # Type tools
    if name == "get_type_effectiveness":
        return get_type_effectiveness(
            args.get("attack_type", ""),
            args.get("defender_types", [])
        )
    
    if name == "get_all_type_matchups":
        return get_all_type_matchups(
            args.get("pokemon_types", [])
        )
    
    # Damage tools
    if name == "calculate_damage":
        return calculate_damage(battle, args.get("move_name", ""))
    
    if name == "calculate_all_damages":
        return calculate_all_damages(battle)
    
    # Speed tools
    if name == "get_speed_comparison":
        return get_speed_comparison(battle, args.get("move_name"))
    
    # Matchup tools
    if name == "evaluate_matchup":
        return evaluate_matchup(battle, args.get("pokemon_name"))
    
    if name == "evaluate_all_matchups":
        return evaluate_all_matchups(battle)
    
    if name == "should_switch":
        return should_switch(battle)
    
    # Info tools
    if name == "get_move_details":
        return get_move_details(args.get("move_name", ""))
    
    if name == "get_pokemon_info":
        return get_pokemon_info(args.get("pokemon_name", ""))
    
    # Field tools
    if name == "get_field_analysis":
        return get_field_analysis(battle)
    
    # Team tools
    if name == "get_team_pokemon":
        return get_team_pokemon(battle, args.get("pokemon_name", ""))
    
    if name == "get_team_summary":
        return get_team_summary(battle)
    
    if name == "get_opponent_pokemon":
        return get_opponent_pokemon(battle, args.get("pokemon_name", ""))
    
    if name == "get_opponent_team_summary":
        return get_opponent_team_summary(battle)
    
    # Battle log tools
    if name == "get_battle_log":
        return get_battle_log(
            battle,
            args.get("format", "narrative"),
            args.get("from_turn", 1)
        )
    
    if name == "get_turn_details":
        return get_turn_details(battle, args.get("turn", 1))
    
    # Plan tools (require context)
    if name == "get_battle_plan":
        battle_plan = context.get("battle_plan", {})
        return get_battle_plan(battle_plan)
    
    if name == "update_battle_plan":
        battle_plan = context.get("battle_plan", {})
        result = update_battle_plan(
            battle_plan,
            args.get("action", ""),
            args.get("goal_id"),
            args.get("text")
        )
        return result
    
    return {"error": f"Unknown tool: {name}"}
