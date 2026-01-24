"""LLM-powered Pokemon battle player with tool-calling capabilities."""

import json
from typing import Optional
from poke_env.player import Player
from poke_env.player.player import Battle, AbstractBattle
from poke_env import ServerConfiguration, AccountConfiguration
import litellm

from .state_formatter import format_battle_state
from .response_parser import parse_llm_response
from .event_formatter import format_events
from .tools.definitions import TOOL_DEFINITIONS
from .tools.executor import execute_tool


# Custom server configuration for port 8088
CUSTOM_SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8088/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?"
)


# System prompt for tool-calling LLM
SYSTEM_PROMPT = """You are playing a competitive Pokemon battle (Gen 4 OU format). Your goal is to win.

You have access to information tools:
- Type effectiveness and matchup analysis
- Damage calculations
- Move/Pokemon details lookup
- Complete battle log (objective record from the game)
- Speed comparison
- Field condition analysis
- Strategic planning (set and track goals)

IMPORTANT:
- Tools provide DATA. YOU reason about strategy and prediction.
- The battle log is the objective record - use it to review what actually happened.
- Consider what the opponent might do - that's YOUR job, not the tools'.
- You may call multiple tools to gather information before deciding.

Your final response MUST include:
- ACTION: move <move_name> or switch <pokemon_name>
- REASONING: why you chose this (1 sentence)
- PREDICTION: what you expect opponent to do (optional)

Available actions:
- move <name>: Use one of your available moves
- switch <name>: Switch to a Pokemon from your bench"""


class LLMPlayer(Player):
    """
    A Pokemon battle player powered by an LLM with tool-calling capabilities.

    Uses a subagent architecture where tool calls are ephemeral per turn,
    preventing context explosion while allowing thorough analysis.

    Uses LiteLLM for multi-provider support. Compatible with:
    - OpenAI (gpt-4o, gpt-4-turbo, etc.)
    - Anthropic (claude-3-opus, claude-sonnet-4-20250514, etc.)
    - Google (gemini/gemini-pro, gemini/gemini-1.5-flash, etc.)
    - xAI (xai/grok-2, etc.)
    - Local models via Ollama (ollama/llama3, etc.)
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 500,
        timeout: float = 30.0,
        system_prompt: str = SYSTEM_PROMPT,
        verbose: bool = False,
        max_tool_calls: int = 8,
        **kwargs
    ):
        """
        Initialize an LLM player.

        Args:
            model: LiteLLM model identifier (e.g., "gpt-4o", "claude-sonnet-4-20250514")
            temperature: Sampling temperature for the LLM
            max_tokens: Maximum tokens in response
            timeout: API call timeout in seconds
            system_prompt: Custom system prompt (optional)
            verbose: If True, print full LLM responses and tool calls
            max_tool_calls: Maximum tool calls per turn (default: 8)
            **kwargs: Additional arguments passed to poke_env.Player
        """
        super().__init__(**kwargs)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.system_prompt = system_prompt
        self.verbose = verbose
        self.max_tool_calls = max_tool_calls

        # Per-battle state (persistent across turns)
        self.decision_history: dict[str, list[dict]] = {}  # battle_id -> decisions
        self.battle_plans: dict[str, dict] = {}  # battle_id -> {goals: [], predictions: {}}

    async def choose_move(self, battle: AbstractBattle) -> str:
        """
        Choose a move using subagent with tools and strategic planning.

        This is called by poke-env each turn. We:
        1. Get previous turn events (objective record)
        2. Update previous turn's outcome
        3. Format current state
        4. Run reasoning subagent with tools (ephemeral context)
        5. Record decision with reasoning
        6. Return valid order
        """
        battle_id = battle.battle_tag

        # Initialize per-battle state
        if battle_id not in self.decision_history:
            self.decision_history[battle_id] = []
            self.battle_plans[battle_id] = {"goals": [], "predictions": {}}

        # 1. Get previous turn events (objective, from Showdown)
        prev_turn_events = self._get_previous_turn_events(battle)

        # 2. Update previous turn's outcome (did prediction match reality?)
        self._update_previous_outcome(battle_id, prev_turn_events)

        # 3. Format current state
        current_state = format_battle_state(battle)

        # 4. Format decision history with reasoning
        decision_summary = self._format_decision_history(battle_id)

        # 5. Get current strategic plan
        battle_plan = self.battle_plans[battle_id]

        # 6. Run reasoning subagent (ephemeral context)
        result = await self._run_reasoning_subagent(
            battle=battle,
            prev_turn_events=prev_turn_events,
            current_state=current_state,
            decision_history=decision_summary,
            battle_plan=battle_plan
        )

        # 7. Record decision with reasoning (outcome added next turn)
        self.decision_history[battle_id].append({
            "turn": battle.turn,
            "action": result["action"],
            "reasoning": result.get("reasoning", ""),
            "prediction": result.get("prediction", ""),
            "outcome": None  # Filled in next turn
        })

        # 8. Update strategic plan if subagent modified it
        if "plan_updates" in result:
            self._apply_plan_updates(battle_id, result["plan_updates"])

        # 9. Parse and return
        action = parse_llm_response(result["action"], battle)

        if self.verbose:
            print(f"\n[{self.username}] === Turn {battle.turn} ===")
            print(f"[{self.username}] Action: {result['action']}")
            print(f"[{self.username}] Reasoning: {result.get('reasoning', 'N/A')}")
            print(f"[{self.username}] Prediction: {result.get('prediction', 'N/A')}")
            print(f"[{self.username}] Parsed: {action}")
            print(f"[{self.username}] === End Turn ===\n")

        if action:
            print(f"[{self.username}] Turn {battle.turn}: {action}")
            return self.create_order(action)
        else:
            print(f"[{self.username}] Could not parse response: {result['action'][:200]}...")
            return self.choose_random_move(battle)

    def _get_previous_turn_events(self, battle: AbstractBattle) -> str:
        """Get formatted events from the previous turn (objective record)."""
        prev_turn = battle.turn - 1
        if prev_turn <= 0 or prev_turn not in battle.observations:
            return ""

        events = battle.observations[prev_turn].events
        perspective = battle.player_role or "p1"
        return format_events(events, perspective)

    def _update_previous_outcome(self, battle_id: str, prev_events: str):
        """Update the previous turn's decision with what actually happened."""
        if not self.decision_history[battle_id]:
            return

        last_decision = self.decision_history[battle_id][-1]
        if last_decision["outcome"] is None:
            # Summarize what happened (truncated for context management)
            last_decision["outcome"] = prev_events[:100] if prev_events else "no events"

    def _format_decision_history(self, battle_id: str) -> str:
        """Format decision history with reasoning and outcomes."""
        lines = []
        for d in self.decision_history[battle_id][-8:]:  # Last 8 turns
            line = f"T{d['turn']}: {d['action']}"
            if d.get('reasoning'):
                line += f" | {d['reasoning']}"
            if d.get('prediction') and d.get('outcome'):
                # Show if prediction was correct
                line += f" → {d['outcome'][:50]}"
            lines.append(line)
        return "\n".join(lines)

    def _format_battle_plan(self, plan: dict) -> str:
        """Format battle plan for display."""
        lines = []
        for goal in plan.get("goals", []):
            if goal["status"] == "completed":
                status = "✓"
            elif goal["status"] == "abandoned":
                status = "✗"
            else:
                status = "○"
            lines.append(f"{status} {goal['goal']}")
            if goal.get("notes"):
                lines.append(f"   └─ {goal['notes']}")
        return "\n".join(lines) if lines else ""

    async def _run_reasoning_subagent(
        self,
        battle: AbstractBattle,
        prev_turn_events: str,
        current_state: str,
        decision_history: str,
        battle_plan: dict
    ) -> dict:
        """
        Run isolated reasoning subagent with tools.

        This context is EPHEMERAL - not persisted between turns.
        Returns structured result with action, reasoning, and plan updates.
        """
        # Format strategic plan
        plan_text = self._format_battle_plan(battle_plan)

        # Build subagent prompt with all objective information
        user_content = f"""PREVIOUS TURN:
{prev_turn_events if prev_turn_events else "(Battle just started)"}

CURRENT STATE:
{current_state}

YOUR DECISION HISTORY (with reasoning):
{decision_history if decision_history else "(First turn)"}

YOUR STRATEGIC PLAN:
{plan_text if plan_text else "(No plan yet - consider setting goals)"}

Analyze the situation. You may:
1. Use tools to gather information
2. Update your strategic plan (add/complete goals)
3. Make your decision

Your final response must include:
- ACTION: move <name> or switch <name>
- REASONING: why you chose this (1 sentence)
- PREDICTION: what you expect opponent to do (optional)"""

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content}
        ]

        # Tool-calling loop (all in ephemeral context)
        tool_calls_made = 0
        plan_updates = []
        context = {"battle_plan": battle_plan}

        while tool_calls_made < self.max_tool_calls:
            try:
                response = await litellm.acompletion(
                    model=self.model,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=self.timeout,
                )

                message = response.choices[0].message

                # Check for tool calls
                if message.tool_calls:
                    tool_calls_made += len(message.tool_calls)

                    # Add assistant message with tool calls
                    messages.append({
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in message.tool_calls
                        ]
                    })

                    # Execute each tool call
                    for tool_call in message.tool_calls:
                        # Track plan updates
                        if tool_call.function.name == "update_battle_plan":
                            try:
                                args = json.loads(tool_call.function.arguments)
                                plan_updates.append(args)
                            except json.JSONDecodeError:
                                pass

                        # Execute tool
                        result = execute_tool(
                            tool_call.function.name,
                            tool_call.function.arguments,
                            battle,
                            context
                        )

                        # Add tool result
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })

                    if self.verbose:
                        tool_names = [tc.function.name for tc in message.tool_calls]
                        print(f"[{self.username}] Tools called: {tool_names}")

                    continue  # Loop back for more reasoning

                # No tool calls - this is the final answer
                return self._parse_subagent_response(message.content or "", plan_updates)

            except Exception as e:
                print(f"[{self.username}] Subagent error: {e}")
                return {"action": "", "reasoning": str(e), "plan_updates": plan_updates}

        # Exceeded max tool calls - force a decision
        messages.append({
            "role": "user",
            "content": "Tool call limit reached. Provide your final action now: ACTION: move <name> or switch <name>"
        })

        try:
            response = await litellm.acompletion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=200,
                timeout=self.timeout,
            )
            return self._parse_subagent_response(
                response.choices[0].message.content or "",
                plan_updates
            )
        except Exception as e:
            print(f"[{self.username}] Final response error: {e}")
            return {"action": "", "reasoning": "", "plan_updates": plan_updates}

    def _parse_subagent_response(self, content: str, plan_updates: list) -> dict:
        """Parse structured response from subagent."""
        result = {"action": "", "reasoning": "", "prediction": "", "plan_updates": plan_updates}

        # Parse ACTION: line
        if "ACTION:" in content:
            action_line = content.split("ACTION:")[-1].split("\n")[0].strip()
            result["action"] = action_line

        # Parse REASONING: line
        if "REASONING:" in content:
            reasoning_line = content.split("REASONING:")[-1].split("\n")[0].strip()
            result["reasoning"] = reasoning_line

        # Parse PREDICTION: line
        if "PREDICTION:" in content:
            prediction_line = content.split("PREDICTION:")[-1].split("\n")[0].strip()
            result["prediction"] = prediction_line

        # Fallback: try to find move/switch anywhere
        if not result["action"]:
            result["action"] = content.strip()

        return result

    def _apply_plan_updates(self, battle_id: str, updates: list):
        """Apply plan updates from subagent."""
        plan = self.battle_plans[battle_id]

        for update in updates:
            action = update.get("action")

            if action == "add_goal":
                plan["goals"].append({
                    "id": len(plan["goals"]) + 1,
                    "goal": update.get("text", ""),
                    "status": "active",
                    "notes": ""
                })

            elif action == "complete_goal":
                goal_id = update.get("goal_id")
                for goal in plan["goals"]:
                    if goal["id"] == goal_id:
                        goal["status"] = "completed"

            elif action == "abandon_goal":
                goal_id = update.get("goal_id")
                for goal in plan["goals"]:
                    if goal["id"] == goal_id:
                        goal["status"] = "abandoned"

            elif action == "add_note":
                goal_id = update.get("goal_id")
                for goal in plan["goals"]:
                    if goal["id"] == goal_id:
                        goal["notes"] = update.get("text", "")

    def battle_finished_callback(self, battle: AbstractBattle) -> None:
        """Called when a battle ends. Clean up per-battle state."""
        battle_id = battle.battle_tag
        if battle_id in self.decision_history:
            del self.decision_history[battle_id]
        if battle_id in self.battle_plans:
            del self.battle_plans[battle_id]


# Backwards compatibility alias
LLMPlayerWithTools = LLMPlayer
