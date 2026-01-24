# LLM Pokemon Battle Arena

A Pokemon battle arena where multiple LLM models compete against each other using the [poke-env](https://github.com/hsahovic/poke-env) library.

## Overview

This project allows you to run Pokemon battles between different LLM models (GPT-4, Claude, Gemini, etc.) and track their performance. The arena uses Pokemon Showdown for battle simulation and LiteLLM for unified API access to multiple LLM providers.

**Key Feature**: Models without API keys automatically fall back to random-move or heuristic bots, so you can run tournaments even without full API access.

## Features

- **Multi-model support**: Battle any LLM against any other via LiteLLM
- **Automatic fallback**: Missing API keys → random bot (no errors!)
- **Gen 4 OU format**: Curated teams from the DPP OU metagame
- **Tournament system**: Run round-robin tournaments with automatic result tracking
- **SQLite database**: Persist tournament results and Elo ratings
- **Live viewing**: Watch battles in real-time via Pokemon Showdown web UI
- **External bot support**: Integration guide for Technical Machine and other AI bots

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

The server will be available at http://localhost:8088

### 4. Configure API Keys (Optional)

Copy the example environment file and add your API keys:

```bash
cp env/.env.example env/.env
# Edit env/.env with your API keys
```

Or set environment variables directly:
```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="..."
export XAI_API_KEY="..."
```

**Note**: Models without API keys will automatically use random-move bots.

### 5. Run a Tournament

```bash
# Run with default models (missing keys use random bots)
python scripts/run_tournament.py --battles 5

# Use heuristic bots instead of random for fallback
python scripts/run_tournament.py --fallback heuristic --battles 5
```

## Project Structure

```
llm-arena/
├── src/
│   ├── __init__.py
│   ├── llm_player.py          # LLM-powered battle player
│   ├── player_factory.py      # Player creation with auto-fallback
│   ├── env_manager.py         # API key management
│   ├── team_pool.py           # Load teams from Raw-Teams/
│   ├── state_formatter.py     # Battle state → text for LLM
│   ├── response_parser.py     # LLM response → action
│   ├── tournament.py          # Tournament runner
│   └── results.py             # SQLite database
├── config/
│   └── models.yaml            # LLM model configurations
├── env/
│   └── .env.example           # Example environment file
├── results/
│   └── battles.db             # SQLite results database
├── Raw-Teams/                 # Curated DPP OU teams
├── scripts/
│   ├── run_tournament.py      # Main entry point
│   ├── setup_showdown.sh      # Pokemon Showdown setup
│   └── setup_technical_machine.sh  # Technical Machine AI setup
├── pokemon-showdown/          # Pokemon Showdown server (cloned)
└── requirements.txt
```

## Usage

### Run a Tournament

```bash
# Default: 4 models, 10 battles per matchup
python scripts/run_tournament.py

# Custom tournament
python scripts/run_tournament.py \
    --name "Claude vs GPT" \
    --models config/models.yaml \
    --format gen4ou \
    --battles 20

# Quick test with fewer battles
python scripts/run_tournament.py --battles 3

# Use custom env file
python scripts/run_tournament.py --env-file /path/to/.env --battles 5
```

### Configure Models

Edit `config/models.yaml` to customize which models compete:

```yaml
models:
  - name: "GPT-4o"
    model: "gpt-4o"
    temperature: 0.7

  - name: "Claude-Sonnet"
    model: "claude-sonnet-4-20250514"
    temperature: 0.7
    
  # Force a model to use random bot (useful for baseline testing)
  - name: "Random-Baseline"
    model: "gpt-4o"
    force_fallback: true
```

### Watch Battles

Open http://localhost:8088 in your browser while the tournament runs.

## API Key Status

When running a tournament, the system shows which models have valid API keys:

```
=== API Key Status ===
  ✓ OPENAI_API_KEY: sk-p...1234
  ✗ ANTHROPIC_API_KEY: not set
  ✓ GOOGLE_API_KEY: AIza...5678
  
Player Status:
  • GPT-4o: LLM
  • Claude-Sonnet: Fallback (random)
  • Gemini-Flash: LLM
```

## External AI Bots

### Technical Machine

[Technical Machine](https://github.com/davidstone/technical-machine) is a sophisticated C++ Pokemon AI. To use it:

1. Build Technical Machine (requires clang trunk, Boost 1.86+):
   ```bash
   bash scripts/setup_technical_machine.sh
   ```

2. Test the installation:
   ```bash
   bash scripts/test_technical_machine.sh
   ```
   This will auto-configure TM, start the Showdown server if needed, and run a test battle.

3. Run Technical Machine as a separate process while running your tournament

**Note**: Technical Machine requires C++26 features (parallel execution policies) that are only available on Linux with libstdc++. It will **not build on macOS**.

## How It Works

1. **Team Selection**: Each battle, players randomly select from the curated Gen 4 OU teams
2. **State Formatting**: The battle state is converted to a text description for the LLM
3. **LLM Decision**: The LLM receives the state and returns a move or switch command
4. **Action Parsing**: The response is parsed to extract the chosen action
5. **Battle Execution**: poke-env sends the action to Pokemon Showdown

## Supported LLMs

The default tournament configuration includes:
- **Anthropic**: Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5
- **OpenAI**: GPT-5.1, GPT-5-Mini, GPT-4.1
- **Google**: Gemini 3.0 Pro, Gemini 3.0 Flash
- **DeepSeek**: DeepSeek V3.2 Thinking
- **xAI**: Grok 4

Via LiteLLM, additional providers are also supported:
- Together AI, Groq, Mistral, Cohere, Azure OpenAI, AWS Bedrock, Ollama (local)

## License

MIT
