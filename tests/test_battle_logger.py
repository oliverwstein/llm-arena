"""Tests for the battle logging system."""

import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.battle_logger import BattleLogger


def test_basic_logging():
    """Test basic battle logging flow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = BattleLogger(log_dir=tmpdir, enabled=True)

        # Start a battle
        logger.start_battle(
            battle_id="battle-test-123",
            player_name="TestPlayer",
            model="claude-sonnet-4-20250514",
            opponent_name="Heuristic",
            opponent_model=None
        )

        # Log a turn
        logger.log_turn(
            battle_id="battle-test-123",
            player_name="TestPlayer",
            turn=1,
            observation="(Battle just started)",
            state="YOUR ACTIVE: Heatran (100% HP)",
            raw_response="ACTION: move stealthrock\nREASONING: Set up entry hazards.",
            tool_calls=[
                {"name": "get_type_matchup", "args": "{}", "result": "neutral", "duration_ms": 10}
            ],
            parsed={"action": "move stealthrock", "reasoning": "Set up entry hazards.", "prediction": ""},
            tokens={"input": 100, "output": 50},
            latency_ms=1500,
            battle_plan=[{"goal": "Set up hazards", "status": "active"}]
        )

        # Check temp file exists
        active_dir = Path(tmpdir) / "active"
        temp_files = list(active_dir.glob("*.json"))
        assert len(temp_files) == 1, "Should have one active battle file"

        # End battle
        logger.end_battle(
            battle_id="battle-test-123",
            player_name="TestPlayer",
            won=True,
            total_turns=15,
            forfeit=False
        )

        # Check temp file is removed
        temp_files = list(active_dir.glob("*.json"))
        assert len(temp_files) == 0, "Temp file should be removed after battle ends"

        # Check JSONL file
        jsonl_path = Path(tmpdir) / "battles.jsonl"
        assert jsonl_path.exists(), "JSONL file should exist"

        with open(jsonl_path) as f:
            lines = f.readlines()

        assert len(lines) == 1, "Should have one line in JSONL"

        data = json.loads(lines[0])
        assert data["battle_id"] == "battle-test-123"
        assert data["player_name"] == "TestPlayer"
        assert data["model"] == "claude-sonnet-4-20250514"
        assert data["opponent"]["name"] == "Heuristic"
        assert data["opponent"]["model"] == "heuristic"
        assert len(data["turns"]) == 1
        assert data["turns"][0]["turn"] == 1
        assert data["turns"][0]["latency_ms"] == 1500
        assert data["outcome"]["won"] is True
        assert data["outcome"]["total_turns"] == 15

        print("All assertions passed!")


def test_disabled_logging():
    """Test that disabled logger doesn't create files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = BattleLogger(log_dir=tmpdir, enabled=False)

        logger.start_battle(
            battle_id="battle-test-456",
            player_name="TestPlayer",
            model="gpt-4o",
            opponent_name="Opponent",
        )

        logger.log_turn(
            battle_id="battle-test-456",
            player_name="TestPlayer",
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
            player_name="TestPlayer",
            won=False,
            total_turns=1,
        )

        # Nothing should be created
        log_dir = Path(tmpdir)
        assert not (log_dir / "battles.jsonl").exists()
        assert not (log_dir / "active").exists()

        print("Disabled logger test passed!")


def test_multiple_participants():
    """Test logging for both participants in a battle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = BattleLogger(log_dir=tmpdir, enabled=True)

        # Start battles for both players
        logger.start_battle("battle-123", "Player1", "claude-sonnet-4-20250514", "Player2", "gpt-4o")
        logger.start_battle("battle-123", "Player2", "gpt-4o", "Player1", "claude-sonnet-4-20250514")

        # Log turns
        logger.log_turn("battle-123", "Player1", 1, "", "", "ACTION: move thunderbolt", [], {}, {}, 1000)
        logger.log_turn("battle-123", "Player2", 1, "", "", "ACTION: move earthquake", [], {}, {}, 1200)

        # End battles
        logger.end_battle("battle-123", "Player1", won=True, total_turns=10)
        logger.end_battle("battle-123", "Player2", won=False, total_turns=10)

        # Check JSONL has two lines
        jsonl_path = Path(tmpdir) / "battles.jsonl"
        with open(jsonl_path) as f:
            lines = f.readlines()

        assert len(lines) == 2, "Should have two lines (one per participant)"

        data1 = json.loads(lines[0])
        data2 = json.loads(lines[1])

        assert data1["battle_id"] == data2["battle_id"]
        assert data1["player_name"] != data2["player_name"]
        assert data1["outcome"]["won"] != data2["outcome"]["won"]

        print("Multiple participants test passed!")


if __name__ == "__main__":
    test_basic_logging()
    test_disabled_logging()
    test_multiple_participants()
    print("\nAll tests passed!")
