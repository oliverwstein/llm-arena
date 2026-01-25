"""LLM-powered Pokemon battle player with tool-calling capabilities."""

import json
import time
from typing import Optional, TYPE_CHECKING
from poke_env.player import Player
from poke_env.player.player import Battle, AbstractBattle
from poke_env import ServerConfiguration, AccountConfiguration
import litellm

from .state_formatter import format_battle_state
from .response_parser import parse_llm_response
from .event_formatter import get_recent_events
from .tools.definitions import TOOL_DEFINITIONS
from .tools.executor import execute_tool

if TYPE_CHECKING:
    from .battle_logger import BattleLogger


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


NO_TOOLS_SYSTEM_PROMPT = """You are playing a competitive Pokemon battle (Gen 4 OU format). Your goal is to win.

You receive a summary of the current battle state.
- The battle log is the objective record - use it to review what actually happened.
- Consider what the opponent might do - that's YOUR job.

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
        battle_logger: Optional["BattleLogger"] = None,
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
            battle_logger: Optional BattleLogger for comprehensive output logging
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
        self.battle_logger = battle_logger

        # Multi-provider compatibility: Disable tools for reasoning models that don't support them well
        self.use_tools = True
        if "reasoner" in self.model.lower() and "deepseek" in self.model.lower():
            self.use_tools = False
            if self.system_prompt == SYSTEM_PROMPT:
                self.system_prompt = NO_TOOLS_SYSTEM_PROMPT
            if self.verbose:
                print(f"[{self.username}] Tools disabled for reasoning model: {model}")

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
        6. Log turn data
        7. Return valid order
        """
        battle_id = battle.battle_tag

        # Initialize per-battle state
        if battle_id not in self.decision_history:
            self.decision_history[battle_id] = []
            self.battle_plans[battle_id] = {"goals": [], "predictions": {}}
            # Start logging for this battle
            if self.battle_logger:
                # Determine opponent info (best effort - may not know model)
                opponent_name = "opponent"
                for player in [battle.player_username, battle.opponent_username]:
                    if player and player != self.username:
                        opponent_name = player
                        break
                self.battle_logger.start_battle(
                    battle_id=battle_id,
                    player_name=self.username,
                    model=self.model,
                    opponent_name=opponent_name,
                    opponent_model=None  # We don't know opponent's model
                )

        # 1. Get recent events (objective, from Showdown)
        prev_turn_events = get_recent_events(battle)

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

        # 9. Log turn data
        if self.battle_logger:
            self.battle_logger.log_turn(
                battle_id=battle_id,
                player_name=self.username,
                turn=battle.turn,
                observation=prev_turn_events or "(Battle just started)",
                state=current_state,
                raw_response=result.get("raw_response", ""),
                tool_calls=result.get("tool_calls", []),
                parsed={
                    "action": result.get("action", ""),
                    "reasoning": result.get("reasoning", ""),
                    "prediction": result.get("prediction", "")
                },
                tokens=result.get("tokens", {}),
                latency_ms=result.get("latency_ms", 0),
                battle_plan=self.battle_plans[battle_id].get("goals", [])
            )

        # 10. Parse and return
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
        Returns structured result with action, reasoning, plan updates,
        and logging data (raw_response, tool_calls, tokens, latency_ms).
        """
        start_time = time.time()

        # Format strategic plan
        plan_text = self._format_battle_plan(battle_plan)

        # Build subagent prompt with all objective information
        if self.use_tools:
            instructions = """Analyze the situation. You may:
1. Use tools to gather information
2. Update your strategic plan (add/complete goals)
3. Make your decision"""
        else:
            instructions = """Analyze the situation.
1. Review the battle log and current state
2. Reason about the best move
3. Make your decision"""

        user_content = f"""PREVIOUS TURN:
{prev_turn_events if prev_turn_events else "(Battle just started)"}

CURRENT STATE:
{current_state}

YOUR DECISION HISTORY (with reasoning):
{decision_history if decision_history else "(First turn)"}

YOUR STRATEGIC PLAN:
{plan_text if plan_text else "(No plan yet - consider setting goals)"}

{instructions}

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

        # Logging data
        logged_tool_calls = []
        total_input_tokens = 0
        total_output_tokens = 0
        raw_response_parts = []

        # If tools are disabled, we run once without tools using default tools=None
        current_tools = TOOL_DEFINITIONS if self.use_tools else None
        current_tool_choice = "auto" if self.use_tools else None

        while tool_calls_made < self.max_tool_calls:
            try:
                response = await litellm.acompletion(
                    model=self.model,
                    messages=messages,
                    tools=current_tools,
                    tool_choice=current_tool_choice,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=self.timeout,
                )

                message = response.choices[0].message

                # Track token usage
                if hasattr(response, 'usage') and response.usage:
                    total_input_tokens += getattr(response.usage, 'prompt_tokens', 0)
                    total_output_tokens += getattr(response.usage, 'completion_tokens', 0)

                # Capture response content for logging
                if message.content:
                    raw_response_parts.append(message.content)

                # Check for tool calls
                if message.tool_calls:
                    tool_calls_made += len(message.tool_calls)

                    # Add assistant message with tool calls
                    # For DeepSeek Reasoner and similar models, include reasoning_content if present
                    assistant_msg = {
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
                    }

                    # Include reasoning_content if available (required for DeepSeek Reasoner)
                    if hasattr(message, 'reasoning_content') and message.reasoning_content:
                        assistant_msg["reasoning_content"] = message.reasoning_content

                    messages.append(assistant_msg)

                    # Execute each tool call
                    for tool_call in message.tool_calls:
                        tool_start = time.time()

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

                        tool_duration_ms = int((time.time() - tool_start) * 1000)

                        # Log tool call
                        logged_tool_calls.append({
                            "name": tool_call.function.name,
                            "args": tool_call.function.arguments,
                            "result": result[:500] if len(result) > 500 else result,  # Truncate long results
                            "duration_ms": tool_duration_ms
                        })

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
                latency_ms = int((time.time() - start_time) * 1000)
                parsed = self._parse_subagent_response(message.content or "", plan_updates)
                parsed["raw_response"] = "\n---\n".join(raw_response_parts) if raw_response_parts else (message.content or "")
                parsed["tool_calls"] = logged_tool_calls
                parsed["tokens"] = {"input": total_input_tokens, "output": total_output_tokens}
                parsed["latency_ms"] = latency_ms
                return parsed

            except Exception as e:
                print(f"[{self.username}] Subagent error: {e}")
                latency_ms = int((time.time() - start_time) * 1000)
                return {
                    "action": "",
                    "reasoning": str(e),
                    "plan_updates": plan_updates,
                    "raw_response": f"ERROR: {e}",
                    "tool_calls": logged_tool_calls,
                    "tokens": {"input": total_input_tokens, "output": total_output_tokens},
                    "latency_ms": latency_ms
                }

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
            # Track token usage for final response
            if hasattr(response, 'usage') and response.usage:
                total_input_tokens += getattr(response.usage, 'prompt_tokens', 0)
                total_output_tokens += getattr(response.usage, 'completion_tokens', 0)

            final_content = response.choices[0].message.content or ""
            raw_response_parts.append(final_content)

            latency_ms = int((time.time() - start_time) * 1000)
            parsed = self._parse_subagent_response(final_content, plan_updates)
            parsed["raw_response"] = "\n---\n".join(raw_response_parts)
            parsed["tool_calls"] = logged_tool_calls
            parsed["tokens"] = {"input": total_input_tokens, "output": total_output_tokens}
            parsed["latency_ms"] = latency_ms
            return parsed
        except Exception as e:
            print(f"[{self.username}] Final response error: {e}")
            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "action": "",
                "reasoning": "",
                "plan_updates": plan_updates,
                "raw_response": "\n---\n".join(raw_response_parts) + f"\n---\nERROR: {e}",
                "tool_calls": logged_tool_calls,
                "tokens": {"input": total_input_tokens, "output": total_output_tokens},
                "latency_ms": latency_ms
            }

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
        """Called when a battle ends. Finalize logging and clean up per-battle state."""
        battle_id = battle.battle_tag

        # Log battle completion
        if self.battle_logger:
            won = battle.won if battle.won is not None else False
            self.battle_logger.end_battle(
                battle_id=battle_id,
                player_name=self.username,
                won=won,
                total_turns=battle.turn,
                forfeit=battle.forfeit
            )

        # Clean up per-battle state
        if battle_id in self.decision_history:
            del self.decision_history[battle_id]
        if battle_id in self.battle_plans:
            del self.battle_plans[battle_id]


# Backwards compatibility alias
LLMPlayerWithTools = LLMPlayer
