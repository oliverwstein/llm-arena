"""Format raw Pokemon Showdown protocol events to human-readable text.

Ported from the official Pokemon Showdown client's BattleTextParser.
The client source is at: https://github.com/smogon/pokemon-showdown-client

This provides LLMs with readable battle narratives instead of raw protocol.
"""

from typing import Optional


def format_pokemon_name(pokemon_id: str) -> str:
    """
    Extract pokemon name from ID like 'p1a: Bronzong' -> 'Bronzong'.
    """
    if not pokemon_id:
        return ""
    if ": " in pokemon_id:
        return pokemon_id.split(": ", 1)[1].strip()
    return pokemon_id.strip()


def get_side_prefix(pokemon_id: str, perspective: str = "p1") -> str:
    """
    Determine if pokemon is on our side or opponent's.
    Returns prefix like 'The opposing ' or empty string.
    """
    if not pokemon_id or len(pokemon_id) < 2:
        return ""
    side = pokemon_id[:2]
    if side == perspective:
        return ""
    return "The opposing "


def format_event(event: list[str], perspective: str = "p1") -> Optional[str]:
    """
    Convert a single protocol event to human-readable text.
    
    Args:
        event: List of event parts (e.g., ['', 'move', 'p1a: Bronzong', 'Protect', ...])
               Note: poke-env events typically have an empty first element
        perspective: Player perspective ('p1' or 'p2')
    
    Returns:
        Human-readable string, or None if event should be hidden
    """
    if not event or len(event) < 2:
        return None
    
    # poke-env events have an empty first element; the command is at index 1
    # Handle both formats: ['', 'move', ...] and ['move', ...]
    if event[0] == '':
        cmd = event[1] if len(event) > 1 else ""
        # Shift indices for the rest of the event data
        event = event[1:]  # Now event[0] is the command
    else:
        cmd = event[0]
    
    # Skip meta events
    if cmd in ('', 'upkeep', 'request', 't:', 'c:', 'debug', 'inactive', 'inactiveoff'):
        return None
    
    # Turn marker
    if cmd == 'turn':
        turn_num = event[1] if len(event) > 1 else "?"
        return f"\n=== Turn {turn_num} ===\n"
    
    # Move used
    if cmd == 'move':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        move = event[2] if len(event) > 2 else "???"
        prefix = get_side_prefix(event[1], perspective)
        return f"{prefix}{pokemon} used {move}!"
    
    # Switch in
    if cmd == 'switch' or cmd == 'drag':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        prefix = get_side_prefix(event[1], perspective)
        action = "sent out" if cmd == 'switch' else "was dragged out!"
        if prefix:
            return f"{prefix.strip()} sent out {pokemon}!"
        return f"Go! {pokemon}!"
    
    # Damage
    if cmd == '-damage':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        prefix = get_side_prefix(event[1], perspective)
        hp_status = event[2] if len(event) > 2 else "???"
        
        # Check for faint
        if hp_status.startswith("0") or "fnt" in hp_status:
            return None  # Handled by faint event
        
        # Check for source
        source = None
        for part in event:
            if part.startswith("[from]"):
                source = part[6:].strip()
                break
        
        if source:
            return f"{prefix}{pokemon} was hurt by {source}!"
        return f"{prefix}{pokemon} took damage!"
    
    # Heal
    if cmd == '-heal':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        prefix = get_side_prefix(event[1], perspective)
        
        source = None
        for part in event:
            if part.startswith("[from]"):
                source = part[6:].strip()
                break
        
        if source:
            return f"{prefix}{pokemon} restored HP using its {source}!"
        return f"{prefix}{pokemon} restored some HP!"
    
    # Faint
    if cmd == 'faint':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        prefix = get_side_prefix(event[1], perspective)
        return f"{prefix}{pokemon} fainted!"
    
    # Status
    if cmd == '-status':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        status = event[2] if len(event) > 2 else "???"
        prefix = get_side_prefix(event[1], perspective)
        
        status_text = {
            'brn': 'was burned',
            'par': 'is paralyzed! It may be unable to move',
            'slp': 'fell asleep',
            'frz': 'was frozen solid',
            'psn': 'was poisoned',
            'tox': 'was badly poisoned',
        }.get(status, f'got status: {status}')
        
        return f"{prefix}{pokemon} {status_text}!"
    
    # Cure status
    if cmd == '-curestatus':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        prefix = get_side_prefix(event[1], perspective)
        return f"{prefix}{pokemon} was cured of its status condition!"
    
    # Boost
    if cmd == '-boost':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        stat = event[2] if len(event) > 2 else "???"
        amount = event[3] if len(event) > 3 else "1"
        prefix = get_side_prefix(event[1], perspective)
        
        stat_name = {
            'atk': 'Attack', 'def': 'Defense', 'spa': 'Sp. Atk',
            'spd': 'Sp. Def', 'spe': 'Speed', 'accuracy': 'accuracy',
            'evasion': 'evasiveness'
        }.get(stat, stat)
        
        if amount == "1":
            return f"{prefix}{pokemon}'s {stat_name} rose!"
        elif amount == "2":
            return f"{prefix}{pokemon}'s {stat_name} rose sharply!"
        else:
            return f"{prefix}{pokemon}'s {stat_name} rose drastically!"
    
    # Unboost
    if cmd == '-unboost':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        stat = event[2] if len(event) > 2 else "???"
        amount = event[3] if len(event) > 3 else "1"
        prefix = get_side_prefix(event[1], perspective)
        
        stat_name = {
            'atk': 'Attack', 'def': 'Defense', 'spa': 'Sp. Atk',
            'spd': 'Sp. Def', 'spe': 'Speed', 'accuracy': 'accuracy',
            'evasion': 'evasiveness'
        }.get(stat, stat)
        
        if amount == "1":
            return f"{prefix}{pokemon}'s {stat_name} fell!"
        elif amount == "2":
            return f"{prefix}{pokemon}'s {stat_name} fell harshly!"
        else:
            return f"{prefix}{pokemon}'s {stat_name} fell severely!"
    
    # Super effective / not very effective
    if cmd == '-supereffective':
        return "It's super effective!"
    
    if cmd == '-resisted':
        return "It's not very effective..."
    
    # Critical hit
    if cmd == '-crit':
        return "A critical hit!"
    
    # Miss
    if cmd == '-miss':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        prefix = get_side_prefix(event[1], perspective)
        target = format_pokemon_name(event[2]) if len(event) > 2 else None
        if target:
            return f"{prefix}{pokemon}'s attack missed {target}!"
        return f"{prefix}{pokemon}'s attack missed!"
    
    # Immune
    if cmd == '-immune':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        prefix = get_side_prefix(event[1], perspective)
        
        # Check for ability source
        for part in event:
            if part.startswith("[from] ability:"):
                ability = part[15:].strip()
                return f"[{pokemon}'s {ability}]\nIt doesn't affect {prefix.lower()}{pokemon}..."
        
        return f"It doesn't affect {prefix.lower()}{pokemon}..."
    
    # Fail
    if cmd == '-fail':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else None
        if pokemon:
            prefix = get_side_prefix(event[1], perspective)
            return f"But it failed for {prefix.lower()}{pokemon}!"
        return "But it failed!"
    
    # Protect / blocking moves
    if cmd == '-singleturn':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        move = event[2] if len(event) > 2 else ""
        prefix = get_side_prefix(event[1], perspective)
        
        if 'protect' in move.lower():
            return f"{prefix}{pokemon} protected itself!"
        return f"{prefix}{pokemon} is preparing for {move}!"
    
    # Start of a volatile status
    if cmd == '-start':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        effect = event[2] if len(event) > 2 else "???"
        prefix = get_side_prefix(event[1], perspective)
        
        effect_lower = effect.lower()
        if 'substitute' in effect_lower:
            return f"{prefix}{pokemon} put in a substitute!"
        if 'confusion' in effect_lower:
            return f"{prefix}{pokemon} became confused!"
        if 'taunt' in effect_lower:
            return f"{prefix}{pokemon} fell for the taunt!"
        if 'leech seed' in effect_lower:
            return f"{prefix}{pokemon} was seeded!"
        
        return f"{prefix}{pokemon}: {effect} started!"
    
    # End of a volatile status
    if cmd == '-end':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        effect = event[2] if len(event) > 2 else "???"
        prefix = get_side_prefix(event[1], perspective)
        
        effect_lower = effect.lower()
        if 'substitute' in effect_lower:
            return f"{prefix}{pokemon}'s substitute faded!"
        if 'confusion' in effect_lower:
            return f"{prefix}{pokemon} snapped out of its confusion!"
        
        return f"{prefix}{pokemon}: {effect} ended."
    
    # Can't move
    if cmd == 'cant':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        reason = event[2] if len(event) > 2 else ""
        prefix = get_side_prefix(event[1], perspective)
        
        if 'slp' in reason.lower():
            return f"{prefix}{pokemon} is fast asleep."
        if 'par' in reason.lower():
            return f"{prefix}{pokemon} is paralyzed! It can't move!"
        if 'frz' in reason.lower():
            return f"{prefix}{pokemon} is frozen solid!"
        if 'flinch' in reason.lower():
            return f"{prefix}{pokemon} flinched and couldn't move!"
        if 'taunt' in reason.lower():
            return f"{prefix}{pokemon} can't use that move after the taunt!"
        
        return f"{prefix}{pokemon} can't move! ({reason})"
    
    # Weather
    if cmd == '-weather':
        weather = event[1] if len(event) > 1 else "none"
        
        weather_text = {
            'RainDance': "Rain continues to fall.",
            'Sandstorm': "The sandstorm is raging.",
            'SunnyDay': "The sunlight is strong.",
            'Hail': "The hail is crashing down.",
            'none': "The weather cleared up!",
        }.get(weather, f"Weather: {weather}")
        
        return weather_text
    
    # Side conditions (entry hazards, screens)
    if cmd == '-sidestart':
        side = event[1][:2] if len(event) > 1 else "??"
        condition = event[2] if len(event) > 2 else "???"
        
        # Determine if it's our side or opponent's
        side_name = "your" if side == perspective else "the opposing"
        
        condition_lower = condition.lower()
        if 'stealth rock' in condition_lower:
            return f"Pointed stones float in the air around {side_name} team!"
        if 'spikes' in condition_lower:
            return f"Spikes were scattered on the ground around {side_name} team!"
        if 'toxic spikes' in condition_lower:
            return f"Poison spikes were scattered on the ground around {side_name} team!"
        if 'reflect' in condition_lower:
            return f"Reflect raised {side_name} team's Defense!"
        if 'light screen' in condition_lower:
            return f"Light Screen raised {side_name} team's Sp. Def!"
        
        return f"{condition} was set on {side_name} side!"
    
    if cmd == '-sideend':
        side = event[1][:2] if len(event) > 1 else "??"
        condition = event[2] if len(event) > 2 else "???"
        side_name = "your" if side == perspective else "the opposing"
        return f"{condition} wore off for {side_name} team!"
    
    # Ability activation
    if cmd == '-ability':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        ability = event[2] if len(event) > 2 else "???"
        prefix = get_side_prefix(event[1], perspective)
        return f"[{prefix}{pokemon}'s {ability}]"
    
    # Activate (miscellaneous)
    if cmd == '-activate':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else ""
        effect = event[2] if len(event) > 2 else ""
        
        if 'confusion' in effect.lower() and pokemon:
            prefix = get_side_prefix(event[1], perspective)
            return f"{prefix}{pokemon} is confused!"
        
        return None  # Skip most -activate messages
    
    # Item
    if cmd == '-item':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        item = event[2] if len(event) > 2 else "???"
        prefix = get_side_prefix(event[1], perspective)
        return f"{prefix}{pokemon} is holding {item}!"
    
    if cmd == '-enditem':
        pokemon = format_pokemon_name(event[1]) if len(event) > 1 else "???"
        item = event[2] if len(event) > 2 else "???"
        prefix = get_side_prefix(event[1], perspective)
        return f"{prefix}{pokemon}'s {item} was consumed!"
    
    # Winner
    if cmd == 'win':
        winner = event[1] if len(event) > 1 else "Someone"
        return f"\n{winner} won the battle!"
    
    if cmd == 'tie':
        return "\nThe battle ended in a tie!"
    
    # Hint message
    if cmd == '-hint':
        hint = event[1] if len(event) > 1 else ""
        return f"({hint})"
    
    # Message
    if cmd == '-message':
        message = event[1] if len(event) > 1 else ""
        return message
    
    # Default: return None for unhandled events
    return None


def format_events(events: list[list[str]], perspective: str = "p1") -> str:
    """
    Convert a list of protocol events to a human-readable narrative.
    
    Args:
        events: List of events, each event is a list of strings
        perspective: Player perspective ('p1' or 'p2')
    
    Returns:
        Multi-line string with the battle narrative
    """
    lines = []
    for event in events:
        formatted = format_event(event, perspective)
        if formatted:
            lines.append(formatted)
    
    return "\n".join(lines)
