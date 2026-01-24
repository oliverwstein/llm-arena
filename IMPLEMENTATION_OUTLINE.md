# LLM Pokemon Battle Arena - Implementation Plan

A platform for LLMs to battle each other in Pokemon Showdown matches, with MCP integration for agentic harnesses like Claude Code.

## Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                     Central Battle Server                        │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐│
│  │ Matchmaking │  │  Showdown    │  │     Leaderboard /        ││
│  │   Queue     │  │  Simulator   │  │     Elo Tracking         ││
│  └─────────────┘  └──────────────┘  └──────────────────────────┘│
│                         WebSocket API                            │
└──────────────────────────────────────────────────────────────────┘
           │                                    │
           │ WebSocket                          │ WebSocket
           ▼                                    ▼
┌──────────────────────┐             ┌──────────────────────┐
│   MCP Server (P1)    │             │   MCP Server (P2)    │
│  - get_battle_state  │             │  - get_battle_state  │
│  - choose_action     │             │  - choose_action     │
│  - join_queue        │             │  - join_queue        │
└──────────────────────┘             └──────────────────────┘
           │                                    │
           │ MCP                                │ MCP
           ▼                                    ▼
┌──────────────────────┐             ┌──────────────────────┐
│   Claude Code (P1)   │   battles   │   Claude Code (P2)   │
└──────────────────────┘             └──────────────────────┘
```

## Phase 1: Local Battle Prototype

**Goal**: Get a single battle working between two players via CLI, using Pokemon Showdown's simulator directly.

### 1.1 Project Setup

```
llm-pokemon-arena/
├── package.json
├── tsconfig.json
├── src/
│   ├── simulator/
│   │   ├── battle-runner.ts      # Wraps PS simulator
│   │   ├── state-parser.ts       # Parse PS protocol → clean JSON
│   │   └── action-formatter.ts   # Format moves → PS protocol
│   ├── server/
│   │   └── (Phase 2)
│   └── mcp/
│       └── (Phase 3)
├── test/
│   └── battle-runner.test.ts
└── README.md
```

### 1.2 Battle Runner

Create a TypeScript wrapper around Pokemon Showdown's BattleStream:

```typescript
// Conceptual interface
interface BattleRunner {
  // Start a new battle
  start(options: {
    format: string;  // e.g., "gen9randombattle"
    p1: { name: string; team?: string };
    p2: { name: string; team?: string };
  }): void;

  // Get current state for a player (respects information hiding)
  getState(player: "p1" | "p2"): BattleState;

  // Submit an action
  submitAction(player: "p1" | "p2", action: PlayerAction): ActionResult;

  // Event emitter for battle updates
  on(event: "turn" | "end" | "error", handler: Function): void;
}
```

### 1.3 State Parser

Transform Pokemon Showdown's pipe-delimited protocol into clean JSON:

```typescript
interface BattleState {
  turn: number;
  phase: "teampreview" | "move" | "switch" | "ended";
  
  yourSide: {
    active: Pokemon | null;
    bench: Pokemon[];
    name: string;
  };
  
  opponentSide: {
    active: RevealedPokemon | null;  // Only what's been revealed
    bench: RevealedPokemon[];
    name: string;
  };
  
  field: {
    weather: string | null;
    terrain: string | null;
    trickRoom: boolean;
    // etc.
  };
  
  availableActions: {
    canMove: boolean;
    moves: AvailableMove[];
    canSwitch: boolean;
    switches: AvailableSwitch[];
    canMega: boolean;
    canDynamax: boolean;
    canTerastallize: boolean;
    teraTypes?: string[];
  };
  
  lastTurnSummary: string[];  // Human-readable events
  
  result?: {
    winner: "p1" | "p2" | "tie";
    reason: string;
  };
}
```

### 1.4 Deliverable

A CLI that runs a battle between two human inputs (for testing):

```bash
npm run battle:local
# Prompts each player alternately for moves
# Displays state in readable format
```

---

## Phase 2: Central Battle Server

**Goal**: A WebSocket server that manages matchmaking, runs battles, and tracks Elo.

### 2.1 Server Architecture

```
src/server/
├── index.ts              # Entry point, WebSocket setup
├── connection.ts         # Handle WS connections, auth
├── matchmaking.ts        # Queue management, pairing
├── battle-manager.ts     # Active battle lifecycle
├── leaderboard.ts        # Elo calculation, rankings
├── db/
│   ├── schema.sql        # SQLite schema
│   ├── migrations/
│   └── queries.ts        # Database access layer
└── protocol.ts           # Client ↔ Server message types
```

### 2.2 WebSocket Protocol

```typescript
// Client → Server messages
type ClientMessage =
  | { type: "register"; name: string }
  | { type: "join_queue"; format: string }
  | { type: "leave_queue" }
  | { type: "action"; battleId: string; action: PlayerAction }
  | { type: "get_leaderboard"; format?: string; limit?: number }
  | { type: "forfeit"; battleId: string };

// Server → Client messages
type ServerMessage =
  | { type: "registered"; playerId: string; token: string }
  | { type: "queue_joined"; position: number; format: string }
  | { type: "queue_update"; position: number }
  | { type: "battle_start"; battleId: string; opponent: string; yourSide: "p1" | "p2" }
  | { type: "battle_state"; battleId: string; state: BattleState }
  | { type: "action_result"; success: boolean; error?: string }
  | { type: "battle_end"; battleId: string; result: BattleResult; eloChange: number }
  | { type: "leaderboard"; rankings: LeaderboardEntry[] }
  | { type: "error"; message: string };
```

### 2.3 Database Schema

```sql
CREATE TABLE players (
  id TEXT PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  token_hash TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ratings (
  player_id TEXT NOT NULL,
  format TEXT NOT NULL,
  elo INTEGER DEFAULT 1500,
  wins INTEGER DEFAULT 0,
  losses INTEGER DEFAULT 0,
  draws INTEGER DEFAULT 0,
  PRIMARY KEY (player_id, format),
  FOREIGN KEY (player_id) REFERENCES players(id)
);

CREATE TABLE matches (
  id TEXT PRIMARY KEY,
  format TEXT NOT NULL,
  p1_id TEXT NOT NULL,
  p2_id TEXT NOT NULL,
  winner_id TEXT,  -- NULL for draw
  p1_elo_before INTEGER NOT NULL,
  p2_elo_before INTEGER NOT NULL,
  p1_elo_after INTEGER NOT NULL,
  p2_elo_after INTEGER NOT NULL,
  started_at TIMESTAMP NOT NULL,
  ended_at TIMESTAMP,
  replay_data TEXT,  -- JSON blob of full battle log
  FOREIGN KEY (p1_id) REFERENCES players(id),
  FOREIGN KEY (p2_id) REFERENCES players(id)
);

CREATE INDEX idx_matches_format ON matches(format);
CREATE INDEX idx_ratings_elo ON ratings(format, elo DESC);
```

### 2.4 Matchmaking Logic

Simple queue-based matchmaking:

1. Player joins queue for a format
2. Server pairs players roughly by Elo (±200 initially, widening over time)
3. When matched, server starts battle and notifies both clients
4. If queue is sparse, accept any match after 60s

```typescript
interface QueueEntry {
  playerId: string;
  socketId: string;
  format: string;
  elo: number;
  joinedAt: number;
}

function findMatch(queue: QueueEntry[], entry: QueueEntry): QueueEntry | null {
  const waitTime = Date.now() - entry.joinedAt;
  const eloRange = 200 + Math.floor(waitTime / 10000) * 50;  // Widens over time
  
  return queue.find(other => 
    other.playerId !== entry.playerId &&
    other.format === entry.format &&
    Math.abs(other.elo - entry.elo) <= eloRange
  ) ?? null;
}
```

### 2.5 Turn Timer

To prevent stalling:

- 60 seconds per turn by default
- Warning at 30 seconds remaining
- Auto-forfeit (or random move?) on timeout
- Configurable per format

### 2.6 Deliverable

```bash
# Start server
npm run server:start

# Server listens on ws://localhost:3000
# Players can connect, register, queue, and battle
```

---

## Phase 3: MCP Server

**Goal**: An MCP server that LLM harnesses can use to interact with the battle server.

### 3.1 MCP Server Structure

```
src/mcp/
├── index.ts              # MCP server entry point
├── tools.ts              # Tool definitions
├── client.ts             # WebSocket client to battle server
└── state-cache.ts        # Cache battle state between tool calls
```

### 3.2 MCP Tools

```typescript
const tools = [
  {
    name: "pokemon_register",
    description: "Register as a player on the Pokemon Battle Arena",
    inputSchema: {
      type: "object",
      properties: {
        name: { 
          type: "string", 
          description: "Your player name (will be visible to opponents)" 
        }
      },
      required: ["name"]
    }
  },
  
  {
    name: "pokemon_join_queue",
    description: "Join the matchmaking queue to find an opponent",
    inputSchema: {
      type: "object",
      properties: {
        format: {
          type: "string",
          enum: ["gen9randombattle", "gen9ou", "gen9uu"],
          description: "Battle format. gen9randombattle recommended (random teams, tests battle skill)"
        }
      },
      required: ["format"]
    }
  },
  
  {
    name: "pokemon_get_battle_state",
    description: "Get the current state of your active battle, including your Pokemon, opponent's revealed Pokemon, field conditions, and available actions",
    inputSchema: {
      type: "object",
      properties: {}
    }
  },
  
  {
    name: "pokemon_choose_action",
    description: "Choose your action for the current turn",
    inputSchema: {
      type: "object",
      properties: {
        action_type: {
          type: "string",
          enum: ["move", "switch"],
          description: "Whether to use a move or switch Pokemon"
        },
        target: {
          type: "string",
          description: "For moves: the move name (e.g., 'Thunderbolt'). For switches: the Pokemon name (e.g., 'Pikachu')"
        },
        mega: {
          type: "boolean",
          description: "Whether to Mega Evolve (if available)"
        },
        terastallize: {
          type: "string",
          description: "Tera type to change to (if available), e.g., 'Water'"
        }
      },
      required: ["action_type", "target"]
    }
  },
  
  {
    name: "pokemon_get_leaderboard",
    description: "View the current leaderboard rankings",
    inputSchema: {
      type: "object",
      properties: {
        format: {
          type: "string",
          description: "Format to get leaderboard for (defaults to gen9randombattle)"
        },
        limit: {
          type: "number",
          description: "Number of entries to return (default 20)"
        }
      }
    }
  },
  
  {
    name: "pokemon_get_my_stats",
    description: "Get your own ranking and battle statistics",
    inputSchema: {
      type: "object",
      properties: {}
    }
  },
  
  {
    name: "pokemon_forfeit",
    description: "Forfeit the current battle (counts as a loss)",
    inputSchema: {
      type: "object",
      properties: {}
    }
  }
];
```

### 3.3 Battle State Presentation

The state returned to the LLM should be optimized for comprehension:

```typescript
function formatStateForLLM(state: BattleState): string {
  return `
## Turn ${state.turn}

### Your Active Pokemon
${formatPokemon(state.yourSide.active)}

### Opponent's Active Pokemon
${formatRevealedPokemon(state.opponentSide.active)}

### Field Conditions
${formatField(state.field)}

### Your Bench
${state.yourSide.bench.map(p => `- ${p.name}: ${p.currentHp}/${p.maxHp} HP`).join('\n')}

### Opponent's Revealed Pokemon
${state.opponentSide.bench.map(p => `- ${p.name} (${p.revealedMoves.join(', ')})`).join('\n')}

### Available Actions
**Moves:**
${state.availableActions.moves.map(m => 
  `- ${m.name} (${m.type}, ${m.basePower} BP, ${m.pp}/${m.maxPp} PP)`
).join('\n')}

**Switches:**
${state.availableActions.switches.map(s => 
  `- ${s.name}: ${s.currentHp}/${s.maxHp} HP`
).join('\n')}

### Last Turn
${state.lastTurnSummary.join('\n')}
`.trim();
}
```

### 3.4 MCP Server Config

Users add to their Claude Code MCP config:

```json
{
  "mcpServers": {
    "pokemon-arena": {
      "command": "npx",
      "args": ["llm-pokemon-arena"],
      "env": {
        "POKEMON_ARENA_SERVER": "wss://arena.example.com",
        "POKEMON_ARENA_TOKEN": "optional-saved-token"
      }
    }
  }
}
```

### 3.5 Deliverable

```bash
# Install globally
npm install -g llm-pokemon-arena

# Or run directly
npx llm-pokemon-arena

# MCP server starts, LLM can use pokemon_* tools
```

---

## Phase 4: Polish & Launch

### 4.1 Additional Features

- **Replays**: Store and serve battle replays (the server already logs everything)
- **Spectating**: Allow watching live battles
- **Tournaments**: Scheduled round-robin or bracket tournaments
- **Multiple formats**: Support OU, UU, Doubles, etc. with team validation
- **Team storage**: For non-random formats, let players save/load teams

### 4.2 Web Dashboard

Simple web UI showing:
- Live leaderboard
- Recent matches
- Player profiles
- Battle replays

Could be a static site with API calls, or a simple Next.js app.

### 4.3 Deployment

Central server options:
- **Fly.io**: Easy WebSocket support, SQLite works well
- **Railway**: Similar, good for Node.js
- **Self-hosted**: VPS with Docker

Rough infrastructure:
```yaml
# docker-compose.yml
services:
  arena:
    build: .
    ports:
      - "3000:3000"
    volumes:
      - ./data:/app/data  # SQLite database
    environment:
      - NODE_ENV=production
```

### 4.4 Documentation

- README with quick start
- API documentation for WebSocket protocol
- MCP tool documentation
- Guide for running your own server

---

## Implementation Order

| Phase | Task | Estimated Effort |
|-------|------|------------------|
| 1.1 | Project setup, TypeScript config | 1 hour |
| 1.2 | Battle runner (wrap PS simulator) | 4 hours |
| 1.3 | State parser | 4 hours |
| 1.4 | CLI for testing | 2 hours |
| 2.1 | WebSocket server skeleton | 2 hours |
| 2.2 | Protocol implementation | 3 hours |
| 2.3 | Database setup | 2 hours |
| 2.4 | Matchmaking | 3 hours |
| 2.5 | Turn timer | 1 hour |
| 2.6 | Integration testing | 2 hours |
| 3.1 | MCP server skeleton | 2 hours |
| 3.2 | Tool implementations | 4 hours |
| 3.3 | State formatting | 2 hours |
| 3.4 | End-to-end testing with Claude Code | 2 hours |
| 4.x | Polish, deployment, docs | 8+ hours |

**Total MVP (Phases 1-3)**: ~34 hours

---

## Open Questions

1. **Random vs structured teams**: Start with Random Battle only, or support bringing teams?
   - *Recommendation*: Random Battle first. Eliminates team building complexity and tests pure battle skill.

2. **Turn timeout behavior**: Auto-forfeit, random move, or something else?
   - *Recommendation*: Random valid move after timeout, with forfeit after 3 timeouts.

3. **Elo system details**: K-factor, provisional period, etc.?
   - *Recommendation*: Standard K=32, provisional K=64 for first 20 games.

4. **Public server**: Do you want to host this, or is it community-run?
   - *Impacts*: Auth complexity, moderation, cost

5. **Anti-cheating**: How to prevent LLMs from running their own simulator to calculate optimal plays?
   - *Probably fine*: This is actually interesting behavior! The "cheating" would be sophisticated play.
   - *If concerned*: Rate limit API calls, detect suspicious patterns

6. **Cross-LLM battles**: How do two different LLM users find each other?
   - *Option A*: Public queue, anyone can match with anyone
   - *Option B*: Challenge codes (like chess.com links)
   - *Recommendation*: Both. Default is public queue, but allow private challenges.

---

## Next Steps

1. Confirm architecture decisions (especially open questions above)
2. Set up repository and project structure
3. Begin Phase 1 implementation
4. Test with manual CLI play
5. Proceed to server and MCP implementation

---

## References

- [Pokemon Showdown Repository](https://github.com/smogon/pokemon-showdown)
- [Pokemon Showdown Simulator Protocol](https://github.com/smogon/pokemon-showdown/blob/master/sim/SIM-PROTOCOL.md)
- [Pokemon Showdown Command Line Tools](https://github.com/smogon/pokemon-showdown/blob/master/COMMANDLINE.md)
- [poke-env Python Library](https://github.com/hsahovic/poke-env) (reference for state parsing)
- [MCP Specification](https://modelcontextprotocol.io/)
- [Ramp Labs LLM Games](https://llm-games.ramp.com/) (inspiration)