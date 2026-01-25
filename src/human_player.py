"""Human-controlled player for testing the tool harness experience."""

import json
from poke_env.player import Player
from poke_env.player.player import AbstractBattle

from .state_formatter import format_battle_state
from .event_formatter import get_recent_events
from .response_parser import parse_llm_response
from .tools import (
    damage_tools,
    team_tools,
    battle_log_tools,
    field_tools,
    type_tools,
    info_tools,
)


class HumanPlayer(Player):
    """
    Human-controlled player for testing the tool harness experience.
    
    Lets you experience exactly what the LLM sees and interact with
    tools from the terminal.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_battle = None

    async def choose_move(self, battle: AbstractBattle) -> str:
        """Interactive move selection with tool access."""
        self._current_battle = battle

        # Auto-show team details on Turn 1 (before turn header)
        if battle.turn == 1:
            print("\n" + "=" * 60)
            print("INITIAL TEAM STATE (Full Details):")
            print("=" * 60)
            # We import json at top of file, so we can use it
            details = team_tools.get_full_team_details(battle)
            print(json.dumps(details, indent=2, default=str))
            print("=" * 60 + "\n")

        # Show what LLM would see (recent events + current state)
        event_text = get_recent_events(battle)
        if event_text:
            print("\nWHAT HAPPENED:")
            print(event_text)

        print("\nCURRENT STATE:")
        print(format_battle_state(battle))

        # Interactive prompt
        while True:
            print("\n[Commands: move <name>, switch <name>]")
            print("[Tools: state, damage, team, opponent, log, field, type, info]")
            print("[Type 'help' for details]")
            
            try:
                user_input = input("> ").strip()
            except EOFError:
                # Non-interactive mode - use random move
                return self.choose_random_move(battle)

            if not user_input:
                continue

            # Check for action commands
            if user_input.lower().startswith(("move ", "switch ")):
                action = parse_llm_response(user_input, battle)
                if action:
                    return self.create_order(action)
                print("Invalid action. Try again.")
                continue

            # Check for tool commands
            result = self._handle_tool_command(user_input.lower(), battle)
            if result is not None:
                print(json.dumps(result, indent=2, default=str))
                continue

            # Help
            if user_input.lower() == "help":
                self._print_help()
                continue

            print("Unknown command. Type 'help' for options.")

    def _get_state_summary(self, battle: AbstractBattle) -> dict:
        """Get a focused summary: your active, opponent's active (detailed), and all 6 opponent slots."""
        result = {}

        # Your active Pokemon
        active = battle.active_pokemon
        if active and not active.fainted:
            result["your_active"] = {
                "species": active.species,
                "hp_percent": round(active.current_hp_fraction * 100, 1),
                "status": active.status.name if active.status else None,
                "boosts": {k: v for k, v in active.boosts.items() if v != 0} or None
            }
        else:
            result["your_active"] = None

        # Opponent's active Pokemon (detailed)
        opp_active = battle.opponent_active_pokemon
        if opp_active:
            result["opponent_active"] = {
                "species": opp_active.species,
                "hp_percent": round(opp_active.current_hp_fraction * 100, 1),
                "status": opp_active.status.name if opp_active.status else None,
                "known_moves": [m.id for m in opp_active.moves.values()],
                "known_ability": opp_active.ability,
                "known_item": opp_active.item,
                "boosts": {k: v for k, v in opp_active.boosts.items() if v != 0} or None
            }
        else:
            result["opponent_active"] = None

        # All 6 opponent slots
        revealed = list(battle.opponent_team.values())
        revealed_count = len(revealed)

        opponent_team = []
        for pokemon in revealed:
            if pokemon.fainted:
                status = "FNT"
            elif pokemon.status:
                status = pokemon.status.name
            else:
                status = None
            opponent_team.append({
                "species": pokemon.species,
                "hp_percent": round(pokemon.current_hp_fraction * 100, 1),
                "status": status
            })

        # Add UNKNOWN slots for unrevealed Pokemon
        for _ in range(6 - revealed_count):
            opponent_team.append({"species": "UNKNOWN"})

        result["opponent_team"] = opponent_team

        return result

    def _handle_tool_command(self, cmd: str, battle: AbstractBattle) -> dict | None:
        """Handle tool commands and return result, or None if not a tool command."""

        # State summary
        if cmd == "state":
            return self._get_state_summary(battle)

        # Damage tools
        if cmd == "damage":
            return damage_tools.calculate_all_damages(battle)
        if cmd.startswith("damage "):
            move_name = cmd[7:].strip()
            return damage_tools.calculate_damage(battle, move_name)
        
        # Team tools
        if cmd == "team":
            return team_tools.get_team_summary(battle)
        if cmd in ["team details", "team full"]:
            return team_tools.get_full_team_details(battle)
        if cmd.startswith("team "):
            pokemon_name = cmd[5:].strip()
            return team_tools.get_team_pokemon(battle, pokemon_name)
        if cmd == "opponent":
            return team_tools.get_opponent_team_summary(battle)
        if cmd.startswith("opponent "):
            pokemon_name = cmd[9:].strip()
            return team_tools.get_opponent_pokemon(battle, pokemon_name)
        
        # Battle log tools
        if cmd == "log":
            return battle_log_tools.get_battle_log(battle, "narrative")
        if cmd.startswith("log "):
            parts = cmd[4:].strip().split()
            format_type = parts[0] if parts else "narrative"
            from_turn = int(parts[1]) if len(parts) > 1 else 1
            return battle_log_tools.get_battle_log(battle, format_type, from_turn)
        if cmd.startswith("turn "):
            turn_num = int(cmd[5:].strip())
            return battle_log_tools.get_turn_details(battle, turn_num)
        
        # Field tools
        if cmd == "field":
            return field_tools.get_field_analysis(battle)

        # Type tools
        if cmd.startswith("type "):
            parts = cmd[5:].strip().split()
            if "vs" in parts:
                vs_idx = parts.index("vs")
                attack_type = parts[0]
                defender_types = parts[vs_idx + 1:]
                return type_tools.get_type_effectiveness(attack_type, defender_types)
            else:
                return type_tools.get_all_type_matchups(parts)
        
        # Info tools
        if cmd.startswith("move ") and " info" in cmd:
            move_name = cmd[5:].replace(" info", "").strip()
            return info_tools.get_move_details(move_name)
        if cmd.startswith("pokemon ") or cmd.startswith("info "):
            pokemon_name = cmd.split(" ", 1)[1].strip()
            
            # 1. Try our team first (Get detailed current state)
            team_info = team_tools.get_team_pokemon(battle, pokemon_name)
            if "error" not in team_info:
                return team_info
                
            # 2. Try opponent team (Get revealed info)
            opp_info = team_tools.get_opponent_pokemon(battle, pokemon_name)
            if "error" not in opp_info:
                return opp_info
                
            # 3. Fallback to generic species info
            return info_tools.get_pokemon_info(pokemon_name)
        if cmd == "info":
            return {"error": "Usage: info <pokemon_name> or pokemon <name>"}
        
        return None

    def _print_help(self):
        """Print help message."""
        print("""
ACTIONS:
  move <name>          Use a move (e.g., 'move earthquake')
  switch <name>        Switch Pokemon (e.g., 'switch gengar')

STATE:
  state                Your active, opponent's active (detailed), all 6 opponent slots

DAMAGE TOOLS:
  damage               Calculate damage for all your moves
  damage <move>        Calculate damage for a specific move

TEAM TOOLS:
  team                 Summary of your entire team
  team details         Full details of all team members
  team <pokemon>       Detailed info about one of your Pokemon
  opponent             Summary of opponent's revealed team
  opponent <pokemon>   Info about a specific opponent Pokemon

BATTLE LOG:
  log                  Full battle log (narrative format)
  log detailed         Full battle log (structured format)
  log raw              Full battle log (Showdown protocol)
  log <format> <turn>  Log starting from specific turn
  turn <n>             Details of a specific turn

FIELD TOOLS:
  field                Analyze field conditions (weather, hazards, screens)

TYPE TOOLS:
  type <t1> <t2>       Get all type matchups for types
  type <atk> vs <def>  Check effectiveness (e.g., 'type fire vs grass steel')

INFO TOOLS:
  info <pokemon>       Look up Pokemon species data
  pokemon <name>       Same as above
  move <name> info     Look up move details
""")
