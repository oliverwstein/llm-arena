"""Damage calculation tools using SimpleHeuristicsPlayer's approach."""

from poke_env.player.player import AbstractBattle
from poke_env.battle.move_category import MoveCategory


def _stat_estimation(mon, stat: str) -> float:
    """
    Estimate effective stat value with boosts.
    Directly from SimpleHeuristicsPlayer._stat_estimation.
    """
    base = mon.base_stats.get(stat, 80)
    boost = mon.boosts.get(stat, 0)
    
    if boost >= 0:
        boost_mult = (2 + boost) / 2
    else:
        boost_mult = 2 / (2 - boost)
    
    # Simplified stat calculation: ((2 * base + 31) + 5) * boost
    return ((2 * base + 31) + 5) * boost_mult


def calc_move_score(move, attacker, defender, physical_ratio: float, special_ratio: float) -> float:
    """
    Calculate heuristic score for a move.
    Derived from SimpleHeuristicsPlayer.choose_singles_move scoring formula.
    """
    if move.category == MoveCategory.STATUS:
        return 0

    # Type effectiveness
    effectiveness = defender.damage_multiplier(move)
    
    # STAB bonus
    is_stab = move.type in [t for t in attacker.types if t is not None]
    stab = 1.5 if is_stab else 1.0
    
    # Physical vs Special ratio
    if move.category == MoveCategory.PHYSICAL:
        ratio = physical_ratio
    else:
        ratio = special_ratio

    return (
        move.base_power
        * stab
        * ratio
        * move.accuracy
        * move.expected_hits
        * effectiveness
    )


def calculate_all_damages(battle: AbstractBattle) -> dict:
    """
    Calculate damage scores for all available moves.
    Uses SimpleHeuristicsPlayer's scoring approach.
    """
    active = battle.active_pokemon
    opponent = battle.opponent_active_pokemon

    if not active:
        return {"error": "No active Pokemon"}
    if not opponent:
        return {"error": "No opponent Pokemon visible"}

    # Calculate stat ratios
    physical_ratio = _stat_estimation(active, "atk") / max(1, _stat_estimation(opponent, "def"))
    special_ratio = _stat_estimation(active, "spa") / max(1, _stat_estimation(opponent, "spd"))

    moves = []
    for move in battle.available_moves:
        if move.category == MoveCategory.STATUS:
            moves.append({
                "move": move.id,
                "type": move.type.name.lower() if move.type else "unknown",
                "category": "status",
                "is_status": True,
                "effect": _get_status_effect_description(move)
            })
            continue

        score = calc_move_score(move, active, opponent, physical_ratio, special_ratio)
        effectiveness = opponent.damage_multiplier(move)
        is_stab = move.type in [t for t in active.types if t is not None]

        # Convert score to approximate damage percentage
        # Heuristic: score of ~150-200 is roughly OHKO range for neutral matchups
        approx_percent = min(100, (score / 150) * 100)

        move_info = {
            "move": move.id,
            "type": move.type.name.lower() if move.type else "unknown",
            "category": move.category.name.lower(),
            "base_power": move.base_power,
            "heuristic_score": round(score, 1),
            "approx_percent": round(approx_percent, 1),
            "effectiveness": effectiveness,
            "is_stab": is_stab,
            "accuracy": move.accuracy,
            "priority": move.priority,
            "can_ohko": approx_percent >= 100,
            "can_2hko": approx_percent >= 50
        }

        # Add note for immunities
        if effectiveness == 0:
            move_info["note"] = f"{opponent.species} is immune to {move.type.name}"

        moves.append(move_info)

    # Sort by score descending
    moves.sort(key=lambda m: m.get("heuristic_score", 0), reverse=True)

    return {
        "your_pokemon": active.species,
        "opponent_pokemon": opponent.species,
        "moves": moves,
        "physical_ratio": round(physical_ratio, 2),
        "special_ratio": round(special_ratio, 2)
    }


def calculate_damage(battle: AbstractBattle, move_name: str) -> dict:
    """Calculate damage for a specific move. Wrapper around calculate_all_damages."""
    result = calculate_all_damages(battle)
    if "error" in result:
        return result

    # Normalize move name for comparison
    normalized = move_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    
    for move in result["moves"]:
        move_id = move["move"].lower().replace("-", "").replace("_", "")
        if move_id == normalized or normalized in move_id:
            return move

    return {"error": f"Move '{move_name}' not found in available moves"}


def _get_status_effect_description(move) -> str:
    """Get a description of a status move's effect."""
    move_id = move.id.lower()
    
    status_effects = {
        "stealthrock": "Sets Stealth Rock entry hazard",
        "spikes": "Sets Spikes entry hazard",
        "toxicspikes": "Sets Toxic Spikes entry hazard",
        "rapidspin": "Removes entry hazards",
        "defog": "Removes entry hazards and screens",
        "roost": "Heals 50% HP",
        "recover": "Heals 50% HP",
        "softboiled": "Heals 50% HP",
        "wish": "Heals next turn",
        "protect": "Blocks attacks this turn",
        "substitute": "Creates substitute (25% HP)",
        "swordsdance": "Raises Attack sharply (+2)",
        "dragondance": "Raises Attack and Speed (+1 each)",
        "nastyplot": "Raises Sp. Atk sharply (+2)",
        "calmmind": "Raises Sp. Atk and Sp. Def (+1 each)",
        "bulkup": "Raises Attack and Defense (+1 each)",
        "agility": "Raises Speed sharply (+2)",
        "thunderwave": "Paralyzes target",
        "willowisp": "Burns target",
        "toxic": "Badly poisons target",
        "hypnosis": "Puts target to sleep",
        "sleeppowder": "Puts target to sleep",
        "spore": "Puts target to sleep (100% accurate)",
        "taunt": "Prevents status moves",
        "encore": "Locks target into last move",
        "trick": "Swaps items with target",
        "uturn": "Switches out after attacking",
        "voltswitch": "Switches out after attacking",
        "batonpass": "Passes stat changes to switch-in",
        "whirlwind": "Forces opponent to switch",
        "roar": "Forces opponent to switch",
    }
    
    return status_effects.get(move_id, "Status move")
