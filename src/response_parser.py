"""Parse LLM responses into battle actions."""

import re
from poke_env.player.player import Battle, Move, Pokemon
from typing import Union, Optional


def parse_llm_response(
    response: str,
    battle: Battle
) -> Optional[Union[Move, Pokemon]]:
    """
    Parse an LLM's response to extract the chosen action.

    Handles various response formats:
    - "move earthquake"
    - "I'll use Earthquake"
    - "switch to Gengar"
    - "Gengar, I choose you!"

    Returns:
        Move or Pokemon object, or None if parsing failed.
    """
    response = response.lower().strip()

    # Try to find explicit action format first
    # Pattern: "move <name>" or "use <name>"
    move_match = re.search(r'\b(?:move|use|attack with)\s+([a-z]+(?:\s+[a-z]+)?)', response)
    if move_match:
        move_name = move_match.group(1).replace(" ", "")
        move = find_move(move_name, battle.available_moves)
        if move:
            return move

    # Pattern: "switch <name>" or "switch to <name>" or "go <name>"
    switch_match = re.search(r'\b(?:switch(?:\s+to)?|go|send out)\s+([a-z]+)', response)
    if switch_match:
        pokemon_name = switch_match.group(1)
        pokemon = find_pokemon(pokemon_name, battle.available_switches)
        if pokemon:
            return pokemon

    # Fallback: look for any move name mentioned
    for move in battle.available_moves:
        if move.id.lower() in response:
            return move

    # Fallback: look for any Pokemon name mentioned
    for pokemon in battle.available_switches:
        if pokemon.species.lower() in response:
            return pokemon

    return None


def find_move(name: str, available_moves: list[Move]) -> Optional[Move]:
    """Find a move by name (fuzzy match)."""
    name = name.lower().replace(" ", "").replace("-", "")
    for move in available_moves:
        move_id = move.id.lower().replace("-", "")
        if move_id == name or move_id.startswith(name):
            return move
    return None


def find_pokemon(name: str, available_switches: list[Pokemon]) -> Optional[Pokemon]:
    """Find a Pokemon by name (fuzzy match)."""
    name = name.lower().replace(" ", "").replace("-", "")
    for pokemon in available_switches:
        species = pokemon.species.lower().replace("-", "")
        if species == name or species.startswith(name):
            return pokemon
    return None
