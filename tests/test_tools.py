"""Unit tests for tool implementations."""

import pytest
from unittest.mock import MagicMock, PropertyMock


# Test type tools
class TestTypeTools:
    """Tests for type_tools module."""

    def test_get_type_effectiveness_super_effective(self):
        from src.tools.type_tools import get_type_effectiveness
        result = get_type_effectiveness("fire", ["grass"])
        assert result["multiplier"] == 2.0
        assert "super effective" in result["description"]

    def test_get_type_effectiveness_double_super_effective(self):
        from src.tools.type_tools import get_type_effectiveness
        result = get_type_effectiveness("fire", ["grass", "steel"])
        assert result["multiplier"] == 4.0
        assert "doubly super effective" in result["description"]

    def test_get_type_effectiveness_immune(self):
        from src.tools.type_tools import get_type_effectiveness
        result = get_type_effectiveness("ground", ["flying"])
        assert result["multiplier"] == 0
        assert "immune" in result["description"]

    def test_get_type_effectiveness_resisted(self):
        from src.tools.type_tools import get_type_effectiveness
        result = get_type_effectiveness("fire", ["water"])
        assert result["multiplier"] == 0.5
        assert "resisted" in result["description"]

    def test_get_type_effectiveness_neutral(self):
        from src.tools.type_tools import get_type_effectiveness
        result = get_type_effectiveness("normal", ["ground"])
        assert result["multiplier"] == 1.0
        assert "neutral" in result["description"]

    def test_get_type_effectiveness_invalid_type(self):
        from src.tools.type_tools import get_type_effectiveness
        result = get_type_effectiveness("invalid", ["grass"])
        assert "error" in result

    def test_get_all_type_matchups(self):
        from src.tools.type_tools import get_all_type_matchups
        result = get_all_type_matchups(["steel", "psychic"])
        assert "weaknesses" in result
        assert "resistances" in result
        assert "immunities" in result
        assert "poison" in result["immunities"]
        assert "fire" in result["weaknesses"]


# Test info tools
class TestInfoTools:
    """Tests for info_tools module."""

    def test_get_pokemon_info(self):
        from src.tools.info_tools import get_pokemon_info
        result = get_pokemon_info("gengar")
        assert "error" not in result
        assert result["name"].lower() == "gengar"
        assert "ghost" in [t.lower() for t in result["types"]]
        assert "base_stats" in result
        assert result["base_stats"]["spe"] == 110

    def test_get_pokemon_info_invalid(self):
        from src.tools.info_tools import get_pokemon_info
        result = get_pokemon_info("notapokemon123")
        assert "error" in result

    def test_get_move_details(self):
        from src.tools.info_tools import get_move_details
        result = get_move_details("earthquake")
        assert "error" not in result
        assert result["type"] == "ground"
        assert result["base_power"] == 100
        assert result["category"] == "physical"

    def test_get_move_details_invalid(self):
        from src.tools.info_tools import get_move_details
        result = get_move_details("notamove123")
        assert "error" in result


# Test plan tools
class TestPlanTools:
    """Tests for plan_tools module."""

    def test_add_goal(self):
        from src.tools.plan_tools import update_battle_plan, get_battle_plan
        plan = {"goals": [], "predictions": {}}
        
        result = update_battle_plan(plan, "add_goal", text="Set up Stealth Rock")
        assert result["success"]
        assert result["goal_id"] == 1
        
        summary = get_battle_plan(plan)
        assert len(summary["active_goals"]) == 1
        assert summary["active_goals"][0]["goal"] == "Set up Stealth Rock"

    def test_complete_goal(self):
        from src.tools.plan_tools import update_battle_plan, get_battle_plan
        plan = {"goals": [{"id": 1, "goal": "Test", "status": "active", "notes": ""}], "predictions": {}}
        
        result = update_battle_plan(plan, "complete_goal", goal_id=1)
        assert result["success"]
        
        summary = get_battle_plan(plan)
        assert len(summary["completed_goals"]) == 1
        assert len(summary["active_goals"]) == 0

    def test_abandon_goal(self):
        from src.tools.plan_tools import update_battle_plan, get_battle_plan
        plan = {"goals": [{"id": 1, "goal": "Test", "status": "active", "notes": ""}], "predictions": {}}
        
        result = update_battle_plan(plan, "abandon_goal", goal_id=1)
        assert result["success"]
        
        summary = get_battle_plan(plan)
        assert len(summary["abandoned_goals"]) == 1

    def test_add_note(self):
        from src.tools.plan_tools import update_battle_plan
        plan = {"goals": [{"id": 1, "goal": "Test", "status": "active", "notes": ""}], "predictions": {}}
        
        result = update_battle_plan(plan, "add_note", goal_id=1, text="Progress made")
        assert result["success"]
        assert plan["goals"][0]["notes"] == "Progress made"


# Mock battle for testing battle-dependent tools
def create_mock_battle():
    """Create a mock battle object for testing."""
    battle = MagicMock()
    
    # Mock active Pokemon
    active = MagicMock()
    active.species = "tyranitar"
    active.current_hp_fraction = 0.8
    active.fainted = False
    active.status = None
    active.boosts = {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
    active.base_stats = {"hp": 100, "atk": 134, "def": 110, "spa": 95, "spd": 100, "spe": 61}
    active.types = [MagicMock(name="ROCK"), MagicMock(name="DARK")]
    active.types[0].name = "ROCK"
    active.types[1].name = "DARK"
    active.ability = "sandstream"
    active.item = "leftovers"
    active.moves = {}
    
    # Mock opponent
    opponent = MagicMock()
    opponent.species = "gengar"
    opponent.current_hp_fraction = 1.0
    opponent.fainted = False
    opponent.status = None
    opponent.boosts = {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
    opponent.base_stats = {"hp": 60, "atk": 65, "def": 60, "spa": 130, "spd": 75, "spe": 110}
    opponent.types = [MagicMock(name="GHOST"), MagicMock(name="POISON")]
    opponent.types[0].name = "GHOST"
    opponent.types[1].name = "POISON"
    opponent.ability = "levitate"
    opponent.item = None
    opponent.moves = {}
    
    # Mock damage multiplier method
    def damage_multiplier(move_or_type):
        # Simplified - just return 1.0 for testing
        return 1.0
    
    active.damage_multiplier = damage_multiplier
    opponent.damage_multiplier = damage_multiplier
    
    battle.active_pokemon = active
    battle.opponent_active_pokemon = opponent
    battle.team = {"p1: Tyranitar": active}
    battle.opponent_team = {"p2: Gengar": opponent}
    battle.available_moves = []
    battle.available_switches = []
    battle.turn = 1
    battle.player_role = "p1"
    battle.weather = {}
    battle.side_conditions = {}
    battle.opponent_side_conditions = {}
    battle.fields = {}
    battle.observations = {}
    
    return battle


class TestTeamTools:
    """Tests for team_tools module."""

    def test_get_team_summary(self):
        from src.tools.team_tools import get_team_summary
        battle = create_mock_battle()
        
        result = get_team_summary(battle)
        assert "active" in result
        assert "bench" in result
        assert "alive_count" in result

    def test_get_opponent_team_summary(self):
        from src.tools.team_tools import get_opponent_team_summary
        battle = create_mock_battle()
        
        result = get_opponent_team_summary(battle)
        assert "revealed_count" in result
        assert "unrevealed_count" in result


class TestFieldTools:
    """Tests for field_tools module."""

    def test_get_field_analysis_empty(self):
        from src.tools.field_tools import get_field_analysis
        battle = create_mock_battle()
        
        result = get_field_analysis(battle)
        assert "weather" in result
        assert "your_hazards" in result
        assert "opponent_hazards" in result
        assert "tactical_notes" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
