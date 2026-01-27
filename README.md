# LLM Pokemon Battle Arena

A competitive Pokemon battle arena where LLM models battle each other using the [poke-env](https://github.com/hsahovic/poke-env) library and [Pokemon Showdown](https://github.com/smogon/pokemon-showdown) simulator.

## Overview

This project pits different LLM models (Claude, GPT, Gemini, etc.) against each other in Pokemon battles and tracks their performance. Each LLM acts as a strategic player, receiving battle state information and making move/switch decisions.

**Key Features**:
- **Tool-calling architecture**: LLMs have access to strategic tools (damage calculation, type effectiveness, speed comparison, etc.) for informed decision-making
- **Comprehensive logging**: Every turn captures the LLM's reasoning, tool calls, predictions, and actions
- **Multi-model support**: Battle any LLM against any other via LiteLLM's unified API
- **Human testing mode**: Play as a human with the exact same interface the LLM sees
- **Automatic fallback**: Missing API keys → heuristic/random bot (no errors!)
- **Gen 4 OU format**: Curated teams from the DPP OU metagame

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│   LLM Provider  │◄────│   LLMPlayer      │◄────│  Pokemon Showdown   │
│  (via LiteLLM)  │     │  (tool-calling)  │     │      Server         │
└─────────────────┘     └──────────────────┘     └─────────────────────┘
                               │                          │
                               ▼                          ▼
                        ┌──────────────┐          ┌──────────────┐
                        │   Tools      │          │   poke-env   │
                        │  (registry)  │          │  (protocol)  │
                        └──────────────┘          └──────────────┘
```

### How poke-env Works

[poke-env](https://poke-env.readthedocs.io/) is a Python library that abstracts Pokémon Showdown's websocket protocol:

1. **Websocket Connection**: poke-env manages real-time communication with the Showdown server
2. **Battle State Parsing**: Incoming messages are parsed into structured `Battle` objects with `Pokemon`, `Move`, and field state data
3. **Player Interface**: You subclass `Player` and implement `choose_move(battle)` to return actions
4. **Action Execution**: poke-env translates your choice into Showdown protocol commands

This project builds on poke-env by:
- Adding an **LLMPlayer** that queries language models for decisions
- Providing **tools** that expose battle information in LLM-friendly formats
- Formatting battle state as **structured text** for the LLM prompt
- **Parsing** LLM responses back into valid game actions

### How Pokemon Showdown Works

[Pokemon Showdown](https://pokemonshowdown.com/) is an open-source battle simulator:

1. **Server-based battles**: All game logic runs server-side; clients send commands and receive updates
2. **Protocol**: Text-based protocol over websockets (e.g., `|move|p1a: Pikachu|Thunderbolt|p2a: Squirtle`)
3. **Formats**: Supports all generations and rulesets (this project uses Gen 4 OU)
4. **No-security mode**: Local servers can run with `--no-security` to allow bot connections without authentication

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Setup Pokemon Showdown Server

```bash
bash scripts/setup_showdown.sh
```

### 3. Start the Server

In a separate terminal:
```bash
cd pokemon-showdown && node pokemon-showdown start --no-security
```

The server will be available at http://localhost:8000

### 4. Configure API Keys

Set environment variables:
```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="..."
export XAI_API_KEY="..."
export DEEPSEEK_API_KEY="..."
```

Or create `env/.env`:
```bash
cp env/.env.example env/.env
# Edit env/.env with your API keys
```

### 5. Run Battles

```bash
# Quick 1v1 between two models
python scripts/llm_vs_llm.py --a Claude-Sonnet-4.5 --b GPT-5.1 --battles 5

# Benchmark against heuristic baseline
python scripts/benchmark_vs_heuristic.py --all --battles 10

# Run a round-robin tournament
python scripts/run_round_robin.py generate --models Claude-Sonnet-4.5 GPT-5.1 Gemini-3-Flash --games-per-pair 3
python scripts/run_round_robin.py run --manifest logs/{tournament}/manifest.json
NOTE: DOES NOT WORK, WHAT I AM TRYING TO FIX
```

## Project Structure

```
llm-arena/
├── src/                       # Core library
│   ├── llm_player.py          # LLM-powered battle player with tool-calling
│   ├── agent_player.py        # Base class for agents (shared state management)
│   ├── human_player.py        # Human-controlled player for testing
│   ├── state_formatter.py     # Battle state → structured text for LLM
│   ├── event_formatter.py     # Protocol events → readable descriptions
│   ├── response_parser.py     # LLM response → poke-env action
│   ├── tools/                 # Tool harness (see src/tools/README.md)
│   ├── tournament.py          # Tournament runner with cross_evaluate
│   ├── battle_logger.py       # Comprehensive JSONL logging
│   ├── config.py              # Model configuration loader
│   ├── player_factory.py      # Player creation with auto-fallback
│   ├── env_manager.py         # API key management
│   ├── team_pool.py           # Team loading from Raw-Teams/
│   └── results.py             # SQLite database for results
│
├── scripts/                   # Entry points (see scripts/README.md)
│   ├── llm_vs_llm.py          # 1v1 battles between LLMs
│   ├── benchmark_vs_heuristic.py  # Benchmark vs SimpleHeuristicsPlayer
│   ├── run_round_robin.py     # Manifest-based tournament runner
│   ├── human_vs_heuristic.py  # Play as human with tool access
│   └── setup_showdown.sh      # Server setup script
│
├── config/
│   └── models.yaml            # LLM model configurations
├── Raw-Teams/                 # Curated Gen 4 OU teams (Showdown format)
├── logs/                      # Battle logs and tournament data
├── pokemon-showdown/          # Showdown server (cloned by setup script)
└── tests/                     # Test suite
```

## LLM Player Architecture

### Tool-Calling Loop

The `LLMPlayer` uses a **subagent architecture**:

1. **Ephemeral context per turn**: Each decision starts fresh with battle state
2. **Tool loop**: LLM can call tools (damage, type, team info, etc.) up to N times
3. **Final answer**: LLM returns `ACTION:`, `REASONING:`, `PREDICTION:`, `CONFIDENCE:`
4. **Parsing**: Response is parsed and converted to a poke-env order

```python
# Simplified flow
async def choose_move(self, battle):
    state = format_battle_state(battle)
    
    # Tool-calling loop
    while tool_calls < max_tools:
        response = await llm.complete(messages, tools=TOOL_DEFINITIONS)
        if response.has_tool_calls:
            for tool in response.tool_calls:
                result = execute_tool(tool.name, tool.args, battle)
                messages.append(tool_result)
        else:
            # Final answer
            return parse_action(response.content, battle)
```

### Available Tools

| Tool | Description |
|------|-------------|
| `damage` | Calculate damage ranges for moves against current opponent |
| `team` | Get your team's HP, status, moves, and stats |
| `opponent` | Get revealed opponent information |
| `log` | Retrieve battle history by turn |
| `field` | Analyze weather, hazards, screens, terrain |
| `type` | Type effectiveness for any type combination |
| `pokedex` | Look up Pokemon base stats and abilities |
| `movedex` | Look up move details (power, accuracy, effects) |
| `help` | Get tool documentation |

See [src/tools/README.md](src/tools/README.md) for detailed tool documentation.

## Configuration

### Model Configuration (`config/models.yaml`)

```yaml
models:
  - name: "Claude-Sonnet-4.5"
    model: "claude-sonnet-4-5-20251101"  # LiteLLM model ID
    temperature: 0.7
    team: "Raw-Teams/Dragonite-Lead-Boom-Offense.md"  # Optional fixed team

  - name: "GPT-5.1"
    model: "gpt-5.1"
    temperature: 0.7
    max_tokens: 16384
    timeout: 180

  - name: "Heuristic-Baseline"
    model: "any"
    force_fallback: true  # Always use SimpleHeuristicsPlayer
```

### Supported LLM Providers

Via LiteLLM:
- **Anthropic**: Claude models
- **OpenAI**: GPT models  
- **Google**: Gemini models
- **xAI**: Grok models
- **DeepSeek**: DeepSeek models (including reasoning models)
- **Local**: Ollama, vLLM
- **Cloud**: Azure OpenAI, AWS Bedrock, Together AI, Groq, etc.

## Logging

Each battle logs to `logs/battles/{battle_id}/`:

- `{player_id}.jsonl` - Per-turn decisions with:
  - Raw LLM response
  - Tool calls and results
  - Parsed action, reasoning, prediction
  - Token usage and latency
- `protocol.jsonl` - Raw Showdown protocol events

Tournament logs go to `logs/{tournament_name}/`:
- `manifest.json` - Match schedule and results
- `match-XXXX/` - Per-match battle logs

## Testing & Development

```bash
# Run tests
pytest tests/

# Play as human to see the LLM interface
python scripts/human_vs_heuristic.py

# Watch battles in browser
open http://localhost:8000
```

## How Battles Work

1. **Team Selection**: Each player gets a team (fixed or random from pool)
2. **Battle Start**: poke-env connects both players to a Showdown battle
3. **Turn Loop**:
   - Showdown sends battle state update
   - poke-env parses into `Battle` object
   - `LLMPlayer.choose_move()` is called
   - LLM receives formatted state + tools
   - LLM reasons, calls tools, returns action
   - Response is parsed → poke-env order
   - Order sent to Showdown
4. **Battle End**: Winner determined, stats logged

## License

MIT
