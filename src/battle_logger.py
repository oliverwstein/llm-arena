"""Battle logging for LLM outputs and decision tracking.

Logs comprehensive turn-by-turn data for article writing and debugging.
Uses JSONL format with one line per participant per battle.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field, asdict


@dataclass
class TurnData:
    """Data logged for a single turn."""
    turn: int
    observation: str  # What happened previous turn (battle events)
    state: str  # Current battle state shown to LLM
    raw_response: str  # Full LLM response before parsing
    tool_calls: list[dict] = field(default_factory=list)  # [{name, args, result, duration_ms}]
    parsed: dict = field(default_factory=dict)  # {action, reasoning, prediction}
    tokens: dict = field(default_factory=dict)  # {input, output}
    latency_ms: int = 0


@dataclass
class BattleEntry:
    """Complete record for one participant in a battle."""
    battle_id: str
    player_name: str
    model: str
    opponent: dict  # {name, model or "heuristic"}
    turns: list[dict] = field(default_factory=list)
    outcome: Optional[dict] = None  # {won, total_turns, forfeit}
    battle_plan: list[dict] = field(default_factory=list)  # Goals over time
    started_at: str = ""
    completed_at: str = ""


class BattleLogger:
    """
    Logger for LLM battle outputs.

    Writes to:
    - logs/active/{battle_id}_{player}.json - In-progress battles (crash-safe)
    - logs/battles.jsonl - Completed battles (one line per participant)
    """

    def __init__(self, log_dir: str = "logs", enabled: bool = True):
        """
        Initialize the battle logger.

        Args:
            log_dir: Directory for log files
            enabled: If False, all operations are no-ops
        """
        self.enabled = enabled
        self.log_dir = Path(log_dir)
        self.active_dir = self.log_dir / "active"
        self.jsonl_path = self.log_dir / "battles.jsonl"

        # Track active battles: (battle_id, player_name) -> BattleEntry
        self._active_battles: dict[tuple[str, str], BattleEntry] = {}

        if self.enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.active_dir.mkdir(parents=True, exist_ok=True)

    def _get_active_path(self, battle_id: str, player_name: str) -> Path:
        """Get path to active battle temp file."""
        # Sanitize names for filesystem
        safe_battle_id = battle_id.replace("/", "_").replace("\\", "_")
        safe_player = player_name.replace("/", "_").replace("\\", "_")
        return self.active_dir / f"{safe_battle_id}_{safe_player}.json"

    def _now_iso(self) -> str:
        """Get current time as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    def start_battle(
        self,
        battle_id: str,
        player_name: str,
        model: str,
        opponent_name: str,
        opponent_model: Optional[str] = None
    ) -> None:
        """
        Start tracking a new battle for a participant.

        Creates a temp file in logs/active/ for crash safety.

        Args:
            battle_id: Unique battle identifier
            player_name: This player's display name
            model: This player's LLM model ID
            opponent_name: Opponent's display name
            opponent_model: Opponent's model ID (None for heuristic/random bots)
        """
        if not self.enabled:
            return

        key = (battle_id, player_name)

        entry = BattleEntry(
            battle_id=battle_id,
            player_name=player_name,
            model=model,
            opponent={
                "name": opponent_name,
                "model": opponent_model or "heuristic"
            },
            started_at=self._now_iso()
        )

        self._active_battles[key] = entry
        self._save_active(entry)

    def log_turn(
        self,
        battle_id: str,
        player_name: str,
        turn: int,
        observation: str,
        state: str,
        raw_response: str,
        tool_calls: list[dict],
        parsed: dict,
        tokens: dict,
        latency_ms: int,
        battle_plan: Optional[list[dict]] = None
    ) -> None:
        """
        Log data for a single turn.

        Appends to temp file immediately for crash safety.

        Args:
            battle_id: Battle identifier
            player_name: Player name
            turn: Turn number
            observation: Previous turn events
            state: Current battle state shown to LLM
            raw_response: Full LLM response
            tool_calls: List of tool call records
            parsed: Parsed action/reasoning/prediction
            tokens: Token usage {input, output}
            latency_ms: Total decision time
            battle_plan: Optional current battle plan state
        """
        if not self.enabled:
            return

        key = (battle_id, player_name)
        entry = self._active_battles.get(key)

        if not entry:
            # Battle not started via start_battle - auto-create
            entry = BattleEntry(
                battle_id=battle_id,
                player_name=player_name,
                model="unknown",
                opponent={"name": "unknown", "model": "unknown"},
                started_at=self._now_iso()
            )
            self._active_battles[key] = entry

        turn_data = TurnData(
            turn=turn,
            observation=observation,
            state=state,
            raw_response=raw_response,
            tool_calls=tool_calls,
            parsed=parsed,
            tokens=tokens,
            latency_ms=latency_ms
        )

        entry.turns.append(asdict(turn_data))

        if battle_plan is not None:
            entry.battle_plan = battle_plan

        self._save_active(entry)

    def log_fallback(
        self,
        battle_id: str,
        player_name: str,
        turn: int,
        reason: str,
        random_action: str
    ) -> None:
        """
        Log when LLM fails and a random move is chosen.

        Args:
            battle_id: Battle identifier
            player_name: Player name
            turn: Turn number
            reason: Why fallback occurred (timeout, api_error, token_limit, etc.)
            random_action: Description of the random action chosen
        """
        if not self.enabled:
            return

        key = (battle_id, player_name)
        entry = self._active_battles.get(key)

        if not entry:
            return

        # Add fallback info to the last turn if it exists, or create a minimal entry
        fallback_data = {
            "fallback": True,
            "reason": reason,
            "random_action": random_action
        }

        if entry.turns:
            # Update the last turn with fallback info
            entry.turns[-1]["fallback"] = fallback_data
        else:
            # No turns yet - create a fallback-only entry
            entry.turns.append({
                "turn": turn,
                "observation": "",
                "state": "",
                "raw_response": "",
                "tool_calls": [],
                "parsed": {"action": random_action, "reasoning": f"FALLBACK: {reason}"},
                "tokens": {},
                "latency_ms": 0,
                "fallback": fallback_data
            })

        self._save_active(entry)

    def end_battle(
        self,
        battle_id: str,
        player_name: str,
        won: bool,
        total_turns: int,
        forfeit: bool = False
    ) -> None:
        """
        Finalize a battle and write to JSONL.

        Reads from temp file, appends as JSONL line, deletes temp file.

        Args:
            battle_id: Battle identifier
            player_name: Player name
            won: Whether this player won
            total_turns: Total turns in the battle
            forfeit: Whether battle ended by forfeit
        """
        if not self.enabled:
            return

        key = (battle_id, player_name)
        entry = self._active_battles.pop(key, None)

        if not entry:
            # Try loading from temp file (crash recovery)
            temp_path = self._get_active_path(battle_id, player_name)
            if temp_path.exists():
                try:
                    with open(temp_path) as f:
                        data = json.load(f)
                    entry = BattleEntry(**data)
                except Exception:
                    return
            else:
                return

        # Set outcome
        entry.outcome = {
            "won": won,
            "total_turns": total_turns,
            "forfeit": forfeit
        }
        entry.completed_at = self._now_iso()

        # Append to JSONL
        self._append_jsonl(entry)

        # Remove temp file
        temp_path = self._get_active_path(battle_id, player_name)
        if temp_path.exists():
            temp_path.unlink()

    def _save_active(self, entry: BattleEntry) -> None:
        """Save entry to active temp file."""
        temp_path = self._get_active_path(entry.battle_id, entry.player_name)
        with open(temp_path, "w") as f:
            json.dump(asdict(entry), f, indent=2)

    def _append_jsonl(self, entry: BattleEntry) -> None:
        """Append entry as a single JSONL line."""
        with open(self.jsonl_path, "a") as f:
            f.write(json.dumps(asdict(entry), separators=(",", ":")) + "\n")

    def get_orphaned_battles(self) -> list[Path]:
        """
        Find orphaned active battle files (from crashes).

        Returns list of paths to orphaned temp files.
        """
        if not self.active_dir.exists():
            return []
        return list(self.active_dir.glob("*.json"))

    def recover_orphaned_battle(self, temp_path: Path) -> Optional[dict]:
        """
        Load an orphaned battle file for inspection/recovery.

        Args:
            temp_path: Path to orphaned temp file

        Returns:
            Battle data dict or None if load failed
        """
        try:
            with open(temp_path) as f:
                return json.load(f)
        except Exception:
            return None


# Singleton instance for easy access
_default_logger: Optional[BattleLogger] = None


def get_logger(log_dir: str = "logs", enabled: bool = True) -> BattleLogger:
    """
    Get or create the default battle logger.

    Args:
        log_dir: Directory for log files
        enabled: If False, returns a disabled logger

    Returns:
        BattleLogger instance
    """
    global _default_logger
    if _default_logger is None:
        _default_logger = BattleLogger(log_dir=log_dir, enabled=enabled)
    return _default_logger
