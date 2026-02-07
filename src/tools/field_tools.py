"""Field state analysis tools."""

from poke_env.player.player import AbstractBattle


def get_field_analysis(battle: AbstractBattle) -> dict:
    """
    Get analysis of current field conditions and their tactical implications.
    """
    result = {
        "weather": None,
        "your_hazards": {},
        "opponent_hazards": {},
        "your_screens": {},
        "opponent_screens": {},
        "terrain": None,
        "tactical_notes": []
    }

    # Weather
    if battle.weather:
        weather_dict = {}
        for weather, turn_count in battle.weather.items():
            weather_name = weather.name.lower()
            weather_dict["type"] = weather_name
            weather_dict["turns_remaining"] = turn_count if turn_count > 0 else "permanent"
            
            # Add effects description
            effects = _get_weather_effects(weather_name)
            weather_dict["effects"] = effects
        result["weather"] = weather_dict

    # Your side conditions (hazards on your side = bad for you)
    if battle.side_conditions:
        for condition, count in battle.side_conditions.items():
            cond_name = condition.name.lower()
            if "stealth" in cond_name or "rock" in cond_name:
                result["your_hazards"]["stealth_rock"] = True
            elif "spikes" in cond_name and "toxic" not in cond_name:
                result["your_hazards"]["spikes"] = count
            elif "toxic" in cond_name and "spikes" in cond_name:
                result["your_hazards"]["toxic_spikes"] = count
            elif "reflect" in cond_name:
                result["your_screens"]["reflect"] = count
            elif "light" in cond_name and "screen" in cond_name:
                result["your_screens"]["light_screen"] = count

    # Opponent's side conditions (hazards on their side = good for you)
    if battle.opponent_side_conditions:
        for condition, count in battle.opponent_side_conditions.items():
            cond_name = condition.name.lower()
            if "stealth" in cond_name or "rock" in cond_name:
                result["opponent_hazards"]["stealth_rock"] = True
            elif "spikes" in cond_name and "toxic" not in cond_name:
                result["opponent_hazards"]["spikes"] = count
            elif "toxic" in cond_name and "spikes" in cond_name:
                result["opponent_hazards"]["toxic_spikes"] = count
            elif "reflect" in cond_name:
                result["opponent_screens"]["reflect"] = count
            elif "light" in cond_name and "screen" in cond_name:
                result["opponent_screens"]["light_screen"] = count

    # Terrain
    if battle.fields:
        for field, count in battle.fields.items():
            field_name = field.name.lower()
            result["terrain"] = {
                "type": field_name,
                "turns_remaining": count
            }

    # Check grounded status for active Pokemon (affects Spikes, Toxic Spikes, terrain)
    active = battle.active_pokemon
    opponent = battle.opponent_active_pokemon

    if active:
        # Use poke-env's is_grounded if available, otherwise infer from types
        if hasattr(battle, 'is_grounded'):
            your_grounded = battle.is_grounded(active)
        else:
            # Flying types and Levitate are not grounded
            flying = any(t and t.name == "FLYING" for t in active.types)
            levitate = active.ability and "levitate" in active.ability.lower()
            your_grounded = not (flying or levitate)
        result["your_pokemon_grounded"] = your_grounded

    if opponent:
        flying = any(t and t.name == "FLYING" for t in opponent.types)
        if opponent.ability:
            # Ability is known - check if it's Levitate
            levitate = "levitate" in str(opponent.ability).lower()
            opponent_known_grounded = not (flying or levitate)
        else:
            # Ability unknown - check if species can even have Levitate
            can_have_levitate = False
            try:
                from poke_env.data import GenData
                gen_data = GenData.from_gen(4)
                species_id = opponent.species.lower().replace(" ", "").replace("-", "")
                for pid, pdata in gen_data.pokedex.items():
                    if pid.replace("-", "") == species_id:
                        possible_abilities = [a.lower() for a in pdata.get("abilities", {}).values()]
                        can_have_levitate = "levitate" in possible_abilities
                        break
            except Exception:
                pass  # Fall back to uncertain if lookup fails
            
            if flying:
                opponent_known_grounded = False  # Flying type, definitely not grounded
            elif can_have_levitate:
                opponent_known_grounded = None  # Unknown - might have Levitate
            else:
                opponent_known_grounded = True  # Can't have Levitate, so grounded
        result["opponent_pokemon_known_grounded"] = opponent_known_grounded

    # Generate tactical notes
    notes = []

    # Hazard damage on opponent switch
    if result["opponent_hazards"]:
        damage = 0
        if result["opponent_hazards"].get("stealth_rock"):
            notes.append("Opponent takes Stealth Rock damage on switch")
            damage += 12.5  # Base damage, varies by type
        spikes = result["opponent_hazards"].get("spikes", 0)
        if spikes:
            spikes_dmg = {1: 12.5, 2: 16.67, 3: 25}.get(spikes, 0)
            notes.append(f"Opponent takes {spikes_dmg}% from Spikes on switch")
            damage += spikes_dmg
        if damage:
            notes.append(f"Total switch damage to opponent: ~{damage}%")

    # Hazard damage on your switch
    if result["your_hazards"]:
        damage = 0
        if result["your_hazards"].get("stealth_rock"):
            notes.append("You take Stealth Rock damage on switch")
            damage += 12.5
        spikes = result["your_hazards"].get("spikes", 0)
        if spikes:
            spikes_dmg = {1: 12.5, 2: 16.67, 3: 25}.get(spikes, 0)
            # Note: Spikes don't affect non-grounded Pokemon
            notes.append(f"Grounded Pokemon take {spikes_dmg}% from Spikes on switch")
            damage += spikes_dmg
        toxic_spikes = result["your_hazards"].get("toxic_spikes", 0)
        if toxic_spikes:
            poison_type = "Badly poisoned" if toxic_spikes >= 2 else "Poisoned"
            notes.append(f"Grounded Pokemon get {poison_type} on switch")
        if damage:
            notes.append(f"Total switch damage to you: ~{damage}% (for grounded Pokemon)")

    # Screens
    if result["your_screens"]:
        if result["your_screens"].get("reflect"):
            notes.append("Reflect halves incoming physical damage")
        if result["your_screens"].get("light_screen"):
            notes.append("Light Screen halves incoming special damage")
    
    if result["opponent_screens"]:
        if result["opponent_screens"].get("reflect"):
            notes.append("Opponent's Reflect halves your physical damage")
        if result["opponent_screens"].get("light_screen"):
            notes.append("Opponent's Light Screen halves your special damage")

    result["tactical_notes"] = notes
    return result


def _get_weather_effects(weather: str) -> list[str]:
    """Get description of weather effects."""
    effects = {
        "raindance": [
            "Water moves boosted 50%",
            "Fire moves weakened 50%",
            "Thunder and Hurricane have 100% accuracy"
        ],
        "sunnyday": [
            "Fire moves boosted 50%",
            "Water moves weakened 50%",
            "Solar Beam charges instantly"
        ],
        "sandstorm": [
            "Rock types get +50% Sp. Def",
            "Non-Rock/Ground/Steel take 6.25% damage per turn"
        ],
        "hail": [
            "Non-Ice types take 6.25% damage per turn",
            "Blizzard has 100% accuracy"
        ]
    }
    return effects.get(weather, [f"Weather: {weather}"])
