"""Type effectiveness tools using poke-env's type chart."""

from poke_env.data import GenData


def get_type_effectiveness(attack_type: str, defender_types: list[str], gen: int = 4) -> dict:
    """
    Calculate type effectiveness multiplier.
    
    Args:
        attack_type: The attacking type (e.g., 'fire')
        defender_types: List of defender's types (e.g., ['grass', 'poison'])
        gen: Generation for type chart (default: 4)
    
    Returns:
        Dict with multiplier and description
    """
    try:
        gen_data = GenData.from_gen(gen)
        type_chart = gen_data.type_chart

        # Normalize types to uppercase
        atk_type = attack_type.upper()
        def_types = [t.upper() for t in defender_types if t]

        if not def_types:
            return {"error": "No defender types provided"}
        
        if atk_type not in type_chart:
            return {"error": f"Unknown attacking type: {attack_type}"}

        # Calculate multiplier
        # poke-env type_chart[DEF][ATK] = multiplier (damage taken)
        # So we need to look up type_chart[DEF_TYPE][ATK_TYPE]
        multiplier = 1.0
        for def_type in def_types:
            if def_type not in type_chart:
                return {"error": f"Unknown defending type: {def_type}"}
            # type_chart[DEF][ATK] gives how much damage DEF takes from ATK
            mult = type_chart[def_type].get(atk_type, 1.0)
            multiplier *= mult

        # Human-readable description
        if multiplier == 0:
            desc = "immune (0x)"
        elif multiplier == 0.25:
            desc = "doubly resisted (0.25x)"
        elif multiplier == 0.5:
            desc = "resisted (0.5x)"
        elif multiplier == 1:
            desc = "neutral (1x)"
        elif multiplier == 2:
            desc = "super effective (2x)"
        elif multiplier == 4:
            desc = "doubly super effective (4x)"
        else:
            desc = f"{multiplier}x"

        return {
            "multiplier": multiplier,
            "description": desc
        }
    except Exception as e:
        return {"error": str(e)}


def get_all_type_matchups(pokemon_types: list[str], gen: int = 4) -> dict:
    """
    Get complete type matchup analysis for a Pokemon.
    
    Args:
        pokemon_types: List of the Pokemon's types
        gen: Generation for type chart (default: 4)
    
    Returns:
        Dict with weaknesses, resistances, and immunities
    """
    try:
        gen_data = GenData.from_gen(gen)
        type_chart = gen_data.type_chart

        # Normalize types
        def_types = [t.upper() for t in pokemon_types if t]

        if not def_types:
            return {"error": "No types provided"}

        weaknesses = {}
        resistances = {}
        immunities = []

        # Check all attacking types
        all_types = list(type_chart.keys())

        for atk_type in all_types:
            # Skip fairy in gen 4
            if gen < 6 and atk_type == "FAIRY":
                continue
                
            # Calculate how much damage we take from this type
            multiplier = 1.0
            for def_type in def_types:
                mult = type_chart[def_type].get(atk_type, 1.0)
                multiplier *= mult

            type_lower = atk_type.lower()
            if multiplier == 0:
                immunities.append(type_lower)
            elif multiplier < 1:
                resistances[type_lower] = multiplier
            elif multiplier > 1:
                weaknesses[type_lower] = multiplier

        return {
            "defending_types": [t.lower() for t in pokemon_types],
            "weaknesses": weaknesses,
            "resistances": resistances,
            "immunities": immunities
        }
    except Exception as e:
        return {"error": str(e)}
