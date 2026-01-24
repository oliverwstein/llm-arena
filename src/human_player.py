"""Human-controlled player for testing the tool harness experience."""

import json
from poke_env.player import Player
from poke_env.environment import AbstractBattle

from .state_formatter import format_battle_state
from .event_formatter import format_events
from .response_parser import parse_llm_response
from .tools import (
    damage_tools,
    matchup_tools,
    team_tools,
    battle_log_tools,
    field_tools,
    type_tools,
    info_tools,
    speed_tools,
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

        # Show what LLM would see
        print("\n" + "=" * 60)
        print(f"TURN {battle.turn}")
        print("=" * 60)

        # Previous turn events
        perspective = battle.player_role or "p1"
        if battle.turn > 1 and (battle.turn - 1) in battle.observations:
            events = battle.observations[battle.turn - 1].events
            print("\nWHAT HAPPENED:")
            print(format_events(events, perspective))

        print("\nCURRENT STATE:")
        print(format_battle_state(battle))

        # Interactive prompt
        while True:
            print("\n[Commands: move <name>, switch <name>]")
            print("[Tools: damage, matchup, matchups, switch?, team, opponent, log, field, speed, type, info]")
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

    def _handle_tool_command(self, cmd: str, battle: AbstractBattle) -> dict | None:
        """Handle tool commands and return result, or None if not a tool command."""
        
        # Damage tools
        if cmd == "damage":
            return damage_tools.calculate_all_damages(battle)
        if cmd.startswith("damage "):
            move_name = cmd[7:].strip()
            return damage_tools.calculate_damage(battle, move_name)
        
        # Matchup tools
        if cmd == "matchup":
            return matchup_tools.evaluate_matchup(battle)
        if cmd.startswith("matchup "):
            pokemon_name = cmd[8:].strip()
            return matchup_tools.evaluate_matchup(battle, pokemon_name)
        if cmd == "matchups":
            return matchup_tools.evaluate_all_matchups(battle)
        if cmd == "switch?":
            return matchup_tools.should_switch(battle)
        
        # Team tools
        if cmd == "team":
            return team_tools.get_team_summary(battle)
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
        
        # Speed tools
        if cmd == "speed":
            return speed_tools.get_speed_comparison(battle)
        if cmd.startswith("speed "):
            move_name = cmd[6:].strip()
            return speed_tools.get_speed_comparison(battle, move_name)
        
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

DAMAGE TOOLS:
  damage               Calculate damage for all your moves
  damage <move>        Calculate damage for a specific move

MATCHUP TOOLS:
  matchup              Evaluate current matchup
  matchup <pokemon>    Evaluate matchup for a different Pokemon
  matchups             Evaluate all your Pokemon vs current opponent
  switch?              Get advice on whether to switch

TEAM TOOLS:
  team                 Summary of your entire team
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

SPEED TOOLS:
  speed                Compare speed stats
  speed <move>         Check if you outspeed with a specific move (priority)

TYPE TOOLS:
  type <t1> <t2>       Get all type matchups for types
  type <atk> vs <def>  Check effectiveness (e.g., 'type fire vs grass steel')

INFO TOOLS:
  info <pokemon>       Look up Pokemon species data
  pokemon <name>       Same as above
  move <name> info     Look up move details
""")
