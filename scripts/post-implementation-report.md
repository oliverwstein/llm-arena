# Post-Implementation Report: Round Robin Tournament Restructuring

**Date:** 2026-01-27

## Summary

Successfully implemented the round robin tournament restructuring as specified in `scripts/plan.md`. All changes were confined to `scripts/run_round_robin.py` as required, with no modifications to the `src/` layer.

## Changes Made

### 1. New `MatchLogger` Subclass (Lines 52-105)

Created a `BattleLogger` subclass that writes files flat into a match directory:

```python
class MatchLogger(BattleLogger):
    def __init__(self, match_dir: str, enabled: bool = True):
        # Initialize directly to match_dir, bypassing battles/ subdirectory
        
    def _battle_dir(self, battle_id: str) -> Path:
        # Returns log_dir directly (the match directory)
        
    def log_action(...):
        # Calls parent, then updates metadata.json with current_turn
```

Key features:
- One instance per match
- Writes directly to `match-XXXX/` directory
- Updates `metadata.json` with `current_turn` on each action for live tracking

### 2. `generate_manifest()` Restructured (Lines 108-192)

Changes:
- **Parameter change**: `output_path` → `log_dir` (default: `logs`)
- **Return value**: Now returns `(manifest, manifest_path)` tuple
- **Directory creation**: Creates `logs/{tournament-name}/` and `match-XXXX/` subdirectories
- **Manifest location**: Written inside tournament directory as `manifest.json`
- **Match schema**: Removed `result` field, renamed `battle_id` to `battle_tag`

### 3. `run_match()` Restructured (Lines 209-316)

Changes:
- **Parameter change**: `logger: BattleLogger` → `match_dir: Path`
- **Username format**: `{model_name[:16]}-A` / `{model_name[:16]}-B` (always preserves suffix)
- **Player ID = username**: JSONL files now named `{username}.jsonl` (e.g., `Grok-4-A.jsonl`)
- **Per-match logger**: Creates `MatchLogger(match_dir)` instead of using shared global logger
- **Battle tag capture**: Stores actual Showdown battle tag for debugging reference
- **Removed**: UUID generation, session_id, `result` field

### 4. `run_tournament()` Updated (Lines 319-520)

Changes:
- **Tournament directory**: Derived from `manifest_path.parent`
- **Global logger removed**: No longer creates shared `BattleLogger`
- **Worker function**: Computes `match_dir` and passes to `run_match()`
- **Import cleanup**: Removed inner `import random` (now at top of file)

### 5. CLI Changes

**`cmd_generate()` (Lines 585-645)**:
- Removed `--output/-o` argument
- Added `--log-dir` argument (default: `logs`)
- Checks tournament directory existence (not just manifest file)
- Prints manifest path instead of generic output path

**Argument parser (Lines 684-699)**:
- `--log-dir` replaces `--output/-o`
- Help text updated for `--force` flag

### 6. Other Changes

- **Imports**: Removed `uuid`, added `random` to top-level imports (line 29)
- **Docstring**: Updated examples to use `logs/{tournament-name}/manifest.json` paths

## New Directory Structure

```
logs/{tournament-name}/
  manifest.json              # Tournament manifest
  match-0001/                # Per-match directory
    metadata.json            # Battle info + current_turn tracking
    protocol.jsonl           # Raw Showdown protocol
    {ModelA}-A.jsonl         # Player A decisions
    {ModelB}-B.jsonl         # Player B decisions
  match-0002/
    ...
```

## Match Schema Changes

**Before:**
```json
{
  "id": 1,
  "model_a": "Grok-4",
  "model_b": "DeepSeek",
  "status": "pending",
  "result": null,
  "winner": null,
  "battle_id": "abc12345"
}
```

**After:**
```json
{
  "id": 1,
  "model_a": "Grok-4",
  "model_b": "DeepSeek",
  "status": "pending",
  "winner": null,
  "battle_tag": null
}
```

## Files Unchanged (as required)

- `src/battle_logger.py`
- `src/agent_player.py`
- `src/llm_player.py`
- `src/mock_player.py`

## Verification

### Syntax Check
```bash
python3 -m py_compile scripts/run_round_robin.py  # ✓ Passed
```

### CLI Help Verification
```bash
python3 scripts/run_round_robin.py generate --help
# Shows --log-dir instead of --output ✓
```

### Directory Structure Test
```python
# Generated test tournament
manifest, path = generate_manifest(models, 2, team_pool, log_dir='logs', tournament_name='test-structure')
# Result:
#   logs/test-structure/manifest.json ✓
#   logs/test-structure/match-0001/ ✓
#   logs/test-structure/match-0002/ ✓
```

## Outstanding Items

1. **Full integration test**: Requires running Pokemon Showdown server to verify complete battle flow
2. **Cleanup tasks from plan**: 
   - Delete `logs/tournament/` (old logs)
   - Delete stale `tournament.json` in repo root
   
   *(Not performed - these may contain data the user wants to review first)*

## Usage Examples

```bash
# Generate tournament
python3 scripts/run_round_robin.py generate \
  --models Grok-4 DeepSeek-Reasoner Gemini-3-Flash GPT-5-Mini \
  --games-per-pair 3

# Run tournament (mock)
python3 scripts/run_round_robin.py run \
  --manifest logs/round-robin-2026-01-27-0204/manifest.json \
  --mock

# Check status
python3 scripts/run_round_robin.py status \
  --manifest logs/round-robin-2026-01-27-0204/manifest.json
```
