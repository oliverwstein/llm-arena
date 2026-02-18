"""Unified tool registry for both human and LLM interfaces.

Single source of truth for all tools - names, descriptions, parameters, and handlers.
Both human text commands and LLM API calls use this registry.
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Any, Optional
from poke_env.player.player import AbstractBattle

from . import type_tools, damage_tools, team_tools, battle_log_tools, field_tools, info_tools, plan_tools
from ..state_formatter import get_battle_state


@dataclass
class ToolParam:
    """Definition of a tool parameter."""
    name: str
    type: str  # "string", "integer", "array"
    description: str
    required: bool = True
    enum: list = None
    items_type: str = None  # For arrays, the type of items


@dataclass
class Tool:
    """Definition of a tool."""
    name: str
    description: str
    handler: Callable[[AbstractBattle, dict, dict], Any]
    params: list[ToolParam] = field(default_factory=list)
    needs_context: bool = False  # True if handler needs context dict (for plan tools)


# =============================================================================
# Tool Handlers
# =============================================================================

def _handle_help(battle: AbstractBattle, args: dict, context: dict) -> dict:
    """Get help for tools."""
    tool_name = args.get("tool")
    if tool_name:
        tool = TOOLS.get(tool_name)
        if not tool:
            return {"error": f"Unknown tool: {tool_name}"}

        result = {
            "tool": tool.name,
            "description": tool.description,
        }
        if tool.params:
            result["parameters"] = [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                }
                for p in tool.params
            ]
        return result
    else:
        # List all tools
        return {
            "tools": [
                {"name": t.name, "description": t.description}
                for t in TOOLS.values()
            ]
        }


def _handle_damage(battle: AbstractBattle, args: dict, context: dict) -> dict:
    move_name = args.get("move")
    if move_name:
        return damage_tools.calculate_damage(battle, move_name)
    return damage_tools.calculate_all_damages(battle)


def _handle_team(battle: AbstractBattle, args: dict, context: dict) -> dict:
    pokemon_name = args.get("pokemon")
    if pokemon_name:
        return team_tools.get_team_pokemon(battle, pokemon_name)
    if args.get("full"):
        return team_tools.get_full_team_details(battle)
    return team_tools.get_team_summary(battle)


def _handle_opponent(battle: AbstractBattle, args: dict, context: dict) -> dict:
    pokemon_name = args.get("pokemon")
    if pokemon_name:
        return team_tools.get_opponent_pokemon(battle, pokemon_name)
    if args.get("full"):
        return team_tools.get_opponent_team_summary(battle)
    return team_tools.get_opponent_summary(battle)


def _handle_log(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return battle_log_tools.get_battle_log(
        battle,
        args.get("from_turn", 0),
        args.get("turn")
    )


def _handle_field(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return field_tools.get_field_analysis(battle)


def _handle_type(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return type_tools.get_all_type_matchups(args.get("types", []))


def _handle_pokedex(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return info_tools.get_pokemon_info(args.get("pokemon", ""))


def _handle_movedex(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return info_tools.get_move_details(args.get("move", ""))


def _handle_abilitydex(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return info_tools.get_ability_info(args.get("ability", ""))


def _handle_plan(battle: AbstractBattle, args: dict, context: dict) -> dict:
    battle_plan = context.get("battle_plan", {})
    return plan_tools.get_battle_plan(battle_plan)


def _handle_plan_update(battle: AbstractBattle, args: dict, context: dict) -> dict:
    battle_plan = context.get("battle_plan", {})
    return plan_tools.update_battle_plan(
        battle_plan,
        args.get("action", ""),
        args.get("goal_id"),
        args.get("text")
    )


def _handle_state(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return get_battle_state(battle)


# =============================================================================
# Tool Registry
# =============================================================================

TOOLS: dict[str, Tool] = {
    "help": Tool(
        name="help",
        description="Get help on available tools. Call with no arguments for a list, or with a tool name for details.",
        handler=_handle_help,
        params=[
            ToolParam("tool", "string", "Tool name to get help for", required=False),
        ],
    ),

    # Damage tools
    "damage": Tool(
        name="damage",
        description="Calculate damage for your ACTIVE Pokemon's available moves against the current opponent. Call without args for all available moves, or specify a move name. Only works for moves your active Pokemon can use — for general move info, use 'movedex'.",
        handler=_handle_damage,
        params=[
            ToolParam("move", "string", "Name of the specific move to calculate damage for", required=False),
        ],
    ),

    # Team tools
    "team": Tool(
        name="team",
        description="Get team info. No args: summary. 'pokemon': specific mon details. 'full': detailed list of all.",
        handler=_handle_team,
        params=[
            ToolParam("pokemon", "string", "Name of specific Pokemon to inspect", required=False),
            ToolParam("full", "boolean", "Get full details for entire team", required=False),
        ],
    ),
    "opponent": Tool(
        name="opponent",
        description="Get opponent info. No args: active + fainted/unrevealed counts. 'full': all 6 slots. 'pokemon': specific mon details.",
        handler=_handle_opponent,
        params=[
            ToolParam("pokemon", "string", "Name of opponent's Pokemon to inspect", required=False),
            ToolParam("full", "boolean", "Show all 6 slots with NOT_REVEALED for unseen Pokemon", required=False),
        ],
    ),

    # Battle log tools
    "log": Tool(
        name="log",
        description="Get the battle log as structured events. Use 'turn' for a specific turn only. Turn 0 contains initial switch events.",
        handler=_handle_log,
        params=[
            ToolParam("turn", "integer", "Get a specific turn's events only", required=False),
            ToolParam("from_turn", "integer", "Start from this turn number (default: 0)", required=False),
        ],
    ),

    # Field tools
    "field": Tool(
        name="field",
        description="Analyze current field conditions (weather, hazards, screens) and their effects.",
        handler=_handle_field,
        params=[],
    ),
    "state": Tool(
        name="state",
        description="Get the full structured state summary of the battle (same as shown at the start of turn).",
        handler=_handle_state,
        params=[],
    ),

    # Type tools
    "type": Tool(
        name="type",
        description="Get type analysis: weaknesses, resistances, and immunities for a type combination.",
        handler=_handle_type,
        params=[
            ToolParam("types", "array", "The types to analyze (e.g. ['fire', 'flying'])", items_type="string"),
        ],
    ),

    # Info tools
    "pokedex": Tool(
        name="pokedex",
        description="Look up base stats, types, abilities, and typical role for a Pokemon species.",
        handler=_handle_pokedex,
        params=[
            ToolParam("pokemon", "string", "Pokemon species name"),
        ],
    ),
    "movedex": Tool(
        name="movedex",
        description="Look up move details by name (power, accuracy, type, effects). For ability info, use 'abilitydex'. For Pokemon info, use 'pokedex'.",
        handler=_handle_movedex,
        params=[
            ToolParam("move", "string", "Move name"),
        ],
    ),
    "abilitydex": Tool(
        name="abilitydex",
        description="Look up ability details (effect description, which Pokemon have it).",
        handler=_handle_abilitydex,
        params=[
            ToolParam("ability", "string", "Ability name"),
        ],
    ),

    # Plan tools
    # "plan": Tool(
    #     name="plan",
    #     description="Review your current strategic battle plan and goals.",
    #     handler=_handle_plan,
    #     params=[],
    #     needs_context=True,
    # ),
    # "plan_update": Tool(
    #     name="plan_update",
    #     description="Update your long-term strategic plan: add goals, mark complete, abandon, or add notes.",
    #     handler=_handle_plan_update,
    #     params=[
    #         ToolParam("action", "string", "Action to perform", enum=["add_goal", "complete_goal", "abandon_goal", "add_note"]),
    #         ToolParam("goal_id", "integer", "Goal ID (for complete_goal, abandon_goal, add_note)", required=False),
    #         ToolParam("text", "string", "Goal text (for add_goal) or note text (for add_note)", required=False),
    #     ],
    #     needs_context=True,
    # ),
}


# =============================================================================
# Public API
# =============================================================================

def execute_tool(
    name: str,
    args: dict | str,
    battle: AbstractBattle,
    context: dict = None
) -> str:
    """
    Execute a tool and return JSON result string.

    Args:
        name: Tool name
        args: Tool arguments (dict or JSON string)
        battle: Current battle state
        context: Additional context (battle_plan, etc.)

    Returns:
        JSON string with tool result
    """
    # Parse args if string
    if isinstance(args, str):
        try:
            args = json.loads(args) if args else {}
        except json.JSONDecodeError:
            args = {}

    args = args or {}
    context = context or {}

    tool = TOOLS.get(name)
    if not tool:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        result = tool.handler(battle, args, context)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def parse_command(text: str) -> tuple[str, dict]:
    """
    Parse human command text into tool name and arguments.

    Examples:
        "damage" -> ("damage", {})
        "damage earthquake" -> ("damage_move", {"move": "earthquake"})
        "team" -> ("team", {})
        "team skarmory" -> ("team_pokemon", {"pokemon": "skarmory"})
        "type fire vs grass steel" -> ("type", {"attack_type": "fire", "defender_types": ["grass", "steel"]})

    Returns:
        Tuple of (tool_name, args_dict) or (None, {}) if not recognized
    """
    parts = text.strip().lower().split()
    if not parts:
        return None, {}

    cmd = parts[0]
    rest = parts[1:] if len(parts) > 1 else []

    # Help
    if cmd == "help":
        if rest:
            return "help", {"tool": rest[0]}
        return "help", {}

    # Damage
    if cmd == "damage":
        if rest:
            return "damage", {"move": " ".join(rest)}
        return "damage", {}

    # Team
    if cmd == "team":
        if rest:
            if rest[0] == "full":
                return "team", {"full": True}
            return "team", {"pokemon": " ".join(rest)}
        return "team", {}

    # Opponent - "opponent" (summary), "opponent full" (all 6 slots), "opponent <name>" (specific)
    if cmd == "opponent":
        if rest:
            if rest[0] == "full":
                return "opponent", {"full": True}
            return "opponent", {"pokemon": " ".join(rest)}
        return "opponent", {}

    # Log - supports getting a specific turn: "log" (all), "log 3" (turn 3 only)
    if cmd == "log":
        args = {}
        if rest:
            try:
                args["turn"] = int(rest[0])
            except ValueError:
                pass
        return "log", args


    # Field
    if cmd == "field":
        return "field", {}

    # State
    if cmd == "state":
        return "state", {}

    # Type
    if cmd == "type":
        if rest:
            return "type", {"types": rest}
        return "help", {"tool": "type"}

    # Pokemon info
    if cmd == "pokedex" or cmd == "pokemon" or cmd == "info":
        if rest:
            return "pokedex", {"pokemon": " ".join(rest)}
        return "help", {"tool": "pokedex"}

    # Move info - use "movedex <name>" to avoid conflict with "move <name>" action
    # Also support legacy "move <name> info" syntax
    if cmd == "movedex" or cmd == "moveinfo":
        if rest:
            return "movedex", {"move": " ".join(rest)}
        return "help", {"tool": "movedex"}
    if cmd == "move" and rest and rest[-1] == "info":
        # "move earthquake info" -> movedex earthquake
        return "movedex", {"move": " ".join(rest[:-1])}

    # Ability info
    if cmd == "abilitydex" or cmd == "ability":
        if rest:
            return "abilitydex", {"ability": " ".join(rest)}
        return "help", {"tool": "abilitydex"}

    # Plan
    if cmd == "plan":
        if not rest:
            return "plan", {}
        # plan add <text>, plan complete <id>, plan abandon <id>, plan note <id> <text>
        action = rest[0]
        if action == "add" and len(rest) > 1:
            return "plan_update", {"action": "add_goal", "text": " ".join(rest[1:])}
        elif action == "complete" and len(rest) > 1:
            try:
                return "plan_update", {"action": "complete_goal", "goal_id": int(rest[1])}
            except ValueError:
                pass
        elif action == "abandon" and len(rest) > 1:
            try:
                return "plan_update", {"action": "abandon_goal", "goal_id": int(rest[1])}
            except ValueError:
                pass
        elif action == "note" and len(rest) > 2:
            try:
                return "plan_update", {"action": "add_note", "goal_id": int(rest[1]), "text": " ".join(rest[2:])}
            except ValueError:
                pass
        return "plan", {}

    return None, {}


def get_llm_tool_definitions() -> list[dict]:
    """
    Generate LiteLLM-compatible tool definitions from the registry.

    Returns:
        List of tool definition dicts for the LLM API
    """
    definitions = []

    for tool in TOOLS.values():
        properties = {}
        required = []

        for param in tool.params:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.type == "array" and param.items_type:
                prop["items"] = {"type": param.items_type}

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        definitions.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })

    return definitions


def get_help_text() -> str:
    """
    Get formatted help text for all tools (for system prompts).

    Returns:
        Formatted string listing all tools
    """
    lines = ["AVAILABLE TOOLS:", ""]

    categories = {
        "Damage": ["damage"],
        "Team": ["team", "opponent"],
        "Battle Log": ["log"],
        "Field": ["field", "state"],
        "Type": ["type"],
        "Info": ["pokedex", "movedex", "abilitydex"],
        # "Planning": ["plan", "plan_update"],
        "Help": ["help"],
    }

    for category, tool_names in categories.items():
        lines.append(f"{category}:")
        for name in tool_names:
            tool = TOOLS.get(name)
            if tool:
                params = ""
                if tool.params:
                    param_strs = [f"<{p.name}>" if p.required else f"[{p.name}]" for p in tool.params]
                    params = " " + " ".join(param_strs)
                lines.append(f"  {tool.name}{params} - {tool.description}")
        lines.append("")

    return "\n".join(lines)
