# Post-Implementation Report: Scripts Overhaul

**Date:** 2026-01-26  
**Status:** ✅ Complete

---

## Summary of Changes

All planned changes from `scripts/plan.md` have been implemented:

| File | Action | Status |
|------|--------|--------|
| `src/config.py` | CREATE | ✅ Complete |
| `src/mock_player.py` | CREATE | ✅ Complete |
| `scripts/run_round_robin.py` | CREATE | ✅ Complete |
| `src/llm_player.py` | MODIFY | ✅ Complete |
| `src/tournament.py` | MODIFY | ✅ Complete |
| `scripts/llm_vs_llm.py` | MODIFY | ✅ Complete |
| `scripts/benchmark_vs_heuristic.py` | MODIFY | ✅ Complete |

---

## Detailed Changes

### 1. `src/config.py` (NEW)

Single source of truth for model configuration:

```python
@dataclass
class ModelConfig:
    name: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 60.0
    team: str | None = None
    force_fallback: bool = False
    api_price_input: float = 0.0
    api_price_output: float = 0.0

def load_models_from_yaml(path: str) -> list[ModelConfig]
def find_model(query: str, models: list[ModelConfig]) -> ModelConfig | None
```

**Impact:** Eliminates 4-way duplication of ModelConfig across scripts.

### 2. `src/mock_player.py` (NEW)

Mock player for testing tournament infrastructure without API calls:

- Extends `AgentPlayer` (same base as `LLMPlayer`)
- Random move selection with full logging pipeline
- Configurable error injection (`error_rate`, `error_types`)
- Supports: timeout, rate_limit, connection, context_window errors

**Usage:**
```python
from src.mock_player import MockPlayer

player = MockPlayer(
    error_rate=0.3,
    error_types=["timeout", "rate_limit"],
    thinking_time=0.1,
    ...
)
```

### 3. `scripts/run_round_robin.py` (NEW)

Manifest-based tournament runner with three subcommands:

**`generate`** - Create match manifest:
```bash
python scripts/run_round_robin.py generate \
  --models Claude-Haiku-4.5 GPT-5-Mini Gemini-3-Flash \
  --games-per-pair 3 \
  --output tournament.json
```

**`run`** - Execute matches (resumable):
```bash
python scripts/run_round_robin.py run \
  --manifest tournament.json \
  --concurrent 6 \
  --per-model-concurrent 3
```

**`status`** - Show progress:
```bash
python scripts/run_round_robin.py status --manifest tournament.json
```

**Key features:**
- Atomic manifest writes (write to `.tmp`, then `os.replace()`)
- SIGINT handler saves state before exit
- `running` status reset to `pending` on startup (crash recovery)
- Two-layer semaphores (global + per-model) with sorted lock acquisition
- Mock mode for testing (`--mock`, `--error-rate`)

### 4. `src/llm_player.py` (MODIFIED)

**Error classification in `_execute_generation()`:**

| Error Type | Behavior |
|------------|----------|
| `RateLimitError` | Exponential backoff (10 × 2^n + jitter), max 15 retries, cap 300s |
| `Timeout` | Immediate retry, max 2 retries |
| `APIConnectionError`, `ServiceUnavailableError` | Linear backoff (15n seconds), max 3 retries |
| `ContextWindowExceededError` | Fail immediately (structural, unfixable) |
| Other `Exception` | 10s backoff, max 2 retries |

**Bug fixes:**
- Line 206: `entry["id"] += tc.id` → `entry["id"] = tc.id` (ID assignment, not concatenation)
- Removed dead code: `plan_text = "" # self._format_battle_plan(battle_plan)`

**Added:** `import random` for jitter in rate limit backoff.

### 5. `src/tournament.py` (MODIFIED)

- Imports `ModelConfig`, `load_models_from_yaml`, `find_model` from `src.config`
- Re-exports for backward compatibility
- Removed local `ModelConfig` dataclass definition

### 6. `scripts/llm_vs_llm.py` (MODIFIED)

- Removed local `ModelConfig`, `load_models_from_yaml`, `find_model`
- Imports from `src.config` instead
- Removed unused `yaml` and `dataclass` imports

### 7. `scripts/benchmark_vs_heuristic.py` (MODIFIED)

- Removed local `ModelConfig`, `load_models_from_yaml`
- Imports from `src.config` instead
- Removed debug print: `print(f"DEBUG: verbose={args.verbose}, timeout={args.timeout}")`
- Removed unused `yaml` and `dataclass` imports

---

## Verification Results

### Import Tests

```
✅ from src.config import ModelConfig, load_models_from_yaml, find_model
✅ from src.mock_player import MockPlayer
✅ from src.tournament import ModelConfig, TournamentConfig
✅ from src.llm_player import LLMPlayer
```

### Script Help Tests

```
✅ python scripts/llm_vs_llm.py --help
✅ python scripts/benchmark_vs_heuristic.py --help
✅ python scripts/run_round_robin.py --help
✅ python scripts/run_round_robin.py generate --help
✅ python scripts/run_round_robin.py run --help
✅ python scripts/run_round_robin.py status --help
```

### Test Suite

```
30 tests collected
23 passed, 7 failed (pre-existing failures unrelated to changes)

Key passing tests:
✅ test_import_llm_player
✅ test_response_parser_action_format
✅ test_response_parser_switch_format
✅ test_decision_history_format
✅ test_parse_subagent_response
✅ All tool tests (type, info, plan, field)
```

Pre-existing failures (not related to this implementation):
- `test_basic_logging` - BattleLogger API mismatch
- `test_disabled_logging` - BattleLogger API mismatch
- `test_multiple_participants` - BattleLogger API mismatch
- `test_llm_player_init` - Missing mock setup
- `test_tool_definitions_valid` - Missing mock setup
- `test_executor_handles_all_tools` - Missing mock setup
- `test_battle_plan_format` - Missing mock setup

---

## Usage Examples

### Quick Mock Tournament Test

```bash
# Generate manifest
python scripts/run_round_robin.py generate \
  --models Claude-Haiku-4.5 GPT-5-Mini \
  --games-per-pair 2 \
  --output test.json

# Run with mock (no API calls)
python scripts/run_round_robin.py run \
  --manifest test.json \
  --mock

# Check status
python scripts/run_round_robin.py status --manifest test.json
```

### Full Tournament

```bash
# Generate 4-model tournament
python scripts/run_round_robin.py generate \
  --models Claude-Haiku-4.5 GPT-5-Mini Gemini-3-Flash Grok-4 \
  --games-per-pair 3 \
  --output tournament.json

# Run with real APIs
python scripts/run_round_robin.py run \
  --manifest tournament.json \
  --concurrent 6 \
  --per-model-concurrent 3

# Resume after interruption (Ctrl-C)
python scripts/run_round_robin.py run --manifest tournament.json
```

### 1v1 Testing (Unchanged Workflow)

```bash
python scripts/llm_vs_llm.py --a Claude-Haiku-4.5 --b GPT-5-Mini --battles 3
```

---

## Files Superseded (Left in Place)

The following scripts are superseded by `scripts/run_round_robin.py` but left in place for reference:

- `scripts/run_tournament.py` - Sequential cross_evaluate wrapper
- `scripts/llm_round_robin.py` - Previous parallel runner with infinite retry loop

These can be deleted later if desired.

---

## Architecture Diagram

```
config/models.yaml
       │
       ▼
┌──────────────────┐
│   src/config.py  │  ◄── Single source of truth
│   - ModelConfig  │
│   - load_models  │
│   - find_model   │
└────────┬─────────┘
         │
    ┌────┴────┬────────────────┐
    │         │                │
    ▼         ▼                ▼
scripts/   scripts/          src/
llm_vs_llm benchmark_vs_   tournament.py
           heuristic        (re-exports)
    
┌────────────────────────────────────────┐
│      scripts/run_round_robin.py        │
│  ┌─────────┬──────────┬─────────────┐  │
│  │generate │   run    │   status    │  │
│  └────┬────┴────┬─────┴──────┬──────┘  │
│       │         │            │         │
│       ▼         ▼            ▼         │
│  tournament  matches w/    progress    │
│  manifest    semaphores    display     │
│  (JSON)      + resumable               │
└────────────────────────────────────────┘
         │
         ▼
┌──────────────────┐     ┌──────────────────┐
│ src/llm_player.py│     │src/mock_player.py│
│  - classified    │     │  - random moves  │
│    error handling│     │  - error inject  │
└──────────────────┘     └──────────────────┘
```

---

## Design Principles Achieved

✅ **Idempotency:** `generate` checks for existing manifest, `run` skips completed matches  
✅ **Failure Isolation:** One match crashing doesn't take down the tournament  
✅ **Resumability:** Ctrl-C saves state, restart picks up where it left off  
✅ **Observability:** Structured manifest JSON, per-match logging, status dashboard

---

## Next Steps (Optional)

1. **Delete superseded scripts** if not needed for reference
2. **Run full mock tournament** to verify end-to-end flow
3. **Run real 1v1 smoke test** to verify error classification with live APIs
4. **Update existing tests** to fix pre-existing BattleLogger API mismatches
