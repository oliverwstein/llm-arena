"""Damage calculation tools using Gen 4 damage formula."""

from poke_env.player.player import AbstractBattle
from poke_env.battle.move_category import MoveCategory

from .context import check_move_context


def _get_stat(pokemon, stat: str) -> int:
    """Get a Pokemon's effective stat value with boosts applied."""
    if pokemon.stats and pokemon.stats.get(stat):
        base_stat = pokemon.stats[stat]
    else:
        # Fallback estimate: level 100, 31 IVs, 0 EVs, neutral nature
        base_value = pokemon.base_stats.get(stat, 80)
        if stat == "hp":
            base_stat = ((2 * base_value + 31) * 100 // 100) + 100 + 10
        else:
            base_stat = ((2 * base_value + 31) * 100 // 100) + 5

    # Apply stat boosts
    boost = pokemon.boosts.get(stat, 0)
    if boost >= 0:
        multiplier = (2 + boost) / 2
    else:
        multiplier = 2 / (2 - boost)

    return int(base_stat * multiplier)


def _get_stat_range(pokemon, stat: str) -> tuple[int, int]:
    """
    Get min and max possible stat values for a Pokemon.
    Used for opponent Pokemon where we don't know exact EVs/IVs/nature.
    Returns (min_stat, max_stat) with boosts applied.
    """
    base_value = pokemon.base_stats.get(stat, 80)

    if stat == "hp":
        # HP formula: ((2 * Base + IV + EV/4) * Level / 100) + Level + 10
        # Min: 0 IVs, 0 EVs
        min_stat = ((2 * base_value + 0) * 100 // 100) + 100 + 10
        # Max: 31 IVs, 252 EVs (63 at level 100)
        max_stat = ((2 * base_value + 31 + 63) * 100 // 100) + 100 + 10
    else:
        # Other stats: ((2 * Base + IV + EV/4) * Level / 100) + 5) * Nature
        # Min: 0 IVs, 0 EVs, hindering nature (0.9)
        min_stat = int((((2 * base_value + 0) * 100 // 100) + 5) * 0.9)
        # Max: 31 IVs, 252 EVs, beneficial nature (1.1)
        max_stat = int((((2 * base_value + 31 + 63) * 100 // 100) + 5) * 1.1)

    # Apply stat boosts
    boost = pokemon.boosts.get(stat, 0)
    if boost >= 0:
        multiplier = (2 + boost) / 2
    else:
        multiplier = 2 / (2 - boost)

    return (int(min_stat * multiplier), int(max_stat * multiplier))


def _calc_damage_range(attacker, defender, move, battle) -> tuple[int, int, int, int]:
    """
    Calculate damage range using Gen 4 formula.
    Returns (min_damage, max_damage, min_hp, max_hp).

    - min_damage: lowest roll against opponent with max defensive stats
    - max_damage: highest roll against opponent with min defensive stats
    - min_hp/max_hp: opponent's possible HP range

    Formula: ((2 * Level / 5 + 2) * Power * A/D) / 50 + 2) * Modifiers
    """
    # Status moves do no damage
    if move.category == MoveCategory.STATUS:
        return (0, 0, 1, 1)

    level = 100
    power = move.base_power

    if power == 0:
        return (0, 0, 1, 1)

    # Get attacker's attack stat (we know our exact stats)
    if move.category == MoveCategory.PHYSICAL:
        attack = _get_stat(attacker, "atk")
        def_min, def_max = _get_stat_range(defender, "def")
    else:
        attack = _get_stat(attacker, "spa")
        def_min, def_max = _get_stat_range(defender, "spd")

    # Get opponent's HP range
    hp_min, hp_max = _get_stat_range(defender, "hp")

    # Modifiers
    modifier = 1.0

    # STAB
    if move.type in [t for t in attacker.types if t]:
        modifier *= 1.5

    # Type effectiveness
    effectiveness = defender.damage_multiplier(move)
    modifier *= effectiveness

    # Weather (simplified - check for rain/sun effects)
    weather = list(battle.weather.keys())
    if weather:
        weather_name = weather[0].name if weather else None
        if weather_name == "RAINDANCE":
            if move.type and move.type.name == "WATER":
                modifier *= 1.5
            elif move.type and move.type.name == "FIRE":
                modifier *= 0.5
        elif weather_name == "SUNNYDAY":
            if move.type and move.type.name == "FIRE":
                modifier *= 1.5
            elif move.type and move.type.name == "WATER":
                modifier *= 0.5

    # Calculate damage against max defense (worst case) with low roll
    base_damage_min = ((2 * level / 5 + 2) * power * attack / def_max) / 50 + 2
    min_damage = int(base_damage_min * modifier * 0.85)

    # Calculate damage against min defense (best case) with high roll
    base_damage_max = ((2 * level / 5 + 2) * power * attack / def_min) / 50 + 2
    max_damage = int(base_damage_max * modifier * 1.0)

    return (min_damage, max_damage, hp_min, hp_max)


def calculate_all_damages(battle: AbstractBattle) -> dict:
    """
    Calculate damage for all available moves using Gen 4 damage formula.
    Returns min/max damage as percentage of opponent's HP.
    """
    # Check context first
    context_error = check_move_context(battle)
    if context_error:
        return {"error": context_error}

    active = battle.active_pokemon
    opponent = battle.opponent_active_pokemon

    if not active:
        return {"error": "No active Pokemon"}
    if not opponent:
        return {"error": "No opponent Pokemon visible"}

    moves = []
    for move in battle.available_moves:
        if move.category == MoveCategory.STATUS:
            moves.append({
                "move": move.id,
                "type": move.type.name.lower() if move.type else "unknown",
                "category": "status",
                "effect": _get_status_effect_description(move)
            })
            continue

        effectiveness = opponent.damage_multiplier(move)
        is_stab = move.type in [t for t in active.types if t]

        min_dmg, max_dmg, hp_min, hp_max = _calc_damage_range(active, opponent, move, battle)
        # min_percent: min damage vs max HP (worst case)
        # max_percent: max damage vs min HP (best case)
        min_percent = round((min_dmg / hp_max) * 100, 1)
        max_percent = round((max_dmg / hp_min) * 100, 1)

        move_info = {
            "move": move.id,
            "type": move.type.name.lower() if move.type else "unknown",
            "category": move.category.name.lower(),
            "base_power": move.base_power,
            "min_percent": min_percent,
            "max_percent": max_percent,
            "effectiveness": effectiveness,
            "is_stab": is_stab,
            "accuracy": move.accuracy,
            "priority": move.priority,
        }

        # Add note for immunities
        if effectiveness == 0:
            move_info["note"] = f"{opponent.species} is immune to {move.type.name}"

        moves.append(move_info)

    # Sort by max damage descending
    moves.sort(key=lambda m: m.get("max_percent", 0), reverse=True)

    return {
        "your_pokemon": active.species,
        "opponent_pokemon": opponent.species,
        "opponent_hp_percent": round(opponent.current_hp_fraction * 100, 1),
        "moves": moves
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
    """Get a description of a status move's effect using Move properties."""
    effects = []

    # Check for stat boosts (self)
    if hasattr(move, 'self_boost') and move.self_boost:
        boost_strs = []
        for stat, val in move.self_boost.items():
            stat_name = {"atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}.get(stat, stat)
            boost_strs.append(f"{stat_name} {'+' if val > 0 else ''}{val}")
        if boost_strs:
            effects.append(f"Self: {', '.join(boost_strs)}")

    # Check for stat changes on target
    if hasattr(move, 'boosts') and move.boosts:
        boost_strs = []
        for stat, val in move.boosts.items():
            stat_name = {"atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}.get(stat, stat)
            boost_strs.append(f"{stat_name} {'+' if val > 0 else ''}{val}")
        if boost_strs:
            effects.append(f"Target: {', '.join(boost_strs)}")

    # Check for status infliction
    if hasattr(move, 'status') and move.status:
        status_names = {"brn": "Burn", "par": "Paralyze", "slp": "Sleep", "psn": "Poison", "tox": "Toxic", "frz": "Freeze"}
        effects.append(status_names.get(str(move.status).lower(), str(move.status)))

    # Check for healing
    if hasattr(move, 'heal') and move.heal:
        effects.append(f"Heals {int(move.heal * 100)}% HP")

    # Check for side conditions (hazards, screens)
    if hasattr(move, 'side_condition') and move.side_condition:
        effects.append(f"Sets {move.side_condition}")

    # Check for self-switch (U-turn, Volt Switch)
    if hasattr(move, 'self_switch') and move.self_switch:
        effects.append("Switches out after use")

    # Check for forcing opponent switch (Roar, Whirlwind)
    if hasattr(move, 'force_switch') and move.force_switch:
        effects.append("Forces opponent to switch")

    # Check for protect
    if hasattr(move, 'is_protect_move') and move.is_protect_move:
        effects.append("Protects from attacks")

    # Check for weather
    if hasattr(move, 'weather') and move.weather:
        effects.append(f"Sets {move.weather}")

    # Check for terrain
    if hasattr(move, 'terrain') and move.terrain:
        effects.append(f"Sets {move.terrain}")

    return "; ".join(effects) if effects else "Status move"
