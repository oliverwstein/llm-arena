"""Team information tools using poke-env battle state."""

from poke_env.player.player import AbstractBattle


def get_team_pokemon(battle: AbstractBattle, pokemon_name: str) -> dict:
    """Get detailed info about one of your team members."""

    # Find the pokemon in your team
    pokemon = None
    for mon in battle.team.values():
        if mon.species.lower() == pokemon_name.lower():
            pokemon = mon
            break

    if not pokemon:
        return {"error": f"Pokemon '{pokemon_name}' not found on your team"}

    # Format moves with PP
    moves = []
    for move in pokemon.moves.values():
        move_info = {
            "name": move.id,
            "type": move.type.name.lower() if move.type else "unknown",
            "pp": f"{move.current_pp}/{move.max_pp}" if move.current_pp is not None else "?/?"
        }
        if move.base_power > 0:
            move_info["base_power"] = move.base_power
            move_info["category"] = move.category.name.lower() if move.category else "unknown"
        else:
            move_info["category"] = "status"
        moves.append(move_info)

    return {
        "species": pokemon.species,
        "hp_percent": round(pokemon.current_hp_fraction * 100, 1),
        "status": pokemon.status.name if pokemon.status else None,
        "is_active": pokemon == battle.active_pokemon,
        "fainted": pokemon.fainted,
        "ability": pokemon.ability,
        "item": pokemon.item,
        "moves": moves,
        "boosts": {k: v for k, v in pokemon.boosts.items() if v != 0},
        "types": [t.name.lower() for t in pokemon.types if t],
        "base_stats": pokemon.base_stats
    }


def get_team_summary(battle: AbstractBattle) -> dict:
    """Get summary of entire team status."""

    active_mon = battle.active_pokemon
    active_info = None
    if active_mon and not active_mon.fainted:
        active_info = {
            "species": active_mon.species,
            "hp_percent": round(active_mon.current_hp_fraction * 100, 1),
            "status": active_mon.status.name if active_mon.status else None,
            "boosts": {k: v for k, v in active_mon.boosts.items() if v != 0}
        }

    bench = []
    alive_count = 0
    fainted_count = 0

    for pokemon in battle.team.values():
        if pokemon == active_mon:
            if not pokemon.fainted:
                alive_count += 1
            else:
                fainted_count += 1
            continue

        bench.append({
            "species": pokemon.species,
            "hp_percent": round(pokemon.current_hp_fraction * 100, 1),
            "status": pokemon.status.name if pokemon.status else None,
            "fainted": pokemon.fainted
        })

        if pokemon.fainted:
            fainted_count += 1
        else:
            alive_count += 1

    return {
        "active": active_info,
        "bench": bench,
        "alive_count": alive_count,
        "fainted_count": fainted_count
    }


def get_opponent_pokemon(battle: AbstractBattle, pokemon_name: str) -> dict:
    """Get known info about opponent's Pokemon (only revealed info)."""

    # Find in opponent's team
    pokemon = None
    for mon in battle.opponent_team.values():
        if mon.species.lower() == pokemon_name.lower():
            pokemon = mon
            break

    if not pokemon:
        return {"error": f"Pokemon '{pokemon_name}' not seen on opponent's team"}

    # Only show revealed moves
    known_moves = []
    for move in pokemon.moves.values():
        known_moves.append({
            "name": move.id,
            "type": move.type.name.lower() if move.type else "unknown"
        })

    return {
        "species": pokemon.species,
        "hp_percent": round(pokemon.current_hp_fraction * 100, 1),
        "status": pokemon.status.name if pokemon.status else None,
        "is_active": pokemon == battle.opponent_active_pokemon,
        "fainted": pokemon.fainted,
        "known_ability": pokemon.ability,
        "known_item": pokemon.item,
        "known_moves": known_moves,
        "possible_moves_remaining": max(0, 4 - len(known_moves)),
        "types": [t.name.lower() for t in pokemon.types if t],
        "base_stats": pokemon.base_stats
    }


def get_opponent_team_summary(battle: AbstractBattle) -> dict:
    """Get summary of entire opponent team (only revealed info)."""

    # opponent_team only contains Pokemon that have been revealed
    revealed = list(battle.opponent_team.values())
    revealed_count = len(revealed)
    unrevealed_count = 6 - revealed_count  # Assuming 6v6

    active_mon = battle.opponent_active_pokemon
    active_info = None
    if active_mon:
        active_info = {
            "species": active_mon.species,
            "hp_percent": round(active_mon.current_hp_fraction * 100, 1),
            "status": active_mon.status.name if active_mon.status else None,
            "known_moves": [m.id for m in active_mon.moves.values()],
            "known_ability": active_mon.ability,
            "known_item": active_mon.item
        }

    bench = []
    fainted_count = 0
    alive_count = 0

    for pokemon in revealed:
        if pokemon == active_mon:
            if not pokemon.fainted:
                alive_count += 1
            else:
                fainted_count += 1
            continue

        bench.append({
            "species": pokemon.species,
            "hp_percent": round(pokemon.current_hp_fraction * 100, 1),
            "status": pokemon.status.name if pokemon.status else None,
            "fainted": pokemon.fainted,
            "known_moves": [m.id for m in pokemon.moves.values()],
            "known_ability": pokemon.ability,
            "known_item": pokemon.item
        })

        if pokemon.fainted:
            fainted_count += 1
        else:
            alive_count += 1

    return {
        "revealed_count": revealed_count,
        "unrevealed_count": unrevealed_count,
        "fainted_count": fainted_count,
        "alive_revealed_count": alive_count,
        "active": active_info,
        "bench": bench,
        "max_pokemon_remaining": alive_count + unrevealed_count
    }
