# LLM Pokemon Battle Arena - poke-env Implementation Plan

## Overview

A simpler alternative to the MCP-based plan. Uses [poke-env](https://github.com/hsahovic/poke-env) as the foundation, which handles all Pokemon Showdown integration. You just plug in LLM API calls.

**Goal**: Have multiple LLM models battle each other in Pokemon matches and record the results.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Battle format | Gen 4 OU (DPP) | Curated Smogon DPP OU teams ready in `Raw-Teams/` |
| Team selection | Random from pool | Tests pure battle skill, not team-building |
| Lead Pokemon | First in team file | No team preview; first Pokemon listed is the lead |
| Turn timeout | 30 seconds (configurable) | Balance between thinking time and game flow |
| Hosting | Local Mac Studio | Zero cost, easy iteration during development |

## Important Notes

- **poke-env API**: Battle attributes like `weather`, `fields`, `side_conditions` return `Dict[Enum, int]`, not single values. The code iterates over `.keys()` to get the active conditions.
- **Forced switches**: When a Pokemon faints, `battle.force_switch` is a list (for doubles compatibility). Use `any(battle.force_switch)` to check.
- **Async LLM calls**: Uses `litellm.acompletion()` (async) to avoid blocking the event loop during API calls.
- **Server config**: poke-env defaults to `LocalhostServerConfiguration` (`ws://localhost:8000/showdown/websocket`).
- **Gen 4 support**: poke-env was developed primarily for recent generations. If you find Gen 4-specific bugs, report them to the poke-env repo.

## Key Differences from MCP Plan

| Aspect | MCP Plan | poke-env Plan |
|--------|----------|---------------|
| Complexity | High - custom WebSocket server, protocol, state parser | Low - poke-env handles everything |
| Multi-model support | Claude only (or needs LangGraph) | Any LLM via LiteLLM |
| Lines of code | ~2000+ | ~200 |
| Setup time | Hours | Minutes |
| Flexibility | Full control | Constrained to poke-env's interface |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│              Local Pokemon Showdown Server                      │
│                   (localhost:8000)                              │
│                                                                 │
│   - Handles battle simulation                                   │
│   - Web UI for watching battles                                 │
│   - All Pokemon mechanics built-in                              │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                          poke-env library
                      (handles PS protocol)
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
         ▼                      ▼                      ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ LLMPlayer       │  │ LLMPlayer       │  │ LLMPlayer       │
│ (GPT-4o)        │  │ (Claude)        │  │ (Gemini)        │
│                 │  │                 │  │                 │
│ choose_move():  │  │ choose_move():  │  │ choose_move():  │
│  → format state │  │  → format state │  │  → format state │
│  → call LLM API │  │  → call LLM API │  │  → call LLM API │
│  → parse action │  │  → parse action │  │  → parse action │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                      │                      │
         ▼                      ▼                      ▼
    OpenAI API           Anthropic API          Google API
```

## Project Structure

```
llm-pokemon-arena/
├── README.md
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── llm_player.py          # LLMPlayer class
│   ├── team_pool.py           # Load teams from Raw-Teams/
│   ├── state_formatter.py     # Battle state → text
│   ├── response_parser.py     # LLM response → action
│   ├── tournament.py          # Run tournaments
│   └── results.py             # Track and display results
├── config/
│   └── models.yaml            # LLM model configurations
├── results/
│   ├── battles.db             # SQLite results database
│   └── replays/               # Battle replay files
├── Raw-Teams/                 # Curated DPP OU teams (Showdown paste format)
│   ├── Mixed-Jirachi-Gengar-Offense.md
│   ├── Forretress-Zapdos-Balance.md
│   ├── Mixed-Flygon-Spikes-Stack.md
│   ├── Quagsire-Scarf-Tyranitar-Stall.md
│   ├── Roserade-SubCM-Suicune-Balance.md
│   └── Dragonite-Lead-Boom-Offense.md
└── scripts/
    ├── run_tournament.py      # Main entry point
    └── setup_showdown.sh      # Install Pokemon Showdown
```

---

## Phase 1: Environment Setup

### 1.1 Install Pokemon Showdown Server

```bash
#!/bin/bash
# scripts/setup_showdown.sh

# Clone Pokemon Showdown
git clone https://github.com/smogon/pokemon-showdown.git
cd pokemon-showdown

# Install dependencies
npm install

# Copy config (required)
cp config/config-example.js config/config.js

# Start server (run in background or separate terminal)
# --no-security disables rate limiting and authentication (required for bot training)
node pokemon-showdown start --no-security
```

The server runs at `localhost:8000`. You can open this in a browser to watch battles.

**Note:** poke-env uses `LocalhostServerConfiguration` by default, which connects to `ws://localhost:8000/showdown/websocket`. No additional configuration needed for local play.

### 1.2 Python Dependencies

```txt
# requirements.txt
poke-env>=0.7.0
litellm>=1.0.0
pyyaml>=6.0
aiosqlite>=0.19.0
rich>=13.0.0  # Pretty terminal output
```

```bash
pip install -r requirements.txt
```

### 1.3 API Keys

Set environment variables for each provider you want to test:

```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="..."
export XAI_API_KEY="..."
# LiteLLM reads these automatically
```

---

## Phase 2: Core Implementation

### 2.1 State Formatter (`src/state_formatter.py`)

Converts poke-env's Battle object into a text description for the LLM.

```python
"""Format battle state for LLM consumption."""

from poke_env.environment import Battle, Pokemon, Move


def format_pokemon(pokemon: Pokemon, full_info: bool = False) -> str:
    """Format a single Pokemon's information."""
    lines = []

    # Basic info
    hp_pct = pokemon.current_hp_fraction * 100
    status = f" [{pokemon.status.name}]" if pokemon.status else ""
    lines.append(f"{pokemon.species} ({hp_pct:.0f}% HP){status}")

    if full_info:
        # Types
        types = "/".join(t.name for t in pokemon.types if t)
        lines.append(f"  Type: {types}")

        # Stats (if known)
        if pokemon.stats:
            lines.append(f"  Stats: {pokemon.stats}")

        # Ability
        if pokemon.ability:
            lines.append(f"  Ability: {pokemon.ability}")

        # Item
        if pokemon.item:
            lines.append(f"  Item: {pokemon.item}")

        # Moves (for your own Pokemon)
        if pokemon.moves:
            move_strs = []
            for move in pokemon.moves.values():
                move_strs.append(f"{move.id} ({move.type.name}, {move.base_power} BP)")
            lines.append(f"  Moves: {', '.join(move_strs)}")

    return "\n".join(lines)


def format_move(move: Move) -> str:
    """Format a move option."""
    pp_str = f"{move.current_pp}/{move.max_pp} PP" if move.current_pp is not None else ""
    return f"{move.id} ({move.type.name}, {move.base_power} BP) {pp_str}".strip()


def format_battle_state(battle: Battle) -> str:
    """
    Format the complete battle state for an LLM.

    Returns a human-readable text description of:
    - Turn number
    - Your active Pokemon and available moves
    - Opponent's active Pokemon
    - Your bench
    - Known opponent Pokemon
    - Field conditions
    """
    lines = []

    # Header
    lines.append(f"=== Turn {battle.turn} ===")
    lines.append("")

    # Check for forced switch (Pokemon fainted)
    # force_switch is a list (for doubles compatibility), check with any()
    is_forced_switch = any(battle.force_switch) if battle.force_switch else False
    if is_forced_switch:
        lines.append("*** YOUR POKEMON FAINTED - YOU MUST SWITCH ***")
        lines.append("")

    # Your active Pokemon
    if battle.active_pokemon and not battle.active_pokemon.fainted:
        lines.append("YOUR ACTIVE POKEMON:")
        lines.append(format_pokemon(battle.active_pokemon, full_info=True))
        lines.append("")

    # Available moves (only if not forced to switch)
    if battle.available_moves and not is_forced_switch:
        lines.append("AVAILABLE MOVES:")
        for move in battle.available_moves:
            lines.append(f"  - {format_move(move)}")
        lines.append("")

    # Available switches
    if battle.available_switches:
        lines.append("AVAILABLE SWITCHES:")
        for pokemon in battle.available_switches:
            lines.append(f"  - {format_pokemon(pokemon)}")
        lines.append("")

    # Opponent's active Pokemon (may be None at battle start)
    if battle.opponent_active_pokemon:
        lines.append("OPPONENT'S ACTIVE POKEMON:")
        lines.append(format_pokemon(battle.opponent_active_pokemon))

        # Known moves
        if battle.opponent_active_pokemon.moves:
            known_moves = list(battle.opponent_active_pokemon.moves.keys())
            lines.append(f"  Known moves: {', '.join(known_moves)}")
        lines.append("")

    # Your bench (excluding fainted)
    bench = [p for p in battle.team.values()
             if p != battle.active_pokemon and not p.fainted]
    if bench:
        lines.append("YOUR BENCH:")
        for pokemon in bench:
            lines.append(f"  - {format_pokemon(pokemon)}")
        lines.append("")

    # Known opponent Pokemon
    if battle.opponent_team:
        opp_pokemon = [p for p in battle.opponent_team.values()
                       if p != battle.opponent_active_pokemon]
        if opp_pokemon:
            lines.append("KNOWN OPPONENT POKEMON:")
            for pokemon in opp_pokemon:
                lines.append(f"  - {format_pokemon(pokemon)}")
            lines.append("")

    # Field conditions
    # Note: weather, fields, side_conditions are Dict[Enum, int] not single values
    field_conditions = []
    if battle.weather:
        weather_names = [w.name for w in battle.weather.keys()]
        field_conditions.append(f"Weather: {', '.join(weather_names)}")
    if battle.fields:
        field_names = [f.name for f in battle.fields.keys()]
        field_conditions.append(f"Terrain: {', '.join(field_names)}")

    # Side conditions (hazards, screens, etc.)
    if battle.side_conditions:
        sc_names = [sc.name for sc in battle.side_conditions.keys()]
        field_conditions.append(f"Your side: {', '.join(sc_names)}")
    if battle.opponent_side_conditions:
        osc_names = [sc.name for sc in battle.opponent_side_conditions.keys()]
        field_conditions.append(f"Opponent side: {', '.join(osc_names)}")

    if field_conditions:
        lines.append("FIELD CONDITIONS:")
        for condition in field_conditions:
            lines.append(f"  {condition}")
        lines.append("")

    return "\n".join(lines)
```

### 2.2 Response Parser (`src/response_parser.py`)

Extracts the chosen action from the LLM's response.

```python
"""Parse LLM responses into battle actions."""

import re
from poke_env.environment import Battle, Move, Pokemon
from typing import Union, Optional


def parse_llm_response(
    response: str,
    battle: Battle
) -> Optional[Union[Move, Pokemon]]:
    """
    Parse an LLM's response to extract the chosen action.

    Handles various response formats:
    - "move earthquake"
    - "I'll use Earthquake"
    - "switch to Gengar"
    - "Gengar, I choose you!"

    Returns:
        Move or Pokemon object, or None if parsing failed.
    """
    response = response.lower().strip()

    # Try to find explicit action format first
    # Pattern: "move <name>" or "use <name>"
    move_match = re.search(r'\b(?:move|use|attack with)\s+([a-z]+(?:\s+[a-z]+)?)', response)
    if move_match:
        move_name = move_match.group(1).replace(" ", "")
        move = find_move(move_name, battle.available_moves)
        if move:
            return move

    # Pattern: "switch <name>" or "switch to <name>" or "go <name>"
    switch_match = re.search(r'\b(?:switch(?:\s+to)?|go|send out)\s+([a-z]+)', response)
    if switch_match:
        pokemon_name = switch_match.group(1)
        pokemon = find_pokemon(pokemon_name, battle.available_switches)
        if pokemon:
            return pokemon

    # Fallback: look for any move name mentioned
    for move in battle.available_moves:
        if move.id.lower() in response:
            return move

    # Fallback: look for any Pokemon name mentioned
    for pokemon in battle.available_switches:
        if pokemon.species.lower() in response:
            return pokemon

    return None


def find_move(name: str, available_moves: list[Move]) -> Optional[Move]:
    """Find a move by name (fuzzy match)."""
    name = name.lower().replace(" ", "").replace("-", "")
    for move in available_moves:
        move_id = move.id.lower().replace("-", "")
        if move_id == name or move_id.startswith(name):
            return move
    return None


def find_pokemon(name: str, available_switches: list[Pokemon]) -> Optional[Pokemon]:
    """Find a Pokemon by name (fuzzy match)."""
    name = name.lower().replace(" ", "").replace("-", "")
    for pokemon in available_switches:
        species = pokemon.species.lower().replace("-", "")
        if species == name or species.startswith(name):
            return pokemon
    return None
```

### 2.3 Team Pool (`src/team_pool.py`)

Load teams from the `Raw-Teams/` directory. Each player gets a random team per battle.

```python
"""Load and manage the team pool from Raw-Teams/ directory."""

import random
from pathlib import Path
from poke_env.teambuilder import Teambuilder


class TeamPool(Teambuilder):
    """
    Loads teams from markdown files in Showdown paste format.

    Each battle, a random team is selected from the pool.
    Both players draw from the same pool (may get the same team).
    The first Pokemon in each team file is the lead.
    """

    def __init__(self, teams_dir: str = "Raw-Teams"):
        """
        Load all teams from the specified directory.

        Args:
            teams_dir: Path to directory containing .md files with teams
        """
        super().__init__()  # Initialize base Teambuilder
        self.teams_dir = Path(teams_dir)
        self.teams: list[str] = []  # Packed team strings
        self.team_names: list[str] = []  # For logging
        self._load_teams()

    def _load_teams(self) -> None:
        """Load all .md files from the teams directory."""
        if not self.teams_dir.exists():
            raise FileNotFoundError(f"Teams directory not found: {self.teams_dir}")

        team_files = list(self.teams_dir.glob("*.md"))
        if not team_files:
            raise ValueError(f"No .md team files found in {self.teams_dir}")

        for team_file in team_files:
            paste = team_file.read_text()
            # poke-env's Teambuilder can parse Showdown paste format
            packed = self.join_team(self.parse_showdown_team(paste))
            self.teams.append(packed)
            self.team_names.append(team_file.stem)

        print(f"Loaded {len(self.teams)} teams: {', '.join(self.team_names)}")

    def yield_team(self) -> str:
        """Return a random team from the pool (called by poke-env)."""
        idx = random.randint(0, len(self.teams) - 1)
        return self.teams[idx]

    def get_team_count(self) -> int:
        """Return number of teams in the pool."""
        return len(self.teams)


# Singleton instance for convenience
_default_pool: TeamPool | None = None


def get_team_pool(teams_dir: str = "Raw-Teams") -> TeamPool:
    """Get or create the default team pool."""
    global _default_pool
    if _default_pool is None:
        _default_pool = TeamPool(teams_dir)
    return _default_pool
```

### 2.4 LLM Player (`src/llm_player.py`)

The main player class that integrates poke-env with any LLM.

```python
"""LLM-powered Pokemon battle player."""

from typing import Optional
from poke_env.player import Player
from poke_env.environment import Battle, AbstractBattle
import litellm

from .state_formatter import format_battle_state
from .response_parser import parse_llm_response


# System prompt for the LLM
SYSTEM_PROMPT = """You are playing a competitive Pokemon battle (Gen 4 OU format). Your goal is to win by knocking out all of your opponent's Pokemon.

Each turn, you will receive the current battle state and must choose an action:
- Use a move: "move <move_name>"
- Switch Pokemon: "switch <pokemon_name>"

Consider:
- Type matchups and effectiveness
- Your Pokemon's HP and status
- The opponent's likely moves
- Entry hazards and field conditions
- When to switch vs when to attack

Respond with ONLY your chosen action in the format above. Be decisive."""


class LLMPlayer(Player):
    """
    A Pokemon battle player powered by an LLM.

    Uses LiteLLM for multi-provider support. Compatible with:
    - OpenAI (gpt-4o, gpt-4-turbo, etc.)
    - Anthropic (claude-3-opus, claude-sonnet-4-20250514, etc.)
    - Google (gemini/gemini-pro, gemini/gemini-1.5-flash, etc.)
    - xAI (xai/grok-2, etc.)
    - Local models via Ollama (ollama/llama3, etc.)
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 150,
        timeout: float = 30.0,
        system_prompt: str = SYSTEM_PROMPT,
        **kwargs
    ):
        """
        Initialize an LLM player.

        Args:
            model: LiteLLM model identifier (e.g., "gpt-4o", "claude-sonnet-4-20250514")
            temperature: Sampling temperature for the LLM
            max_tokens: Maximum tokens in response
            timeout: API call timeout in seconds
            system_prompt: Custom system prompt (optional)
            **kwargs: Additional arguments passed to poke_env.Player
        """
        super().__init__(**kwargs)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.system_prompt = system_prompt

        # Track battle history for context
        self.battle_history: dict[str, list[dict]] = {}

    async def choose_move(self, battle: AbstractBattle) -> str:
        """
        Choose a move for the current turn (async).

        This is called by poke-env each turn. We:
        1. Format the battle state
        2. Call the LLM (async)
        3. Parse the response
        4. Return a valid order
        """
        # Format current state
        state_text = format_battle_state(battle)

        # Build messages
        messages = [
            {"role": "system", "content": self.system_prompt},
        ]

        # Add battle history for context
        battle_id = battle.battle_tag
        if battle_id not in self.battle_history:
            self.battle_history[battle_id] = []

        # Include last few turns of history
        history = self.battle_history[battle_id][-6:]  # Last 3 turns (state + response each)
        for msg in history:
            messages.append(msg)

        # Add current state
        messages.append({"role": "user", "content": state_text})

        # Call LLM (async to not block the event loop)
        try:
            response = await litellm.acompletion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.timeout,
            )
            response_text = response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[{self.username}] LLM error: {e}")
            return self.choose_random_move(battle)

        # Save to history
        self.battle_history[battle_id].append({"role": "user", "content": state_text})
        self.battle_history[battle_id].append({"role": "assistant", "content": response_text})

        # Parse response
        action = parse_llm_response(response_text, battle)

        if action:
            return self.create_order(action)
        else:
            print(f"[{self.username}] Could not parse response: {response_text}")
            return self.choose_random_move(battle)

    def battle_finished_callback(self, battle: AbstractBattle) -> None:
        """Called when a battle ends. Clean up history."""
        battle_id = battle.battle_tag
        if battle_id in self.battle_history:
            del self.battle_history[battle_id]


class LLMPlayerWithTools(LLMPlayer):
    """
    Extended LLM player that can use tools (web search, calculators, etc.)

    This version allows the LLM to request additional information before
    making a decision. Useful for testing tool-use capabilities.
    """

    # TODO: Implement tool-calling loop
    # - Define available tools (type chart lookup, damage calc, Smogon search)
    # - Allow LLM to call tools before deciding
    # - Set a max tool-call limit per turn
    pass
```

### 2.5 Tournament Runner (`src/tournament.py`)

Run battles between multiple LLM players.

```python
"""Tournament management for LLM battles."""

import asyncio
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from poke_env.player import cross_evaluate  # Note: imported from player module

from .llm_player import LLMPlayer
from .team_pool import get_team_pool
from .results import ResultsDB


@dataclass
class TournamentConfig:
    """Configuration for a tournament."""
    name: str
    format: str = "gen4ou"
    n_battles: int = 10  # Battles per matchup
    save_replays: bool = True
    replay_dir: str = "results/replays"
    teams_dir: str = "Raw-Teams"  # Directory containing team files


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""
    name: str           # Display name
    model: str          # LiteLLM model ID
    temperature: float = 0.7
    max_tokens: int = 150


def create_players(
    models: list[ModelConfig],
    battle_format: str,
    teams_dir: str = "Raw-Teams",
    save_replays: bool = False,
    replay_dir: str = "replays"
) -> list[LLMPlayer]:
    """Create LLMPlayer instances for each model."""
    # Load the team pool (shared by all players)
    team_pool = get_team_pool(teams_dir)

    players = []
    for config in models:
        player = LLMPlayer(
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            username=config.name,
            battle_format=battle_format,
            team=team_pool,  # Each player draws random teams from the pool
            save_replays=save_replays,
        )
        players.append(player)
    return players


async def run_tournament(
    config: TournamentConfig,
    models: list[ModelConfig],
    results_db: Optional[ResultsDB] = None
) -> dict:
    """
    Run a round-robin tournament between all models.

    Args:
        config: Tournament configuration
        models: List of model configurations
        results_db: Optional database for persisting results

    Returns:
        Dictionary with win rates for each matchup
    """
    print(f"\n{'='*60}")
    print(f"Tournament: {config.name}")
    print(f"Format: {config.format}")
    print(f"Battles per matchup: {config.n_battles}")
    print(f"Models: {[m.name for m in models]}")
    print(f"{'='*60}\n")

    # Create players
    players = create_players(
        models=models,
        battle_format=config.format,
        teams_dir=config.teams_dir,
        save_replays=config.save_replays,
        replay_dir=config.replay_dir
    )

    # Run cross-evaluation
    # This runs all pairwise matchups
    start_time = datetime.now()

    results = await cross_evaluate(players, n_battles=config.n_battles)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Process results
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}\n")

    # Print win rate matrix
    model_names = [m.name for m in models]
    print(f"{'':15}", end="")
    for name in model_names:
        print(f"{name:15}", end="")
    print()

    for i, p1 in enumerate(players):
        print(f"{model_names[i]:15}", end="")
        for j, p2 in enumerate(players):
            if i == j:
                print(f"{'---':15}", end="")
            else:
                win_rate = results[p1.username][p2.username]
                print(f"{win_rate*100:5.1f}%{'':<9}", end="")
        print()

    print(f"\nTotal time: {duration:.1f}s")

    # Calculate overall rankings
    rankings = []
    for i, player in enumerate(players):
        wins = sum(
            results[player.username][opp.username] * config.n_battles
            for j, opp in enumerate(players) if i != j
        )
        total = (len(players) - 1) * config.n_battles
        rankings.append((model_names[i], wins, total))

    rankings.sort(key=lambda x: x[1], reverse=True)

    print("\nOVERALL RANKINGS:")
    for rank, (name, wins, total) in enumerate(rankings, 1):
        print(f"  {rank}. {name}: {wins:.0f}/{total} ({wins/total*100:.1f}%)")

    # Save to database if provided
    if results_db:
        await results_db.save_tournament(config, models, results)

    return results


async def run_single_battle(
    player1: LLMPlayer,
    player2: LLMPlayer,
    n_battles: int = 1
) -> dict:
    """
    Run battles between two specific players.

    Returns dict with win counts.
    """
    await player1.battle_against(player2, n_battles=n_battles)

    return {
        player1.username: player1.n_won_battles,
        player2.username: player2.n_won_battles,
    }
```

### 2.6 Results Storage (`src/results.py`)

Persist tournament results to SQLite.

```python
"""Results tracking and persistence."""

import aiosqlite
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import json


class ResultsDB:
    """SQLite database for tournament results."""

    def __init__(self, db_path: str = "results/battles.db"):
        self.db_path = db_path

    async def initialize(self):
        """Create tables if they don't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS tournaments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    format TEXT NOT NULL,
                    n_battles INTEGER NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    results_json TEXT
                );

                CREATE TABLE IF NOT EXISTS models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    model_id TEXT NOT NULL,
                    first_seen TIMESTAMP NOT NULL
                );

                CREATE TABLE IF NOT EXISTS elo_ratings (
                    model_id INTEGER NOT NULL,
                    format TEXT NOT NULL,
                    elo INTEGER DEFAULT 1500,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    last_updated TIMESTAMP,
                    PRIMARY KEY (model_id, format),
                    FOREIGN KEY (model_id) REFERENCES models(id)
                );

                CREATE TABLE IF NOT EXISTS matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER,
                    format TEXT NOT NULL,
                    player1_model TEXT NOT NULL,
                    player2_model TEXT NOT NULL,
                    winner_model TEXT,
                    played_at TIMESTAMP NOT NULL,
                    replay_file TEXT,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
                );
            """)
            await db.commit()

    async def save_tournament(self, config, models, results):
        """Save tournament results."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO tournaments (name, format, n_battles, started_at, completed_at, results_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (config.name, config.format, config.n_battles,
                 datetime.now(), datetime.now(), json.dumps(results))
            )
            await db.commit()

    async def get_leaderboard(self, format: str = "gen4ou", limit: int = 20):
        """Get Elo leaderboard for a format."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT m.name, e.elo, e.wins, e.losses
                   FROM elo_ratings e
                   JOIN models m ON e.model_id = m.id
                   WHERE e.format = ?
                   ORDER BY e.elo DESC
                   LIMIT ?""",
                (format, limit)
            )
            return await cursor.fetchall()

    async def update_elo(self, winner: str, loser: str, format: str):
        """Update Elo ratings after a match."""
        K = 32  # K-factor

        async with aiosqlite.connect(self.db_path) as db:
            # Get current ratings
            cursor = await db.execute(
                """SELECT m.name, COALESCE(e.elo, 1500) as elo
                   FROM models m
                   LEFT JOIN elo_ratings e ON m.id = e.model_id AND e.format = ?
                   WHERE m.name IN (?, ?)""",
                (format, winner, loser)
            )
            ratings = {row[0]: row[1] for row in await cursor.fetchall()}

            winner_elo = ratings.get(winner, 1500)
            loser_elo = ratings.get(loser, 1500)

            # Calculate new ratings
            expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
            expected_loser = 1 - expected_winner

            new_winner_elo = round(winner_elo + K * (1 - expected_winner))
            new_loser_elo = round(loser_elo + K * (0 - expected_loser))

            # Update (upsert)
            await db.execute(
                """INSERT INTO elo_ratings (model_id, format, elo, wins, last_updated)
                   SELECT id, ?, ?, 1, ?
                   FROM models WHERE name = ?
                   ON CONFLICT(model_id, format) DO UPDATE SET
                   elo = ?, wins = wins + 1, last_updated = ?""",
                (format, new_winner_elo, datetime.now(), winner,
                 new_winner_elo, datetime.now())
            )
            await db.execute(
                """INSERT INTO elo_ratings (model_id, format, elo, losses, last_updated)
                   SELECT id, ?, ?, 1, ?
                   FROM models WHERE name = ?
                   ON CONFLICT(model_id, format) DO UPDATE SET
                   elo = ?, losses = losses + 1, last_updated = ?""",
                (format, new_loser_elo, datetime.now(), loser,
                 new_loser_elo, datetime.now())
            )
            await db.commit()
```

### 2.7 Main Entry Point (`scripts/run_tournament.py`)

```python
#!/usr/bin/env python3
"""Run an LLM Pokemon tournament."""

import asyncio
import argparse
import yaml
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tournament import run_tournament, TournamentConfig, ModelConfig
from src.results import ResultsDB


# Default models to test
DEFAULT_MODELS = [
    ModelConfig(name="GPT-4o", model="gpt-4o"),
    ModelConfig(name="Claude-Sonnet", model="claude-sonnet-4-20250514"),
    ModelConfig(name="Gemini-Flash", model="gemini/gemini-2.0-flash"),
    ModelConfig(name="Grok-2", model="xai/grok-2"),
]


def load_models_from_yaml(path: str) -> list[ModelConfig]:
    """Load model configurations from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    return [ModelConfig(**m) for m in data["models"]]


async def main():
    parser = argparse.ArgumentParser(description="Run LLM Pokemon Tournament")
    parser.add_argument("--name", default="LLM Battle Tournament", help="Tournament name")
    parser.add_argument("--format", default="gen4ou", help="Battle format")
    parser.add_argument("--battles", type=int, default=10, help="Battles per matchup")
    parser.add_argument("--models", help="Path to models YAML config")
    parser.add_argument("--teams-dir", default="Raw-Teams", help="Directory containing team files")
    parser.add_argument("--no-replays", action="store_true", help="Don't save replays")
    parser.add_argument("--db", default="results/battles.db", help="Results database path")

    args = parser.parse_args()

    # Load models
    if args.models:
        models = load_models_from_yaml(args.models)
    else:
        models = DEFAULT_MODELS

    # Initialize database
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    db = ResultsDB(args.db)
    await db.initialize()

    # Create tournament config
    config = TournamentConfig(
        name=args.name,
        format=args.format,
        n_battles=args.battles,
        teams_dir=args.teams_dir,
        save_replays=not args.no_replays,
    )

    # Run tournament
    results = await run_tournament(config, models, db)

    print("\nTournament complete!")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Phase 3: Configuration

### 3.1 Models Configuration (`config/models.yaml`)

```yaml
# Model configurations for tournament

models:
  # OpenAI
  - name: "GPT-4o"
    model: "gpt-4o"
    temperature: 0.7

  - name: "GPT-4-Turbo"
    model: "gpt-4-turbo"
    temperature: 0.7

  - name: "GPT-4o-Mini"
    model: "gpt-4o-mini"
    temperature: 0.7

  # Anthropic
  - name: "Claude-Opus"
    model: "claude-opus-4-20250514"
    temperature: 0.7

  - name: "Claude-Sonnet"
    model: "claude-sonnet-4-20250514"
    temperature: 0.7

  - name: "Claude-Haiku"
    model: "claude-3-5-haiku-20241022"
    temperature: 0.7

  # Google
  - name: "Gemini-Pro"
    model: "gemini/gemini-1.5-pro"
    temperature: 0.7

  - name: "Gemini-Flash"
    model: "gemini/gemini-2.0-flash"
    temperature: 0.7

  # xAI
  - name: "Grok-2"
    model: "xai/grok-2"
    temperature: 0.7

  # Meta (via various providers)
  - name: "Llama-3-70B"
    model: "together_ai/meta-llama/Llama-3-70b-chat-hf"
    temperature: 0.7

  # Local (Ollama)
  - name: "Llama-3-Local"
    model: "ollama/llama3"
    temperature: 0.7
```

---

## Phase 4: Running Tournaments

### Quick Start

```bash
# Terminal 1: Start Pokemon Showdown server
cd pokemon-showdown
node pokemon-showdown start --no-security

# Terminal 2: Run tournament
cd llm-pokemon-arena
python scripts/run_tournament.py --battles 5
```

### Watch Battles Live

Open `http://localhost:8000` in your browser while the tournament runs.

### Custom Tournament

```bash
# Run with specific models
python scripts/run_tournament.py \
    --name "Claude vs GPT" \
    --models config/models.yaml \
    --format gen4ou \
    --battles 20

# Quick test with fewer battles
python scripts/run_tournament.py --battles 3
```

### View Results

```python
# Quick script to view leaderboard
import asyncio
from src.results import ResultsDB

async def show_leaderboard():
    db = ResultsDB()
    await db.initialize()
    leaders = await db.get_leaderboard("gen4ou")
    for rank, (name, elo, wins, losses) in enumerate(leaders, 1):
        print(f"{rank}. {name}: {elo} Elo ({wins}W/{losses}L)")

asyncio.run(show_leaderboard())
```

---

## Optional Enhancements

### A. Tool-Enabled Players

Let LLMs use tools for research:

```python
TOOLS = [
    {
        "name": "lookup_type_matchup",
        "description": "Get type effectiveness for an attacking type vs defending types",
        "parameters": {"attacking": "str", "defending": "list[str]"}
    },
    {
        "name": "search_smogon",
        "description": "Search Smogon for Pokemon strategy info",
        "parameters": {"query": "str"}
    },
]

# In LLMPlayer.choose_move():
# 1. Call LLM with tools available
# 2. Execute any tool calls
# 3. Return final decision
```

### B. Streaming Battle Commentary

```python
from rich.live import Live
from rich.table import Table

async def stream_battle(player1, player2):
    with Live(auto_refresh=True) as live:
        async for event in battle_events:
            table = format_battle_table(event)
            live.update(table)
```

---

## Comparison: This Plan vs MCP Plan

| Feature | poke-env Plan | MCP Plan |
|---------|---------------|----------|
| Setup complexity | Low | High |
| Multi-model support | Native (LiteLLM) | Requires LangGraph |
| Battle simulation | poke-env handles | Custom BattleRunner |
| Teams | Random from Raw-Teams/ pool | Random from Raw-Teams/ pool |
| State formatting | ~100 lines | ~200 lines |
| Tool use for LLMs | Optional add-on | Built-in via MCP |
| Live battle viewing | Built-in (localhost:8000) | Not included |
| Replays | Built-in | Manual implementation |
| Elo tracking | Simple add-on | Full implementation |
| Total code | ~500 lines | ~2000 lines |

**Recommendation**: Start with poke-env plan for quick results. Add MCP layer later if you want Claude Code integration for interactive play.
