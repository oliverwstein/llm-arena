"""LLM-powered Pokemon battle player."""

from typing import Optional
from poke_env.player import Player
from poke_env.player.player import Battle, AbstractBattle
from poke_env import ServerConfiguration, AccountConfiguration
import litellm

from .state_formatter import format_battle_state
from .response_parser import parse_llm_response
from .event_formatter import format_events


# Custom server configuration for port 8088
CUSTOM_SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8088/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?"
)


# System prompt for the LLM
SYSTEM_PROMPT = """You are playing a competitive Pokemon battle (Gen 4 OU format). Your goal is to win by knocking out all of your opponent's Pokemon.

Each turn, you will receive the current battle state and must choose an action:
- Use a move: "move <move_name>"
- Switch Pokemon: "switch <pokemon_name>"

Consider:
- Type matchups and effectiveness
- Your Pokemon's HP and status
- The opponent's likely moves
- Entry hazards and field conditions
- When to switch vs when to attack

Respond with ONLY your chosen action in the format above. Be decisive."""


class LLMPlayer(Player):
    """
    A Pokemon battle player powered by an LLM.

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
        max_tokens: int = 150,
        timeout: float = 30.0,
        system_prompt: str = SYSTEM_PROMPT,
        verbose: bool = False,
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
            verbose: If True, print full LLM responses
            **kwargs: Additional arguments passed to poke_env.Player
        """
        super().__init__(**kwargs)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.system_prompt = system_prompt
        self.verbose = verbose

        # Track conversation history per battle (for multi-turn context)
        self.conversations: dict[str, list[dict]] = {}
        self.last_turn_processed: dict[str, int] = {}

    async def choose_move(self, battle: AbstractBattle) -> str:
        """
        Choose a move for the current turn (async).

        This is called by poke-env each turn. We:
        1. Format the battle state
        2. Call the LLM (async)
        3. Parse the response
        4. Return a valid order
        """
        # Debug: ALWAYS print verbose status (unconditional)
        print(f"[{self.username}] Turn {battle.turn} - verbose={self.verbose}")

        # Format current state
        state_text = format_battle_state(battle)

        # Initialize conversation for this battle if needed
        battle_id = battle.battle_tag
        if battle_id not in self.conversations:
            self.conversations[battle_id] = []
            self.last_turn_processed[battle_id] = 0

        # Gather new events since last turn
        raw_events = []
        for turn_num in sorted(battle.observations.keys()):
            if turn_num > self.last_turn_processed[battle_id]:
                events = battle.observations[turn_num].events
                raw_events.extend(events)
                self.last_turn_processed[battle_id] = turn_num

        # Format events as human-readable text
        # Determine perspective based on our player position
        perspective = "p1" if self.username in str(battle.player_username) else "p2"
        events_text = format_events(raw_events, perspective)

        # Build the user message for this turn
        if events_text.strip():
            user_content = f"WHAT HAPPENED:\n{events_text}\n\nCURRENT STATE:\n{state_text}"
        else:
            # First turn - no events yet
            user_content = f"CURRENT STATE:\n{state_text}"

        # Build full message list: system + conversation history + new message
        messages = [
            {"role": "system", "content": self.system_prompt},
        ]
        messages.extend(self.conversations[battle_id])
        messages.append({"role": "user", "content": user_content})

        # Call LLM (async to not block the event loop)
        try:
            response = await litellm.acompletion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.timeout,
            )
            message = response.choices[0].message

            # Debug: print raw response structure
            if self.verbose:
                print(f"[{self.username}] === RAW RESPONSE DEBUG ===")
                print(f"[{self.username}] Full response type: {type(response)}")
                print(f"[{self.username}] Message type: {type(message)}")
                print(f"[{self.username}] Message dict: {message.model_dump() if hasattr(message, 'model_dump') else message}")
                print(f"[{self.username}] === END RAW RESPONSE ===")

            # Capture reasoning content if present (for reasoning models)
            # Try multiple possible attribute names
            reasoning_text = None
            for attr in ['reasoning_content', 'reasoning', 'thinking', 'thought']:
                if hasattr(message, attr) and getattr(message, attr):
                    reasoning_text = str(getattr(message, attr)).strip()
                    if self.verbose:
                        print(f"[{self.username}] Found reasoning in '{attr}': {reasoning_text[:200]}...")
                    break

            # Get main response content
            response_text = message.content or ""
            if not response_text and reasoning_text:
                # Fall back to reasoning content if main content is empty
                response_text = reasoning_text
            response_text = response_text.strip()
        except Exception as e:
            print(f"[{self.username}] LLM error: {e}")
            return self.choose_random_move(battle)

        # Parse response
        action = parse_llm_response(response_text, battle)

        # Save to conversation history for next turn
        self.conversations[battle_id].append({"role": "user", "content": user_content})
        self.conversations[battle_id].append({"role": "assistant", "content": response_text})

        # Verbose logging - show full reasoning trace + action
        if self.verbose:
            print(f"\n[{self.username}] === Turn {battle.turn} ===")
            print(f"[{self.username}] New message:\n{user_content}")
            print(f"[{self.username}] Conversation history: {len(self.conversations[battle_id])} messages")
            if reasoning_text and reasoning_text != response_text:
                print(f"[{self.username}] Reasoning:\n{reasoning_text}")
            print(f"[{self.username}] Response:\n{response_text}")
            print(f"[{self.username}] Parsed action: {action}")
            print(f"[{self.username}] === End Turn {battle.turn} ===\n")

        if action:
            print(f"[{self.username}] Turn {battle.turn}: {action}")
            return self.create_order(action)
        else:
            print(f"[{self.username}] Could not parse response: {response_text[:200]}...")
            return self.choose_random_move(battle)

    def battle_finished_callback(self, battle: AbstractBattle) -> None:
        """Called when a battle ends. Clean up conversation history."""
        battle_id = battle.battle_tag
        if battle_id in self.conversations:
            del self.conversations[battle_id]
        if battle_id in self.last_turn_processed:
            del self.last_turn_processed[battle_id]


class LLMPlayerWithTools(LLMPlayer):
    """
    Extended LLM player that can use tools (web search, calculators, etc.)

    This version allows the LLM to request additional information before
    making a decision. Useful for testing tool-use capabilities.
    """

    # TODO: Implement tool-calling loop
    # - Define available tools (type chart lookup, damage calc, Smogon search)
    # - Allow LLM to call tools before deciding
    # - Set a max tool-call limit per turn
    pass
