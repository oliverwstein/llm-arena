# Pre-Refactor Analysis Report

## Executive Summary

This report analyzes the current LLM Arena codebase and the planned tool harness overhaul before implementation begins.

---

## Current Architecture

### Overview

The LLM Arena is a Pokemon battle arena that pits LLM-powered players against each other (or heuristic baselines) using the poke-env library and a local Pokemon Showdown server.

### File Structure

```
src/
├── llm_player.py        # Core LLM player (push-based architecture)
├── player_factory.py    # Creates players with API key fallback
├── state_formatter.py   # Formats battle state for LLM consumption
├── event_formatter.py   # Formats Showdown protocol to human-readable text
├── response_parser.py   # Parses LLM responses into actions
├── team_pool.py         # Manages Pokemon teams
├── tournament.py        # Tournament orchestration
├── results.py           # Result tracking
└── env_manager.py       # Environment variable management
```

### Current LLMPlayer Implementation

**Design Pattern: Push-Based**
- All battle state is dumped into a single message each turn
- LLM receives everything at once and must parse/reason about it
- No ability to query for specific information
- Conversation history accumulates (potential context explosion)

**Key Methods:**
- `choose_move()`: Main decision loop - formats state, calls LLM, parses response
- `battle_finished_callback()`: Cleanup after battle

**Limitations:**
1. **Context bloat**: Conversation history grows unbounded
2. **No tool support**: `LLMPlayerWithTools` class exists but is a stub (TODO)
3. **No strategic planning**: Each turn is independent, no persistent goals
4. **Information overload**: LLM must process everything even when only type chart matters

### Supporting Modules

| Module | Purpose | Status |
|--------|---------|--------|
| `state_formatter.py` | Formats current battle state | Solid, will be reused |
| `event_formatter.py` | Human-readable event narrative | Solid, will be reused |
| `response_parser.py` | Parses "move X" / "switch Y" | Needs update for new format |
| `player_factory.py` | Creates players with fallback | Needs simplification |

---

## Planned Design: Tool Harness

### Philosophy Change

**From Push to Pull:**
- Instead of dumping everything, LLM receives concise summary
- LLM can query for specific information via tools
- Inspired by Ramp's RollerCoaster Tycoon + Claude Code project

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Information-only tools** | LLM reasons; tools provide data |
| **Max 8 tool calls/turn** | Cost control while allowing analysis |
| **Subagent architecture** | Tool context ephemeral; only decisions persist |
| **Strategic planning system** | Goals persist across turns |
| **Battle log via tool** | Objective history accessible on demand |

### Tool Categories

1. **Type Analysis**: `get_type_effectiveness`, `get_all_type_matchups`
2. **Damage Calculation**: `calculate_damage`, `calculate_all_damages`
3. **Speed/Priority**: `get_speed_comparison`
4. **Matchup Assessment**: `evaluate_matchup`, `evaluate_all_matchups`
5. **Move/Pokemon Info**: `get_move_details`, `get_pokemon_info`
6. **Field State**: `get_field_analysis`
7. **Team Info**: `get_team_pokemon`, `get_team_summary`, `get_opponent_pokemon`, `get_opponent_team_summary`
8. **Battle Log**: `get_battle_log`, `get_turn_details`
9. **Strategic Planning**: `get_battle_plan`, `update_battle_plan`

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     MAIN CONTEXT (persistent)                    │
│ - System prompt                                                  │
│ - Previous turn events (always included)                         │
│ - Current state summary                                          │
│ - Decision history (compact)                                     │
│ - Strategic plan                                                 │
└───────────────────────────────────┬─────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              REASONING SUBAGENT (ephemeral per turn)             │
│ - Has access to all tools                                        │
│ - Tool calls NOT persisted                                       │
│ - Returns: decision + reasoning + prediction                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan Analysis

### Phase 1: Tool Infrastructure
- Create `src/tools/` module
- Define tool schemas in LiteLLM format
- Build executor dispatcher

### Phase 2: Tool Implementations
- Derive from `SimpleHeuristicsPlayer` where possible (battle-tested)
- Type tools use `GenData.from_gen(4).type_chart`
- Damage tools use heuristic scoring formula
- Matchup tools call `_estimate_matchup()` directly

### Phase 3: Replace LLMPlayer
- Full implementation with subagent pattern
- Tool-calling loop with max 8 calls
- Decision history with reasoning
- Strategic planning system

### Phase 4: Human Player
- Interactive terminal player for testing
- Same tools as LLM, manual control

### Phase 5: Integration
- Update `player_factory.py`
- Update benchmark script

### Phase 6: Tests
- Unit tests for tools
- Integration tests for full player

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Context still grows via decision history | History limited to last 8 turns |
| Tool calls add latency | Max 8 calls bounds worst case |
| LiteLLM tool format differences | Using OpenAI-compatible format (works across providers) |
| State tools become stale | Most tools read current `Battle` state (auto-updated by poke-env) |

---

## Files to Change

| Action | File | Notes |
|--------|------|-------|
| NEW | `src/tools/__init__.py` | Module exports |
| NEW | `src/tools/definitions.py` | LiteLLM tool schemas |
| NEW | `src/tools/executor.py` | Tool dispatcher |
| NEW | `src/tools/type_tools.py` | Type effectiveness |
| NEW | `src/tools/damage_tools.py` | Damage calculations |
| NEW | `src/tools/matchup_tools.py` | Matchup evaluation |
| NEW | `src/tools/team_tools.py` | Team information |
| NEW | `src/tools/battle_log_tools.py` | Battle history |
| NEW | `src/tools/plan_tools.py` | Strategic planning |
| REPLACE | `src/llm_player.py` | Full tool-calling implementation |
| REPLACE | `src/response_parser.py` | Handle ACTION/REASONING format |
| SIMPLIFY | `src/player_factory.py` | Remove stale branching |
| NEW | `src/human_player.py` | Interactive testing |
| NEW | `scripts/human_vs_heuristic.py` | Human vs bot script |
| NEW | `tests/test_tools.py` | Tool unit tests |
| NEW | `tests/test_llm_player.py` | Integration tests |

---

## Conclusion

The current implementation is functional but limited by its push-based architecture. The planned tool harness will:

1. **Reduce context size** via subagent pattern
2. **Enable strategic planning** with persistent goals
3. **Give LLMs control** over what information to query
4. **Leverage existing code** (event_formatter, state_formatter, heuristic methods)

The implementation plan is well-structured and the design document is thorough. Ready to proceed with implementation.
