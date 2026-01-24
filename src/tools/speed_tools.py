"""Speed comparison tools."""

from poke_env.player.player import AbstractBattle


def get_speed_comparison(battle: AbstractBattle, move_name: str = None) -> dict:
    """
    Compare speed stats to determine who moves first.
    Accounts for paralysis, boosts, and priority moves.
    
    Args:
        battle: Current battle state
        move_name: Optional move to check priority for
    """
    active = battle.active_pokemon
    opponent = battle.opponent_active_pokemon
    
    if not active:
        return {"error": "No active Pokemon"}
    if not opponent:
        return {"error": "No opponent Pokemon visible"}
    
    # Calculate effective speeds
    your_speed = _calc_effective_speed(active)
    opp_speed = _calc_effective_speed(opponent)
    
    # Base speed comparison
    you_are_faster = your_speed > opp_speed
    
    result = {
        "your_pokemon": active.species,
        "opponent_pokemon": opponent.species,
        "your_speed": round(your_speed),
        "opponent_speed": round(opp_speed),
        "you_are_faster": you_are_faster,
        "speed_tie": your_speed == opp_speed
    }
    
    # Check for status effects
    notes = []
    if active.status and active.status.name == "PAR":
        notes.append("Your Pokemon is paralyzed (speed halved)")
    if opponent.status and opponent.status.name == "PAR":
        notes.append("Opponent is paralyzed (speed halved)")
    
    # Check for speed boosts
    your_boost = active.boosts.get("spe", 0)
    opp_boost = opponent.boosts.get("spe", 0)
    if your_boost != 0:
        notes.append(f"Your speed boost: {'+' if your_boost > 0 else ''}{your_boost}")
    if opp_boost != 0:
        notes.append(f"Opponent speed boost: {'+' if opp_boost > 0 else ''}{opp_boost}")
    
    # Check priority if move specified
    if move_name:
        priority = _get_move_priority(battle, move_name)
        if priority is not None:
            result["move_priority"] = priority
            if priority > 0:
                result["with_move_you_go_first"] = True
                notes.append(f"{move_name} has +{priority} priority, so you move first")
            elif priority < 0:
                result["with_move_you_go_first"] = False
                notes.append(f"{move_name} has {priority} priority, so you move last")
            else:
                result["with_move_you_go_first"] = you_are_faster
    
    result["notes"] = notes
    return result


def _calc_effective_speed(pokemon) -> float:
    """Calculate effective speed stat with boosts and status."""
    # Base speed estimation
    base_speed = pokemon.base_stats.get("spe", 80)
    
    # Apply boost
    boost = pokemon.boosts.get("spe", 0)
    if boost >= 0:
        boost_mult = (2 + boost) / 2
    else:
        boost_mult = 2 / (2 - boost)
    
    # Estimate effective speed (simplified formula)
    effective = ((2 * base_speed + 31) + 5) * boost_mult
    
    # Apply paralysis
    if pokemon.status and pokemon.status.name == "PAR":
        effective *= 0.25  # Gen 4 paralysis quarters speed
    
    return effective


def _get_move_priority(battle: AbstractBattle, move_name: str) -> int | None:
    """Get the priority of a move from available moves."""
    normalized = move_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    
    for move in battle.available_moves:
        move_id = move.id.lower().replace("-", "").replace("_", "")
        if move_id == normalized or normalized in move_id:
            return move.priority
    
    return None
