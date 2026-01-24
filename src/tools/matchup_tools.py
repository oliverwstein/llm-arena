"""Matchup evaluation tools using SimpleHeuristicsPlayer's approach."""

from poke_env.player.player import AbstractBattle


# Constants from SimpleHeuristicsPlayer
SPEED_TIER_COEFICIENT = 0.1
HP_FRACTION_COEFICIENT = 0.4
SWITCH_OUT_MATCHUP_THRESHOLD = -2


def _estimate_matchup(mon, opponent) -> float:
    """
    Estimate matchup score between two Pokemon.
    Directly based on SimpleHeuristicsPlayer._estimate_matchup.
    
    Positive score = favorable, negative = unfavorable.
    """
    if mon is None or opponent is None:
        return 0.0

    # Type effectiveness: how well we hit them vs how well they hit us
    # Get max multiplier from our types against them
    our_offense = 1.0
    for t in mon.types:
        if t is not None:
            mult = opponent.damage_multiplier(t)
            if mult > our_offense:
                our_offense = mult

    # Get max multiplier from their types against us
    their_offense = 1.0
    for t in opponent.types:
        if t is not None:
            mult = mon.damage_multiplier(t)
            if mult > their_offense:
                their_offense = mult

    # Speed tier comparison
    speed_diff = 0
    mon_speed = mon.base_stats.get("spe", 80)
    opp_speed = opponent.base_stats.get("spe", 80)
    if mon_speed > opp_speed:
        speed_diff = SPEED_TIER_COEFICIENT
    elif opp_speed > mon_speed:
        speed_diff = -SPEED_TIER_COEFICIENT

    # HP fraction comparison
    hp_diff = (mon.current_hp_fraction - opponent.current_hp_fraction) * HP_FRACTION_COEFICIENT

    # Combined score
    score = (our_offense - their_offense) + speed_diff + hp_diff
    
    return score


def evaluate_matchup(battle: AbstractBattle, pokemon_name: str = None) -> dict:
    """
    Evaluate matchup score using SimpleHeuristicsPlayer's formula.
    Positive score = favorable, negative = unfavorable.
    """
    # Get the Pokemon to evaluate
    if pokemon_name:
        mon = None
        for p in battle.team.values():
            if p.species.lower() == pokemon_name.lower():
                mon = p
                break
        if not mon:
            return {"error": f"Pokemon '{pokemon_name}' not found on your team"}
    else:
        mon = battle.active_pokemon

    opponent = battle.opponent_active_pokemon

    if not mon:
        return {"error": "No Pokemon specified and no active Pokemon"}
    if not opponent:
        return {"error": "No opponent Pokemon visible"}

    score = _estimate_matchup(mon, opponent)

    # Interpret the score
    if score > 1.0:
        verdict = "strongly favorable"
    elif score > 0.3:
        verdict = "favorable"
    elif score > -0.3:
        verdict = "neutral"
    elif score > -1.0:
        verdict = "unfavorable"
    else:
        verdict = "strongly unfavorable"

    # Break down the components for transparency
    our_offense = 1.0
    for t in mon.types:
        if t is not None:
            mult = opponent.damage_multiplier(t)
            if mult > our_offense:
                our_offense = mult

    their_offense = 1.0
    for t in opponent.types:
        if t is not None:
            mult = mon.damage_multiplier(t)
            if mult > their_offense:
                their_offense = mult

    mon_speed = mon.base_stats.get("spe", 80)
    opp_speed = opponent.base_stats.get("spe", 80)
    if mon_speed > opp_speed:
        speed_diff = SPEED_TIER_COEFICIENT
    elif opp_speed > mon_speed:
        speed_diff = -SPEED_TIER_COEFICIENT
    else:
        speed_diff = 0

    hp_diff = (mon.current_hp_fraction - opponent.current_hp_fraction) * HP_FRACTION_COEFICIENT

    return {
        "your_pokemon": mon.species,
        "opponent_pokemon": opponent.species,
        "matchup_score": round(score, 2),
        "verdict": verdict,
        "factors": {
            "offensive_typing": round(our_offense - 1, 2),
            "defensive_typing": round(-(their_offense - 1), 2),
            "speed_tier": round(speed_diff, 2),
            "hp_difference": round(hp_diff, 2)
        },
        "is_active": mon == battle.active_pokemon
    }


def evaluate_all_matchups(battle: AbstractBattle) -> dict:
    """Evaluate matchups for all your Pokemon against current opponent."""
    opponent = battle.opponent_active_pokemon
    if not opponent:
        return {"error": "No opponent Pokemon visible"}

    matchups = []
    for pokemon in battle.team.values():
        if pokemon.fainted:
            continue

        score = _estimate_matchup(pokemon, opponent)
        matchups.append({
            "pokemon": pokemon.species,
            "matchup_score": round(score, 2),
            "is_active": pokemon == battle.active_pokemon,
            "hp_percent": round(pokemon.current_hp_fraction * 100, 1)
        })

    # Sort by matchup score descending
    matchups.sort(key=lambda m: m["matchup_score"], reverse=True)

    return {
        "opponent": opponent.species,
        "matchups": matchups,
        "best_matchup": matchups[0]["pokemon"] if matchups else None
    }


def should_switch(battle: AbstractBattle) -> dict:
    """
    Determine if switching is advisable.
    Based on SimpleHeuristicsPlayer._should_switch_out logic.
    """
    active = battle.active_pokemon
    opponent = battle.opponent_active_pokemon

    if not active or not opponent:
        return {"should_switch": False, "reason": "Missing Pokemon"}

    current_matchup = _estimate_matchup(active, opponent)

    # Find best switch
    best_switch = None
    best_score = current_matchup
    for mon in battle.available_switches:
        score = _estimate_matchup(mon, opponent)
        if score > best_score:
            best_score = score
            best_switch = mon

    # Check if current matchup is bad enough to switch
    should = current_matchup < SWITCH_OUT_MATCHUP_THRESHOLD

    return {
        "should_switch": should,
        "current_matchup": round(current_matchup, 2),
        "best_switch": best_switch.species if best_switch else None,
        "best_switch_matchup": round(best_score, 2) if best_switch else None,
        "threshold": SWITCH_OUT_MATCHUP_THRESHOLD,
        "reason": "Matchup below threshold" if should else "Matchup acceptable"
    }
