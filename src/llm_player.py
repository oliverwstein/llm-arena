"""LLM-powered Pokemon battle player."""

from typing import Optional
from poke_env.player import Player
from poke_env.player.player import Battle, AbstractBattle
from poke_env import ServerConfiguration, AccountConfiguration
import litellm

from .state_formatter import format_battle_state
from .response_parser import parse_llm_response


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
            **kwargs: Additional arguments passed to poke_env.Player
        """
        super().__init__(**kwargs)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.system_prompt = system_prompt

        # Track battle history for context
        self.battle_history: dict[str, list[dict]] = {}

    async def choose_move(self, battle: AbstractBattle) -> str:
        """
        Choose a move for the current turn (async).

        This is called by poke-env each turn. We:
        1. Format the battle state
        2. Call the LLM (async)
        3. Parse the response
        4. Return a valid order
        """
        # Format current state
        state_text = format_battle_state(battle)

        # Build messages
        messages = [
            {"role": "system", "content": self.system_prompt},
        ]

        # Add battle history for context
        battle_id = battle.battle_tag
        if battle_id not in self.battle_history:
            self.battle_history[battle_id] = []

        # Include last few turns of history
        history = self.battle_history[battle_id][-6:]  # Last 3 turns (state + response each)
        for msg in history:
            messages.append(msg)

        # Add current state
        messages.append({"role": "user", "content": state_text})

        # Call LLM (async to not block the event loop)
        try:
            response = await litellm.acompletion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.timeout,
            )
            response_text = response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[{self.username}] LLM error: {e}")
            return self.choose_random_move(battle)

        # Save to history
        self.battle_history[battle_id].append({"role": "user", "content": state_text})
        self.battle_history[battle_id].append({"role": "assistant", "content": response_text})

        # Parse response
        action = parse_llm_response(response_text, battle)

        if action:
            return self.create_order(action)
        else:
            print(f"[{self.username}] Could not parse response: {response_text}")
            return self.choose_random_move(battle)

    def battle_finished_callback(self, battle: AbstractBattle) -> None:
        """Called when a battle ends. Clean up history."""
        battle_id = battle.battle_tag
        if battle_id in self.battle_history:
            del self.battle_history[battle_id]


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
