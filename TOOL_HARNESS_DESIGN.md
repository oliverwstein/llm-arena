# Tool-Calling Harness Design for LLM Pokemon Players

> Inspired by [Ramp's RollerCoaster Tycoon + Claude Code project](https://ramp.com/blog/claude-code-rollercoaster-tycoon), this design creates a "battlectl"-style interface that gives LLMs structured access to battle information and analysis tools.

## Design Philosophy

From the RCT article:
> *"The limiting factor for general-purpose agents is the legibility of their environments, and the strength of their interfaces."*

**Current approach (push-based):** Everything is dumped into a single message. The LLM must parse and reason about all information at once.

**New approach (pull-based):** The LLM receives a concise state summary and can query for specific information as needed. This mirrors how Claude Code uses `rctctl` to pull up financials, guest feedback, or map areas on demand.

## Goals

1. **Cross-provider compatibility** - Works with OpenAI, Anthropic, Google, DeepSeek, xAI via LiteLLM's unified tool calling
2. **Leverage existing infrastructure** - Use poke-env's damage calculator, type charts, and GenData
3. **Information retrieval, not decision-making** - Tools provide data; LLM does the reasoning
4. **Bounded tool use** - Max 8 tool calls per turn to control costs while allowing thorough analysis

## Design Decisions

Based on requirements discussion:

| Decision | Rationale |
|----------|-----------|
| **No "best move" tools** | LLM should reason about strategy, not outsource decisions |
| **No opponent prediction tools** | Leave game-theoretic reasoning to the LLM |
| **Information-focused tools** | Type charts, damage calc, Pokemon/move data, field state |
| **Objective battle log tool** | LLM can query exact battle history from Showdown (not its own memory) |
| **Previous turn always included** | Last turn's events are in every prompt (no tool call needed) |
| **Subagent architecture** | Tool reasoning is ephemeral; only decisions persist |
| **Budget: 8 calls/turn** | Enough for thorough analysis, not so many it becomes expensive |

---

## Tool Definitions

### Category A: Type Analysis

#### `get_type_effectiveness`
Query how effective a move type is against a defender.

```python
{
    "name": "get_type_effectiveness",
    "description": "Get the damage multiplier for an attacking type against a Pokemon's types. Returns 0 (immune), 0.25, 0.5, 1, 2, or 4.",
    "parameters": {
        "type": "object",
        "properties": {
            "attack_type": {
                "type": "string",
                "description": "The attacking move's type (e.g., 'fire', 'water', 'electric')"
            },
            "defender_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The defending Pokemon's type(s) (e.g., ['grass', 'poison'])"
            }
        },
        "required": ["attack_type", "defender_types"]
    }
}
```

**Example:**
```
Input: attack_type="fire", defender_types=["grass", "steel"]
Output: {"multiplier": 4.0, "description": "super effective (4x)"}
```

#### `get_all_type_matchups`
Get offensive and defensive matchups for a Pokemon.

```python
{
    "name": "get_all_type_matchups",
    "description": "Get complete type matchup analysis for a Pokemon - what it's weak to, resists, and immune to.",
    "parameters": {
        "type": "object",
        "properties": {
            "pokemon_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The Pokemon's type(s)"
            }
        },
        "required": ["pokemon_types"]
    }
}
```

**Example:**
```
Input: pokemon_types=["steel", "psychic"]
Output: {
    "weaknesses": {"fire": 2, "ground": 2, "ghost": 2, "dark": 2},
    "resistances": {"normal": 0.5, "flying": 0.5, "rock": 0.5, ...},
    "immunities": ["poison"]
}
```

---

### Category B: Damage Calculation

#### `calculate_damage`
Estimate damage for a specific move against a target.

```python
{
    "name": "calculate_damage",
    "description": "Calculate estimated damage for a move. Returns min/max damage and whether it can KO.",
    "parameters": {
        "type": "object",
        "properties": {
            "move_name": {
                "type": "string",
                "description": "Name of the move to use"
            },
            "target": {
                "type": "string",
                "enum": ["opponent", "self"],
                "description": "Who to calculate damage against (default: opponent)"
            }
        },
        "required": ["move_name"]
    }
}
```

**Example:**
```
Input: move_name="earthquake"
Output: {
    "move": "earthquake",
    "type": "ground",
    "base_power": 100,
    "min_damage": 85,
    "max_damage": 102,
    "min_percent": 42.5,
    "max_percent": 51.0,
    "effectiveness": 2.0,
    "is_stab": true,
    "can_ohko": false,
    "can_2hko": true
}
```

#### `calculate_all_damages`
Calculate damage for all available moves at once.

```python
{
    "name": "calculate_all_damages",
    "description": "Calculate damage for all your available moves against the current opponent. More efficient than calling calculate_damage multiple times.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
```

**Example:**
```
Output: {
    "your_pokemon": "tyranitar",
    "opponent_pokemon": "gengar",
    "moves": [
        {
            "move": "crunch",
            "type": "dark",
            "base_power": 80,
            "min_percent": 85.2,
            "max_percent": 100.6,
            "effectiveness": 2.0,
            "is_stab": true,
            "can_ohko": true,
            "priority": 0
        },
        {
            "move": "earthquake",
            "type": "ground",
            "base_power": 100,
            "min_percent": 0,
            "max_percent": 0,
            "effectiveness": 0,
            "is_stab": false,
            "can_ohko": false,
            "priority": 0,
            "note": "Gengar has Levitate - immune to Ground"
        },
        {
            "move": "stone_edge",
            "type": "rock",
            "base_power": 100,
            "min_percent": 62.1,
            "max_percent": 73.4,
            "effectiveness": 1.0,
            "is_stab": false,
            "can_ohko": false,
            "priority": 0
        },
        {
            "move": "stealth_rock",
            "type": "rock",
            "is_status": true,
            "effect": "Sets entry hazard"
        }
    ]
}
```

---

### Category C: Speed and Priority

#### `get_speed_comparison`
Determine who moves first.

```python
{
    "name": "get_speed_comparison",
    "description": "Compare speed stats to determine who moves first. Accounts for paralysis, boosts, and priority moves.",
    "parameters": {
        "type": "object",
        "properties": {
            "move_name": {
                "type": "string",
                "description": "Optional: check priority for a specific move"
            }
        },
        "required": []
    }
}
```

**Example:**
```
Input: move_name="quick_attack"
Output: {
    "your_speed": 298,
    "opponent_speed": 312,
    "you_are_faster": false,
    "move_priority": 1,
    "with_move_you_go_first": true,
    "notes": ["Quick Attack has +1 priority, so you move first despite lower speed"]
}
```

---

### Category D: Matchup Assessment

#### `evaluate_matchup`
Get an overall assessment of the current matchup (mirrors `_estimate_matchup` from heuristic player).

```python
{
    "name": "evaluate_matchup",
    "description": "Evaluate how favorable the current matchup is. Positive score = favorable, negative = unfavorable. Uses the same formula as the heuristic baseline player.",
    "parameters": {
        "type": "object",
        "properties": {
            "pokemon_name": {
                "type": "string",
                "description": "Optional: evaluate a different Pokemon from your team instead of the active one"
            }
        },
        "required": []
    }
}
```

**Example:**
```
Input: (no params - evaluate active)
Output: {
    "your_pokemon": "tyranitar",
    "opponent_pokemon": "gengar",
    "matchup_score": 1.8,
    "factors": {
        "offensive_typing": 0.5,  # Your types are effective against opponent
        "defensive_typing": -0.3, # Opponent has some effective moves
        "speed_advantage": -0.1,  # Opponent is faster
        "hp_advantage": 0.4,      # You have more HP remaining
        "boost_advantage": 1.1    # You have stat boosts
    }
}
```

#### `evaluate_all_matchups`
Get matchup scores for all your Pokemon against the current opponent.

```python
{
    "name": "evaluate_all_matchups",
    "description": "Evaluate matchup scores for your active Pokemon and all available switches against the current opponent.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
```

**Example:**
```
Output: {
    "opponent": "alakazam",
    "matchups": [
        {"pokemon": "tyranitar", "matchup_score": 2.1, "is_active": false, "hp_percent": 85},
        {"pokemon": "scizor", "matchup_score": 1.2, "is_active": true, "hp_percent": 100},
        {"pokemon": "blissey", "matchup_score": 0.8, "is_active": false, "hp_percent": 72},
        {"pokemon": "starmie", "matchup_score": -0.5, "is_active": false, "hp_percent": 100}
    ]
}
```

---

### Category E: Move Information

#### `get_move_details`
Look up detailed information about a move.

```python
{
    "name": "get_move_details",
    "description": "Get detailed information about a move including effects, priority, accuracy, and secondary effects.",
    "parameters": {
        "type": "object",
        "properties": {
            "move_name": {
                "type": "string",
                "description": "Name of the move to look up"
            }
        },
        "required": ["move_name"]
    }
}
```

**Example:**
```
Input: move_name="close_combat"
Output: {
    "name": "close_combat",
    "type": "fighting",
    "category": "physical",
    "base_power": 120,
    "accuracy": 100,
    "pp": 5,
    "priority": 0,
    "makes_contact": true,
    "secondary_effect": "Lowers user's Defense and Sp. Def by 1 stage",
    "description": "High power but defensive drawback. Best used when you can KO or when defense doesn't matter."
}
```

---

### Category F: Pokemon Information

#### `get_pokemon_info`
Look up information about a Pokemon species.

```python
{
    "name": "get_pokemon_info",
    "description": "Get base stats, types, common abilities, and typical role for a Pokemon species.",
    "parameters": {
        "type": "object",
        "properties": {
            "pokemon_name": {
                "type": "string",
                "description": "Name of the Pokemon to look up"
            }
        },
        "required": ["pokemon_name"]
    }
}
```

**Example:**
```
Input: pokemon_name="gengar"
Output: {
    "name": "gengar",
    "types": ["ghost", "poison"],
    "base_stats": {"hp": 60, "atk": 65, "def": 60, "spa": 130, "spd": 75, "spe": 110},
    "abilities": ["levitate"],
    "common_moves": ["shadow_ball", "sludge_bomb", "focus_blast", "thunderbolt", "hypnosis", "substitute"],
    "role": "Special sweeper / wallbreaker",
    "notes": "Levitate grants Ground immunity. Very fast and powerful but fragile."
}
```

---

### Category G: Field State

#### `get_field_analysis`
Analyze current field conditions and their effects.

```python
{
    "name": "get_field_analysis",
    "description": "Get analysis of current field conditions (weather, hazards, screens) and their tactical implications.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
```

**Example:**
```
Output: {
    "weather": {
        "type": "sandstorm",
        "turns_remaining": 3,
        "effects": [
            "Rock types get +50% Sp. Def",
            "Non-Rock/Ground/Steel take 6.25% damage per turn",
            "Your Tyranitar benefits, opponent's Alakazam takes chip damage"
        ]
    },
    "your_hazards": {
        "stealth_rock": true,
        "spikes": 2,
        "toxic_spikes": 0
    },
    "opponent_hazards": {
        "stealth_rock": false,
        "spikes": 0,
        "toxic_spikes": 0
    },
    "screens": {
        "your_reflect": 0,
        "your_light_screen": 3,
        "opponent_reflect": 0,
        "opponent_light_screen": 0
    },
    "tactical_notes": [
        "Opponent takes 25% on switch from Stealth Rock + Spikes",
        "Your Light Screen reduces incoming special damage"
    ]
}
```

---

---

### Category H: Team Information

#### `get_team_pokemon`
Get detailed information about a specific Pokemon on your team.

```python
{
    "name": "get_team_pokemon",
    "description": "Get detailed information about one of your team members - their moves, item, ability, HP, status, and stat boosts.",
    "parameters": {
        "type": "object",
        "properties": {
            "pokemon_name": {
                "type": "string",
                "description": "Name of the Pokemon to look up (e.g., 'skarmory')"
            }
        },
        "required": ["pokemon_name"]
    }
}
```

**Example:**
```
Input: pokemon_name="skarmory"
Output: {
    "species": "skarmory",
    "hp_percent": 85.0,
    "hp_fraction": "272/320",
    "status": null,
    "is_active": false,
    "ability": "sturdy",
    "item": "leftovers",
    "moves": [
        {"name": "spikes", "type": "ground", "category": "status", "pp": "18/20"},
        {"name": "whirlwind", "type": "normal", "category": "status", "pp": "24/24"},
        {"name": "brave_bird", "type": "flying", "base_power": 120, "pp": "10/15"},
        {"name": "roost", "type": "flying", "category": "status", "pp": "16/16"}
    ],
    "boosts": {"def": 0, "spd": 0, ...},
    "types": ["steel", "flying"]
}
```

#### `get_team_summary`
Get a summary of your entire team's current status.

```python
{
    "name": "get_team_summary",
    "description": "Get a summary of all your team members - HP, status, and whether they've been revealed to opponent.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
```

**Example:**
```
Output: {
    "active": {
        "species": "tyranitar",
        "hp_percent": 75.0,
        "status": null,
        "boosts": {"atk": 1}
    },
    "bench": [
        {"species": "skarmory", "hp_percent": 85.0, "status": null, "fainted": false},
        {"species": "blissey", "hp_percent": 100.0, "status": null, "fainted": false},
        {"species": "starmie", "hp_percent": 0.0, "status": null, "fainted": true},
        {"species": "gengar", "hp_percent": 100.0, "status": null, "fainted": false},
        {"species": "flygon", "hp_percent": 45.0, "status": "par", "fainted": false}
    ],
    "alive_count": 5,
    "fainted_count": 1
}
```

#### `get_opponent_pokemon`
Get what you know about a specific opponent's Pokemon (only revealed information).

```python
{
    "name": "get_opponent_pokemon",
    "description": "Get known information about an opponent's Pokemon. Only shows what has been revealed in battle.",
    "parameters": {
        "type": "object",
        "properties": {
            "pokemon_name": {
                "type": "string",
                "description": "Name of the opponent's Pokemon"
            }
        },
        "required": ["pokemon_name"]
    }
}
```

**Example:**
```
Input: pokemon_name="gengar"
Output: {
    "species": "gengar",
    "hp_percent": 55.0,
    "status": null,
    "is_active": true,
    "known_ability": "levitate",
    "known_item": null,  # Not yet revealed
    "known_moves": [
        {"name": "shadow_ball", "type": "ghost"},
        {"name": "focus_blast", "type": "fighting"}
    ],
    "possible_moves_remaining": 2,  # Likely has 2 more moves
    "types": ["ghost", "poison"],
    "base_stats": {"hp": 60, "atk": 65, "def": 60, "spa": 130, "spd": 75, "spe": 110}
}
```

#### `get_opponent_team_summary`
Get a summary of everything known about the opponent's team.

```python
{
    "name": "get_opponent_team_summary",
    "description": "Get a summary of the opponent's team - all revealed Pokemon, their HP/status, known moves, and how many are unrevealed.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
```

**Example:**
```
Output: {
    "revealed_count": 4,
    "unrevealed_count": 2,  # Haven't seen 2 Pokemon yet
    "fainted_count": 1,
    "active": {
        "species": "alakazam",
        "hp_percent": 100.0,
        "status": null,
        "known_moves": ["psychic", "shadow_ball"],
        "known_ability": "synchronize",
        "known_item": null
    },
    "bench": [
        {
            "species": "gengar",
            "hp_percent": 0.0,
            "status": null,
            "fainted": true,
            "known_moves": ["shadow_ball", "focus_blast", "thunderbolt"],
            "known_ability": "levitate",
            "known_item": "life_orb"
        },
        {
            "species": "skarmory",
            "hp_percent": 72.0,
            "status": null,
            "fainted": false,
            "known_moves": ["spikes", "brave_bird"],
            "known_ability": null,
            "known_item": "leftovers"
        },
        {
            "species": "blissey",
            "hp_percent": 85.0,
            "status": "tox",
            "fainted": false,
            "known_moves": ["soft_boiled", "toxic"],
            "known_ability": "natural_cure",
            "known_item": null
        }
    ],
    "unrevealed_pokemon": "2 Pokemon not yet seen",
    "threats_summary": [
        "Alakazam: Fast special attacker, only 2 moves known",
        "Blissey: Special wall, badly poisoned (will faint eventually)",
        "Skarmory: Physical wall with hazards"
    ]
}
```

---

### Category I: Battle Log

#### `get_battle_log`
Retrieve the complete objective battle log - everything that happened from turn 1 to now.

```python
{
    "name": "get_battle_log",
    "description": "Get the complete battle log from turn 1 to now. This is the objective record of what happened - damage dealt, moves used, switches, status effects, etc. Use this to review battle history or analyze patterns.",
    "parameters": {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["narrative", "detailed", "raw"],
                "description": "Output format: 'narrative' (human-readable story), 'detailed' (structured with exact HP), 'raw' (Showdown protocol)"
            },
            "from_turn": {
                "type": "integer",
                "description": "Optional: start from this turn (default: 1)"
            }
        },
        "required": []
    }
}
```

**Example (narrative format):**
```
Input: format="narrative"
Output: {
    "turns": [
        {
            "turn": 1,
            "events": "Go! Tyranitar!\nThe opposing trainer sent out Gengar!\nSandstorm kicked up!"
        },
        {
            "turn": 2,
            "events": "Tyranitar used Crunch!\nIt's super effective!\nThe opposing Gengar took 45% damage.\nThe opposing Gengar used Shadow Ball!\nTyranitar took 28% damage.\nThe sandstorm rages."
        }
    ]
}
```

**Example (detailed format):**
```
Input: format="detailed"
Output: {
    "turns": [
        {
            "turn": 2,
            "your_pokemon": {"species": "tyranitar", "hp": "287/320", "status": null},
            "opponent_pokemon": {"species": "gengar", "hp": "55/100", "status": null},
            "actions": [
                {"type": "move", "user": "tyranitar", "move": "crunch", "target": "gengar"},
                {"type": "damage", "target": "gengar", "hp_before": "100/100", "hp_after": "55/100"},
                {"type": "supereffective"},
                {"type": "move", "user": "gengar", "move": "shadowball", "target": "tyranitar"},
                {"type": "damage", "target": "tyranitar", "hp_before": "320/320", "hp_after": "287/320"}
            ],
            "end_of_turn": ["sandstorm_damage: gengar -6%"]
        }
    ]
}
```

**Example (raw format):**
```
Input: format="raw"
Output: {
    "protocol": [
        "|move|p1a: Tyranitar|Crunch|p2a: Gengar",
        "|-supereffective|p2a: Gengar",
        "|-damage|p2a: Gengar|55/100",
        "|move|p2a: Gengar|Shadow Ball|p1a: Tyranitar",
        "|-damage|p1a: Tyranitar|287/320",
        "|-weather|Sandstorm|[upkeep]",
        "|-damage|p2a: Gengar|49/100|[from] Sandstorm"
    ]
}
```

#### `get_turn_details`
Get detailed information about a specific turn.

```python
{
    "name": "get_turn_details",
    "description": "Get detailed information about what happened on a specific turn, including exact damage numbers and all effects.",
    "parameters": {
        "type": "object",
        "properties": {
            "turn": {
                "type": "integer",
                "description": "The turn number to examine"
            }
        },
        "required": ["turn"]
    }
}
```

---

## Context Management Architecture

### The Problem

Tool-calling creates context bloat:
- 8 tool calls × 30 turns = 240 tool interactions
- Each adds ~100-200 tokens
- Context could hit 50k+ tokens

### Solution: Subagent Pattern + Objective Battle Log

```
┌─────────────────────────────────────────────────────────────────┐
│                     MAIN CONTEXT (persistent)                    │
├─────────────────────────────────────────────────────────────────┤
│ System prompt                                                    │
│                                                                  │
│ PREVIOUS TURN EVENTS (always included, from Showdown):          │
│   "Tyranitar used Crunch! It's super effective!                 │
│    The opposing Gengar took 45% damage.                         │
│    The opposing Gengar used Shadow Ball!                        │
│    Tyranitar took 28% damage."                                  │
│                                                                  │
│ CURRENT STATE (formatted)                                        │
│                                                                  │
│ Decision history (compact):                                      │
│   T1: lead tyranitar | T2: crunch | T3: crunch (KO) | ...       │
│                                                                  │
└───────────────────────────────────┬─────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              REASONING SUBAGENT (ephemeral per turn)             │
├─────────────────────────────────────────────────────────────────┤
│ Receives: Current state + previous turn events + decision history│
│ Has access to: All tools (including get_battle_log)             │
│ Does: Tool calls, analysis, reasoning                           │
│ Returns: Decision only ("move crunch" or "switch skarmory")     │
│                                                                  │
│ [All tool calls happen here - NOT persisted to main context]    │
└─────────────────────────────────────────────────────────────────┘
```

### Key Principles

1. **Objective battle log is ALWAYS available** via `get_battle_log` tool
   - This is Showdown's record, not LLM's memory
   - Exact HP values, not approximations
   - Complete and accurate

2. **Previous turn events are ALWAYS in the prompt**
   - LLM doesn't need to call a tool to know what just happened
   - Formatted via `event_formatter.py`

3. **Tool reasoning is ephemeral**
   - Subagent context is discarded after each turn
   - Only the decision + rationale persists
   - Prevents context explosion

4. **Decision history includes reasoning**
   - Format: `T5: earthquake | predicted Skarmory switch → opponent stayed, 45% damage`
   - LLM can evaluate if its predictions were correct
   - Enables learning from mistakes within the battle

5. **Multi-turn strategic planning**
   - LLM can set strategic goals that persist across turns
   - Example: "Set up Stealth Rock before sweeping"
   - Can mark goals as complete or abandoned
   - Similar to Claude Code's todo system

### Pre-Battle Planning Phase

Before turn 1, the LLM gets a chance to review its team and set initial strategy:

```
Battle Starts (before turn 1)
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PRE-BATTLE PLANNING PHASE                     │
├─────────────────────────────────────────────────────────────────┤
│ System: "You are about to battle. Review your team and plan."   │
│                                                                  │
│ Available tools:                                                 │
│   - get_team_summary / get_team_pokemon (review your 6 Pokemon) │
│   - get_pokemon_info / get_move_details (look up anything)      │
│   - update_battle_plan (set initial goals)                      │
│                                                                  │
│ NOT available yet (no opponent info):                           │
│   - Damage calcs, matchups, opponent queries, battle log        │
│                                                                  │
│ LLM reviews team, identifies:                                    │
│   - Win conditions (e.g., "Sweep with DD Salamence")            │
│   - Key Pokemon to preserve                                      │
│   - Hazard setters/removers                                      │
│   - Defensive cores                                              │
│   - Likely threats to prepare for                               │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Initial Battle Plan (persists through battle)                    │
│                                                                  │
│ Goals:                                                           │
│   ○ Set up Stealth Rock early (Skarmory)                        │
│   ○ Preserve Tyranitar for late-game (Sand + Pursuit trapping)  │
│   ○ Keep Starmie healthy for Rapid Spin                         │
│   ○ Find opportunity to Dragon Dance sweep with Salamence       │
│                                                                  │
│ Team Roles:                                                      │
│   - Skarmory: Lead, hazards, phaze                              │
│   - Blissey: Special wall, status absorb                        │
│   - Tyranitar: Pursuit trapper, Sand setter                     │
│   - Starmie: Spinner, revenge killer                            │
│   - Salamence: Win condition, late-game sweeper                 │
│   - Gengar: Spinblocker, special attacker                       │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
Turn 1 begins (opponent's lead is revealed)
```

### Implementation

```python
async def _run_pre_battle_planning(self, battle: AbstractBattle) -> dict:
    """Run pre-battle planning phase before turn 1."""

    # Tools available during pre-battle (no opponent info yet)
    pre_battle_tools = [
        "get_team_summary",
        "get_team_pokemon",
        "get_pokemon_info",
        "get_move_details",
        "get_battle_plan",
        "update_battle_plan"
    ]

    messages = [
        {"role": "system", "content": PRE_BATTLE_SYSTEM_PROMPT},
        {"role": "user", "content": "Review your team and create an initial battle plan."}
    ]

    # Allow more tool calls for planning (no time pressure)
    max_planning_calls = 12

    # Run tool loop...
    # Returns initial battle plan
```

```python
PRE_BATTLE_SYSTEM_PROMPT = """You are about to battle. Before the fight begins, review your team and plan your strategy.

You have access to tools to examine your team:
- get_team_summary: See all 6 Pokemon
- get_team_pokemon: Examine one Pokemon's moves/item/ability in detail
- get_pokemon_info: Look up Pokedex data
- update_battle_plan: Set strategic goals

Consider:
- What is your win condition? (Sweeper? Stall? Hazard stacking?)
- Which Pokemon should you preserve for specific threats?
- Who is your lead? Why?
- What common threats should you prepare for?

Set your initial goals using update_battle_plan. You can adjust the plan during battle as you learn about your opponent."""
```

### Pre-Battle vs In-Battle Tools

| Tool | Pre-Battle | In-Battle |
|------|------------|-----------|
| `get_team_summary` | ✅ | ✅ |
| `get_team_pokemon` | ✅ | ✅ |
| `get_pokemon_info` | ✅ | ✅ |
| `get_move_details` | ✅ | ✅ |
| `get_battle_plan` | ✅ | ✅ |
| `update_battle_plan` | ✅ | ✅ |
| `calculate_damage` | ❌ (no opponent) | ✅ |
| `evaluate_matchup` | ❌ (no opponent) | ✅ |
| `get_opponent_*` | ❌ (no opponent) | ✅ |
| `get_battle_log` | ❌ (no events) | ✅ |

---

### Data Flow

```
Turn N starts
    │
    ▼
┌─────────────────────────────────────────────┐
│ 1. Get events from turn N-1                 │
│    battle.observations[N-1].events          │
│    → format with event_formatter            │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 2. Evaluate previous turn's prediction      │
│    Compare what LLM predicted vs happened   │
│    "Predicted switch → opponent attacked"   │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 3. Format current state + strategic plan    │
│    - Current battle state                   │
│    - Active strategic goals                 │
│    - Decision history with reasoning        │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 4. Subagent reasoning loop                  │
│    - Reviews strategic plan                 │
│    - Calls tools as needed                  │
│    - Returns: decision + reasoning + plan   │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 5. Record decision with reasoning           │
│    "T{N}: {action} | {reasoning} → {result}"│
│    Update strategic plan if needed          │
└─────────────────────────────────────────────┘
    │
    ▼
Turn N+1...
```

### Strategic Planning System

The LLM can maintain a strategic plan that persists across turns:

```python
# Example strategic plan structure
{
    "goals": [
        {
            "id": 1,
            "goal": "Set up Stealth Rock early",
            "status": "completed",
            "turn_completed": 2
        },
        {
            "id": 2,
            "goal": "Preserve Tyranitar for opposing Gengar",
            "status": "active",
            "notes": "Gengar not yet revealed, keeping TTar healthy"
        },
        {
            "id": 3,
            "goal": "Sweep with Dragon Dance Salamence late game",
            "status": "active",
            "conditions": "Need to remove Skarmory first"
        }
    ],
    "predictions": {
        "opponent_unrevealed": ["likely has a Ground-type", "probably Scarfed revenge killer"],
        "key_threats": ["Gengar if revealed", "potential priority moves"]
    }
}
```

#### Plan Management Tools

```python
{
    "name": "update_battle_plan",
    "description": "Update your strategic plan. Add goals, mark complete, or add notes.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_goal", "complete_goal", "abandon_goal", "add_note"],
            },
            "goal_id": {"type": "integer"},
            "text": {"type": "string"}
        },
        "required": ["action"]
    }
}

{
    "name": "get_battle_plan",
    "description": "Review your current strategic plan and goals.",
    "parameters": {"type": "object", "properties": {}, "required": []}
}
```

### Decision History with Reasoning

Each turn's decision includes:
1. **Action taken**: "move earthquake"
2. **Reasoning/prediction**: "predicted switch to Skarmory"
3. **Outcome** (added next turn): "opponent stayed in, dealt 45%"

```
DECISION HISTORY:
T1: switch tyranitar | lead matchup unfavorable → sandstorm up, took 20% from Focus Blast
T2: crunch | predicted stay-in for Shadow Ball → correct, KO'd Gengar
T3: stone edge | predicted Skarmory switch → WRONG, Alakazam stayed, 60% damage
T4: pursuit | reading the switch this time → correct, trapped Alakazam
```

This allows the LLM to:
- **Learn from mistakes** within the battle
- **Adjust predictions** based on opponent's patterns
- **Evaluate its own reasoning** quality
```

---

## Implementation Architecture

### File Structure

```
src/
├── llm_player.py              # Base LLMPlayer class
├── llm_player_with_tools.py   # New: LLMPlayerWithTools
├── tools/
│   ├── __init__.py
│   ├── definitions.py         # Tool JSON schemas for LiteLLM
│   ├── executor.py            # Tool execution dispatcher
│   ├── type_tools.py          # get_type_effectiveness, get_all_type_matchups
│   ├── damage_tools.py        # calculate_damage, calculate_all_damages
│   ├── speed_tools.py         # get_speed_comparison
│   ├── matchup_tools.py       # evaluate_matchup, evaluate_all_matchups
│   ├── info_tools.py          # get_move_details, get_pokemon_info
│   ├── field_tools.py         # get_field_analysis
│   ├── team_tools.py          # get_team_pokemon, get_team_summary, get_opponent_pokemon
│   ├── battle_log_tools.py    # get_battle_log, get_turn_details
│   └── plan_tools.py          # get_battle_plan, update_battle_plan
├── state_formatter.py         # Existing
├── event_formatter.py         # Existing
└── response_parser.py         # Existing
```

### Tool Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        TURN START                                │
└───────────────────────────┬─────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. Format concise battle state (simplified for tool mode)      │
│     - Active Pokemon (yours + opponent)                          │
│     - HP percentages                                             │
│     - Available moves/switches (names only)                      │
│     - Field conditions summary                                   │
└───────────────────────────┬─────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. Send to LLM with tools available                            │
│     - System prompt explains tool usage                          │
│     - Tools defined via LiteLLM's unified format                │
│     - Request: "Analyze and choose your action"                  │
└───────────────────────────┬─────────────────────────────────────┘
                            ▼
         ┌─────────────────────────────────────┐
         │     LLM Response                     │
         │  ┌───────────┐    ┌───────────────┐ │
         │  │Tool Calls │ OR │ Final Answer  │ │
         │  └─────┬─────┘    └───────┬───────┘ │
         └────────┼──────────────────┼─────────┘
                  ▼                  ▼
┌─────────────────────────┐  ┌──────────────────────────────────┐
│ 3. Execute Tool Calls   │  │ 5. Parse final action            │
│    (max N per turn)     │  │    "move earthquake" or          │
│    Return results       │  │    "switch skarmory"             │
└───────────┬─────────────┘  └──────────────────────────────────┘
            │                              ▲
            ▼                              │
┌─────────────────────────────────────────────────────────────────┐
│  4. Append tool results to conversation                         │
│     Loop back to step 2 (until final answer or max calls)       │
└─────────────────────────────────────────────────────────────────┘
```

### Core Implementation

```python
# src/llm_player_with_tools.py

from typing import Optional, Tuple
from poke_env.player.player import AbstractBattle
import litellm

from .llm_player import LLMPlayer
from .tools.definitions import TOOL_DEFINITIONS
from .tools.executor import execute_tool
from .state_formatter import format_battle_state
from .event_formatter import format_events
from .response_parser import parse_llm_response

TOOLS_SYSTEM_PROMPT = """You are playing a competitive Pokemon battle. Your goal is to win.

You have access to information tools:
- Type effectiveness and matchup analysis
- Damage calculations
- Move/Pokemon details lookup
- Complete battle log (objective record from the game)

IMPORTANT:
- Tools provide DATA. YOU reason about strategy and prediction.
- The battle log is the objective record - use it to review what actually happened.
- Consider what the opponent might do - that's YOUR job, not the tools'.
- Your final answer MUST be: "move <move_name>" or "switch <pokemon_name>"

Available actions:
- move <name>: Use one of your available moves
- switch <name>: Switch to a Pokemon from your bench
"""

class LLMPlayerWithTools(LLMPlayer):
    """LLM player with tool-calling capabilities, subagent architecture, and strategic planning."""

    def __init__(
        self,
        model: str,
        max_tool_calls: int = 8,
        **kwargs
    ):
        super().__init__(model=model, **kwargs)
        self.max_tool_calls = max_tool_calls

        # Per-battle state
        self.decision_history: dict[str, list[dict]] = {}  # battle_id -> [{turn, action, reasoning, outcome}]
        self.battle_plans: dict[str, dict] = {}  # battle_id -> {goals: [...], predictions: {...}}

    async def choose_move(self, battle: AbstractBattle) -> str:
        """Choose a move using subagent with tools and strategic planning."""

        battle_id = battle.battle_tag

        # Initialize per-battle state
        if battle_id not in self.decision_history:
            self.decision_history[battle_id] = []
            self.battle_plans[battle_id] = {"goals": [], "predictions": {}}

        # 1. Get previous turn events (objective, from Showdown)
        prev_turn_events = self._get_previous_turn_events(battle)

        # 2. Update previous turn's outcome (did prediction match reality?)
        self._update_previous_outcome(battle_id, prev_turn_events)

        # 3. Format current state
        current_state = format_battle_state(battle)

        # 4. Format decision history with reasoning
        decision_summary = self._format_decision_history(battle_id)

        # 5. Get current strategic plan
        battle_plan = self.battle_plans[battle_id]

        # 6. Run reasoning subagent (ephemeral context)
        result = await self._run_reasoning_subagent(
            battle=battle,
            prev_turn_events=prev_turn_events,
            current_state=current_state,
            decision_history=decision_summary,
            battle_plan=battle_plan
        )

        # 7. Record decision with reasoning (outcome added next turn)
        self.decision_history[battle_id].append({
            "turn": battle.turn,
            "action": result["action"],
            "reasoning": result.get("reasoning", ""),
            "prediction": result.get("prediction", ""),
            "outcome": None  # Filled in next turn
        })

        # 8. Update strategic plan if subagent modified it
        if "plan_updates" in result:
            self._apply_plan_updates(battle_id, result["plan_updates"])

        # 9. Parse and return
        action = parse_llm_response(result["action"], battle)
        if action:
            return self.create_order(action)
        return self.choose_random_move(battle)

    def _update_previous_outcome(self, battle_id: str, prev_events: str):
        """Update the previous turn's decision with what actually happened."""
        if not self.decision_history[battle_id]:
            return

        last_decision = self.decision_history[battle_id][-1]
        if last_decision["outcome"] is None:
            # Summarize what happened (could be more sophisticated)
            last_decision["outcome"] = prev_events[:100] if prev_events else "no events"

    def _format_decision_history(self, battle_id: str) -> str:
        """Format decision history with reasoning and outcomes."""
        lines = []
        for d in self.decision_history[battle_id][-8:]:  # Last 8 turns
            line = f"T{d['turn']}: {d['action']}"
            if d.get('reasoning'):
                line += f" | {d['reasoning']}"
            if d.get('prediction') and d.get('outcome'):
                # Show if prediction was correct
                line += f" → {d['outcome'][:50]}"
            lines.append(line)
        return "\n".join(lines)

    def _get_previous_turn_events(self, battle: AbstractBattle) -> str:
        """Get formatted events from the previous turn (objective record)."""
        prev_turn = battle.turn - 1
        if prev_turn <= 0 or prev_turn not in battle.observations:
            return ""

        events = battle.observations[prev_turn].events
        perspective = "p1" if "p1" in str(battle.player_username) else "p2"
        return format_events(events, perspective)

    async def _run_reasoning_subagent(
        self,
        battle: AbstractBattle,
        prev_turn_events: str,
        current_state: str,
        decision_history: str,
        battle_plan: dict
    ) -> dict:
        """
        Run isolated reasoning subagent with tools.

        This context is EPHEMERAL - not persisted between turns.
        Returns structured result with action, reasoning, and plan updates.
        """

        # Format strategic plan
        plan_text = self._format_battle_plan(battle_plan)

        # Build subagent prompt with all objective information
        user_content = f"""PREVIOUS TURN:
{prev_turn_events if prev_turn_events else "(Battle just started)"}

CURRENT STATE:
{current_state}

YOUR DECISION HISTORY (with reasoning):
{decision_history if decision_history else "(First turn)"}

YOUR STRATEGIC PLAN:
{plan_text if plan_text else "(No plan yet - consider setting goals)"}

Analyze the situation. You may:
1. Use tools to gather information
2. Update your strategic plan (add/complete goals)
3. Make your decision

Your final response must include:
- ACTION: move <name> or switch <name>
- REASONING: why you chose this (1 sentence)
- PREDICTION: what you expect opponent to do (optional)"""

        messages = [
            {"role": "system", "content": TOOLS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        # Tool-calling loop (all in ephemeral context)
        tool_calls_made = 0
        plan_updates = []

        while tool_calls_made < self.max_tool_calls:
            try:
                response = await litellm.acompletion(
                    model=self.model,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=self.timeout,
                )

                message = response.choices[0].message

                if message.tool_calls:
                    tool_calls_made += len(message.tool_calls)

                    messages.append({
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": message.tool_calls
                    })

                    for tool_call in message.tool_calls:
                        # Track plan updates
                        if tool_call.function.name == "update_battle_plan":
                            plan_updates.append(json.loads(tool_call.function.arguments))

                        result = execute_tool(
                            tool_call.function.name,
                            tool_call.function.arguments,
                            battle
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })

                    if self.verbose:
                        print(f"[{self.username}] Tools: {[tc.function.name for tc in message.tool_calls]}")
                    continue

                # Final answer - parse structured response
                return self._parse_subagent_response(message.content, plan_updates)

            except Exception as e:
                print(f"[{self.username}] Subagent error: {e}")
                return {"action": "", "reasoning": "", "plan_updates": plan_updates}

        # Force decision after max tool calls
        messages.append({
            "role": "user",
            "content": "Provide your final action now: ACTION: move <name> or switch <name>"
        })

        try:
            response = await litellm.acompletion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=100,
                timeout=self.timeout,
            )
            return self._parse_subagent_response(response.choices[0].message.content, plan_updates)
        except:
            return {"action": "", "reasoning": "", "plan_updates": plan_updates}

    def _format_battle_plan(self, plan: dict) -> str:
        """Format battle plan for display."""
        lines = []
        for goal in plan.get("goals", []):
            status = "✓" if goal["status"] == "completed" else "○"
            lines.append(f"{status} {goal['goal']}")
            if goal.get("notes"):
                lines.append(f"   └─ {goal['notes']}")
        return "\n".join(lines) if lines else ""

    def _parse_subagent_response(self, content: str, plan_updates: list) -> dict:
        """Parse structured response from subagent."""
        result = {"action": "", "reasoning": "", "prediction": "", "plan_updates": plan_updates}

        # Parse ACTION: line
        if "ACTION:" in content:
            action_line = content.split("ACTION:")[-1].split("\n")[0].strip()
            result["action"] = action_line

        # Parse REASONING: line
        if "REASONING:" in content:
            reasoning_line = content.split("REASONING:")[-1].split("\n")[0].strip()
            result["reasoning"] = reasoning_line

        # Parse PREDICTION: line
        if "PREDICTION:" in content:
            prediction_line = content.split("PREDICTION:")[-1].split("\n")[0].strip()
            result["prediction"] = prediction_line

        # Fallback: try to find move/switch anywhere
        if not result["action"]:
            result["action"] = content.strip()

        return result

    def _apply_plan_updates(self, battle_id: str, updates: list):
        """Apply plan updates from subagent."""
        plan = self.battle_plans[battle_id]

        for update in updates:
            action = update.get("action")

            if action == "add_goal":
                plan["goals"].append({
                    "id": len(plan["goals"]) + 1,
                    "goal": update.get("text", ""),
                    "status": "active",
                    "notes": ""
                })

            elif action == "complete_goal":
                goal_id = update.get("goal_id")
                for goal in plan["goals"]:
                    if goal["id"] == goal_id:
                        goal["status"] = "completed"

            elif action == "add_note":
                goal_id = update.get("goal_id")
                for goal in plan["goals"]:
                    if goal["id"] == goal_id:
                        goal["notes"] = update.get("text", "")

    def battle_finished_callback(self, battle: AbstractBattle) -> None:
        """Clean up when battle ends."""
        super().battle_finished_callback(battle)
        battle_id = battle.battle_tag
        if battle_id in self.decision_history:
            del self.decision_history[battle_id]
        if battle_id in self.battle_plans:
            del self.battle_plans[battle_id]
```

---

## Tool Implementation Examples

### Type Effectiveness (using poke-env)

```python
# src/tools/type_tools.py

from poke_env.data import GenData
from poke_env.environment import PokemonType

def get_type_effectiveness(attack_type: str, defender_types: list[str], gen: int = 4) -> dict:
    """Calculate type effectiveness multiplier."""

    gen_data = GenData.from_gen(gen)
    type_chart = gen_data.type_chart

    # Convert strings to PokemonType enums
    atk_type = PokemonType[attack_type.upper()]
    def_types = [PokemonType[t.upper()] for t in defender_types]

    # Calculate multiplier
    multiplier = atk_type.damage_multiplier(
        def_types[0],
        def_types[1] if len(def_types) > 1 else None,
        type_chart=type_chart
    )

    # Human-readable description
    if multiplier == 0:
        desc = "immune (0x)"
    elif multiplier == 0.25:
        desc = "doubly resisted (0.25x)"
    elif multiplier == 0.5:
        desc = "resisted (0.5x)"
    elif multiplier == 1:
        desc = "neutral (1x)"
    elif multiplier == 2:
        desc = "super effective (2x)"
    elif multiplier == 4:
        desc = "doubly super effective (4x)"
    else:
        desc = f"{multiplier}x"

    return {
        "multiplier": multiplier,
        "description": desc
    }
```

### Damage Calculation (using poke-env's calculator)

```python
# src/tools/damage_tools.py

from poke_env.calc import calculate_damage
from poke_env.player.player import AbstractBattle

def calc_damage_for_move(move_name: str, battle: AbstractBattle) -> dict:
    """Calculate damage for a move against current opponent."""

    attacker = battle.active_pokemon
    defender = battle.opponent_active_pokemon

    # Find the move object
    move = None
    for m in battle.available_moves:
        if m.id == move_name.lower().replace(" ", ""):
            move = m
            break

    if not move:
        return {"error": f"Move '{move_name}' not found in available moves"}

    if move.category.name == "STATUS":
        return {
            "move": move.id,
            "type": move.type.name.lower(),
            "is_status": True,
            "damage": 0,
            "effect": move.entry.get("shortDesc", "Status move")
        }

    # Use poke-env's damage calculator
    min_dmg, max_dmg = calculate_damage(
        attacker.species,
        defender.species,
        move.id,
        battle
    )

    # Calculate percentages
    defender_hp = defender.max_hp or 100  # Estimate if unknown
    min_pct = (min_dmg / defender_hp) * 100
    max_pct = (max_dmg / defender_hp) * 100
    avg_pct = (min_pct + max_pct) / 2

    # Check for STAB
    is_stab = move.type in attacker.types

    # Effectiveness
    effectiveness = move.type.damage_multiplier(
        defender.types[0],
        defender.types[1] if len(defender.types) > 1 else None,
        type_chart=battle.gen.type_chart
    )

    return {
        "move": move.id,
        "type": move.type.name.lower(),
        "base_power": move.base_power,
        "min_damage": min_dmg,
        "max_damage": max_dmg,
        "min_percent": round(min_pct, 1),
        "max_percent": round(max_pct, 1),
        "avg_percent": round(avg_pct, 1),
        "effectiveness": effectiveness,
        "is_stab": is_stab,
        "can_ohko": max_pct >= 100,
        "can_2hko": avg_pct >= 50
    }
```

### Matchup Evaluation (mirroring heuristic player)

```python
# src/tools/matchup_tools.py

def evaluate_matchup(battle: AbstractBattle, pokemon_name: str = None) -> dict:
    """Evaluate matchup score (mirrors SimpleHeuristicsPlayer._estimate_matchup)."""

    SPEED_TIER_COEF = 0.1
    HP_FRACTION_COEF = 0.4

    # Get the Pokemon to evaluate
    if pokemon_name:
        mon = None
        for p in battle.team.values():
            if p.species.lower() == pokemon_name.lower():
                mon = p
                break
        if not mon:
            return {"error": f"Pokemon '{pokemon_name}' not found"}
    else:
        mon = battle.active_pokemon

    opponent = battle.opponent_active_pokemon

    if not opponent:
        return {"error": "No opponent Pokemon visible"}

    # Offensive typing: how effective are we against them?
    offensive_score = max(
        opponent.damage_multiplier(t) for t in mon.types if t
    )

    # Defensive typing: how effective are they against us?
    defensive_score = -max(
        mon.damage_multiplier(t) for t in opponent.types if t
    )

    # Speed advantage
    speed_score = 0
    if mon.base_stats and opponent.base_stats:
        if mon.base_stats["spe"] > opponent.base_stats["spe"]:
            speed_score = SPEED_TIER_COEF
        else:
            speed_score = -SPEED_TIER_COEF

    # HP advantage
    hp_score = (mon.current_hp_fraction - opponent.current_hp_fraction) * HP_FRACTION_COEF

    # Boost advantage
    boost_score = 0
    for stat, val in mon.boosts.items():
        boost_score += val * 0.1

    total_score = offensive_score + defensive_score + speed_score + hp_score + boost_score

    # Verdict
    if total_score > 1.0:
        verdict = "strongly favorable"
    elif total_score > 0.3:
        verdict = "favorable"
    elif total_score > -0.3:
        verdict = "neutral"
    elif total_score > -1.0:
        verdict = "unfavorable"
    else:
        verdict = "strongly unfavorable"

    return {
        "your_pokemon": mon.species,
        "opponent_pokemon": opponent.species,
        "matchup_score": round(total_score, 2),
        "verdict": verdict,
        "factors": {
            "offensive_typing": round(offensive_score, 2),
            "defensive_typing": round(defensive_score, 2),
            "speed_advantage": round(speed_score, 2),
            "hp_advantage": round(hp_score, 2),
            "boost_advantage": round(boost_score, 2)
        }
    }
```

### Team Tools (using poke-env battle state)

```python
# src/tools/team_tools.py

from poke_env.player.player import AbstractBattle

def get_team_pokemon(battle: AbstractBattle, pokemon_name: str) -> dict:
    """Get detailed info about one of your team members."""

    # Find the pokemon in your team
    pokemon = None
    for ident, mon in battle.team.items():
        if mon.species.lower() == pokemon_name.lower():
            pokemon = mon
            break

    if not pokemon:
        return {"error": f"Pokemon '{pokemon_name}' not found on your team"}

    # Format moves with PP
    moves = []
    for move_id, move in pokemon.moves.items():
        move_info = {
            "name": move.id,
            "type": move.type.name.lower(),
            "pp": f"{move.current_pp}/{move.max_pp}" if move.current_pp is not None else "?/?"
        }
        if move.base_power > 0:
            move_info["base_power"] = move.base_power
            move_info["category"] = move.category.name.lower()
        else:
            move_info["category"] = "status"
        moves.append(move_info)

    return {
        "species": pokemon.species,
        "hp_percent": round(pokemon.current_hp_fraction * 100, 1),
        "status": pokemon.status.name if pokemon.status else None,
        "is_active": pokemon == battle.active_pokemon,
        "fainted": pokemon.fainted,
        "ability": pokemon.ability,
        "item": pokemon.item,
        "moves": moves,
        "boosts": dict(pokemon.boosts),
        "types": [t.name.lower() for t in pokemon.types if t],
        "base_stats": pokemon.base_stats
    }


def get_team_summary(battle: AbstractBattle) -> dict:
    """Get summary of entire team status."""

    active_mon = battle.active_pokemon
    active_info = None
    if active_mon and not active_mon.fainted:
        active_info = {
            "species": active_mon.species,
            "hp_percent": round(active_mon.current_hp_fraction * 100, 1),
            "status": active_mon.status.name if active_mon.status else None,
            "boosts": {k: v for k, v in active_mon.boosts.items() if v != 0}
        }

    bench = []
    alive_count = 0
    fainted_count = 0

    for ident, pokemon in battle.team.items():
        if pokemon == active_mon:
            if not pokemon.fainted:
                alive_count += 1
            continue

        bench.append({
            "species": pokemon.species,
            "hp_percent": round(pokemon.current_hp_fraction * 100, 1),
            "status": pokemon.status.name if pokemon.status else None,
            "fainted": pokemon.fainted
        })

        if pokemon.fainted:
            fainted_count += 1
        else:
            alive_count += 1

    return {
        "active": active_info,
        "bench": bench,
        "alive_count": alive_count,
        "fainted_count": fainted_count
    }


def get_opponent_pokemon(battle: AbstractBattle, pokemon_name: str) -> dict:
    """Get known info about opponent's Pokemon (only revealed info)."""

    # Find in opponent's team
    pokemon = None
    for ident, mon in battle.opponent_team.items():
        if mon.species.lower() == pokemon_name.lower():
            pokemon = mon
            break

    if not pokemon:
        return {"error": f"Pokemon '{pokemon_name}' not seen on opponent's team"}

    # Only show revealed moves
    known_moves = []
    for move_id, move in pokemon.moves.items():
        known_moves.append({
            "name": move.id,
            "type": move.type.name.lower() if move.type else "unknown"
        })

    return {
        "species": pokemon.species,
        "hp_percent": round(pokemon.current_hp_fraction * 100, 1),
        "status": pokemon.status.name if pokemon.status else None,
        "is_active": pokemon == battle.opponent_active_pokemon,
        "fainted": pokemon.fainted,
        "known_ability": pokemon.ability,  # May be None if not revealed
        "known_item": pokemon.item,  # May be None if not revealed
        "known_moves": known_moves,
        "possible_moves_remaining": max(0, 4 - len(known_moves)),
        "types": [t.name.lower() for t in pokemon.types if t],
        "base_stats": pokemon.base_stats
    }


def get_opponent_team_summary(battle: AbstractBattle) -> dict:
    """Get summary of entire opponent team (only revealed info)."""

    # In standard 6v6, opponent has 6 Pokemon
    # opponent_team only contains Pokemon that have been revealed
    revealed = list(battle.opponent_team.values())
    revealed_count = len(revealed)
    unrevealed_count = 6 - revealed_count  # Assuming 6v6

    active_mon = battle.opponent_active_pokemon
    active_info = None
    if active_mon:
        active_info = {
            "species": active_mon.species,
            "hp_percent": round(active_mon.current_hp_fraction * 100, 1),
            "status": active_mon.status.name if active_mon.status else None,
            "known_moves": [m.id for m in active_mon.moves.values()],
            "known_ability": active_mon.ability,
            "known_item": active_mon.item
        }

    bench = []
    fainted_count = 0
    alive_count = 0

    for pokemon in revealed:
        if pokemon == active_mon:
            if not pokemon.fainted:
                alive_count += 1
            else:
                fainted_count += 1
            continue

        bench.append({
            "species": pokemon.species,
            "hp_percent": round(pokemon.current_hp_fraction * 100, 1),
            "status": pokemon.status.name if pokemon.status else None,
            "fainted": pokemon.fainted,
            "known_moves": [m.id for m in pokemon.moves.values()],
            "known_ability": pokemon.ability,
            "known_item": pokemon.item
        })

        if pokemon.fainted:
            fainted_count += 1
        else:
            alive_count += 1

    return {
        "revealed_count": revealed_count,
        "unrevealed_count": unrevealed_count,
        "fainted_count": fainted_count,
        "alive_revealed_count": alive_count,
        "active": active_info,
        "bench": bench,
        "max_pokemon_remaining": alive_count + unrevealed_count
    }
```

### Battle Log Tools (using poke-env observations)

```python
# src/tools/battle_log_tools.py

import json
from poke_env.player.player import AbstractBattle
from src.event_formatter import format_events

def get_battle_log(battle: AbstractBattle, format: str = "narrative", from_turn: int = 1) -> dict:
    """
    Get the complete battle log from Showdown.

    This is the OBJECTIVE record - exactly what happened,
    not what the LLM remembers or infers.
    """

    # Determine perspective
    perspective = "p1" if "p1" in str(battle.player_username) else "p2"

    turns = []

    for turn_num in sorted(battle.observations.keys()):
        if turn_num < from_turn:
            continue

        obs = battle.observations[turn_num]

        if format == "narrative":
            # Human-readable story
            event_text = format_events(obs.events, perspective)
            turns.append({
                "turn": turn_num,
                "events": event_text
            })

        elif format == "detailed":
            # Structured with exact HP values
            turns.append({
                "turn": turn_num,
                "your_pokemon": _serialize_pokemon(obs.active_pokemon),
                "opponent_pokemon": _serialize_pokemon(obs.opponent_active_pokemon),
                "weather": [w.name for w in obs.weather.keys()],
                "your_hazards": [sc.name for sc in obs.side_conditions.keys()],
                "opponent_hazards": [sc.name for sc in obs.opponent_side_conditions.keys()],
                "actions": _parse_actions(obs.events, perspective)
            })

        elif format == "raw":
            # Raw Showdown protocol
            turns.append({
                "turn": turn_num,
                "protocol": ["|".join(event) for event in obs.events]
            })

    return {"turns": turns, "current_turn": battle.turn}


def get_turn_details(battle: AbstractBattle, turn: int) -> dict:
    """Get detailed information about a specific turn."""

    if turn not in battle.observations:
        return {"error": f"Turn {turn} not found. Battle is on turn {battle.turn}."}

    obs = battle.observations[turn]
    perspective = "p1" if "p1" in str(battle.player_username) else "p2"

    return {
        "turn": turn,
        "state_at_turn_start": {
            "your_active": _serialize_pokemon(obs.active_pokemon),
            "opponent_active": _serialize_pokemon(obs.opponent_active_pokemon),
            "weather": [w.name for w in obs.weather.keys()],
            "terrain": [f.name for f in obs.fields.keys()],
            "your_side_conditions": [sc.name for sc in obs.side_conditions.keys()],
            "opponent_side_conditions": [sc.name for sc in obs.opponent_side_conditions.keys()],
        },
        "events_narrative": format_events(obs.events, perspective),
        "events_raw": ["|".join(event) for event in obs.events]
    }


def _serialize_pokemon(pokemon) -> dict:
    """Serialize pokemon state with exact HP."""
    if pokemon is None:
        return None

    # HP is stored as fraction, but we can show it clearly
    hp_fraction = pokemon.current_hp_fraction
    hp_percent = round(hp_fraction * 100, 1)

    return {
        "species": pokemon.species,
        "hp_percent": hp_percent,
        "hp_fraction": hp_fraction,
        "status": pokemon.status.name if pokemon.status else None,
        "boosts": dict(pokemon.boosts) if pokemon.boosts else {},
        "ability": pokemon.ability,
        "item": pokemon.item
    }


def _parse_actions(events: list, perspective: str) -> list:
    """Parse raw events into structured action list."""
    actions = []

    for event in events:
        if not event:
            continue

        event_type = event[0] if event else ""

        if event_type == "move":
            actions.append({
                "type": "move",
                "pokemon": event[1].split(": ")[-1] if len(event) > 1 else "",
                "move": event[2] if len(event) > 2 else "",
                "target": event[3].split(": ")[-1] if len(event) > 3 else ""
            })

        elif event_type == "-damage":
            pokemon = event[1].split(": ")[-1] if len(event) > 1 else ""
            hp = event[2] if len(event) > 2 else ""
            actions.append({
                "type": "damage",
                "pokemon": pokemon,
                "hp_after": hp
            })

        elif event_type == "-heal":
            pokemon = event[1].split(": ")[-1] if len(event) > 1 else ""
            hp = event[2] if len(event) > 2 else ""
            actions.append({
                "type": "heal",
                "pokemon": pokemon,
                "hp_after": hp
            })

        elif event_type == "switch":
            pokemon = event[1].split(": ")[-1] if len(event) > 1 else ""
            hp = event[3] if len(event) > 3 else ""
            actions.append({
                "type": "switch",
                "pokemon": pokemon,
                "hp": hp
            })

        elif event_type == "faint":
            pokemon = event[1].split(": ")[-1] if len(event) > 1 else ""
            actions.append({
                "type": "faint",
                "pokemon": pokemon
            })

        elif event_type == "-status":
            pokemon = event[1].split(": ")[-1] if len(event) > 1 else ""
            status = event[2] if len(event) > 2 else ""
            actions.append({
                "type": "status",
                "pokemon": pokemon,
                "status": status
            })

        elif event_type in ["-supereffective", "-resisted", "-crit", "-miss"]:
            actions.append({"type": event_type.lstrip("-")})

    return actions
```

---

## LiteLLM Tool Format

LiteLLM uses OpenAI-compatible tool format, which works across providers:

```python
# src/tools/definitions.py

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_type_effectiveness",
            "description": "Get the damage multiplier for an attacking type against a Pokemon's types.",
            "parameters": {
                "type": "object",
                "properties": {
                    "attack_type": {"type": "string", "description": "The attacking type"},
                    "defender_types": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["attack_type", "defender_types"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_damage",
            "description": "Calculate damage for a specific move against the current opponent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "move_name": {"type": "string", "description": "Name of the move"}
                },
                "required": ["move_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_all_damages",
            "description": "Calculate damage for ALL your available moves at once. More efficient than multiple calculate_damage calls.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_battle_log",
            "description": "Get the complete objective battle log from the game. Use 'narrative' for readable text, 'detailed' for structured data with exact HP, 'raw' for Showdown protocol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["narrative", "detailed", "raw"],
                        "description": "Output format (default: narrative)"
                    },
                    "from_turn": {
                        "type": "integer",
                        "description": "Start from this turn (default: 1)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_turn_details",
            "description": "Get detailed information about a specific turn including exact HP values and all events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "turn": {"type": "integer", "description": "Turn number to examine"}
                },
                "required": ["turn"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_battle_plan",
            "description": "Update your strategic plan. Add goals, mark complete, or add notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add_goal", "complete_goal", "abandon_goal", "add_note"]
                    },
                    "goal_id": {"type": "integer", "description": "Goal ID (for complete/abandon/note)"},
                    "text": {"type": "string", "description": "Goal text or note"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_battle_plan",
            "description": "Review your current strategic plan and goals.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_team_pokemon",
            "description": "Get detailed info about one of your team members - moves, item, ability, HP, status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {"type": "string", "description": "Pokemon name"}
                },
                "required": ["pokemon_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_team_summary",
            "description": "Get HP/status summary of your entire team.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_opponent_pokemon",
            "description": "Get known info about an opponent's Pokemon (only revealed information).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {"type": "string", "description": "Pokemon name"}
                },
                "required": ["pokemon_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_opponent_team_summary",
            "description": "Get summary of opponent's entire team - revealed Pokemon, their HP/status, known moves, and count of unrevealed Pokemon.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    # ... additional tools (evaluate_matchup, get_speed_comparison, etc.) ...
]
```

---

## Configuration

### Environment Variables

```bash
# Max tool calls per turn (default: 8)
LLM_ARENA_MAX_TOOL_CALLS=8

# Enable/disable specific tool categories
LLM_ARENA_TOOLS_ENABLED=type,damage,speed,matchup,info,field

# Verbose tool logging
LLM_ARENA_TOOL_VERBOSE=true
```

### Per-Model Configuration

```yaml
# config/models.yaml
models:
  claude-sonnet-4-20250514:
    provider: anthropic
    temperature: 0.7
    max_tokens: 500
    tools_enabled: true
    max_tool_calls: 8

  gpt-4o:
    provider: openai
    temperature: 0.7
    max_tokens: 500
    tools_enabled: true
    max_tool_calls: 8

  gemini-1.5-pro:
    provider: google
    temperature: 0.7
    max_tokens: 500
    tools_enabled: true
    max_tool_calls: 8
```

---

## Testing Strategy

### Unit Tests

```python
# tests/test_tools.py

def test_type_effectiveness():
    result = get_type_effectiveness("fire", ["grass", "steel"])
    assert result["multiplier"] == 4.0

def test_type_effectiveness_immunity():
    result = get_type_effectiveness("ground", ["flying"])
    assert result["multiplier"] == 0

def test_damage_calculation():
    # Mock battle state
    result = calc_damage_for_move("earthquake", mock_battle)
    assert "min_damage" in result
    assert "max_damage" in result
    assert result["is_stab"] == True  # Assuming Ground-type attacker
```

### Integration Tests

```python
# tests/test_llm_with_tools.py

async def test_tool_calling_loop():
    player = LLMPlayerWithTools(model="gpt-4o-mini", max_tool_calls=3)

    # Verify tool calls are made and parsed
    action = await player.choose_move(mock_battle)
    assert action is not None
    assert action.startswith("/choose")
```

### Benchmark vs Heuristic

```bash
# Run tool-enabled LLM against heuristic baseline
python scripts/benchmark_vs_heuristic.py \
    --model gpt-4o \
    --tools-enabled \
    --games 50
```

---

## Tool Result Caching

To avoid redundant calculations and save tokens, tool results are cached within a battle:

### Cache Strategy

```python
class ToolCache:
    """Cache tool results to avoid redundant calculations."""

    def __init__(self, max_turns: int = 3):
        self.max_turns = max_turns  # How long to keep cached results
        self.cache: dict[str, dict] = {}  # tool_key -> {result, turn_cached}

    def get(self, tool_name: str, args: dict, current_turn: int) -> Optional[dict]:
        """Get cached result if still valid."""
        key = self._make_key(tool_name, args)
        if key in self.cache:
            cached = self.cache[key]
            age = current_turn - cached["turn_cached"]
            if age <= self.max_turns:
                return cached["result"]
            else:
                del self.cache[key]  # Stale, remove
        return None

    def set(self, tool_name: str, args: dict, result: dict, current_turn: int):
        """Cache a tool result."""
        key = self._make_key(tool_name, args)
        self.cache[key] = {"result": result, "turn_cached": current_turn}

    def invalidate_on_state_change(self, current_turn: int):
        """Invalidate caches that depend on battle state."""
        # Damage calcs, matchups, speed comparisons become stale when:
        # - Pokemon switch
        # - Stats change (boosts)
        # - Weather/terrain changes
        # - HP changes significantly
        state_dependent = ["calculate_damage", "calculate_all_damages",
                          "evaluate_matchup", "evaluate_all_matchups",
                          "get_speed_comparison"]
        for key in list(self.cache.keys()):
            if any(tool in key for tool in state_dependent):
                del self.cache[key]
```

### What Gets Cached

| Tool | Cacheable? | Invalidation |
|------|------------|--------------|
| `get_type_effectiveness` | ✅ Forever | Never (type chart is static) |
| `get_all_type_matchups` | ✅ Forever | Never |
| `get_pokemon_info` | ✅ Forever | Never (Pokedex is static) |
| `get_move_details` | ✅ Forever | Never |
| `calculate_damage` | ✅ 1 turn | On switch, boost, weather change |
| `calculate_all_damages` | ✅ 1 turn | On switch, boost, weather change |
| `evaluate_matchup` | ✅ 1 turn | On switch, boost, HP change |
| `get_speed_comparison` | ✅ 1 turn | On switch, boost, paralysis |
| `get_team_summary` | ❌ No | Changes every turn |
| `get_opponent_team_summary` | ❌ No | Changes every turn |
| `get_battle_log` | ❌ No | Grows every turn |
| `get_field_analysis` | ✅ 1 turn | On weather/hazard/screen change |

### Benefits

1. **Token savings**: Don't repeat static lookups (type chart, Pokedex)
2. **Speed**: Damage calcs are expensive, avoid recalculating same matchup
3. **Consistency**: Same query returns same result within a turn

---

## Next Steps

1. **Implement core tools** - Start with type effectiveness, damage calc, and matchup evaluation
2. **Create tool executor** - Dispatch layer that routes tool calls to implementations
3. **Update LLMPlayerWithTools** - Full tool-calling loop implementation
4. **Add tests** - Unit tests for each tool, integration tests for the full loop
5. **Benchmark** - Compare tool-enabled vs no-tools vs heuristic player
