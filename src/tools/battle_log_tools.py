"""Battle log tools for historical event queries."""

from poke_env.player.player import AbstractBattle
from ..event_formatter import format_event

from .context import get_battle_context


def get_battle_log(battle: AbstractBattle, from_turn: int = 0, turn: int = None) -> dict:
    """
    Get the battle log from Showdown as a list of formatted event strings.
    This is the OBJECTIVE record - exactly what happened.

    Args:
        battle: Current battle state
        from_turn: Start from this turn (default: 0 to include initial switch events)
        turn: If specified, get only this specific turn's events
    """
    # If a specific turn is requested, return just that turn's events
    if turn is not None:
        return _get_single_turn(battle, turn)
    
    ctx = get_battle_context(battle)
    perspective = battle.player_role or "p1"
    turns = []

    # Get all available observations, sorted by turn
    for turn_num in sorted(battle.observations.keys()):
        if turn_num < from_turn:
            continue

        obs = battle.observations[turn_num]
        events = _format_events_as_list(obs.events, perspective)
        turns.append({
            "turn": turn_num,
            "events": events
        })

    # Include current_observation if it has events not yet in observations
    if hasattr(battle, 'current_observation') and battle.current_observation:
        current_obs = battle.current_observation
        if hasattr(current_obs, 'events') and current_obs.events:
            # Check if this turn is already in our turns list
            current_turn_in_list = any(t["turn"] == battle.turn for t in turns)
            if not current_turn_in_list and battle.turn >= from_turn:
                events = _format_events_as_list(current_obs.events, perspective)
                turns.append({
                    "turn": battle.turn,
                    "events": events
                })

    return {
        "turns": turns,
        "current_turn": battle.turn,
        "context": "forced_switch" if ctx["force_switch"] else "normal"
    }


def _get_single_turn(battle: AbstractBattle, turn: int) -> dict:
    """Get events for a specific turn."""
    # Check if turn exists in observations
    if turn not in battle.observations:
        # Also check current_observation for the current turn
        if turn == battle.turn and hasattr(battle, 'current_observation') and battle.current_observation:
            obs = battle.current_observation
        else:
            return {"error": f"Turn {turn} not found. Battle is on turn {battle.turn}."}
    else:
        obs = battle.observations[turn]

    perspective = battle.player_role or "p1"
    events = _format_events_as_list(obs.events, perspective)
    
    return {
        "turn": turn,
        "events": events,
        "current_turn": battle.turn
    }


def _format_events_as_list(events: list, perspective: str) -> list[str]:
    """
    Format raw protocol events into a list of human-readable strings.
    
    Uses the same formatting as event_formatter.format_events, but returns
    a list instead of a newline-joined string.
    """
    result = []
    for event in events:
        formatted = format_event(event, perspective)
        if formatted:
            result.append(formatted)
    return result
