"""Battle context utilities for tool decision-making."""

from poke_env.player.player import AbstractBattle


def get_battle_context(battle: AbstractBattle) -> dict:
    """
    Get current battle context before tool execution.

    Tools should call this first to understand what kind of decision
    is being made and adapt their responses accordingly.

    Returns:
        dict with:
        - turn: Current turn number
        - force_switch: Whether this is a forced switch (faint, etc.)
        - active_fainted: Whether the active Pokemon has fainted
        - decision_type: "move" or "switch"
        - available_pokemon: List of available Pokemon for switch
    """
    active = battle.active_pokemon
    active_fainted = active.fainted if active else True
    force_switch = battle.force_switch

    # Determine decision type
    if force_switch or active_fainted or not battle.available_moves:
        decision_type = "switch"
    else:
        decision_type = "move"

    return {
        "turn": battle.turn,
        "force_switch": force_switch,
        "active_fainted": active_fainted,
        "decision_type": decision_type,
        "available_pokemon": [p.species for p in battle.available_switches],
    }


def check_move_context(battle: AbstractBattle) -> str | None:
    """
    Check if we're in a valid context for move-related tools.

    Returns:
        None if context is valid for move tools.
        Error message string if tools should not be used.
    """
    ctx = get_battle_context(battle)

    if ctx["force_switch"]:
        return f"Cannot use this tool during forced switch. You must switch to one of: {', '.join(ctx['available_pokemon'])}"

    if ctx["active_fainted"]:
        return f"Your active Pokemon has fainted. You must switch to one of: {', '.join(ctx['available_pokemon'])}"

    return None
