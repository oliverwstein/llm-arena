"""Format battle state for LLM consumption."""

from poke_env.player.player import Battle, Pokemon, Move
from typing import List


def format_pokemon(pokemon: Pokemon, full_info: bool = False) -> str:
    """Format a single Pokemon's information."""
    lines = []

    # Basic info
    hp_pct = pokemon.current_hp_fraction * 100
    status = f" [{pokemon.status.name}]" if pokemon.status else ""
    lines.append(f"{pokemon.species} ({hp_pct:.0f}% HP){status}")

    if full_info:
        # Types
        types = "/".join(t.name for t in pokemon.types if t)
        lines.append(f"  Type: {types}")

        # Stats (if known)
        if pokemon.stats:
            lines.append(f"  Stats: {pokemon.stats}")

        # Ability
        if pokemon.ability:
            lines.append(f"  Ability: {pokemon.ability}")

        # Item
        if pokemon.item:
            lines.append(f"  Item: {pokemon.item}")

        # Moves (for your own Pokemon)
        if pokemon.moves:
            move_strs = []
            for move in pokemon.moves.values():
                move_strs.append(f"{move.id} ({move.type.name}, {move.base_power} BP)")
            lines.append(f"  Moves: {', '.join(move_strs)}")

    return "\n".join(lines)


def format_move(move: Move, pokemon: Pokemon = None, battle = None) -> str:
    """Format a move option."""
    pp_info = "?/? PP"

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
                        pp = req_move.get('pp', '?')
                        maxpp = req_move.get('maxpp', '?')
                        pp_info = f"{pp}/{maxpp} PP"
                        break

    return f"{move.id} ({move.type.name}, {move.base_power} BP) {pp_info}"


def format_battle_state(battle: Battle) -> str:
    """
    Format the complete battle state for an LLM.

    Returns a human-readable text description of:
    - Turn number
    - Your active Pokemon and available moves
    - Opponent's active Pokemon
    - Your bench
    - Known opponent Pokemon
    - Field conditions
    """
    lines = []

    # Header
    lines.append(f"=== Turn {battle.turn} ===")
    lines.append("")

    # Check for forced switch
    # force_switch is a bool in singles, list in doubles
    if isinstance(battle.force_switch, bool):
        is_forced_switch = battle.force_switch
    else:
        is_forced_switch = any(battle.force_switch) if battle.force_switch else False
    if is_forced_switch:
        # Distinguish between faint and self-switch (U-turn, Volt Switch, etc.)
        active_fainted = battle.active_pokemon and battle.active_pokemon.fainted
        if active_fainted:
            lines.append("*** YOUR POKEMON FAINTED - YOU MUST SWITCH ***")
        else:
            lines.append("*** YOU MUST SWITCH (U-turn/Volt Switch/Baton Pass) ***")
        lines.append("")

    # Your active Pokemon
    if battle.active_pokemon and not battle.active_pokemon.fainted:
        lines.append("YOUR ACTIVE POKEMON:")
        lines.append(format_pokemon(battle.active_pokemon, full_info=True))
        lines.append("")

    # Available moves (only if not forced to switch)
    if battle.available_moves and not is_forced_switch:
        lines.append("AVAILABLE MOVES:")
        for move in battle.available_moves:
            lines.append(f"  - {format_move(move, battle.active_pokemon, battle)}")
        lines.append("")

    # Available switches
    if battle.available_switches:
        lines.append("AVAILABLE SWITCHES:")
        for pokemon in battle.available_switches:
            lines.append(f"  - {format_pokemon(pokemon)}")
        lines.append("")

    # Opponent's active Pokemon (may be None at battle start)
    if battle.opponent_active_pokemon:
        lines.append("OPPONENT'S ACTIVE POKEMON:")
        lines.append(format_pokemon(battle.opponent_active_pokemon))

        # Known moves
        if battle.opponent_active_pokemon.moves:
            known_moves = list(battle.opponent_active_pokemon.moves.keys())
            lines.append(f"  Known moves: {', '.join(known_moves)}")
        lines.append("")

    # Your bench (excluding fainted)
    bench = [p for p in battle.team.values()
             if p != battle.active_pokemon and not p.fainted]
    if bench:
        lines.append("YOUR BENCH:")
        for pokemon in bench:
            lines.append(f"  - {format_pokemon(pokemon)}")
        lines.append("")

    # Known opponent Pokemon
    if battle.opponent_team:
        opp_pokemon = [p for p in battle.opponent_team.values()
                       if p != battle.opponent_active_pokemon]
        if opp_pokemon:
            lines.append("KNOWN OPPONENT POKEMON:")
            for pokemon in opp_pokemon:
                lines.append(f"  - {format_pokemon(pokemon)}")
            lines.append("")

    # Field conditions
    # Note: weather, fields, side_conditions are Dict[Enum, int] not single values
    field_conditions = []
    if battle.weather:
        weather_names = [w.name for w in battle.weather.keys()]
        field_conditions.append(f"Weather: {', '.join(weather_names)}")
    if battle.fields:
        field_names = [f.name for f in battle.fields.keys()]
        field_conditions.append(f"Terrain: {', '.join(field_names)}")

    # Side conditions (hazards, screens, etc.)
    if battle.side_conditions:
        sc_names = [sc.name for sc in battle.side_conditions.keys()]
        field_conditions.append(f"Your side: {', '.join(sc_names)}")
    if battle.opponent_side_conditions:
        osc_names = [sc.name for sc in battle.opponent_side_conditions.keys()]
        field_conditions.append(f"Opponent side: {', '.join(osc_names)}")

    if field_conditions:
        lines.append("FIELD CONDITIONS:")
        for condition in field_conditions:
            lines.append(f"  {condition}")
        lines.append("")

    return "\n".join(lines)
