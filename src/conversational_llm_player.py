"""
Conversational LLM Player - maintains persistent conversation history across turns.

This is an alternative to LLMPlayer that:
1. Persists structured decisions (ACTION, REASONING, PREDICTION, CONFIDENCE) across turns
2. Keeps tool calls ephemeral (in scratch space only)
3. Allows the LLM to reference its own previous reasoning
"""

from typing import Optional
from poke_env.player.player import AbstractBattle

from .llm_player import LLMPlayer
from .battle_logger import BattleLogger
from .tools import get_llm_tool_definitions, execute_tool


class ConversationalLLMPlayer(LLMPlayer):
    """
    LLM Player with persistent conversation history.
    
    Unlike LLMPlayer which starts fresh each turn, this player maintains
    a running conversation where each turn's structured decision is
    appended to the history. Tool calls happen in a scratch space and
    are NOT persisted.
    
    Benefits:
    - Model can reference "As I predicted last turn..."
    - Strategic discoveries accumulate naturally
    - More coherent multi-turn play
    
    Trade-offs:
    - Context window grows O(n) with turns (but controlled - no tool bloat)
    - May need sliding window for very long battles (50+ turns)
    """
    
    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        timeout: float = 180.0,
        verbose: bool = False,
        max_tool_calls: int = 20,
        battle_logger: Optional[BattleLogger] = None,
        reasoning_effort: Optional[str] = None,
        max_history_turns: int = 50,  # Sliding window size
        **kwargs
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            verbose=verbose,
            max_tool_calls=max_tool_calls,
            battle_logger=battle_logger,
            reasoning_effort=reasoning_effort,
            **kwargs
        )
        
        # Persistent conversation history per battle
        self.conversation_history: dict[str, list[dict]] = {}
        self.max_history_turns = max_history_turns
    
    async def _run_reasoning_subagent(
        self,
        battle: AbstractBattle,
        prev_turn_events: str,
        current_state: str,
        decision_history: str,
        battle_plan: dict
    ) -> dict:
        """
        Run reasoning with persistent conversation history.
        
        Flow:
        1. Load persistent history (or initialize for new battle)
        2. Create scratch space with history + current turn context
        3. Run tool-calling loop in scratch space
        4. Extract structured decision
        5. Append ONLY structured decision to persistent history
        """
        battle_id = battle.battle_tag
        
        # Initialize persistent history for new battle
        if battle_id not in self.conversation_history:
            self.conversation_history[battle_id] = [
                {"role": "system", "content": self.system_prompt}
            ]
        
        # Build current turn's user message (similar to parent but without decision_history since we persist it)
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

{instructions}

Your final response must include:
- ACTION: move <name> or switch <name>
- REASONING: why you chose this (1 sentence)
- PREDICTION: what you expect opponent to do next, e.g., "switch Gengar", "move thunderbolt"
- CONFIDENCE: your perceived chance of winning this battle (0-100)"""

        # Create scratch messages: persistent history + current turn
        scratch_messages = self.conversation_history[battle_id].copy()
        scratch_messages.append({"role": "user", "content": user_content})

        # Tool-calling loop (all in scratch space - not persisted)
        tool_calls_made = 0
        logged_tool_calls = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_reasoning_tokens = 0
        raw_response_parts = []

        current_tools = get_llm_tool_definitions() if self.use_tools else None
        current_tool_choice = "auto" if self.use_tools else None

        while tool_calls_made < self.max_tool_calls:
            try:
                response = await self._execute_generation(
                    messages=scratch_messages,
                    tools=current_tools,
                    tool_choice=current_tool_choice
                )

                message = response.choices[0].message

                # Track token usage
                if hasattr(response, 'usage') and response.usage:
                    total_input_tokens += getattr(response.usage, 'prompt_tokens', 0)
                    total_output_tokens += getattr(response.usage, 'completion_tokens', 0)
                    details = getattr(response.usage, 'completion_tokens_details', None)
                    if details:
                        reasoning = getattr(details, 'reasoning_tokens', 0)
                        if reasoning:
                            total_reasoning_tokens += reasoning

                # Handle tool calls in scratch space
                if message.tool_calls and self.use_tools:
                    tool_calls = message.tool_calls
                    tool_names = [tc.function.name for tc in tool_calls]
                    
                    if self.verbose:
                        print(f"[{self.username}] Tools called: {tool_names}")

                    # Add assistant message with tool calls to scratch
                    scratch_messages.append({
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in tool_calls
                        ]
                    })

                    # Execute tools and add results to scratch
                    for tc in tool_calls:
                        tool_name = tc.function.name
                        tool_result = execute_tool(tool_name, tc.function.arguments, battle, {})
                        
                        logged_tool_calls.append({
                            "name": tool_name,
                            "args": tc.function.arguments,
                            "result": str(tool_result)[:500],
                            "duration_ms": 0
                        })

                        scratch_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": str(tool_result)
                        })

                    tool_calls_made += len(tool_calls)
                    continue

                else:
                    # Final response - no more tool calls
                    content = message.content or ""
                    if hasattr(message, 'reasoning_content') and message.reasoning_content:
                        raw_response_parts.append(f"<thinking>{message.reasoning_content}</thinking>")
                    raw_response_parts.append(content)

                    # Parse the response
                    parsed = self._parse_subagent_response(content, logged_tool_calls)
                    
                    # Persist ONLY structured output to conversation history
                    structured_response = self._format_persistent_response(
                        action=parsed.get("action", ""),
                        reasoning=parsed.get("reasoning", ""),
                        prediction=parsed.get("prediction", ""),
                        confidence=parsed.get("confidence", "")
                    )
                    
                    # Append user context and structured response to persistent history
                    self.conversation_history[battle_id].append(
                        {"role": "user", "content": user_content}
                    )
                    self.conversation_history[battle_id].append(
                        {"role": "assistant", "content": structured_response}
                    )
                    
                    # Apply sliding window if needed
                    self._trim_history_if_needed(battle_id)

                    # Add metadata for logging by parent class
                    parsed["raw_response"] = "\n---\n".join(raw_response_parts)
                    parsed["tool_calls"] = logged_tool_calls
                    parsed["tokens"] = {
                        "input": total_input_tokens,
                        "output": total_output_tokens,
                        "reasoning": total_reasoning_tokens
                    }

                    return parsed

            except Exception as e:
                if self.verbose:
                    print(f"[{self.username}] Subagent error: {e}")
                return {
                    "action": "",
                    "reasoning": str(e),
                    "prediction": "",
                    "confidence": "",
                    "fallback_reason": "subagent_error",
                    "raw_response": f"ERROR: {e}"
                }

        # Max tool calls reached - force final response
        scratch_messages.append({
            "role": "user", 
            "content": "Max tool calls reached. Please provide your final ACTION now."
        })
        
        try:
            response = await self._execute_generation(
                messages=scratch_messages,
                tools=None,
                tool_choice=None
            )
            content = response.choices[0].message.content or ""
            parsed = self._parse_subagent_response(content, logged_tool_calls)
            
            # Still persist the decision
            structured_response = self._format_persistent_response(
                action=parsed.get("action", ""),
                reasoning=parsed.get("reasoning", ""),
                prediction=parsed.get("prediction", ""),
                confidence=parsed.get("confidence", "")
            )
            self.conversation_history[battle_id].append(
                {"role": "user", "content": user_content}
            )
            self.conversation_history[battle_id].append(
                {"role": "assistant", "content": structured_response}
            )
            self._trim_history_if_needed(battle_id)
            
            # Add metadata for logging
            parsed["raw_response"] = content
            # We don't have token counts for this fallback path easily available unless we track them cumulatively
            # but usually this path is rare.
            
            return parsed
            
        except Exception as e:
            return {
                "action": "",
                "reasoning": str(e),
                "prediction": "",
                "confidence": "",
                "fallback_reason": "max_tool_calls_error"
            }

    def _format_persistent_response(
        self,
        action: str,
        reasoning: str,
        prediction: str,
        confidence: str
    ) -> str:
        """Format a clean response for persistent history (no tool calls/thinking)."""
        parts = []
        if action:
            parts.append(f"ACTION: {action}")
        if reasoning:
            parts.append(f"REASONING: {reasoning}")
        if prediction:
            parts.append(f"PREDICTION: {prediction}")
        if confidence:
            parts.append(f"CONFIDENCE: {confidence}")
        return "\n".join(parts) if parts else "ACTION: (none)"
    
    def _trim_history_if_needed(self, battle_id: str):
        """Apply sliding window if history exceeds max turns."""
        history = self.conversation_history.get(battle_id, [])
        
        if len(history) <= 1:  # Just system prompt
            return
        
        # Each turn is 2 messages (user + assistant), plus 1 system prompt
        max_messages = 1 + (self.max_history_turns * 2)
        
        if len(history) > max_messages:
            # Keep system prompt + last N turn pairs
            system_prompt = history[0]
            recent = history[-(self.max_history_turns * 2):]
            self.conversation_history[battle_id] = [system_prompt] + recent
            
            if self.verbose:
                print(f"[{self.username}] Trimmed history to last {self.max_history_turns} turns")
    
    def _battle_finished_callback(self, battle: AbstractBattle) -> None:
        """Clean up conversation history when battle ends."""
        super()._battle_finished_callback(battle)
        
        battle_id = battle.battle_tag
        if battle_id in self.conversation_history:
            if self.verbose:
                turns = (len(self.conversation_history[battle_id]) - 1) // 2
                print(f"[{self.username}] Clearing conversation history ({turns} turns)")
            del self.conversation_history[battle_id]
