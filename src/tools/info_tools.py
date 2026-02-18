"""Move, Pokemon, and Ability information lookup tools."""

import os
import re

from poke_env.data import GenData

from .type_tools import get_all_type_matchups


# Cache for parsed ability text data
_ability_text_cache: dict = {}


def _get_ability_texts(gen: int = 4) -> dict:
    """
    Parse ability descriptions from Showdown's text data.
    Cached after first load. Returns dict of ability_id -> {name, desc, shortDesc}.
    Gen-specific overrides are applied when available.
    """
    if _ability_text_cache:
        return _ability_text_cache

    # Find the abilities text file relative to the project root
    # Walk up from this file's location to find pokemon-showdown/
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(tools_dir))
    filepath = os.path.join(project_root, 'pokemon-showdown', 'data', 'text', 'abilities.ts')

    if not os.path.exists(filepath):
        return {}

    with open(filepath) as f:
        content = f.read()

    gen_key = f'gen{gen}'

    # Parse each ability entry
    pattern = r'\t(\w+):\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}'
    for match in re.finditer(pattern, content):
        ability_id = match.group(1)
        block = match.group(2)

        name_match = re.search(r'name:\s*"([^"]+)"', block)
        desc_match = re.search(r'\bdesc:\s*"([^"]+)"', block)
        short_match = re.search(r'shortDesc:\s*"([^"]+)"', block)

        # Check for gen-specific override
        gen_block = re.search(gen_key + r':\s*\{([^}]+)\}', block)
        gen_desc = None
        gen_short = None
        if gen_block:
            gen_desc_match = re.search(r'\bdesc:\s*"([^"]+)"', gen_block.group(1))
            gen_short_match = re.search(r'shortDesc:\s*"([^"]+)"', gen_block.group(1))
            if gen_desc_match:
                gen_desc = gen_desc_match.group(1)
            if gen_short_match:
                gen_short = gen_short_match.group(1)

        _ability_text_cache[ability_id] = {
            'name': name_match.group(1) if name_match else ability_id,
            'desc': gen_desc or (desc_match.group(1) if desc_match else None),
            'shortDesc': gen_short or (short_match.group(1) if short_match else None),
        }

    return _ability_text_cache


def _is_known_ability(name: str, gen: int = 4) -> bool:
    """Check if a name matches a known ability."""
    normalized = name.lower().replace(" ", "").replace("-", "").replace("_", "")
    texts = _get_ability_texts(gen)
    return normalized in texts


def get_ability_info(ability_name: str, gen: int = 4) -> dict:
    """
    Get information about a Pokemon ability.

    Args:
        ability_name: Name of the ability to look up
        gen: Generation for data (default: 4)
    """
    try:
        normalized = ability_name.lower().replace(" ", "").replace("-", "").replace("_", "")
        texts = _get_ability_texts(gen)

        # Find the ability
        ability_data = None
        ability_id = None
        for aid, adata in texts.items():
            if aid == normalized:
                ability_data = adata
                ability_id = aid
                break

        if not ability_data:
            # Try partial match
            for aid, adata in texts.items():
                if normalized in aid:
                    ability_data = adata
                    ability_id = aid
                    break

        if not ability_data:
            return {"error": f"Ability '{ability_name}' not found"}

        result = {
            "name": ability_data['name'],
            "description": ability_data.get('shortDesc') or ability_data.get('desc') or "No description available",
        }

        if ability_data.get('desc') and ability_data.get('shortDesc'):
            result["full_description"] = ability_data['desc']

        # Find Pokemon with this ability in the gen
        gen_data = GenData.from_gen(gen)
        pokemon_with = []
        for pid, pdata in gen_data.pokedex.items():
            abilities = pdata.get("abilities", {})
            for ability_val in abilities.values():
                if ability_val.lower().replace(" ", "").replace("-", "") == normalized:
                    pokemon_with.append(pdata.get("name", pid))
                    break

        if pokemon_with:
            result["pokemon_with_ability"] = sorted(set(pokemon_with))

        return result

    except Exception as e:
        return {"error": str(e)}


def get_move_details(move_name: str, gen: int = 4) -> dict:
    """
    Get detailed information about a move.
    
    Args:
        move_name: Name of the move to look up
        gen: Generation for move data (default: 4)
    """
    try:
        gen_data = GenData.from_gen(gen)
        
        # Normalize move name
        normalized = move_name.lower().replace(" ", "").replace("-", "").replace("_", "")
        
        # Try to find the move
        move_data = None
        for mid, mdata in gen_data.moves.items():
            if mid.replace("-", "").replace("_", "") == normalized:
                move_data = mdata
                break
        
        if not move_data:
            # Try partial match
            for mid, mdata in gen_data.moves.items():
                if normalized in mid.replace("-", "").replace("_", ""):
                    move_data = mdata
                    break
        
        if not move_data:
            # Check if the user passed an ability name instead of a move
            if _is_known_ability(move_name, gen):
                return {"error": f"'{move_name}' is an ability, not a move. Use the 'abilitydex' tool instead."}
            return {"error": f"Move '{move_name}' not found"}
        
        result = {
            "name": move_data.get("name", move_name),
            "type": move_data.get("type", "unknown").lower(),
            "category": move_data.get("category", "unknown").lower(),
            "base_power": move_data.get("basePower", 0),
            "accuracy": move_data.get("accuracy", 100),
            "pp": move_data.get("pp", 0),
            "priority": move_data.get("priority", 0),
        }
        
        # Add flags
        flags = move_data.get("flags", {})
        if flags.get("contact"):
            result["makes_contact"] = True
        
        # Add secondary effects
        secondary = move_data.get("secondary")
        if secondary:
            chance = secondary.get("chance", 100)
            if secondary.get("status"):
                result["secondary_effect"] = f"{chance}% chance to cause {secondary['status']}"
            elif secondary.get("boosts"):
                boosts = secondary.get("boosts", {})
                boost_strs = [f"{stat} {'+' if v > 0 else ''}{v}" for stat, v in boosts.items()]
                result["secondary_effect"] = f"{chance}% chance: {', '.join(boost_strs)}"
        
        # Self effects
        self_effect = move_data.get("self")
        if self_effect:
            if self_effect.get("boosts"):
                boosts = self_effect.get("boosts", {})
                boost_strs = [f"{stat} {'+' if v > 0 else ''}{v}" for stat, v in boosts.items()]
                result["self_effect"] = f"User: {', '.join(boost_strs)}"
        
        # Description based on move properties
        desc = _generate_move_description(move_data)
        if desc:
            result["description"] = desc
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


def get_pokemon_info(pokemon_name: str, gen: int = 4) -> dict:
    """
    Get information about a Pokemon species.
    
    Args:
        pokemon_name: Name of the Pokemon to look up
        gen: Generation for Pokemon data (default: 4)
    """
    try:
        gen_data = GenData.from_gen(gen)
        
        # Normalize pokemon name
        normalized = pokemon_name.lower().replace(" ", "").replace("-", "").replace("_", "")
        
        # Try to find the pokemon
        poke_data = None
        for pid, pdata in gen_data.pokedex.items():
            if pid.replace("-", "").replace("_", "") == normalized:
                poke_data = pdata
                break
        
        if not poke_data:
            # Try partial match
            for pid, pdata in gen_data.pokedex.items():
                if normalized in pid.replace("-", "").replace("_", ""):
                    poke_data = pdata
                    break
        
        if not poke_data:
            return {"error": f"Pokemon '{pokemon_name}' not found"}
        
        # Extract base stats
        base_stats = poke_data.get("baseStats", {})
        
        result = {
            "name": poke_data.get("name", pokemon_name),
            "types": [t.lower() for t in poke_data.get("types", [])],
            "base_stats": {
                "hp": base_stats.get("hp", 0),
                "atk": base_stats.get("atk", 0),
                "def": base_stats.get("def", 0),
                "spa": base_stats.get("spa", 0),
                "spd": base_stats.get("spd", 0),
                "spe": base_stats.get("spe", 0)
            },
            "abilities": list(poke_data.get("abilities", {}).values()),
        }
        
        # Calculate base stat total
        result["bst"] = sum(result["base_stats"].values())
        
        # Add role hints based on stats
        result["role_hints"] = _infer_role(result["base_stats"])
        
        # Add type matchup info
        type_info = get_all_type_matchups(result["types"], gen=gen)
        if "error" not in type_info:
            result.update({
                "weaknesses": type_info.get("weaknesses", {}),
                "resistances": type_info.get("resistances", {}),
                "immunities": type_info.get("immunities", [])
            })

        return result
        
    except Exception as e:
        return {"error": str(e)}


def _generate_move_description(move_data: dict) -> str:
    """Generate a tactical description for a move."""
    descriptions = []
    
    bp = move_data.get("basePower", 0)
    category = move_data.get("category", "").lower()
    
    if bp >= 120:
        descriptions.append("Very high power")
    elif bp >= 80:
        descriptions.append("High power")
    
    priority = move_data.get("priority", 0)
    if priority > 0:
        descriptions.append(f"+{priority} priority (moves first)")
    elif priority < 0:
        descriptions.append(f"{priority} priority (moves last)")
    
    accuracy = move_data.get("accuracy", 100)
    if accuracy is True:
        descriptions.append("Cannot miss")
    elif accuracy < 100:
        descriptions.append(f"{accuracy}% accuracy")
    
    flags = move_data.get("flags", {})
    if flags.get("recharge"):
        descriptions.append("Requires recharge turn")
    if flags.get("heal"):
        descriptions.append("Restores HP")
    
    return ". ".join(descriptions) if descriptions else None


def _infer_role(stats: dict) -> list[str]:
    """Infer Pokemon role from base stats."""
    roles = []
    
    spe = stats.get("spe", 0)
    atk = stats.get("atk", 0)
    spa = stats.get("spa", 0)
    hp = stats.get("hp", 0)
    def_ = stats.get("def", 0)
    spd = stats.get("spd", 0)
    
    # Offensive roles
    if spe >= 100:
        if atk >= 100:
            roles.append("Fast physical attacker")
        if spa >= 100:
            roles.append("Fast special attacker")
    else:
        if atk >= 110:
            roles.append("Physical wallbreaker")
        if spa >= 110:
            roles.append("Special wallbreaker")
    
    # Defensive roles
    if hp >= 100 and (def_ >= 100 or spd >= 100):
        if def_ > spd:
            roles.append("Physical wall")
        elif spd > def_:
            roles.append("Special wall")
        else:
            roles.append("Mixed wall")
    
    # Setup sweeper hints
    if spe >= 80 and (atk >= 80 or spa >= 80):
        roles.append("Setup sweeper potential")
    
    return roles if roles else ["Balanced stats"]
