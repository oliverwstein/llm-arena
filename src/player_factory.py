"""Player factory with automatic fallback to random bot when API keys are missing."""

import random
import string
from typing import Optional, Union
from poke_env.player import Player, RandomPlayer, SimpleHeuristicsPlayer
from poke_env import AccountConfiguration, ServerConfiguration

from .llm_player import LLMPlayer, CUSTOM_SERVER_CONFIG
from .env_manager import has_api_key, get_api_key_for_model
from .team_pool import TeamPool


def generate_unique_name(base_name: str) -> str:
    """Generate a unique player name by adding a random suffix."""
    suffix = ''.join(random.choices(string.digits, k=4))
    # Pokemon Showdown has max 18 character usernames
    max_base = 18 - len(suffix) - 1  # -1 for separator
    truncated = base_name[:max_base]
    return f"{truncated}{suffix}"


class PlayerFactory:
    """
    Factory for creating battle players with automatic fallback.
    
    When an LLM model's API key is not available, automatically falls back
    to a random-move bot or heuristic bot instead.
    """
    
    def __init__(
        self,
        team_pool: Optional[TeamPool] = None,
        server_config: Optional[ServerConfiguration] = None,
        battle_format: str = "gen4ou",
        fallback_type: str = "random",  # "random" or "heuristic"
        add_random_suffix: bool = True,  # Add random suffix to avoid name collisions
    ):
        """
        Initialize the player factory.
        
        Args:
            team_pool: Team pool to use for all players
            server_config: Server configuration (defaults to CUSTOM_SERVER_CONFIG)
            battle_format: Battle format string
            fallback_type: Type of fallback bot ("random" or "heuristic")
            add_random_suffix: Add random suffix to names to avoid collisions
        """
        self.team_pool = team_pool
        self.server_config = server_config or CUSTOM_SERVER_CONFIG
        self.battle_format = battle_format
        self.fallback_type = fallback_type
        self.add_random_suffix = add_random_suffix
    
    def create_player(
        self,
        name: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 150,
        force_fallback: bool = False,
    ) -> tuple[Player, bool]:
        """
        Create a player, using LLM if available or fallback otherwise.
        
        Args:
            name: Display name for the player
            model: LiteLLM model identifier
            temperature: LLM temperature setting
            max_tokens: Max tokens for LLM response
            force_fallback: If True, always use fallback bot
            
        Returns:
            Tuple of (Player instance, is_llm: bool)
        """
        # Generate unique name if needed
        unique_name = generate_unique_name(name) if self.add_random_suffix else name
        account_config = AccountConfiguration(unique_name, None)
        
        # Check if we should use LLM
        use_llm = not force_fallback and has_api_key(model)
        
        if use_llm:
            player = LLMPlayer(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                account_configuration=account_config,
                battle_format=self.battle_format,
                team=self.team_pool,
                server_configuration=self.server_config,
            )
            return player, True
        else:
            # Log the fallback
            env_var = get_api_key_for_model(model)
            if env_var and not force_fallback:
                print(f"⚠ {name}: {env_var} not set, using {self.fallback_type} bot")
            
            if self.fallback_type == "heuristic":
                player = SimpleHeuristicsPlayer(
                    account_configuration=account_config,
                    battle_format=self.battle_format,
                    team=self.team_pool,
                    server_configuration=self.server_config,
                )
            else:  # random
                player = RandomPlayer(
                    account_configuration=account_config,
                    battle_format=self.battle_format,
                    team=self.team_pool,
                    server_configuration=self.server_config,
                )
            return player, False
    
    def create_random_bot(self, name: str) -> Player:
        """Create a random-move bot."""
        return RandomPlayer(
            account_configuration=AccountConfiguration(name, None),
            battle_format=self.battle_format,
            team=self.team_pool,
            server_configuration=self.server_config,
        )
    
    def create_heuristic_bot(self, name: str) -> Player:
        """Create a simple heuristic bot."""
        return SimpleHeuristicsPlayer(
            account_configuration=AccountConfiguration(name, None),
            battle_format=self.battle_format,
            team=self.team_pool,
            server_configuration=self.server_config,
        )


# Convenience function for quick player creation
def create_player_with_fallback(
    name: str,
    model: str,
    team_pool: Optional[TeamPool] = None,
    battle_format: str = "gen4ou",
    **kwargs
) -> tuple[Player, bool]:
    """
    Create a player with automatic fallback to random bot.
    
    Args:
        name: Display name
        model: LiteLLM model identifier
        team_pool: Optional team pool
        battle_format: Battle format
        **kwargs: Additional arguments for LLMPlayer
        
    Returns:
        Tuple of (Player, is_llm: bool)
    """
    factory = PlayerFactory(
        team_pool=team_pool,
        battle_format=battle_format,
    )
    return factory.create_player(name, model, **kwargs)
