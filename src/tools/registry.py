"""Unified tool registry for both human and LLM interfaces.

Single source of truth for all tools - names, descriptions, parameters, and handlers.
Both human text commands and LLM API calls use this registry.
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Any, Optional
from poke_env.player.player import AbstractBattle

from . import type_tools, damage_tools, team_tools, battle_log_tools, field_tools, info_tools, plan_tools


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
    return damage_tools.calculate_all_damages(battle)


def _handle_damage_move(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return damage_tools.calculate_damage(battle, args.get("move", ""))


def _handle_team(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return team_tools.get_team_summary(battle)


def _handle_team_pokemon(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return team_tools.get_team_pokemon(battle, args.get("pokemon", ""))


def _handle_opponent(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return team_tools.get_opponent_team_summary(battle)


def _handle_opponent_pokemon(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return team_tools.get_opponent_pokemon(battle, args.get("pokemon", ""))


def _handle_log(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return battle_log_tools.get_battle_log(
        battle,
        args.get("format", "narrative"),
        args.get("from_turn", 1)
    )


def _handle_turn(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return battle_log_tools.get_turn_details(battle, args.get("turn", 1))


def _handle_field(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return field_tools.get_field_analysis(battle)


def _handle_type(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return type_tools.get_type_effectiveness(
        args.get("attack_type", ""),
        args.get("defender_types", [])
    )


def _handle_type_pokemon(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return type_tools.get_all_type_matchups(args.get("types", []))


def _handle_pokemon(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return info_tools.get_pokemon_info(args.get("pokemon", ""))


def _handle_move(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return info_tools.get_move_details(args.get("move", ""))


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
        description="Calculate damage for ALL your moves against the current opponent.",
        handler=_handle_damage,
        params=[],
    ),
    "damage_move": Tool(
        name="damage_move",
        description="Calculate damage for a specific move against the current opponent.",
        handler=_handle_damage_move,
        params=[
            ToolParam("move", "string", "Name of the move"),
        ],
    ),

    # Team tools
    "team": Tool(
        name="team",
        description="Get HP/status summary of your entire team.",
        handler=_handle_team,
        params=[],
    ),
    "team_pokemon": Tool(
        name="team_pokemon",
        description="Get detailed info about one of your Pokemon (moves, item, ability, HP, status, boosts).",
        handler=_handle_team_pokemon,
        params=[
            ToolParam("pokemon", "string", "Name of your Pokemon"),
        ],
    ),
    "opponent": Tool(
        name="opponent",
        description="Get summary of opponent's revealed team (Pokemon, HP, status, known moves).",
        handler=_handle_opponent,
        params=[],
    ),
    "opponent_pokemon": Tool(
        name="opponent_pokemon",
        description="Get known info about a specific opponent Pokemon.",
        handler=_handle_opponent_pokemon,
        params=[
            ToolParam("pokemon", "string", "Name of opponent's Pokemon"),
        ],
    ),

    # Battle log tools
    "log": Tool(
        name="log",
        description="Get the battle log. Use format 'narrative' (readable), 'detailed' (structured), or 'raw' (Showdown protocol).",
        handler=_handle_log,
        params=[
            ToolParam("format", "string", "Output format: narrative, detailed, or raw", required=False, enum=["narrative", "detailed", "raw"]),
            ToolParam("from_turn", "integer", "Start from this turn number", required=False),
        ],
    ),
    "turn": Tool(
        name="turn",
        description="Get detailed information about what happened on a specific turn.",
        handler=_handle_turn,
        params=[
            ToolParam("turn", "integer", "Turn number to examine"),
        ],
    ),

    # Field tools
    "field": Tool(
        name="field",
        description="Analyze current field conditions (weather, hazards, screens) and their effects.",
        handler=_handle_field,
        params=[],
    ),

    # Type tools
    "type": Tool(
        name="type",
        description="Get damage multiplier for an attack type against defender type(s). Returns 0, 0.25, 0.5, 1, 2, or 4.",
        handler=_handle_type,
        params=[
            ToolParam("attack_type", "string", "The attacking type (e.g., 'fire')"),
            ToolParam("defender_types", "array", "The defending Pokemon's types", items_type="string"),
        ],
    ),
    "type_pokemon": Tool(
        name="type_pokemon",
        description="Get all type matchups for a Pokemon - what types it's weak to, resists, and immune to.",
        handler=_handle_type_pokemon,
        params=[
            ToolParam("types", "array", "The Pokemon's type(s)", items_type="string"),
        ],
    ),

    # Info tools
    "pokemon": Tool(
        name="pokemon",
        description="Look up base stats, types, abilities, and typical role for a Pokemon species.",
        handler=_handle_pokemon,
        params=[
            ToolParam("pokemon", "string", "Pokemon species name"),
        ],
    ),
    "move": Tool(
        name="move",
        description="Look up move details (power, accuracy, type, effects). Syntax: 'moveinfo <name>'",
        handler=_handle_move,
        params=[
            ToolParam("move", "string", "Move name"),
        ],
    ),

    # Plan tools
    "plan": Tool(
        name="plan",
        description="Review your current strategic battle plan and goals.",
        handler=_handle_plan,
        params=[],
        needs_context=True,
    ),
    "plan_update": Tool(
        name="plan_update",
        description="Update your strategic plan: add goals, mark complete, abandon, or add notes.",
        handler=_handle_plan_update,
        params=[
            ToolParam("action", "string", "Action to perform", enum=["add_goal", "complete_goal", "abandon_goal", "add_note"]),
            ToolParam("goal_id", "integer", "Goal ID (for complete_goal, abandon_goal, add_note)", required=False),
            ToolParam("text", "string", "Goal text (for add_goal) or note text (for add_note)", required=False),
        ],
        needs_context=True,
    ),
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
            return "damage_move", {"move": " ".join(rest)}
        return "damage", {}

    # Team
    if cmd == "team":
        if rest:
            return "team_pokemon", {"pokemon": " ".join(rest)}
        return "team", {}

    # Opponent
    if cmd == "opponent":
        if rest:
            return "opponent_pokemon", {"pokemon": " ".join(rest)}
        return "opponent", {}

    # Log
    if cmd == "log":
        args = {}
        if rest:
            args["format"] = rest[0]
            if len(rest) > 1:
                try:
                    args["from_turn"] = int(rest[1])
                except ValueError:
                    pass
        return "log", args

    # Turn
    if cmd == "turn":
        if rest:
            try:
                return "turn", {"turn": int(rest[0])}
            except ValueError:
                pass
        return "turn", {"turn": 1}

    # Field
    if cmd == "field":
        return "field", {}

    # Type
    if cmd == "type":
        if not rest:
            return "help", {"tool": "type"}
        if "vs" in rest:
            vs_idx = rest.index("vs")
            attack_type = rest[0] if vs_idx > 0 else ""
            defender_types = rest[vs_idx + 1:]
            return "type", {"attack_type": attack_type, "defender_types": defender_types}
        else:
            # Interpret as pokemon types for matchup
            return "type_pokemon", {"types": rest}

    # Pokemon info
    if cmd == "pokemon" or cmd == "info":
        if rest:
            return "pokemon", {"pokemon": " ".join(rest)}
        return "help", {"tool": "pokemon"}

    # Move info - use "moveinfo <name>" to avoid conflict with "move <name>" action
    # Also support legacy "move <name> info" syntax
    if cmd == "moveinfo":
        if rest:
            return "move", {"move": " ".join(rest)}
        return "help", {"tool": "move"}
    if cmd == "move" and rest and rest[-1] == "info":
        # "move earthquake info" -> move info for earthquake
        return "move", {"move": " ".join(rest[:-1])}

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

    # Group by category (with command syntax notes)
    categories = {
        "Damage": ["damage", "damage_move"],
        "Team": ["team", "team_pokemon", "opponent", "opponent_pokemon"],
        "Battle Log": ["log", "turn"],
        "Field": ["field"],
        "Type": ["type", "type_pokemon"],
        "Info": ["pokemon", "move"],  # Note: use "moveinfo <name>" to avoid conflict with action
        "Planning": ["plan", "plan_update"],
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
