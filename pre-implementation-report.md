# Pre-Implementation Report: Scripts Overhaul

**Date:** 2026-01-26  
**Scope:** Tournament script consolidation and error handling improvements

---

## Executive Summary

The LLM Arena battle engine is functionally sound, but the tournament infrastructure is brittle. The plan calls for:
1. **Shared config extraction** - Eliminate 4-way ModelConfig duplication
2. **Classified error handling** - Replace catch-all retry with error-specific behavior
3. **Manifest-based tournament runner** - Replace fragile scripts with resumable, idempotent execution
4. **Mock player for testing** - Enable tournament runner verification without API costs

---

## Current State Analysis

### Files Reviewed

| File | Lines | Status |
|------|-------|--------|
| `src/llm_player.py` | 588 | Needs modification |
| `src/tournament.py` | 225 | Needs modification |
| `src/agent_player.py` | 277 | Good - no changes |
| `src/team_pool.py` | 72 | Good - no changes |
| `scripts/llm_vs_llm.py` | 332 | Needs modification |
| `scripts/benchmark_vs_heuristic.py` | 304 | Needs modification |
| `scripts/llm_round_robin.py` | 334 | To be superseded |
| `scripts/run_tournament.py` | (exists) | To be superseded |

### Identified Issues

#### 1. Error Handling in `src/llm_player.py` (Critical)

Lines 258-262 catch all exceptions identically:
```python
except Exception as e:
    print(f"[{self.username}] API Error: {e}. Retrying in 60s...")
    await asyncio.sleep(60)
    continue
```

**Problems:**
- Rate limit errors get same treatment as structural errors
- Context window exceeded (unfixable) retries forever
- Timeout errors don't have limited retries
- No exponential backoff for rate limits

#### 2. Tool Call ID Bug (Line 206)

```python
if tc.id: entry["id"] += tc.id
```

Should be `=` not `+=`. The ID arrives in one chunk, not streamed. Works in practice but semantically wrong.

#### 3. Dead Code (Line 282)

```python
plan_text = "" # self._format_battle_plan(battle_plan)
```

Commented-out call with dead assignment.

#### 4. ModelConfig Duplication

`ModelConfig` and `load_models_from_yaml()` are defined in:
- `src/tournament.py` (lines 32-40)
- `scripts/llm_vs_llm.py` (lines 28-36)
- `scripts/benchmark_vs_heuristic.py` (lines 33-40)
- `scripts/llm_round_robin.py` (lines 32-54)

Each has slightly different fields (e.g., `api_price_*` only in llm_round_robin.py).

#### 5. Tournament Script Problems

**`scripts/llm_round_robin.py`:**
- Lines 295-327: Infinite retry loop on any exception
- No resumability - restart loses all progress
- Hardcoded model list (lines 204-207)
- Token tracking fields exist but never populated

**`scripts/run_tournament.py`:**
- Uses poke-env's `cross_evaluate()` - sequential, no parallelism
- No error recovery

#### 6. Debug Print (Line 272 of benchmark_vs_heuristic.py)

```python
print(f"DEBUG: verbose={args.verbose}, timeout={args.timeout}")
```

Should be removed.

---

## Implementation Plan

### Phase 1: Shared Configuration

**Create `src/config.py`:**
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

def load_models_from_yaml(path: str) -> list[ModelConfig]: ...
def find_model(query: str, models: list[ModelConfig]) -> ModelConfig | None: ...
```

### Phase 2: Error Classification

**Modify `src/llm_player.py` `_execute_generation()`:**

| Error Type | Behavior |
|------------|----------|
| `RateLimitError` | Exponential backoff, max 15 retries |
| `Timeout` | Linear retry, max 2 retries |
| `APIConnectionError` | Linear backoff, max 3 retries |
| `ContextWindowExceededError` | Fail immediately (structural) |
| Other `Exception` | Limited retry (2x), then propagate |

### Phase 3: Mock Player

**Create `src/mock_player.py`:**
- Extends `AgentPlayer`
- Random move selection
- Configurable error injection for testing
- Full logging pipeline (decisions, tool calls mock)

### Phase 4: Manifest-Based Runner

**Create `scripts/run_round_robin.py`:**

Three subcommands:
1. `generate` - Create match manifest JSON
2. `run` - Execute matches with resumability
3. `status` - Show tournament progress

**Manifest format:**
```json
{
  "tournament": {
    "name": "round-robin-2026-01-26",
    "format": "gen4ou",
    "models": ["Model-A", "Model-B"],
    "games_per_pair": 3
  },
  "matches": [
    {
      "id": 1,
      "model_a": "Model-A",
      "model_b": "Model-B", 
      "team_a": "Team-Name",
      "team_b": "Team-Name",
      "status": "pending",
      "winner": null,
      "error": null,
      "attempts": 0
    }
  ]
}
```

**Key features:**
- Atomic manifest writes (write to .tmp, then `os.replace()`)
- SIGINT handler saves state
- `running` status reset to `pending` on startup (crash recovery)
- Two-layer semaphores (global + per-model) with sorted lock acquisition

### Phase 5: Script Updates

**`scripts/llm_vs_llm.py`:**
- Import from `src.config` instead of local definitions

**`scripts/benchmark_vs_heuristic.py`:**
- Import from `src.config`
- Remove debug print on line 272

**`src/tournament.py`:**
- Re-export from `src.config` for backward compatibility

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/config.py` | CREATE | Shared ModelConfig, YAML loading |
| `src/mock_player.py` | CREATE | Mock player for testing |
| `src/llm_player.py` | MODIFY | Classified error handling, bug fixes |
| `src/tournament.py` | MODIFY | Import from src.config |
| `scripts/run_round_robin.py` | CREATE | Manifest-based tournament runner |
| `scripts/llm_vs_llm.py` | MODIFY | Import from src.config |
| `scripts/benchmark_vs_heuristic.py` | MODIFY | Import from src.config, remove debug |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking existing battle flow | Only modify error handling path, not happy path |
| Import cycles | `src/config.py` has no internal dependencies |
| Manifest corruption | Atomic writes via `os.replace()` |
| Deadlocks in concurrent execution | Sorted lock acquisition (already proven in llm_round_robin.py) |

---

## Verification Checklist

- [ ] `python -c "from src.config import ModelConfig, load_models_from_yaml"` succeeds
- [ ] `python -c "from src.mock_player import MockPlayer"` succeeds
- [ ] `python scripts/llm_vs_llm.py --help` works
- [ ] `python scripts/benchmark_vs_heuristic.py --help` works
- [ ] `python scripts/run_round_robin.py generate --help` works
- [ ] `python scripts/run_round_robin.py status --help` works
- [ ] Existing tests pass (if any)
