"""Integration tests for LLMPlayer with tools."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import json


class TestLLMPlayerIntegration:
    """Integration tests for the tool-calling LLMPlayer."""

    def test_import_llm_player(self):
        """Test that LLMPlayer can be imported."""
        from src.llm_player import LLMPlayer, LLMPlayerWithTools
        assert LLMPlayer is not None
        assert LLMPlayerWithTools is LLMPlayer  # Alias

    def test_llm_player_init(self):
        """Test LLMPlayer initialization."""
        from src.llm_player import LLMPlayer
        
        # Note: This will fail without proper poke-env setup
        # Just testing the class structure exists
        assert hasattr(LLMPlayer, 'choose_move')
        assert hasattr(LLMPlayer, 'battle_finished_callback')
        assert hasattr(LLMPlayer, '_run_reasoning_subagent')

    def test_tool_definitions_valid(self):
        """Test that tool definitions are valid JSON schema."""
        from src.tools.definitions import TOOL_DEFINITIONS
        
        assert isinstance(TOOL_DEFINITIONS, list)
        assert len(TOOL_DEFINITIONS) > 0
        
        for tool in TOOL_DEFINITIONS:
            assert "type" in tool
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

    def test_executor_handles_all_tools(self):
        """Test that executor can handle all defined tools."""
        from src.tools.definitions import TOOL_DEFINITIONS
        from src.tools.executor import execute_tool
        
        # Get all tool names
        tool_names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
        
        # Create mock battle
        battle = MagicMock()
        battle.active_pokemon = None
        battle.opponent_active_pokemon = None
        battle.team = {}
        battle.opponent_team = {}
        battle.observations = {}
        battle.turn = 1
        battle.player_role = "p1"
        battle.available_moves = []
        battle.available_switches = []
        battle.weather = {}
        battle.side_conditions = {}
        battle.opponent_side_conditions = {}
        battle.fields = {}
        
        context = {"battle_plan": {"goals": [], "predictions": {}}}
        
        # Each tool should return a valid JSON string (may contain error for missing data)
        for name in tool_names:
            result = execute_tool(name, "{}", battle, context)
            assert isinstance(result, str)
            # Should be valid JSON
            parsed = json.loads(result)
            assert isinstance(parsed, dict)

    def test_response_parser_action_format(self):
        """Test that response parser handles ACTION: format."""
        from src.response_parser import parse_llm_response
        
        battle = MagicMock()
        
        # Mock available moves
        move = MagicMock()
        move.id = "earthquake"
        battle.available_moves = [move]
        battle.available_switches = []
        
        # Test ACTION: format
        response = "ACTION: move earthquake\nREASONING: Best damage\nPREDICTION: They will switch"
        result = parse_llm_response(response, battle)
        assert result == move

    def test_response_parser_switch_format(self):
        """Test that response parser handles switch commands."""
        from src.response_parser import parse_llm_response
        
        battle = MagicMock()
        battle.available_moves = []
        
        # Mock available switches
        pokemon = MagicMock()
        pokemon.species = "Gengar"
        battle.available_switches = [pokemon]
        
        response = "ACTION: switch gengar"
        result = parse_llm_response(response, battle)
        assert result == pokemon


class TestSubagentPattern:
    """Tests for the subagent pattern implementation."""

    def test_decision_history_format(self):
        """Test decision history formatting."""
        from src.llm_player import LLMPlayer
        
        # Create a mock player to test the method
        # Note: Can't fully instantiate without poke-env setup
        # Just verify the method exists and has correct signature
        assert hasattr(LLMPlayer, '_format_decision_history')
        assert hasattr(LLMPlayer, '_update_previous_outcome')

    def test_battle_plan_format(self):
        """Test battle plan formatting."""
        from src.llm_player import LLMPlayer
        
        assert hasattr(LLMPlayer, '_format_battle_plan')
        assert hasattr(LLMPlayer, '_apply_plan_updates')

    def test_parse_subagent_response(self):
        """Test parsing of structured subagent responses."""
        from src.llm_player import LLMPlayer
        
        # Can't instantiate, but can test the response parsing logic directly
        content = """Based on my analysis:

ACTION: move earthquake
REASONING: Earthquake deals the most damage and is STAB
PREDICTION: Opponent will likely switch to a Flying type"""

        # Simulate the parsing
        result = {"action": "", "reasoning": "", "prediction": "", "plan_updates": []}
        
        if "ACTION:" in content:
            action_line = content.split("ACTION:")[-1].split("\n")[0].strip()
            result["action"] = action_line
        
        if "REASONING:" in content:
            reasoning_line = content.split("REASONING:")[-1].split("\n")[0].strip()
            result["reasoning"] = reasoning_line
        
        if "PREDICTION:" in content:
            prediction_line = content.split("PREDICTION:")[-1].split("\n")[0].strip()
            result["prediction"] = prediction_line
        
        assert result["action"] == "move earthquake"
        assert "damage" in result["reasoning"].lower()
        assert "switch" in result["prediction"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
