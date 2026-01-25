"""Human-controlled player for testing the tool harness experience."""

import json
from .response_parser import parse_llm_response
from .tools.registry import parse_command, execute_tool, TOOLS
from .agent_player import AgentPlayer


class HumanPlayer(AgentPlayer):
    """
    Human-controlled player for testing the tool harness and LLM experience.
    Mirroring the LLM's context and capabilities.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _make_decision(self, context: dict) -> dict:
        """
        Interactive decision making.
        Displays context exactly as LLM sees it, then accepts commands.
        """
        battle = context["battle"]
        battle_plan = context["battle_plan"]
        
        # 1. Show Context (Mirroring LLM Prompt)
        print("\n" + "=" * 60)
        print(f"TURN {battle.turn} CONTEXT")
        print("=" * 60)
        
        if battle.turn == 1:
            print("\n[System] Initial Team Details Available via 'team full'")

        # Event Stream
        if context["prev_events"]:
            print("\n--- PREVIOUS TURN EVENTS ---")
            print(context["prev_events"])
            
        # Current State
        print("\n--- CURRENT STATE ---")
        print(context["current_state"])
            
        # Decision History
        if context["decision_history_str"]:
            print("\n--- DECISION HISTORY ---")
            print(context["decision_history_str"])
            
        # Strategic Plan
        plan_text = self._format_battle_plan(battle_plan)
        if plan_text:
            print("\n--- STRATEGIC PLAN ---")
            print(plan_text)
            
        print("\n" + "=" * 60)

        # 2. Interactive Loop
        while True:
            # Show available tools (same as LLM)
            print(f"\n[Tools: {', '.join(TOOLS.keys())}]")
            print("[Commands: move <name>, switch <name>]")
            
            try:
                user_input = input("> ").strip()
            except EOFError:
                return {"action": ""}  # Triggers random fallback

            if not user_input:
                continue

            # Check for action commands
            if user_input.lower().startswith(("move ", "switch ")):
                # Return action content. 
                # Ideally we'd ask for reasoning/prediction too to match LLM structure
                # For now, let's just assume empty reasoning or parse it if they use | syntax?
                # Let's keep it simple: Action is the command.
                return {
                    "action": user_input,
                    "reasoning": "Human decision",
                    "prediction": ""
                }

            # Check for tool commands
            tool_name, tool_args = parse_command(user_input)
            if tool_name:
                # We need to pass the context dict which contains 'battle_plan'
                # AgentPlayer prepares 'battle_plan' in the context dict passed to this method
                tool_context = {"battle_plan": battle_plan}
                
                result_json = execute_tool(tool_name, tool_args, battle, tool_context)
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
