"""Battle log tools for historical event queries."""

from poke_env.player.player import AbstractBattle
from ..event_formatter import format_events


def get_battle_log(battle: AbstractBattle, format: str = "narrative", from_turn: int = 1) -> dict:
    """
    Get the complete battle log from Showdown.
    This is the OBJECTIVE record - exactly what happened.
    
    Args:
        battle: Current battle state
        format: "narrative" (readable), "detailed" (structured), "raw" (protocol)
        from_turn: Start from this turn (default: 1)
    """
    perspective = battle.player_role or "p1"
    turns = []

    for turn_num in sorted(battle.observations.keys()):
        if turn_num < from_turn:
            continue

        obs = battle.observations[turn_num]

        if format == "narrative":
            event_text = format_events(obs.events, perspective)
            turns.append({
                "turn": turn_num,
                "events": event_text
            })

        elif format == "detailed":
            actions = _parse_actions(obs.events, perspective)
            turns.append({
                "turn": turn_num,
                "actions": actions
            })

        elif format == "raw":
            turns.append({
                "turn": turn_num,
                "protocol": ["|".join(event) for event in obs.events]
            })

    return {"turns": turns, "current_turn": battle.turn}


def get_turn_details(battle: AbstractBattle, turn: int) -> dict:
    """Get detailed information about a specific turn."""

    if turn not in battle.observations:
        return {"error": f"Turn {turn} not found. Battle is on turn {battle.turn}."}

    obs = battle.observations[turn]
    perspective = battle.player_role or "p1"

    return {
        "turn": turn,
        "events_narrative": format_events(obs.events, perspective),
        "events_detailed": _parse_actions(obs.events, perspective),
        "events_raw": ["|".join(event) for event in obs.events]
    }


def _parse_actions(events: list, perspective: str) -> list:
    """Parse raw events into structured action list."""
    actions = []

    for event in events:
        if not event:
            continue

        event_type = event[0] if event else ""

        if event_type == "move":
            actions.append({
                "type": "move",
                "pokemon": event[1].split(": ")[-1] if len(event) > 1 else "",
                "move": event[2] if len(event) > 2 else "",
                "target": event[3].split(": ")[-1] if len(event) > 3 else ""
            })

        elif event_type == "-damage":
            pokemon = event[1].split(": ")[-1] if len(event) > 1 else ""
            hp = event[2] if len(event) > 2 else ""
            actions.append({
                "type": "damage",
                "pokemon": pokemon,
                "hp_after": hp
            })

        elif event_type == "-heal":
            pokemon = event[1].split(": ")[-1] if len(event) > 1 else ""
            hp = event[2] if len(event) > 2 else ""
            actions.append({
                "type": "heal",
                "pokemon": pokemon,
                "hp_after": hp
            })

        elif event_type == "switch":
            pokemon = event[1].split(": ")[-1] if len(event) > 1 else ""
            hp = event[3] if len(event) > 3 else ""
            actions.append({
                "type": "switch",
                "pokemon": pokemon,
                "hp": hp
            })

        elif event_type == "faint":
            pokemon = event[1].split(": ")[-1] if len(event) > 1 else ""
            actions.append({
                "type": "faint",
                "pokemon": pokemon
            })

        elif event_type == "-status":
            pokemon = event[1].split(": ")[-1] if len(event) > 1 else ""
            status = event[2] if len(event) > 2 else ""
            actions.append({
                "type": "status",
                "pokemon": pokemon,
                "status": status
            })

        elif event_type in ["-supereffective", "-resisted", "-crit", "-miss"]:
            actions.append({"type": event_type.lstrip("-")})

    return actions
