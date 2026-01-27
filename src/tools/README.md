# Tools

The tool harness provides strategic information to LLM players during battles. Tools are the LLM's way of gathering information beyond what's in the immediate state summary.

## Architecture

```
┌─────────────────┐
│   LLMPlayer     │
│   (tool loop)   │
└────────┬────────┘
         │ execute_tool(name, args, battle, context)
         ▼
┌─────────────────┐     ┌──────────────┐
│    registry.py  │────►│  Tool Module │
│  (dispatcher)   │     │  (handler)   │
└─────────────────┘     └──────────────┘
```

All tools are registered in `registry.py`, which provides:
- **LLM tool definitions** (JSON schema for LLM API)
- **Human command parsing** (text → tool name + args)
- **Unified execution** (dispatch to appropriate handler)

## Tools Reference

### `damage`

Calculate damage for your available moves against the current opponent.

**LLM Call**:
```json
{"name": "damage", "arguments": {}}
{"name": "damage", "arguments": {"move": "earthquake"}}
```

**Human Command**:
```
damage              # All moves
damage earthquake   # Specific move
```

**Returns**:
```json
{
  "your_pokemon": "Tyranitar",
  "opponent_pokemon": "Gengar",
  "opponent_hp_percent": 75.0,
  "moves": [
    {
      "move": "crunch",
      "type": "dark",
      "category": "physical",
      "base_power": 80,
      "min_percent": 85.2,
      "max_percent": 142.1,
      "effectiveness": 2.0,
      "is_stab": true,
      "accuracy": 100,
      "priority": 0
    }
  ]
}
```

Uses Gen 4 damage formula with stat ranges to calculate min/max damage percentages.

---

### `team`

Get information about your team.

**LLM Call**:
```json
{"name": "team", "arguments": {}}
{"name": "team", "arguments": {"pokemon": "Skarmory"}}
{"name": "team", "arguments": {"full": true}}
```

**Human Command**:
```
team              # Summary (active + bench HP/status)
team skarmory     # Specific Pokemon details
team full         # Full details for entire team
```

**Returns** (summary):
```json
{
  "active": {
    "species": "Tyranitar",
    "hp_percent": 100,
    "status": null,
    "boosts": {}
  },
  "bench": [
    {"species": "Skarmory", "hp_percent": 100, "status": null, "fainted": false},
    {"species": "Blissey", "hp_percent": 45, "status": "TOX", "fainted": false}
  ],
  "alive_count": 6,
  "fainted_count": 0
}
```

**Returns** (specific Pokemon):
```json
{
  "species": "Skarmory",
  "hp_percent": 100,
  "status": null,
  "is_active": false,
  "fainted": false,
  "ability": "Sturdy",
  "item": "Leftovers",
  "moves": [
    {"name": "spikes", "type": "ground", "pp": "3/3", "category": "status"},
    {"name": "bravebird", "type": "flying", "pp": "24/24", "base_power": 120, "category": "physical"}
  ],
  "boosts": {},
  "types": ["steel", "flying"],
  "stats": {"hp": 334, "atk": 196, "def": 416, "spa": 104, "spd": 176, "spe": 262},
  "weaknesses": {"fire": 2, "electric": 2},
  "resistances": {"normal": 0.5, "grass": 0.25, "bug": 0.25},
  "immunities": ["ground", "poison"]
}
```

---

### `opponent`

Get information about the opponent's team (only revealed information).

**LLM Call**:
```json
{"name": "opponent", "arguments": {}}
{"name": "opponent", "arguments": {"pokemon": "Gengar"}}
{"name": "opponent", "arguments": {"full": true}}
```

**Human Command**:
```
opponent          # Active + fainted/unrevealed counts
opponent gengar   # Specific revealed Pokemon
opponent full     # All 6 slots (NOT_REVEALED for unseen)
```

**Returns** (summary):
```json
{
  "active": {
    "species": "Gengar",
    "hp_percent": 75.0,
    "status": null,
    "fainted": false,
    "moves": ["shadowball", "focusblast", "NOT_REVEALED", "NOT_REVEALED"],
    "ability": "Levitate",
    "item": "NOT_REVEALED",
    "types": ["ghost", "poison"]
  },
  "fainted_count": 1,
  "unrevealed_count": 3
}
```

Unknown information is marked as `"NOT_REVEALED"`.

---

### `log`

Get the battle log as structured events by turn.

**LLM Call**:
```json
{"name": "log", "arguments": {}}
{"name": "log", "arguments": {"turn": 3}}
{"name": "log", "arguments": {"from_turn": 2}}
```

**Human Command**:
```
log       # Full battle log
log 3     # Turn 3 only
```

**Returns**:
```json
{
  "turns": [
    {
      "turn": 0,
      "events": ["You sent out Tyranitar!", "Opponent sent out Gengar!"]
    },
    {
      "turn": 1,
      "events": [
        "Gengar used Shadow Ball!",
        "Tyranitar lost 24% HP!",
        "Tyranitar used Crunch!",
        "It's super effective!",
        "Gengar lost 65% HP!"
      ]
    }
  ],
  "current_turn": 2,
  "context": "normal"
}
```

Turn 0 contains initial switch-in events.

---

### `field`

Analyze current field conditions and their tactical implications.

**LLM Call**:
```json
{"name": "field", "arguments": {}}
```

**Human Command**:
```
field
```

**Returns**:
```json
{
  "weather": {
    "type": "sandstorm",
    "turns_remaining": 3,
    "effects": [
      "Rock types get +50% Sp. Def",
      "Non-Rock/Ground/Steel take 6.25% damage per turn"
    ]
  },
  "your_hazards": {"stealth_rock": true, "spikes": 2},
  "opponent_hazards": {"stealth_rock": true},
  "your_screens": {},
  "opponent_screens": {"reflect": 3},
  "terrain": null,
  "your_pokemon_grounded": true,
  "opponent_pokemon_grounded": false,
  "tactical_notes": [
    "Opponent takes Stealth Rock damage on switch",
    "Total switch damage to opponent: ~12.5%",
    "You take Stealth Rock damage on switch",
    "Grounded Pokemon take 16.67% from Spikes on switch",
    "Opponent's Reflect halves your physical damage"
  ]
}
```

---

### `type`

Get type matchup analysis for a type combination.

**LLM Call**:
```json
{"name": "type", "arguments": {"types": ["steel", "flying"]}}
```

**Human Command**:
```
type steel flying
```

**Returns**:
```json
{
  "defending_types": ["steel", "flying"],
  "weaknesses": {"fire": 2, "electric": 2},
  "resistances": {"normal": 0.5, "grass": 0.25, "flying": 0.5, "psychic": 0.5, "bug": 0.25, "steel": 0.5, "dragon": 0.5, "fairy": 0.5},
  "immunities": ["ground", "poison"]
}
```

---

### `pokedex`

Look up Pokemon species information.

**LLM Call**:
```json
{"name": "pokedex", "arguments": {"pokemon": "Tyranitar"}}
```

**Human Command**:
```
pokedex tyranitar
```

**Returns**:
```json
{
  "name": "Tyranitar",
  "types": ["rock", "dark"],
  "base_stats": {"hp": 100, "atk": 134, "def": 110, "spa": 95, "spd": 100, "spe": 61},
  "bst": 600,
  "abilities": ["Sand Stream"],
  "role_hints": ["Physical wallbreaker"],
  "weaknesses": {"fighting": 4, "water": 2, "grass": 2, "ground": 2, "bug": 2, "steel": 2, "fairy": 2},
  "resistances": {"normal": 0.5, "flying": 0.5, "poison": 0.5, "ghost": 0.5, "fire": 0.5, "dark": 0.5},
  "immunities": ["psychic"]
}
```

---

### `movedex`

Look up move details.

**LLM Call**:
```json
{"name": "movedex", "arguments": {"move": "earthquake"}}
```

**Human Command**:
```
movedex earthquake
```

**Returns**:
```json
{
  "name": "Earthquake",
  "type": "ground",
  "category": "physical",
  "base_power": 100,
  "accuracy": 100,
  "pp": 10,
  "priority": 0,
  "makes_contact": false,
  "description": "High power"
}
```

---

### `state`

Get the full battle state (same as shown in turn prompt).

**LLM Call**:
```json
{"name": "state", "arguments": {}}
```

**Human Command**:
```
state
```

Returns the same structured state dict that's formatted into the turn prompt.

---

### `help`

Get tool documentation.

**LLM Call**:
```json
{"name": "help", "arguments": {}}
{"name": "help", "arguments": {"tool": "damage"}}
```

**Human Command**:
```
help
help damage
```

---

## Adding New Tools

1. **Create handler module** in `src/tools/` (e.g., `weather_tools.py`)
2. **Implement handler function** that takes `(battle, args, context) -> dict`
3. **Register in `registry.py`**:

```python
from . import weather_tools

def _handle_weather(battle: AbstractBattle, args: dict, context: dict) -> dict:
    return weather_tools.get_weather_details(battle)

TOOLS["weather"] = Tool(
    name="weather",
    description="Get detailed weather information and effects",
    handler=_handle_weather,
    params=[],  # No parameters
)
```

4. **Add to help categories** in `get_help_text()` if desired

## Tool Design Principles

1. **Return structured data**: Tools return dicts, not prose. The LLM reasons from data.
2. **Mark unknowns explicitly**: Use `"NOT_REVEALED"` rather than omitting or guessing.
3. **Include tactical context**: Add notes like "is_stab", "weaknesses" where helpful.
4. **Respect the fog of war**: Only return information the player would actually know.
5. **Handle errors gracefully**: Return `{"error": "message"}` on failure.

## Context System

Some tools need access to persistent state (like the battle plan). This is passed via the `context` dict:

```python
context = {"battle_plan": {...}}
result = execute_tool("plan", args, battle, context)
```

Tools that need context set `needs_context=True` in their definition.
