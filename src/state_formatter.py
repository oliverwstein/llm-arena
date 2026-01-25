"""Format battle state for LLM consumption."""

from poke_env.player.player import Battle, Pokemon, Move
from typing import List


def get_pokemon_data(pokemon: Pokemon, full_info: bool = False) -> dict:
    """Get structured data for a single Pokemon."""
    data = {
        "species": pokemon.species,
        "hp_percent": round(pokemon.current_hp_fraction * 100),
    }
    
    if pokemon.status:
        data["status"] = pokemon.status.name
    
    if full_info:
        data["types"] = [t.name for t in pokemon.types if t]
        
        if pokemon.stats:
            data["stats"] = pokemon.stats
        
        if pokemon.ability:
            data["ability"] = pokemon.ability
        
        if pokemon.item:
            data["item"] = pokemon.item
    
    return data


def get_move_data(move: Move, pokemon: Pokemon = None, battle = None) -> dict:
    """Get structured data for a move."""
    data = {
        "name": move.id,
        "type": move.type.name,
        "base_power": move.base_power,
    }
    
    # Check battle.last_request for actual PP values
    if battle and battle.last_request:
        request = battle.last_request
        if 'active' in request and request['active']:
            active_data = request['active'][0]
            if 'moves' in active_data:
                for req_move in active_data['moves']:
                    req_id = req_move.get('id', '')
                    # Handle Hidden Power: move.id is "hiddenpowerice" but request has "hiddenpower"
                    if req_id == move.id or move.id.startswith(req_id):
                        data["pp"] = req_move.get('pp', 0)
                        data["max_pp"] = req_move.get('maxpp', 0)
                        break
    
    return data


def get_battle_state(battle: Battle) -> dict:
    """
    Get the complete battle state as a structured dict.

    Returns a dict containing:
    - turn: Turn number
    - active_pokemon: Your active Pokemon and available moves
    - opponent_active: Opponent's active Pokemon
    - available_switches: Your bench Pokemon
    - opponent_team: Known opponent Pokemon
    - field_conditions: Weather, terrain, hazards, screens
    - context: forced_switch info
    """
    state = {
        "turn": battle.turn,
    }
    
    # Check for forced switch
    if isinstance(battle.force_switch, bool):
        is_forced_switch = battle.force_switch
    else:
        is_forced_switch = any(battle.force_switch) if battle.force_switch else False
    
    if is_forced_switch:
        active_fainted = battle.active_pokemon and battle.active_pokemon.fainted
        if active_fainted:
            state["context"] = "pokemon_fainted"
        else:
            state["context"] = "forced_switch"  # U-turn, Volt Switch, etc.
    else:
        state["context"] = "normal"
    
    # Your active Pokemon
    if battle.active_pokemon and not battle.active_pokemon.fainted:
        state["active_pokemon"] = get_pokemon_data(battle.active_pokemon, full_info=True)
    
    # Available moves (only if not forced to switch)
    if battle.available_moves and not is_forced_switch:
        state["available_moves"] = [
            get_move_data(move, battle.active_pokemon, battle)
            for move in battle.available_moves
        ]
    
    # Available switches
    if battle.available_switches:
        state["available_switches"] = [
            get_pokemon_data(pokemon)
            for pokemon in battle.available_switches
        ]
    
    # Opponent info (using the team_tools function for consistency)
    from .tools.team_tools import get_opponent_summary
    state["opponent"] = get_opponent_summary(battle)
    
    # Field conditions
    field = {}
    if battle.weather:
        field["weather"] = [w.name for w in battle.weather.keys()]
    if battle.fields:
        field["terrain"] = [f.name for f in battle.fields.keys()]
    if battle.side_conditions:
        field["your_side"] = [sc.name for sc in battle.side_conditions.keys()]
    if battle.opponent_side_conditions:
        field["opponent_side"] = [sc.name for sc in battle.opponent_side_conditions.keys()]
    
    if field:
        state["field"] = field
    
    return state


def format_battle_state(battle: Battle) -> str:
    """
    Format the complete battle state as a human-readable string.
    
    This is a convenience wrapper that gets the state dict and formats it.
    """
    return format_state_dict(get_battle_state(battle))


def format_state_dict(state: dict) -> str:
    """
    Convert a battle state dict to a human-readable string.
    """
    lines = []
    
    # Header
    lines.append(f"=== Turn {state.get('turn', '?')} ===")
    lines.append("")
    
    # Context messages
    context = state.get("context", "normal")
    if context == "pokemon_fainted":
        lines.append("*** YOUR POKEMON FAINTED - YOU MUST SWITCH ***")
        lines.append("")
    elif context == "forced_switch":
        lines.append("*** YOU MUST SWITCH (U-turn/Volt Switch/Baton Pass) ***")
        lines.append("")
    
    # Your active Pokemon
    if "active_pokemon" in state:
        lines.append("YOUR ACTIVE POKEMON:")
        lines.append(_format_pokemon_str(state["active_pokemon"], full_info=True))
        lines.append("")
    
    # Available moves
    if "available_moves" in state:
        lines.append("AVAILABLE MOVES:")
        for move in state["available_moves"]:
            pp_str = f"{move.get('pp', '?')}/{move.get('max_pp', '?')} PP" if 'pp' in move else "?/? PP"
            lines.append(f"  - {move['name']} ({move['type']}, {move['base_power']} BP) {pp_str}")
        lines.append("")
    
    # Available switches
    if "available_switches" in state:
        lines.append("AVAILABLE SWITCHES:")
        for pokemon in state["available_switches"]:
            lines.append(f"  - {_format_pokemon_str(pokemon)}")
        lines.append("")
    
    # Opponent info
    if "opponent" in state:
        opp = state["opponent"]
        lines.append("OPPONENT:")
        if opp.get("active"):
            active = opp["active"]
            status = f" [{active['status']}]" if active.get('status') else ""
            fainted_str = " [FAINTED]" if active.get('fainted') else ""
            lines.append(f"  Active: {active['species']} ({active['hp_percent']}% HP){status}{fainted_str}")
            if active.get("moves"):
                known = [m for m in active['moves'] if m != "NOT_REVEALED"]
                if known:
                    lines.append(f"    Known moves: {', '.join(known)}")
        lines.append(f"  Fainted: {opp.get('fainted_count', 0)}")
        lines.append(f"  Not yet revealed: {opp.get('unrevealed_count', 0)}")
        lines.append("")
    
    # Field conditions
    if "field" in state:
        lines.append("FIELD CONDITIONS:")
        field = state["field"]
        if "weather" in field:
            lines.append(f"  Weather: {', '.join(field['weather'])}")
        if "terrain" in field:
            lines.append(f"  Terrain: {', '.join(field['terrain'])}")
        if "your_side" in field:
            lines.append(f"  Your side: {', '.join(field['your_side'])}")
        if "opponent_side" in field:
            lines.append(f"  Opponent side: {', '.join(field['opponent_side'])}")
        lines.append("")
    
    return "\n".join(lines)


def _format_pokemon_str(pokemon: dict, full_info: bool = False) -> str:
    """Format a pokemon dict as a string."""
    status = f" [{pokemon['status']}]" if 'status' in pokemon else ""
    line = f"{pokemon['species']} ({pokemon['hp_percent']}% HP){status}"
    
    if full_info:
        parts = [line]
        if "types" in pokemon:
            parts.append(f"  Type: {'/'.join(pokemon['types'])}")
        if "stats" in pokemon:
            parts.append(f"  Stats: {pokemon['stats']}")
        if "ability" in pokemon:
            parts.append(f"  Ability: {pokemon['ability']}")
        if "item" in pokemon:
            parts.append(f"  Item: {pokemon['item']}")
        return "\n".join(parts)
    
    return line


# Legacy functions for backward compatibility
def format_pokemon(pokemon: Pokemon, full_info: bool = False) -> str:
    """Format a single Pokemon's information. (Legacy wrapper)"""
    return _format_pokemon_str(get_pokemon_data(pokemon, full_info), full_info)


def format_move(move: Move, pokemon: Pokemon = None, battle = None) -> str:
    """Format a move option. (Legacy wrapper)"""
    data = get_move_data(move, pokemon, battle)
    pp_str = f"{data.get('pp', '?')}/{data.get('max_pp', '?')} PP" if 'pp' in data else "?/? PP"
    return f"{data['name']} ({data['type']}, {data['base_power']} BP) {pp_str}"
