"""Mock player for testing tournament infrastructure without API calls."""

import random
import time
from typing import Optional, TYPE_CHECKING

import litellm

from .agent_player import AgentPlayer

if TYPE_CHECKING:
    from .battle_logger import BattleLogger


class MockPlayer(AgentPlayer):
    """
    A mock player that makes random moves but goes through the full
    AgentPlayer pipeline (logging, decision history, etc.).
    
    Useful for testing tournament runners without burning API credits.
    Supports configurable error injection for testing error handling.
    """

    def __init__(
        self,
        error_rate: float = 0.0,
        error_types: Optional[list[str]] = None,
        thinking_time: float = 0.1,
        battle_logger: Optional["BattleLogger"] = None,
        verbose: bool = False,
        **kwargs
    ):
        """
        Initialize a mock player.
        
        Args:
            error_rate: Probability (0-1) of injecting an error on each turn
            error_types: List of error types to inject randomly. Options:
                - "timeout": Simulates API timeout
                - "rate_limit": Simulates rate limit error  
                - "connection": Simulates connection error
                - "context_window": Simulates context window exceeded
            thinking_time: Simulated "thinking" delay in seconds
            battle_logger: Optional battle logger
            verbose: Print debug info
        """
        super().__init__(battle_logger=battle_logger, verbose=verbose, **kwargs)
        self.error_rate = error_rate
        self.error_types = error_types or ["timeout"]
        self.thinking_time = thinking_time
        self.model = "mock-player"  # For logging compatibility
        
    async def _make_decision(self, context: dict) -> dict:
        """
        Make a random decision, optionally injecting errors.
        """
        import asyncio
        
        battle = context["battle"]
        start_time = time.time()
        
        # Simulate thinking time
        await asyncio.sleep(self.thinking_time)
        
        # Maybe inject an error
        if self.error_rate > 0 and random.random() < self.error_rate:
            error_type = random.choice(self.error_types)

            if error_type == "context_window":
                raise litellm.ContextWindowExceededError(
                    message="Context window exceeded (mock)",
                    model="mock-player",
                    llm_provider="mock",
                )
            elif error_type == "timeout":
                raise litellm.Timeout(
                    message="Request timed out (mock)",
                    model="mock-player",
                    llm_provider="mock",
                )
            elif error_type == "rate_limit":
                raise litellm.RateLimitError(
                    message="Rate limit exceeded (mock)",
                    model="mock-player",
                    llm_provider="mock",
                )
            elif error_type == "connection":
                raise litellm.APIConnectionError(
                    message="Connection failed (mock)",
                    model="mock-player",
                    llm_provider="mock",
                )
            else:
                raise Exception(f"Mock error: {error_type}")
        
        # Make a random choice
        if battle.available_moves:
            move = random.choice(battle.available_moves)
            action = f"move {move.id}"
            reasoning = f"Randomly selected {move.id}"
        elif battle.available_switches:
            pokemon = random.choice(battle.available_switches)
            action = f"switch {pokemon.species}"
            reasoning = f"Randomly selected switch to {pokemon.species}"
        else:
            action = ""
            reasoning = "No moves or switches available"
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        # Generate mock tool calls for realistic logging
        mock_tool_calls = []
        if random.random() > 0.5:
            mock_tool_calls.append({
                "name": "get_pokemon_info",
                "args": '{"pokemon": "active"}',
                "result": "(mock tool result)",
                "duration_ms": 5,
            })
        
        if self.verbose:
            print(f"[{self.username}] Mock decision: {action}")
        
        return {
            "action": action,
            "reasoning": reasoning,
            "prediction": "opponent uses a move",
            "confidence": str(random.randint(30, 70)),
            "raw_response": f"ACTION: {action}\nREASONING: {reasoning}",
            "tool_calls": mock_tool_calls,
            "tokens": {
                "input": random.randint(500, 2000),
                "output": random.randint(100, 500),
                "reasoning": 0,
            },
            "latency_ms": latency_ms,
        }
