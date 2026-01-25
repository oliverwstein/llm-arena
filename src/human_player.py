"""Human-controlled player for testing the tool harness experience."""

import json
from poke_env.player import Player
from poke_env.player.player import AbstractBattle

from .state_formatter import format_battle_state
from .event_formatter import get_recent_events
from .response_parser import parse_llm_response
from .tools.registry import parse_command, execute_tool
from .tools import team_tools  # Still needed for initial team display


class HumanPlayer(Player):
    """
    Human-controlled player for testing the tool harness experience.

    Lets you experience exactly what the LLM sees and interact with
    tools from the terminal. Uses the same tool registry as LLMPlayer.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_battle = None
        self._battle_plans: dict[str, dict] = {}  # battle_id -> {goals: [], predictions: {}}

    def _get_context(self) -> dict:
        """Get context dict for tool execution (includes battle plan)."""
        if self._current_battle:
            battle_id = self._current_battle.battle_tag
            if battle_id not in self._battle_plans:
                self._battle_plans[battle_id] = {"goals": [], "predictions": {}}
            return {"battle_plan": self._battle_plans[battle_id]}
        return {}

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
            print("[Tools: help, damage, team, opponent, log, field, type, pokemon, moveinfo, plan]")

            try:
                user_input = input("> ").strip()
            except EOFError:
                # Non-interactive mode - use random move
                return self.choose_random_move(battle)

            if not user_input:
                continue

            # Check for action commands
            if user_input.lower().startswith(("move ", "switch ")):
                # But not "move <name>" for move info - that needs a different check
                # If it looks like an action (move/switch followed by pokemon/move name), try parsing
                action = parse_llm_response(user_input, battle)
                if action:
                    return self.create_order(action)
                # If parsing failed, maybe it's a tool command like "move earthquake" for move info
                # Fall through to tool handling

            # Check for tool commands via unified registry
            tool_name, tool_args = parse_command(user_input)
            if tool_name:
                result_json = execute_tool(tool_name, tool_args, battle, self._get_context())
                self._print_tool_result(tool_name, result_json)
                continue

            print("Unknown command. Type 'help' for tool list.")

    def _print_tool_result(self, tool_name: str, result_json: str) -> None:
        """Format and print tool result for human readability."""
        try:
            data = json.loads(result_json)
        except json.JSONDecodeError:
            print(result_json)
            return

        # Handle errors
        if isinstance(data, dict) and "error" in data:
            print(f"Error: {data['error']}")
            return

        # Special formatting for help
        if tool_name == "help":
            if "tools" in data:
                # List of all tools
                print("\nAVAILABLE TOOLS:")
                for tool in data["tools"]:
                    print(f"  {tool['name']:20} {tool['description']}")
                print()
            else:
                # Single tool details
                print(f"\n{data['tool'].upper()}")
                print(f"  {data['description']}")
                if "parameters" in data:
                    print("  Parameters:")
                    for p in data["parameters"]:
                        req = "(required)" if p.get("required", True) else "(optional)"
                        print(f"    {p['name']:15} {p['type']:10} {req} - {p['description']}")
                print()
            return

        # Default: pretty-print JSON with indentation
        print(json.dumps(data, indent=2, default=str))
