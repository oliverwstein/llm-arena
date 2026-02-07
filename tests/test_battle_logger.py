"""Tests for the battle logging system."""

import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.battle_logger import BattleLogger


def test_basic_logging():
    """Test basic battle logging flow: start, log action, end."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = BattleLogger(log_dir=tmpdir, enabled=True)

        # Start a battle (player A)
        logger.start_battle(
            battle_id="battle-test-123",
            player_id="Claude-Sonnet-A",
            model="claude-sonnet-4-20250514",
            showdown_username="Claude-Sonnet-A",
            player_team="Team Stall",
        )

        # Check metadata was created
        battle_dir = Path(tmpdir) / "battles" / "battle-test-123"
        meta_path = battle_dir / "metadata.json"
        assert meta_path.exists(), "metadata.json should exist after start_battle"

        with open(meta_path) as f:
            metadata = json.load(f)

        assert metadata["battle_id"] == "battle-test-123"
        assert "Claude-Sonnet-A" in metadata["players"]
        player_info = metadata["players"]["Claude-Sonnet-A"]
        assert player_info["model"] == "claude-sonnet-4-20250514"
        assert player_info["showdown_username"] == "Claude-Sonnet-A"
        assert player_info["team"] == "Team Stall"

        # Log an action
        logger.log_action(
            battle_id="battle-test-123",
            player_id="Claude-Sonnet-A",
            turn=1,
            observation="(Battle just started)",
            state="YOUR ACTIVE: Heatran (100% HP)",
            raw_response="ACTION: move stealthrock\nREASONING: Set up entry hazards.",
            tool_calls=[
                {"name": "get_type_matchup", "args": "{}", "result": "neutral", "duration_ms": 10}
            ],
            parsed={"action": "move stealthrock", "reasoning": "Set up entry hazards."},
            tokens={"input": 100, "output": 50},
            latency_ms=1500,
        )

        # Check player JSONL was written
        player_log = battle_dir / "Claude-Sonnet-A.jsonl"
        assert player_log.exists(), "Player JSONL should exist after log_action"

        with open(player_log) as f:
            entry = json.loads(f.readline())

        assert entry["turn"] == 1
        assert entry["latency_ms"] == 1500
        assert entry["parsed"]["action"] == "move stealthrock"

        # End battle
        logger.end_battle(
            battle_id="battle-test-123",
            player_id="Claude-Sonnet-A",
            won=True,
            total_turns=15,
            forfeit=False,
        )

        # Check metadata was updated with outcome
        with open(meta_path) as f:
            metadata = json.load(f)

        assert metadata["outcome"]["winner_player_id"] == "Claude-Sonnet-A"
        assert metadata["outcome"]["total_turns"] == 15
        assert "completed_at" in metadata


def test_disabled_logging():
    """Test that disabled logger doesn't create files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = BattleLogger(log_dir=tmpdir, enabled=False)

        logger.start_battle(
            battle_id="battle-test-456",
            player_id="TestPlayer",
            model="gpt-4o",
            showdown_username="TestPlayer",
        )

        logger.log_action(
            battle_id="battle-test-456",
            player_id="TestPlayer",
            turn=1,
            observation="",
            state="",
            raw_response="",
            tool_calls=[],
            parsed={},
            tokens={},
            latency_ms=0,
        )

        logger.end_battle(
            battle_id="battle-test-456",
            player_id="TestPlayer",
            won=False,
            total_turns=1,
        )

        # Nothing should be created
        battles_dir = Path(tmpdir) / "battles"
        assert not battles_dir.exists(), "No battles dir should be created when disabled"


def test_multiple_participants():
    """Test logging for both participants in a battle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = BattleLogger(log_dir=tmpdir, enabled=True)

        # Both players start the same battle
        logger.start_battle(
            battle_id="battle-123",
            player_id="Claude-A",
            model="claude-sonnet-4-20250514",
            showdown_username="Claude-A",
            player_team="Team Offense",
        )
        logger.start_battle(
            battle_id="battle-123",
            player_id="GPT-B",
            model="gpt-4o",
            showdown_username="GPT-B",
            player_team="Team Stall",
        )

        # Check metadata has both players
        battle_dir = Path(tmpdir) / "battles" / "battle-123"
        meta_path = battle_dir / "metadata.json"
        with open(meta_path) as f:
            metadata = json.load(f)

        assert "Claude-A" in metadata["players"]
        assert "GPT-B" in metadata["players"]

        # Log actions for both
        logger.log_action(
            battle_id="battle-123", player_id="Claude-A", turn=1,
            observation="", state="", raw_response="move thunderbolt",
            tool_calls=[], parsed={}, tokens={}, latency_ms=1000,
        )
        logger.log_action(
            battle_id="battle-123", player_id="GPT-B", turn=1,
            observation="", state="", raw_response="move earthquake",
            tool_calls=[], parsed={}, tokens={}, latency_ms=1200,
        )

        # End battles
        logger.end_battle("battle-123", "Claude-A", won=True, total_turns=10)
        logger.end_battle("battle-123", "GPT-B", won=False, total_turns=10)

        with open(meta_path) as f:
            metadata = json.load(f)

        assert metadata["outcome"]["winner_player_id"] == "Claude-A"
        assert metadata["outcome"]["total_turns"] == 10

        # Both player JSONL files should exist
        assert (battle_dir / "Claude-A.jsonl").exists()
        assert (battle_dir / "GPT-B.jsonl").exists()


def test_player_mode_and_class():
    """Test that player_mode and player_class are included in metadata when provided."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = BattleLogger(log_dir=tmpdir, enabled=True)

        # Start with mode and class info
        logger.start_battle(
            battle_id="battle-mirror-1",
            player_id="Gemini-3-Fl-tool-A",
            model="gemini/gemini-3-flash-preview",
            showdown_username="Gemini-3-Fl-tool-A",
            player_team="Team Offense",
            player_mode="tools",
            player_class="LLMPlayer",
        )
        logger.start_battle(
            battle_id="battle-mirror-1",
            player_id="Gemini-3-Fl-conv-B",
            model="gemini/gemini-3-flash-preview",
            showdown_username="Gemini-3-Fl-conv-B",
            player_team="Team Stall",
            player_mode="conversational",
            player_class="ConversationalLLMPlayer",
        )

        battle_dir = Path(tmpdir) / "battles" / "battle-mirror-1"
        meta_path = battle_dir / "metadata.json"
        with open(meta_path) as f:
            metadata = json.load(f)

        player_a = metadata["players"]["Gemini-3-Fl-tool-A"]
        assert player_a["mode"] == "tools"
        assert player_a["player_class"] == "LLMPlayer"

        player_b = metadata["players"]["Gemini-3-Fl-conv-B"]
        assert player_b["mode"] == "conversational"
        assert player_b["player_class"] == "ConversationalLLMPlayer"


def test_player_mode_optional():
    """Test that player_mode and player_class are omitted when not provided (backward compat)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = BattleLogger(log_dir=tmpdir, enabled=True)

        logger.start_battle(
            battle_id="battle-compat-1",
            player_id="SomePlayer",
            model="claude-sonnet-4-20250514",
            showdown_username="SomePlayer",
        )

        battle_dir = Path(tmpdir) / "battles" / "battle-compat-1"
        meta_path = battle_dir / "metadata.json"
        with open(meta_path) as f:
            metadata = json.load(f)

        player_info = metadata["players"]["SomePlayer"]
        assert "mode" not in player_info, "mode should not be present when not provided"
        assert "player_class" not in player_info, "player_class should not be present when not provided"


def test_fallback_logging():
    """Test fallback action logging."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = BattleLogger(log_dir=tmpdir, enabled=True)

        logger.start_battle(
            battle_id="battle-fb-1",
            player_id="TestPlayer",
            model="test-model",
            showdown_username="TestPlayer",
        )

        logger.log_fallback(
            battle_id="battle-fb-1",
            player_id="TestPlayer",
            turn=3,
            reason="timeout",
            random_action="move tackle",
        )

        battle_dir = Path(tmpdir) / "battles" / "battle-fb-1"
        player_log = battle_dir / "TestPlayer.jsonl"
        assert player_log.exists()

        with open(player_log) as f:
            entry = json.loads(f.readline())

        assert entry["fallback"] is True
        assert entry["reason"] == "timeout"
        assert entry["random_action"] == "move tackle"


if __name__ == "__main__":
    test_basic_logging()
    test_disabled_logging()
    test_multiple_participants()
    test_player_mode_and_class()
    test_player_mode_optional()
    test_fallback_logging()
    print("\nAll tests passed!")
