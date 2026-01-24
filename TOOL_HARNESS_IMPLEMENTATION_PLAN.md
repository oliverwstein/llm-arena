# Tool Harness Implementation Plan

This plan describes how to implement `TOOL_HARNESS_DESIGN.md`. Read both documents together.

---

## Overview

Replace the existing `src/llm_player.py` with a tool-calling architecture. The old implementation is in git history.

**Key principle**: Tools derive from `SimpleHeuristicsPlayer` methods where possible (battle-tested code).

---

## Phase 1: Tool Infrastructure

Create `src/tools/` module:

### `src/tools/__init__.py`
```python
from .type_tools import get_type_effectiveness, get_all_type_matchups
from .damage_tools import calculate_damage, calculate_all_damages
from .matchup_tools import evaluate_matchup, evaluate_all_matchups, should_switch
from .team_tools import get_team_summary, get_team_pokemon, get_opponent_team_summary, get_opponent_pokemon
from .battle_log_tools import get_battle_log, get_turn_details
from .executor import execute_tool
from .definitions import TOOL_DEFINITIONS
```

### `src/tools/definitions.py`
LiteLLM-compatible tool schemas. See design doc section "LiteLLM Tool Format" (~lines 2031-2181).

### `src/tools/executor.py`
Dispatcher routing tool calls to implementations:
```python
def execute_tool(name: str, arguments: dict, battle: AbstractBattle, context: dict) -> dict
```
Context includes `battle_plans` for plan tools.

---

## Phase 2: Tool Implementations

### `src/tools/type_tools.py`
- `get_type_effectiveness(attack_type, defender_types)` - use `GenData.from_gen(4).type_chart`
- `get_all_type_matchups(pokemon_types)` - all attacking types vs defender

### `src/tools/damage_tools.py`
Import from `poke_env.player.baselines import SimpleHeuristicsPlayer`:
- Use `SimpleHeuristicsPlayer._stat_estimation()` for stat calculations
- `calculate_all_damages(battle)` - scoring formula from heuristic
- `calculate_damage(battle, move_name)` - single move wrapper

### `src/tools/matchup_tools.py`
- `evaluate_matchup()` - call `SimpleHeuristicsPlayer._estimate_matchup()` directly
- `evaluate_all_matchups()` - loop over team
- `should_switch()` - call `SimpleHeuristicsPlayer._should_switch_out()` directly

### `src/tools/team_tools.py`
Use `battle.team`, `battle.opponent_team`, `battle.active_pokemon`, etc.

### `src/tools/battle_log_tools.py`
Use `battle.observations[turn].events` for historical events.
Use `format_events()` from existing `event_formatter.py`.

### `src/tools/plan_tools.py`
Simple dict storage for battle plans (managed in LLMPlayer).

---

## Phase 3: Replace LLMPlayer

### `src/llm_player.py` (FULL REPLACEMENT)

Replace entire file with implementation from design doc (~lines 1101-1460).

Key components:
- `LLMPlayer.__init__`: Add `max_tool_calls`, `decision_history`, `battle_plans`, `tool_cache`
- `LLMPlayer.choose_move`: Subagent pattern with tool loop
- `_run_reasoning_subagent`: Ephemeral tool-calling context
- `_get_previous_turn_events`: Format using `event_formatter.py`
- `_format_decision_history`: Compact history of past decisions
- `_format_battle_plan` / `_apply_plan_updates`: Goal tracking (include `abandon_goal`)
- `_parse_subagent_response`: Extract ACTION/REASONING/PREDICTION

Use `battle.player_role` for perspective (not string matching).

### `src/response_parser.py` (REPLACE)
Update to parse structured format: ACTION/REASONING/PREDICTION sections.

---

## Phase 4: Human Player for Testing

### `src/human_player.py` (NEW)
Interactive terminal player. See design doc "Human Player (Interactive Testing)" section.

### `scripts/human_vs_heuristic.py` (NEW)
Script to run human vs `SimpleHeuristicsPlayer`.

---

## Phase 5: Integration

### `src/player_factory.py`
Simplify to use the new `LLMPlayer` (remove any stale branching).

### `scripts/benchmark_vs_heuristic.py`
Update imports; no `--tools-enabled` flag needed.

---

## Phase 6: Tests

### `tests/test_tools.py`
Unit tests for each tool with mock battles.

### `tests/test_llm_player.py`
Integration test: tool loop with mocked LLM responses.

---

## File Summary

| Action | File |
|--------|------|
| NEW | `src/tools/__init__.py` |
| NEW | `src/tools/definitions.py` |
| NEW | `src/tools/executor.py` |
| NEW | `src/tools/type_tools.py` |
| NEW | `src/tools/damage_tools.py` |
| NEW | `src/tools/matchup_tools.py` |
| NEW | `src/tools/team_tools.py` |
| NEW | `src/tools/battle_log_tools.py` |
| NEW | `src/tools/plan_tools.py` |
| REPLACE | `src/llm_player.py` |
| REPLACE | `src/response_parser.py` |
| SIMPLIFY | `src/player_factory.py` |
| NEW | `src/human_player.py` |
| NEW | `scripts/human_vs_heuristic.py` |
| NEW | `tests/test_tools.py` |
| NEW | `tests/test_llm_player.py` |

---

## Verification

1. **Unit tests**: `python -m pytest tests/test_tools.py -v`
2. **Human test**: `python scripts/human_vs_heuristic.py` (play a few turns, call each tool)
3. **LLM benchmark**: `python scripts/benchmark_vs_heuristic.py --model gpt-4o-mini --battles 5`

---

## Key Design Details (from TOOL_HARNESS_DESIGN.md)

- **Subagent pattern**: Tool calls are ephemeral per turn (no context bloat)
- **Max 8 tool calls per turn**: Configurable via `LLM_ARENA_MAX_TOOL_CALLS`
- **State from Battle object**: Most tools use `battle.active_pokemon`, `battle.team`, etc. (poke-env tracks state)
- **Observations only for history**: `battle.observations[turn].events` for past events
- **Use `battle.player_role`**: Returns "p1" or "p2" for perspective
