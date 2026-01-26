"""Battle logging with directory-based incremental writes.

Log structure:
  logs/battles/{battle_id}/
    metadata.json              - battle info, created at start, updated at end
    protocol.jsonl             - raw showdown protocol, one line per turn
    {safe_player_id}.jsonl     - one line per action per player (LLM decisions)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any


class BattleLogger:
    """
    Logger for LLM battle outputs.

    Writes incrementally to per-battle directories for crash safety.
    Each action is appended as a single JSONL line immediately.
    """

    def __init__(self, log_dir: str = "logs", enabled: bool = True):
        self.enabled = enabled
        self.log_dir = Path(log_dir)
        self.battles_dir = self.log_dir / "battles"

        # Track per-battle state to avoid duplicate protocol writes
        # battle_id -> {"last_logged_protocol_turn": int}
        self._battle_state: dict[str, dict] = {}

        if self.enabled:
            self.battles_dir.mkdir(parents=True, exist_ok=True)

    def _safe_filename(self, player_id: str) -> str:
        """Sanitize player_id for use as a filename."""
        return player_id.replace("/", "_").replace("\\", "_")

    def _battle_dir(self, battle_id: str) -> Path:
        """Get or create the directory for a battle."""
        safe_id = battle_id.replace("/", "_").replace("\\", "_")
        d = self.battles_dir / safe_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def start_battle(
        self,
        battle_id: str,
        player_id: str,
        model: str,
        showdown_username: str,
        opponent_player_id: Optional[str] = None,
        player_team: str = "unknown",
    ) -> None:
        """
        Register a player for a battle.

        Creates the battle directory and metadata.json on first call per battle_id.
        Updates metadata with the second player on subsequent calls.
        """
        if not self.enabled:
            return

        battle_dir = self._battle_dir(battle_id)
        meta_path = battle_dir / "metadata.json"

        # Load existing metadata or create new
        if meta_path.exists():
            with open(meta_path) as f:
                metadata = json.load(f)
        else:
            metadata = {
                "battle_id": battle_id,
                "players": {},
                "started_at": self._now_iso(),
            }

        # Add this player's info
        metadata["players"][player_id] = {
            "model": model,
            "team": player_team,
            "showdown_username": showdown_username,
        }

        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)

        # Initialize battle state tracking
        if battle_id not in self._battle_state:
            self._battle_state[battle_id] = {"last_logged_protocol_turn": -1}

    def log_action(
        self,
        battle_id: str,
        player_id: str,
        turn: int,
        observation: str,
        state: str,
        raw_response: str,
        tool_calls: list[dict],
        parsed: dict,
        tokens: dict,
        latency_ms: int,
        confidence: str = "",
    ) -> None:
        """
        Append one action entry to the player's JSONL file.

        Called for both regular turns and forced switches (after faints),
        so multiple entries can share the same turn number.
        """
        if not self.enabled:
            return

        battle_dir = self._battle_dir(battle_id)
        safe_name = self._safe_filename(player_id)
        player_path = battle_dir / f"{safe_name}.jsonl"

        entry = {
            "turn": turn,
            "observation": observation,
            "state": state,
            "raw_response": raw_response,
            "tool_calls": tool_calls,
            "parsed": parsed,
            "tokens": tokens,
            "latency_ms": latency_ms,
            "confidence": confidence,
            "timestamp": self._now_iso(),
        }

        with open(player_path, "a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def log_protocol(self, battle_id: str, battle_observations: Any) -> None:
        """
        Write new turns from battle.observations to protocol.jsonl.

        Skips already-logged turns based on _battle_state tracking.
        battle_observations is expected to be a dict-like mapping
        turn_num -> observation object with .events (List[List[str]]).
        """
        if not self.enabled:
            return

        if not battle_observations:
            return

        state = self._battle_state.get(battle_id)
        if state is None:
            state = {"last_logged_protocol_turn": -1}
            self._battle_state[battle_id] = state

        battle_dir = self._battle_dir(battle_id)
        protocol_path = battle_dir / "protocol.jsonl"

        last_logged = state["last_logged_protocol_turn"]

        # Get all turn numbers and sort them
        try:
            turn_nums = sorted(int(k) for k in battle_observations.keys())
        except (AttributeError, ValueError):
            return

        new_entries = []
        for turn_num in turn_nums:
            if turn_num <= last_logged:
                continue
            obs = battle_observations[turn_num]
            events = getattr(obs, "events", None)
            if events is None:
                continue
            new_entries.append({"turn": turn_num, "events": events})
            state["last_logged_protocol_turn"] = turn_num

        if new_entries:
            with open(protocol_path, "a") as f:
                for entry in new_entries:
                    f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def log_fallback(
        self,
        battle_id: str,
        player_id: str,
        turn: int,
        reason: str,
        random_action: str,
    ) -> None:
        """Append a fallback entry to the player's JSONL file."""
        if not self.enabled:
            return

        battle_dir = self._battle_dir(battle_id)
        safe_name = self._safe_filename(player_id)
        player_path = battle_dir / f"{safe_name}.jsonl"

        entry = {
            "turn": turn,
            "fallback": True,
            "reason": reason,
            "random_action": random_action,
            "timestamp": self._now_iso(),
        }

        with open(player_path, "a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def end_battle(
        self,
        battle_id: str,
        player_id: str,
        won: bool,
        total_turns: int,
        forfeit: bool = False,
        battle_observations: Any = None,
    ) -> None:
        """
        Finalize a battle: flush remaining protocol, update metadata with outcome.
        """
        if not self.enabled:
            return

        # Final protocol flush
        if battle_observations:
            self.log_protocol(battle_id, battle_observations)

        battle_dir = self._battle_dir(battle_id)
        meta_path = battle_dir / "metadata.json"

        if not meta_path.exists():
            return

        with open(meta_path) as f:
            metadata = json.load(f)

        # Set outcome (first player to call end_battle wins this section)
        if "outcome" not in metadata:
            metadata["outcome"] = {}

        if won:
            metadata["outcome"]["winner_player_id"] = player_id
        metadata["outcome"]["total_turns"] = total_turns
        metadata["outcome"]["forfeit"] = forfeit
        metadata["completed_at"] = self._now_iso()

        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)

        # Clean up battle state
        self._battle_state.pop(battle_id, None)

    def get_orphaned_battles(self) -> list[Path]:
        """
        Find battle directories with metadata.json lacking completed_at.
        """
        if not self.battles_dir.exists():
            return []

        orphaned = []
        for battle_dir in self.battles_dir.iterdir():
            if not battle_dir.is_dir():
                continue
            meta_path = battle_dir / "metadata.json"
            if meta_path.exists():
                try:
                    with open(meta_path) as f:
                        metadata = json.load(f)
                    if "completed_at" not in metadata:
                        orphaned.append(battle_dir)
                except Exception:
                    orphaned.append(battle_dir)
        return orphaned


# Singleton instance for easy access
_default_logger: Optional[BattleLogger] = None


def get_logger(log_dir: str = "logs", enabled: bool = True) -> BattleLogger:
    """Get or create the default battle logger."""
    global _default_logger
    if _default_logger is None:
        _default_logger = BattleLogger(log_dir=log_dir, enabled=enabled)
    return _default_logger
