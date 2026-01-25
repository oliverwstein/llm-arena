"""LLM-powered Pokemon battle player with tool-calling capabilities."""

import json
import time
from typing import Optional, TYPE_CHECKING
from poke_env import ServerConfiguration

import litellm

from .agent_player import AgentPlayer
from .response_parser import parse_llm_response
from .tools.registry import get_llm_tool_definitions, execute_tool, get_help_text

if TYPE_CHECKING:
    from .battle_logger import BattleLogger
    from poke_env.player.player import AbstractBattle


# Custom server configuration for port 8088
CUSTOM_SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8088/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?"
)


# System prompt for tool-calling LLM - uses get_help_text() for tool list

def _build_system_prompt() -> str:
    """Build the system prompt with current tool help."""
    return f"""You are playing a competitive Pokemon battle (Gen 4 OU format). Your goal is to win.

{get_help_text()}
IMPORTANT:
- Tools provide DATA. YOU reason about strategy and prediction.
- The battle log is the objective record - use it to review what actually happened.
- Consider what the opponent might do - that's YOUR job, not the tools'.
- You may call multiple tools to gather information before deciding.
- Use the 'help' tool if you need details on any tool.

Your final response MUST include:
- ACTION: move <move_name> or switch <pokemon_name>
- REASONING: why you chose this (1 sentence)
- PREDICTION: what you expect opponent to do (optional)

Available actions:
- move <name>: Use one of your available moves
- switch <name>: Switch to a Pokemon from your bench"""


SYSTEM_PROMPT = _build_system_prompt()


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


class LLMPlayer(AgentPlayer):
    """
    A Pokemon battle player powered by an LLM with tool-calling capabilities.

    Uses a subagent architecture where tool calls are ephemeral per turn,
    preventing context explosion while allowing thorough analysis.

    Uses LiteLLM for multi-provider support.
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
        """
        super().__init__(battle_logger=battle_logger, verbose=verbose, **kwargs)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.system_prompt = system_prompt
        self.max_tool_calls = max_tool_calls

        # Multi-provider compatibility: Disable tools for reasoning models that don't support them well
        self.use_tools = True
        if "reasoner" in self.model.lower() and "deepseek" in self.model.lower():
            self.use_tools = False
            if self.system_prompt == SYSTEM_PROMPT:
                self.system_prompt = NO_TOOLS_SYSTEM_PROMPT
            if self.verbose:
                print(f"[{self.username}] Tools disabled for reasoning model: {model}")

    async def _make_decision(self, context: dict) -> dict:
        """
        Run reasoning subagent with tools.
        """
        # Format strategic plan (using helper from base class)
        # Actually the base class helper _format_battle_plan is an instance method, 
        # but _run_reasoning_subagent expects the formatted string in the prompt construction?
        # Let's check _run_reasoning_subagent below. It calls _format_battle_plan internally.
        
        result = await self._run_reasoning_subagent(
            battle=context["battle"],
            prev_turn_events=context["prev_events"],
            current_state=context["current_state"],
            decision_history=context["decision_history_str"],
            battle_plan=context["battle_plan"]
        )

        if self.verbose:
            print(f"\n[{self.username}] === Turn {context['battle'].turn} ===")
            print(f"[{self.username}] Action: {result['action']}")
            print(f"[{self.username}] Reasoning: {result.get('reasoning', 'N/A')}")
            print(f"[{self.username}] Prediction: {result.get('prediction', 'N/A')}")
            # print(f"[{self.username}] Parsed: {action}") # AgentPlayer does parsing 
            print(f"[{self.username}] === End Turn ===\n")
            
        return result

    async def _run_reasoning_subagent(
        self,
        battle: "AbstractBattle",
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
        current_tools = get_llm_tool_definitions() if self.use_tools else None
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

                        # Track plan updates (informational only here, as tool exec modifies plan)
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


# Backwards compatibility alias
LLMPlayerWithTools = LLMPlayer
