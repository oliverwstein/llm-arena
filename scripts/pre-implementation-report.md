# Pre-Implementation Report: Round Robin Tournament Restructuring

**Date:** 2026-01-27

## Overview

This report documents the planned restructuring of the round robin tournament system in `scripts/run_round_robin.py`. The goal is to create a self-contained tournament directory structure with sensible naming conventions, replacing the current scattered and opaque output system.

## Current State Analysis

### Problems Identified

1. **Scattered outputs**: `tournament.json` written to repo root, logs go to `logs/tournament/battles/`
2. **Opaque naming**: Log directories named by Showdown's battle tag (e.g., `battle-gen4ou-1886`), player files use UUID-based names
3. **Fragile username scheme**: `{model_name}-{uuid[:8]}` truncated to 18 chars with hacky collision workaround
4. **No live match tracking**: `metadata.json` only records start/end state, manifest stores unuseful `session_id` as `battle_id`

### Current Code Structure

**`run_round_robin.py`:**
- `generate_manifest()`: Creates `tournament.json` at repo root via `--output` flag
- `run_match()`: Uses UUIDs for usernames and player IDs, creates players with shared global logger
- `run_tournament()`: Creates single `BattleLogger` at `logs/tournament`, shared across all matches
- `cmd_generate()`: Has `--output/-o` argument defaulting to `tournament.json`

**`BattleLogger` (src/battle_logger.py):**
- `_battle_dir()`: Returns `battles_dir / battle_id` (creates `battles/{battle_tag}/`)
- Files named `{player_id}.jsonl` using the `player_id` parameter
- Not modified per plan - only script-level changes

## Planned Changes

### New Directory Structure

```
logs/{tournament-name}/
  manifest.json
  match-0001/
    metadata.json
    protocol.jsonl
    {model-name}-A.jsonl
    {model-name}-B.jsonl
  match-0002/
    ...
```

### Implementation Details

#### 1. New `MatchLogger` Subclass (in script)

```python
class MatchLogger(BattleLogger):
    def _battle_dir(self, battle_id: str) -> Path:
        """Write all files directly to log_dir (the match directory)."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        return self.log_dir
```

- Override `__init__` to avoid creating default `battles/` subdirectory
- Override `log_action` to update `metadata.json` with `current_turn`
- One instance per match, pointed at `match-XXXX/`

#### 2. `generate_manifest()` Changes

- Create `logs/{tournament-name}/` directory
- Create empty `match-XXXX/` subdirectories for each match
- Write `manifest.json` inside tournament directory
- Replace `--output` CLI arg with `--log-dir` (default `logs/`)

#### 3. `run_match()` Changes

- Username format: `{model_name[:16]}-A` / `{model_name[:16]}-B` (always preserve suffix)
- Player ID = username (makes JSONL files named `{username}.jsonl`)
- Remove session_id/UUID generation
- Create per-match `MatchLogger` instead of shared global logger
- Store Showdown battle tag in manifest as `battle_tag`

#### 4. `run_tournament()` Changes

- Derive tournament directory from manifest path (its parent)
- Remove global `BattleLogger` creation
- Remove hardcoded `log_dir = Path("logs/tournament")`

#### 5. CLI Changes

**`cmd_generate()`:**
- Remove `--output/-o`
- Add `--log-dir` (default: `logs/`)
- Output path: `{log-dir}/{tournament-name}/manifest.json`

**`cmd_run()`:**
- `--manifest` now points to `logs/{name}/manifest.json`

### Files Unchanged

- `src/battle_logger.py`
- `src/agent_player.py`
- `src/llm_player.py`
- `src/mock_player.py`

### Misc Cleanup

- Move `import random` to top of file
- Remove `result` field from match entries (redundant with `winner` + `status`)

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking existing functionality | Only modifying script, not src/ layer |
| Log file naming issues | Using username as player_id ensures correct naming |
| Metadata race conditions | One MatchLogger per match prevents conflicts |

## Verification Plan

1. `python3 scripts/run_round_robin.py generate --models Grok-4 DeepSeek-Reasoner Gemini-3-Flash GPT-5-Mini --games-per-pair 3`
2. Check `logs/{name}/manifest.json` exists and `match-0001/` through `match-0018/` directories created
3. `python3 scripts/run_round_robin.py run --manifest logs/{name}/manifest.json --mock`
4. Verify per-match directories contain correct files
5. Verify `metadata.json` tracks `current_turn`, `started_at`, `completed_at`
6. Test Ctrl+C pause and resume
