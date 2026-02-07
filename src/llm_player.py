"""LLM-powered Pokemon battle player with tool-calling capabilities."""

import json
import random
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
Your final response MAY include:
- PREDICTION: what you expect opponent to do next, e.g., "switch Gengar", "move thunderbolt". 
    You may provide a list of predictions if you are uncertain.
    If you are acting unilaterally, such as when making a forced switch, do not provide a prediction.
- CONFIDENCE: your perceived chance of winning this battle (0-100)

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
Your final response MAY include:
- PREDICTION: what you expect opponent to do next, e.g., "switch Gengar", "move thunderbolt". 
    You may provide a list of predictions if you are uncertain.
    If you are acting unilaterally, such as when making a forced switch, do not provide a prediction.
- CONFIDENCE: your perceived chance of winning this battle (0-100)

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
        max_tokens: int = 16384,
        timeout: float = 180.0,
        system_prompt: str = SYSTEM_PROMPT,
        verbose: bool = False,
        max_tool_calls: int = 20,
        battle_logger: Optional["BattleLogger"] = None,
        reasoning_effort: Optional[str] = None,
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
        self.reasoning_effort = reasoning_effort

        # Multi-provider compatibility: Disable tools for reasoning models that don't support them well
        self.use_tools = True
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

    async def _request_action_correction(
        self,
        context: dict,
        invalid_action: str,
        valid_actions: str
    ) -> dict:
        """
        Request a corrected action from the LLM when parsing failed.
        
        Makes a simple, focused request showing what went wrong
        and what actions are actually available.
        """
        correction_prompt = f"""Your previous action could not be executed: "{invalid_action}"

This action is not valid. Here are the ONLY valid actions right now:
{valid_actions}

Please respond with ONLY a valid action from the list above.
Format: ACTION: move <name> or ACTION: switch <name>"""

        messages = [
            {"role": "system", "content": "You are correcting an invalid Pokemon battle action. Respond with ONLY the corrected action."},
            {"role": "user", "content": correction_prompt}
        ]

        try:
            # Simple call without tools - just need the corrected action
            completion_kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": 100,  # Very short response expected
                "timeout": 30.0,  # Quick timeout for correction
            }
            
            if self.reasoning_effort:
                completion_kwargs["reasoning_effort"] = self.reasoning_effort

            response = await litellm.acompletion(**completion_kwargs)
            
            content = response.choices[0].message.content or ""
            
            # Parse the correction
            parsed = self._parse_subagent_response(content, [])
            
            if self.verbose:
                print(f"[{self.username}] Correction response: {parsed.get('action', 'none')}")
            
            return {
                "action": parsed.get("action", ""),
                "reasoning": f"Corrected from '{invalid_action}'"
            }
            
        except Exception as e:
            if self.verbose:
                print(f"[{self.username}] Action correction failed: {e}")
            return {}

    async def _execute_generation(self, messages, tools=None, tool_choice=None, max_tokens=None):
        """
        Execute generation with streaming to capture partial output on timeout.
        Returns a mock response object compatible with the non-streaming response.
        """
        import asyncio
        
        retry_count = 0
        while True:
            response_content = ""
            response_reasoning = ""
            response_tool_calls_dict = {} # index -> {id, type, name, args}
            input_tokens = 0
            output_tokens = 0
            reasoning_tokens = 0
            
            try:
                # Build kwargs for acompletion
                completion_kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": tool_choice,
                    "temperature": self.temperature,
                    "max_tokens": max_tokens or self.max_tokens,
                    "timeout": self.timeout,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
                
                # Add reasoning_effort for reasoning models (GPT-5-Mini, o1, etc.)
                if self.reasoning_effort:
                    completion_kwargs["reasoning_effort"] = self.reasoning_effort
                
                stream = await litellm.acompletion(**completion_kwargs)
                
                async for chunk in stream:
                    # Handle usage if present (often in last chunk)
                    if hasattr(chunk, 'usage') and chunk.usage:
                        input_tokens = getattr(chunk.usage, 'prompt_tokens', 0)
                        output_tokens = getattr(chunk.usage, 'completion_tokens', 0)
                        
                        # Track reasoning tokens if available
                        details = getattr(chunk.usage, 'completion_tokens_details', None)
                        if details:
                            r_tokens = getattr(details, 'reasoning_tokens', 0)
                            if r_tokens:
                                reasoning_tokens = r_tokens
                        elif hasattr(chunk.usage, 'reasoning_tokens'):
                            reasoning_tokens = getattr(chunk.usage, 'reasoning_tokens', 0)
                    
                    if not chunk.choices:
                        continue
                        
                    delta = chunk.choices[0].delta
                    
                    # Content
                    if delta.content:
                        response_content += delta.content
                        
                    # Reasoning
                    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        response_reasoning += delta.reasoning_content
                        
                    # Tool calls
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in response_tool_calls_dict:
                                response_tool_calls_dict[idx] = {
                                    "id": "", "type": "function", "function": {"name": "", "arguments": ""}
                                }
                            
                            entry = response_tool_calls_dict[idx]
                            if tc.id: entry["id"] = tc.id
                            if tc.type: entry["type"] = tc.type
                            if tc.function:
                                if tc.function.name: entry["function"]["name"] += tc.function.name
                                if tc.function.arguments: entry["function"]["arguments"] += tc.function.arguments
    
                # Reconstruct objects to mimic non-streaming response
                class MockFunction:
                    def __init__(self, name, args):
                        self.name = name
                        self.arguments = args
                
                class MockToolCall:
                    def __init__(self, id, type, name, args):
                        self.id = id
                        self.type = type
                        self.function = MockFunction(name, args)
                
                final_tool_calls = []
                for idx in sorted(response_tool_calls_dict.keys()):
                    entry = response_tool_calls_dict[idx]
                    # If ID is missing (common in streaming), generate one or leave empty
                    tid = entry["id"] or f"call_{idx}"
                    final_tool_calls.append(MockToolCall(tid, entry["type"], entry["function"]["name"], entry["function"]["arguments"]))
                    
                class MockMessage:
                    def __init__(self, content, reasoning, tool_calls):
                        self.content = content
                        self.reasoning_content = reasoning
                        self.tool_calls = tool_calls
                
                class MockChoice:
                    def __init__(self, msg):
                        self.message = msg
                        
                class MockUsage:
                    def __init__(self, inp, out, reasoning=0):
                        self.prompt_tokens = inp
                        self.completion_tokens = out
                        self.reasoning_tokens = reasoning
                        self.completion_tokens_details = type('obj', (object,), {'reasoning_tokens': reasoning})
                        
                class MockResponse:
                    def __init__(self, choice, usage):
                        self.choices = [choice]
                        self.usage = usage
                
                return MockResponse(
                    MockChoice(MockMessage(response_content, response_reasoning, final_tool_calls)), 
                    MockUsage(input_tokens, output_tokens, reasoning_tokens)
                )
    
            except litellm.RateLimitError as e:
                retry_count += 1
                if retry_count > 15:
                    raise
                wait = min(10 * (2 ** retry_count) + random.uniform(0, 5), 300)
                print(f"[{self.username}] Rate limited: {e}. Retry {retry_count}/15 in {wait:.0f}s")
                await asyncio.sleep(wait)
                continue

            except litellm.Timeout as e:
                retry_count += 1
                if retry_count > 2:
                    raise
                print(f"[{self.username}] Timeout: {e}. Retry {retry_count}/2...")
                continue

            except (litellm.APIConnectionError, litellm.ServiceUnavailableError) as e:
                retry_count += 1
                if retry_count > 3:
                    raise
                wait = 15 * retry_count
                print(f"[{self.username}] Connection error: {e}. Retry {retry_count}/3 in {wait}s")
                await asyncio.sleep(wait)
                continue

            except litellm.ContextWindowExceededError:
                raise  # Structural - don't retry

            except Exception as e:
                retry_count += 1
                if retry_count > 2:
                    raise
                print(f"[{self.username}] Unexpected error: {e}. Retry {retry_count}/2...")
                await asyncio.sleep(10)
                continue

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

        # Build subagent prompt with all objective information
        if self.use_tools:
            instructions = """Analyze the situation. You may:
1. Use tools to gather information
2. Make your decision"""
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

{instructions}

Your final response must include:
- ACTION: move <name> or switch <name>
- REASONING: why you chose this (1 sentence)
- PREDICTION: what you expect opponent to do next, e.g., "switch Gengar", "move thunderbolt"
- CONFIDENCE: your perceived chance of winning this battle (0-100)"""

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
        total_reasoning_tokens = 0
        raw_response_parts = []

        # If tools are disabled, we run once without tools using default tools=None
        current_tools = get_llm_tool_definitions() if self.use_tools else None
        current_tool_choice = "auto" if self.use_tools else None

        while tool_calls_made < self.max_tool_calls:
            try:
                response = await self._execute_generation(
                    messages=messages,
                    tools=current_tools,
                    tool_choice=current_tool_choice
                )

                message = response.choices[0].message

                # Track token usage
                if hasattr(response, 'usage') and response.usage:
                    total_input_tokens += getattr(response.usage, 'prompt_tokens', 0)
                    total_output_tokens += getattr(response.usage, 'completion_tokens', 0)
                    
                    # Track reasoning tokens if available
                    details = getattr(response.usage, 'completion_tokens_details', None)
                    if details:
                        reasoning = getattr(details, 'reasoning_tokens', 0)
                        if reasoning:
                            total_reasoning_tokens += reasoning
                    elif hasattr(response.usage, 'reasoning_tokens'):
                        total_reasoning_tokens += getattr(response.usage, 'reasoning_tokens', 0)

                # Capture response content (and thinking) for logging
                full_content = ""
                if hasattr(message, 'reasoning_content') and message.reasoning_content:
                    full_content += f"<thinking>{message.reasoning_content}</thinking>\n"
                
                if message.content:
                    full_content += message.content

                if full_content:
                    raw_response_parts.append(full_content)

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

                    # Include reasoning_content if available
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
                
                # If we have reasoning content, treat it as reasoning if parsed reasoning is empty
                if not parsed["reasoning"] and hasattr(message, 'reasoning_content') and message.reasoning_content:
                    parsed["reasoning"] = message.reasoning_content
                
                parsed["raw_response"] = "\n---\n".join(raw_response_parts)
                parsed["tool_calls"] = logged_tool_calls
                parsed["tokens"] = {
                    "input": total_input_tokens, 
                    "output": total_output_tokens,
                    "reasoning": total_reasoning_tokens
                }
                parsed["latency_ms"] = latency_ms
                return parsed

            except Exception as e:
                print(f"[{self.username}] Subagent error: {e}")
                latency_ms = int((time.time() - start_time) * 1000)
                
                # Recover partial content from exception if available
                partial_content = getattr(e, "partial_content", "")
                partial_reasoning = getattr(e, "partial_reasoning", "")
                
                if partial_reasoning:
                    raw_response_parts.append(f"<thinking>{partial_reasoning}</thinking>\n{partial_content}")
                elif partial_content:
                    raw_response_parts.append(partial_content)
                
                current_raw = "\n---\n".join(raw_response_parts)
                return {
                    "action": "",
                    "reasoning": str(e),
                    "plan_updates": plan_updates,
                    "raw_response": f"{current_raw}\n---\nERROR: {e}" if current_raw else f"ERROR: {e}",
                    "tool_calls": logged_tool_calls,
                    "tokens": {
                        "input": total_input_tokens, 
                        "output": total_output_tokens,
                        "reasoning": total_reasoning_tokens
                    },
                    "latency_ms": latency_ms
                }

        # Exceeded max tool calls - force a decision
        messages.append({
            "role": "user",
            "content": "Tool call limit reached. Provide your final action now: ACTION: move <name> or switch <name>"
        })

        try:
            response = await self._execute_generation(
                messages=messages,
                max_tokens=self.max_tokens
            )

            # Track token usage for final response
            if hasattr(response, 'usage') and response.usage:
                total_input_tokens += getattr(response.usage, 'prompt_tokens', 0)
                total_output_tokens += getattr(response.usage, 'completion_tokens', 0)

            final_msg = response.choices[0].message
            final_content = ""
            if hasattr(final_msg, 'reasoning_content') and final_msg.reasoning_content:
                final_content += f"<thinking>{final_msg.reasoning_content}</thinking>\n"
            
            if final_msg.content:
                final_content += final_msg.content
                
            if final_content:
                raw_response_parts.append(final_content)

            latency_ms = int((time.time() - start_time) * 1000)
            parsed = self._parse_subagent_response(final_content, plan_updates)
            parsed["raw_response"] = "\n---\n".join(raw_response_parts)
            parsed["tool_calls"] = logged_tool_calls
            parsed["tokens"] = {
                "input": total_input_tokens, 
                "output": total_output_tokens,
                "reasoning": total_reasoning_tokens
            }
            parsed["latency_ms"] = latency_ms
            return parsed
        except Exception as e:
            print(f"[{self.username}] Final response error: {e}")
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Recover partial content
            partial_content = getattr(e, "partial_content", "")
            partial_reasoning = getattr(e, "partial_reasoning", "")
            if partial_reasoning or partial_content:
                 raw_response_parts.append(f"<thinking>{partial_reasoning}</thinking>\n{partial_content}")
            
            return {
                "action": "",
                "reasoning": "",
                "plan_updates": plan_updates,
                "raw_response": "\n---\n".join(raw_response_parts) + f"\n---\nERROR: {e}",
                "tool_calls": logged_tool_calls,
                "tokens": {
                    "input": total_input_tokens, 
                    "output": total_output_tokens,
                    "reasoning": total_reasoning_tokens
                },
                "latency_ms": latency_ms
            }

    def _parse_subagent_response(self, content: str, plan_updates: list) -> dict:
        """Parse structured response from subagent."""
        import re
        result = {"action": "", "reasoning": "", "prediction": "", "confidence": "", "plan_updates": plan_updates}

        # Remove thinking blocks for parsing
        clean_content = re.sub(r'<thinking>.*?</thinking>', '', content, flags=re.DOTALL).strip()
        
        # Use content if cleaning made it empty (fallback)
        if not clean_content:
            clean_content = content

        # Parse ACTION: line
        if "ACTION:" in clean_content:
            action_line = clean_content.split("ACTION:")[-1].split("\n")[0].strip()
            result["action"] = action_line

        # Parse REASONING: line
        if "REASONING:" in clean_content:
            reasoning_line = clean_content.split("REASONING:")[-1].split("\n")[0].strip()
            result["reasoning"] = reasoning_line

        # Parse PREDICTION: line
        if "PREDICTION:" in clean_content:
            prediction_line = clean_content.split("PREDICTION:")[-1].split("\n")[0].strip()
            result["prediction"] = prediction_line

        # Parse CONFIDENCE: line
        if "CONFIDENCE:" in clean_content:
            confidence_line = clean_content.split("CONFIDENCE:")[-1].split("\n")[0].strip()
            result["confidence"] = confidence_line.rstrip("%").strip()

        # Fallback: try to find move/switch anywhere
        if not result["action"]:
            result["action"] = clean_content.strip()

        return result


# Backwards compatibility alias
LLMPlayerWithTools = LLMPlayer
