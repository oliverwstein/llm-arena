 LLM Pokemon Battle Arena - Complete Implementation Plan                        
                                                                                
 Project Overview                                                               
                                                                                
 Build a platform where LLMs battle each other in Pokemon matches using Pokemon 
  Showdown's simulator. LLMs connect via MCP tools, join a matchmaking queue,   
 and compete for Elo rankings.                                                  
                                                                                
 Resolved Design Decisions                                                      
 Question: Battle format                                                        
 Decision: Gen 4 OU (DPP)                                                       
 Rationale: User has curated Smogon DPP OU teams ready                          
 ────────────────────────────────────────                                       
 Question: Team selection                                                       
 Decision: Random from pool                                                     
 Rationale: Tests pure battle skill, no team-building complexity                
 ────────────────────────────────────────                                       
 Question: Turn timeout                                                         
 Decision: 3 minutes, random valid move on timeout                              
 Rationale: Generous for LLM thinking, no harsh penalties                       
 ────────────────────────────────────────                                       
 Question: Anti-cheat                                                           
 Decision: None                                                                 
 Rationale: Using simulators is interesting LLM behavior                        
 ────────────────────────────────────────                                       
 Question: Hosting                                                              
 Decision: Local Mac Studio                                                     
 Rationale: Zero cost, easy iteration during development                        
 ────────────────────────────────────────                                       
 Question: Matchmaking                                                          
 Decision: Public queue + challenge codes                                       
 Rationale: Both options available                                              
 ────────────────────────────────────────                                       
 Question: Elo system                                                           
 Decision: K=32 standard, K=64 provisional (first 20 games)                     
 Rationale: Standard competitive system                                         
 Project Structure                                                              
                                                                                
 llm-pokemon-arena/                                                             
 ├── package.json                                                               
 ├── tsconfig.json                                                              
 ├── src/                                                                       
 │   ├── simulator/                                                             
 │   │   ├── battle-runner.ts      # Wraps Pokemon Showdown BattleStream        
 │   │   ├── state-parser.ts       # Parse PS protocol → clean JSON             
 │   │   ├── action-formatter.ts   # Format actions → PS protocol               
 │   │   └── team-pool.ts          # Load teams from Raw-Teams/                 
 │   ├── server/                                                                
 │   │   ├── index.ts              # WebSocket server entry point               
 │   │   ├── connection.ts         # Handle WS connections                      
 │   │   ├── matchmaking.ts        # Queue management, Elo-based pairing        
 │   │   ├── battle-manager.ts     # Active battle lifecycle                    
 │   │   ├── leaderboard.ts        # Elo calculation, rankings                  
 │   │   └── protocol.ts           # Client ↔ Server message types              
 │   ├── db/                                                                    
 │   │   ├── index.ts              # Database connection (better-sqlite3)       
 │   │   ├── schema.sql            # SQLite schema                              
 │   │   └── queries.ts            # Database access functions                  
 │   ├── mcp/                                                                   
 │   │   ├── index.ts              # MCP server entry point                     
 │   │   ├── tools.ts              # Tool definitions                           
 │   │   ├── client.ts             # WebSocket client to battle server          
 │   │   └── state-formatter.ts    # Format state for LLM comprehension         
 │   └── cli/                                                                   
 │       └── battle-cli.ts         # CLI for manual testing                     
 ├── data/                                                                      
 │   └── teams/                    # Symlink or copy of Raw-Teams/              
 ├── test/                                                                      
 │   ├── battle-runner.test.ts                                                  
 │   ├── state-parser.test.ts                                                   
 │   └── matchmaking.test.ts                                                    
 └── Raw-Teams/                    # Existing team files (Showdown paste        
 format)                                                                        
     ├── Mixed-Jirachi-Gengar-Offense.md                                        
     ├── Forretress-Zapdos-Balance.md                                           
     ├── Mixed-Flygon-Spikes-Stack.md                                           
     ├── Quagsire-Scarf-Tyranitar-Stall.md                                      
     ├── Roserade-SubCM-Suicune-Balance.md                                      
     └── Dragonite-Lead-Boom-Offense.md                                         
                                                                                
 ---                                                                            
 Phase 1: Local Battle Prototype                                                
                                                                                
 Goal: Get a single battle working between two players via CLI.                 
                                                                                
 1.1 Project Setup                                                              
                                                                                
 # Initialize project                                                           
 npm init -y                                                                    
 npm install typescript @types/node ts-node --save-dev                          
 npm install pokemon-showdown                                                   
 npx tsc --init                                                                 
                                                                                
 tsconfig.json settings:                                                        
 {                                                                              
   "compilerOptions": {                                                         
     "target": "ES2022",                                                        
     "module": "NodeNext",                                                      
     "moduleResolution": "NodeNext",                                            
     "outDir": "./dist",                                                        
     "rootDir": "./src",                                                        
     "strict": true,                                                            
     "esModuleInterop": true,                                                   
     "skipLibCheck": true                                                       
   },                                                                           
   "include": ["src/**/*"]                                                      
 }                                                                              
                                                                                
 package.json scripts:                                                          
 {                                                                              
   "scripts": {                                                                 
     "build": "tsc",                                                            
     "battle:local": "ts-node src/cli/battle-cli.ts",                           
     "server:start": "ts-node src/server/index.ts",                             
     "mcp:start": "ts-node src/mcp/index.ts",                                   
     "test": "vitest"                                                           
   }                                                                            
 }                                                                              
                                                                                
 1.2 Team Pool Loader (src/simulator/team-pool.ts)                              
                                                                                
 Load teams from the existing Raw-Teams/ directory.                             
                                                                                
 import { readFileSync, readdirSync } from 'fs';                                
 import { join, basename } from 'path';                                         
 import { Teams } from 'pokemon-showdown';                                      
                                                                                
 interface TeamEntry {                                                          
   name: string;       // Derived from filename                                 
   packed: string;     // Packed format for PS simulator                        
   pokemon: string[];  // List of Pokemon names for display                     
 }                                                                              
                                                                                
 export class TeamPool {                                                        
   private teams: TeamEntry[] = [];                                             
                                                                                
   constructor(teamsDir: string) {                                              
     this.loadTeams(teamsDir);                                                  
   }                                                                            
                                                                                
   private loadTeams(dir: string): void {                                       
     const files = readdirSync(dir).filter(f => f.endsWith('.md'));             
                                                                                
     for (const file of files) {                                                
       const content = readFileSync(join(dir, file), 'utf-8');                  
       const name = basename(file, '.md');                                      
                                                                                
       // Pokemon Showdown can pack the paste format directly                   
       const packed = Teams.pack(Teams.import(content));                        
                                                                                
       // Extract Pokemon names for display                                     
       const pokemon = content                                                  
         .split('\n')                                                           
         .filter(line => line.match(/^[A-Z][a-z]+(\s|$)/) &&                    
 !line.includes(':'))                                                           
         .map(line => line.split(' ')[0].split('(')[0].trim());                 
                                                                                
       this.teams.push({ name, packed, pokemon });                              
     }                                                                          
   }                                                                            
                                                                                
   getRandomTeam(): TeamEntry {                                                 
     return this.teams[Math.floor(Math.random() * this.teams.length)];          
   }                                                                            
                                                                                
   getAllTeams(): TeamEntry[] {                                                 
     return [...this.teams];                                                    
   }                                                                            
                                                                                
   getTeamCount(): number {                                                     
     return this.teams.length;                                                  
   }                                                                            
 }                                                                              
                                                                                
 1.3 Battle Runner (src/simulator/battle-runner.ts)                             
                                                                                
 Wrap Pokemon Showdown's BattleStream for easy battle management.               
                                                                                
 import { BattleStream, Teams } from 'pokemon-showdown';                        
 import { EventEmitter } from 'events';                                         
 import { TeamPool } from './team-pool';                                        
                                                                                
 interface BattleOptions {                                                      
   format: string;  // 'gen4ou'                                                 
   p1Name: string;                                                              
   p2Name: string;                                                              
   teamPool: TeamPool;                                                          
 }                                                                              
                                                                                
 interface PlayerState {                                                        
   active: Pokemon | null;                                                      
   bench: Pokemon[];                                                            
   name: string;                                                                
 }                                                                              
                                                                                
 export class BattleRunner extends EventEmitter {                               
   private stream: BattleStream;                                                
   private p1State: any = null;                                                 
   private p2State: any = null;                                                 
   private battleLog: string[] = [];                                            
   private waitingFor: Set<'p1' | 'p2'> = new Set();                            
   private ended = false;                                                       
                                                                                
   constructor(private options: BattleOptions) {                                
     super();                                                                   
     this.stream = new BattleStream();                                          
     this.setupStreamHandlers();                                                
   }                                                                            
                                                                                
   private setupStreamHandlers(): void {                                        
     this.stream.on('message', (chunk: string) => {                             
       this.battleLog.push(chunk);                                              
       this.parseMessage(chunk);                                                
     });                                                                        
   }                                                                            
                                                                                
   async start(): Promise<void> {                                               
     const p1Team = this.options.teamPool.getRandomTeam();                      
     const p2Team = this.options.teamPool.getRandomTeam();                      
                                                                                
     this.stream.write(`>start {"formatid":"${this.options.format}"}`);         
     this.stream.write(`>player p1                                              
 {"name":"${this.options.p1Name}","team":"${p1Team.packed}"}`);                 
     this.stream.write(`>player p2                                              
 {"name":"${this.options.p2Name}","team":"${p2Team.packed}"}`);                 
   }                                                                            
                                                                                
   private parseMessage(chunk: string): void {                                  
     const lines = chunk.split('\n');                                           
                                                                                
     for (const line of lines) {                                                
       if (line.startsWith('|request|')) {                                      
         const json = JSON.parse(line.slice(9));                                
         const player = json.side?.id as 'p1' | 'p2';                           
         if (player === 'p1') this.p1State = json;                              
         else if (player === 'p2') this.p2State = json;                         
                                                                                
         if (json.wait) continue;                                               
         this.waitingFor.add(player);                                           
         this.emit('request', player, json);                                    
       }                                                                        
                                                                                
       if (line.startsWith('|win|')) {                                          
         this.ended = true;                                                     
         const winner = line.slice(5);                                          
         this.emit('end', { winner });                                          
       }                                                                        
                                                                                
       if (line.startsWith('|tie')) {                                           
         this.ended = true;                                                     
         this.emit('end', { winner: null });                                    
       }                                                                        
                                                                                
       if (line.startsWith('|turn|')) {                                         
         const turn = parseInt(line.slice(6));                                  
         this.emit('turn', turn);                                               
       }                                                                        
     }                                                                          
   }                                                                            
                                                                                
   getState(player: 'p1' | 'p2'): any {                                         
     return player === 'p1' ? this.p1State : this.p2State;                      
   }                                                                            
                                                                                
   submitAction(player: 'p1' | 'p2', action: string): boolean {                 
     if (!this.waitingFor.has(player)) {                                        
       return false;                                                            
     }                                                                          
                                                                                
     this.stream.write(`>${player} ${action}`);                                 
     this.waitingFor.delete(player);                                            
     return true;                                                               
   }                                                                            
                                                                                
   isWaitingFor(player: 'p1' | 'p2'): boolean {                                 
     return this.waitingFor.has(player);                                        
   }                                                                            
                                                                                
   isEnded(): boolean {                                                         
     return this.ended;                                                         
   }                                                                            
                                                                                
   getLog(): string[] {                                                         
     return this.battleLog;                                                     
   }                                                                            
 }                                                                              
                                                                                
 1.4 State Parser (src/simulator/state-parser.ts)                               
                                                                                
 Transform PS request JSON into a clean, LLM-friendly format.                   
                                                                                
 interface ParsedBattleState {                                                  
   turn: number;                                                                
   phase: 'teampreview' | 'move' | 'switch' | 'ended';                          
                                                                                
   yourSide: {                                                                  
     active: ParsedPokemon | null;                                              
     bench: ParsedPokemon[];                                                    
     name: string;                                                              
   };                                                                           
                                                                                
   opponentSide: {                                                              
     active: RevealedPokemon | null;                                            
     revealedPokemon: RevealedPokemon[];                                        
     name: string;                                                              
   };                                                                           
                                                                                
   field: {                                                                     
     weather: string | null;                                                    
     terrain: string | null;                                                    
     hazards: { p1: string[]; p2: string[] };                                   
   };                                                                           
                                                                                
   availableActions: {                                                          
     canMove: boolean;                                                          
     moves: AvailableMove[];                                                    
     canSwitch: boolean;                                                        
     switches: AvailableSwitch[];                                               
   };                                                                           
                                                                                
   lastTurnEvents: string[];                                                    
 }                                                                              
                                                                                
 interface ParsedPokemon {                                                      
   name: string;                                                                
   species: string;                                                             
   hp: number;                                                                  
   maxHp: number;                                                               
   hpPercent: number;                                                           
   status: string | null;                                                       
   item: string;                                                                
   ability: string;                                                             
   moves: string[];                                                             
   stats: { atk: number; def: number; spa: number; spd: number; spe: number };  
   boosts: { [stat: string]: number };                                          
 }                                                                              
                                                                                
 interface RevealedPokemon {                                                    
   name: string;                                                                
   species: string;                                                             
   hpPercent: number;  // Only percentage known for opponent                    
   status: string | null;                                                       
   revealedMoves: string[];                                                     
   revealedItem: string | null;                                                 
   revealedAbility: string | null;                                              
 }                                                                              
                                                                                
 interface AvailableMove {                                                      
   name: string;                                                                
   id: string;                                                                  
   type: string;                                                                
   pp: number;                                                                  
   maxPp: number;                                                               
   disabled: boolean;                                                           
   target: string;                                                              
 }                                                                              
                                                                                
 interface AvailableSwitch {                                                    
   name: string;                                                                
   species: string;                                                             
   hp: number;                                                                  
   maxHp: number;                                                               
   hpPercent: number;                                                           
   status: string | null;                                                       
 }                                                                              
                                                                                
 export function parseState(request: any, battleLog: string[]):                 
 ParsedBattleState {                                                            
   const side = request.side;                                                   
   const active = request.active?.[0];                                          
                                                                                
   // Parse your Pokemon                                                        
   const yourPokemon = side.pokemon.map((p: any) => parsePokemon(p));           
   const yourActive = yourPokemon.find((p: ParsedPokemon) =>                    
     p.name === side.pokemon[0]?.ident?.split(': ')[1]                          
   ) || null;                                                                   
   const yourBench = yourPokemon.filter((p: ParsedPokemon) => p !==             
 yourActive);                                                                   
                                                                                
   // Parse available actions                                                   
   const moves: AvailableMove[] = active?.moves?.map((m: any) => ({             
     name: m.move,                                                              
     id: m.id,                                                                  
     type: m.type || 'Unknown',                                                 
     pp: m.pp,                                                                  
     maxPp: m.maxpp,                                                            
     disabled: m.disabled || false,                                             
     target: m.target                                                           
   })) || [];                                                                   
                                                                                
   const switches: AvailableSwitch[] = side.pokemon                             
     .filter((p: any) => !p.active && p.condition !== '0 fnt')                  
     .map((p: any) => ({                                                        
       name: p.ident.split(': ')[1],                                            
       species: p.details.split(',')[0],                                        
       hp: parseHp(p.condition).current,                                        
       maxHp: parseHp(p.condition).max,                                         
       hpPercent: parseHp(p.condition).percent,                                 
       status: parseHp(p.condition).status                                      
     }));                                                                       
                                                                                
   // Determine phase                                                           
   let phase: 'teampreview' | 'move' | 'switch' | 'ended' = 'move';             
   if (request.teamPreview) phase = 'teampreview';                              
   else if (request.forceSwitch) phase = 'switch';                              
                                                                                
   return {                                                                     
     turn: extractTurnFromLog(battleLog),                                       
     phase,                                                                     
     yourSide: {                                                                
       active: yourActive,                                                      
       bench: yourBench,                                                        
       name: side.name                                                          
     },                                                                         
     opponentSide: {                                                            
       active: null,  // Parse from battle log                                  
       revealedPokemon: [],  // Parse from battle log                           
       name: ''  // Parse from battle log                                       
     },                                                                         
     field: parseFieldFromLog(battleLog),                                       
     availableActions: {                                                        
       canMove: moves.length > 0 && !request.forceSwitch,                       
       moves,                                                                   
       canSwitch: switches.length > 0,                                          
       switches                                                                 
     },                                                                         
     lastTurnEvents: extractLastTurnEvents(battleLog)                           
   };                                                                           
 }                                                                              
                                                                                
 function parsePokemon(p: any): ParsedPokemon {                                 
   const hp = parseHp(p.condition);                                             
   return {                                                                     
     name: p.ident.split(': ')[1],                                              
     species: p.details.split(',')[0],                                          
     hp: hp.current,                                                            
     maxHp: hp.max,                                                             
     hpPercent: hp.percent,                                                     
     status: hp.status,                                                         
     item: p.item,                                                              
     ability: p.ability,                                                        
     moves: p.moves,                                                            
     stats: p.stats,                                                            
     boosts: p.boosts || {}                                                     
   };                                                                           
 }                                                                              
                                                                                
 function parseHp(condition: string): { current: number; max: number; percent:  
 number; status: string | null } {                                              
   if (condition === '0 fnt') {                                                 
     return { current: 0, max: 100, percent: 0, status: 'fnt' };                
   }                                                                            
   const [hpPart, status] = condition.split(' ');                               
   const [current, max] = hpPart.split('/').map(Number);                        
   return {                                                                     
     current,                                                                   
     max,                                                                       
     percent: Math.round((current / max) * 100),                                
     status: status || null                                                     
   };                                                                           
 }                                                                              
                                                                                
 function extractTurnFromLog(log: string[]): number {                           
   for (let i = log.length - 1; i >= 0; i--) {                                  
     const match = log[i].match(/\|turn\|(\d+)/);                               
     if (match) return parseInt(match[1]);                                      
   }                                                                            
   return 0;                                                                    
 }                                                                              
                                                                                
 function parseFieldFromLog(log: string[]): ParsedBattleState['field'] {        
   // Implementation: scan log for weather, terrain, hazards                    
   return { weather: null, terrain: null, hazards: { p1: [], p2: [] } };        
 }                                                                              
                                                                                
 function extractLastTurnEvents(log: string[]): string[] {                      
   // Implementation: extract human-readable events from last turn              
   return [];                                                                   
 }                                                                              
                                                                                
 1.5 CLI for Testing (src/cli/battle-cli.ts)                                    
                                                                                
 import * as readline from 'readline';                                          
 import { BattleRunner } from '../simulator/battle-runner';                     
 import { TeamPool } from '../simulator/team-pool';                             
 import { parseState } from '../simulator/state-parser';                        
 import { join } from 'path';                                                   
                                                                                
 const rl = readline.createInterface({                                          
   input: process.stdin,                                                        
   output: process.stdout                                                       
 });                                                                            
                                                                                
 function prompt(question: string): Promise<string> {                           
   return new Promise(resolve => rl.question(question, resolve));               
 }                                                                              
                                                                                
 async function main() {                                                        
   const teamPool = new TeamPool(join(__dirname, '../../Raw-Teams'));           
   console.log(`Loaded ${teamPool.getTeamCount()} teams`);                      
                                                                                
   const battle = new BattleRunner({                                            
     format: 'gen4ou',                                                          
     p1Name: 'Player1',                                                         
     p2Name: 'Player2',                                                         
     teamPool                                                                   
   });                                                                          
                                                                                
   battle.on('request', async (player, request) => {                            
     const state = parseState(request, battle.getLog());                        
     console.log(`\n=== ${player.toUpperCase()}'s Turn ===`);                   
     console.log(formatStateForDisplay(state));                                 
                                                                                
     const input = await prompt(`${player} action (move X / switch X): `);      
     battle.submitAction(player, input);                                        
   });                                                                          
                                                                                
   battle.on('turn', (turn) => {                                                
     console.log(`\n--- Turn ${turn} ---`);                                     
   });                                                                          
                                                                                
   battle.on('end', (result) => {                                               
     console.log(`\nBattle ended! Winner: ${result.winner || 'Tie'}`);          
     rl.close();                                                                
     process.exit(0);                                                           
   });                                                                          
                                                                                
   await battle.start();                                                        
 }                                                                              
                                                                                
 function formatStateForDisplay(state: any): string {                           
   // Format state nicely for CLI display                                       
   return JSON.stringify(state, null, 2);                                       
 }                                                                              
                                                                                
 main().catch(console.error);                                                   
                                                                                
 ---                                                                            
 Phase 2: Central Battle Server                                                 
                                                                                
 Goal: WebSocket server managing matchmaking, battles, and Elo.                 
                                                                                
 2.1 Database Schema (src/db/schema.sql)                                        
                                                                                
 -- Players table                                                               
 CREATE TABLE IF NOT EXISTS players (                                           
   id TEXT PRIMARY KEY,                                                         
   name TEXT UNIQUE NOT NULL,                                                   
   token_hash TEXT NOT NULL,                                                    
   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP                               
 );                                                                             
                                                                                
 -- Ratings per format                                                          
 CREATE TABLE IF NOT EXISTS ratings (                                           
   player_id TEXT NOT NULL,                                                     
   format TEXT NOT NULL,                                                        
   elo INTEGER DEFAULT 1500,                                                    
   wins INTEGER DEFAULT 0,                                                      
   losses INTEGER DEFAULT 0,                                                    
   draws INTEGER DEFAULT 0,                                                     
   games_played INTEGER DEFAULT 0,                                              
   PRIMARY KEY (player_id, format),                                             
   FOREIGN KEY (player_id) REFERENCES players(id)                               
 );                                                                             
                                                                                
 -- Match history                                                               
 CREATE TABLE IF NOT EXISTS matches (                                           
   id TEXT PRIMARY KEY,                                                         
   format TEXT NOT NULL,                                                        
   p1_id TEXT NOT NULL,                                                         
   p2_id TEXT NOT NULL,                                                         
   winner_id TEXT,                                                              
   p1_elo_before INTEGER NOT NULL,                                              
   p2_elo_before INTEGER NOT NULL,                                              
   p1_elo_after INTEGER NOT NULL,                                               
   p2_elo_after INTEGER NOT NULL,                                               
   p1_team TEXT NOT NULL,                                                       
   p2_team TEXT NOT NULL,                                                       
   started_at TIMESTAMP NOT NULL,                                               
   ended_at TIMESTAMP,                                                          
   replay_log TEXT,                                                             
   FOREIGN KEY (p1_id) REFERENCES players(id),                                  
   FOREIGN KEY (p2_id) REFERENCES players(id)                                   
 );                                                                             
                                                                                
 CREATE INDEX IF NOT EXISTS idx_matches_format ON matches(format);              
 CREATE INDEX IF NOT EXISTS idx_ratings_leaderboard ON ratings(format, elo      
 DESC);                                                                         
                                                                                
 2.2 Database Access (src/db/index.ts)                                          
                                                                                
 import Database from 'better-sqlite3';                                         
 import { readFileSync } from 'fs';                                             
 import { join } from 'path';                                                   
 import { randomBytes, createHash } from 'crypto';                              
                                                                                
 const db = new Database(join(__dirname, '../../data/arena.db'));               
                                                                                
 // Initialize schema                                                           
 db.exec(readFileSync(join(__dirname, 'schema.sql'), 'utf-8'));                 
                                                                                
 export function createPlayer(name: string): { id: string; token: string } {    
   const id = randomBytes(16).toString('hex');                                  
   const token = randomBytes(32).toString('hex');                               
   const tokenHash = createHash('sha256').update(token).digest('hex');          
                                                                                
   db.prepare('INSERT INTO players (id, name, token_hash) VALUES (?, ?, ?)')    
     .run(id, name, tokenHash);                                                 
                                                                                
   db.prepare('INSERT INTO ratings (player_id, format) VALUES (?, ?)')          
     .run(id, 'gen4ou');                                                        
                                                                                
   return { id, token };                                                        
 }                                                                              
                                                                                
 export function verifyToken(playerId: string, token: string): boolean {        
   const tokenHash = createHash('sha256').update(token).digest('hex');          
   const row = db.prepare('SELECT 1 FROM players WHERE id = ? AND token_hash =  
 ?')                                                                            
     .get(playerId, tokenHash);                                                 
   return !!row;                                                                
 }                                                                              
                                                                                
 export function getPlayerByName(name: string): { id: string; name: string } |  
 null {                                                                         
   return db.prepare('SELECT id, name FROM players WHERE name = ?').get(name)   
 as any;                                                                        
 }                                                                              
                                                                                
 export function getRating(playerId: string, format: string): { elo: number;    
 wins: number; losses: number; draws: number; gamesPlayed: number } {           
   const row = db.prepare('SELECT elo, wins, losses, draws, games_played FROM   
 ratings WHERE player_id = ? AND format = ?')                                   
     .get(playerId, format) as any;                                             
   return row || { elo: 1500, wins: 0, losses: 0, draws: 0, gamesPlayed: 0 };   
 }                                                                              
                                                                                
 export function updateRating(playerId: string, format: string, newElo: number, 
  result: 'win' | 'loss' | 'draw'): void {                                      
   const field = result === 'win' ? 'wins' : result === 'loss' ? 'losses' :     
 'draws';                                                                       
   db.prepare(`UPDATE ratings SET elo = ?, ${field} = ${field} + 1,             
 games_played = games_played + 1 WHERE player_id = ? AND format = ?`)           
     .run(newElo, playerId, format);                                            
 }                                                                              
                                                                                
 export function recordMatch(match: {                                           
   id: string;                                                                  
   format: string;                                                              
   p1Id: string;                                                                
   p2Id: string;                                                                
   winnerId: string | null;                                                     
   p1EloBefore: number;                                                         
   p2EloBefore: number;                                                         
   p1EloAfter: number;                                                          
   p2EloAfter: number;                                                          
   p1Team: string;                                                              
   p2Team: string;                                                              
   replayLog: string;                                                           
 }): void {                                                                     
   db.prepare(`                                                                 
     INSERT INTO matches (id, format, p1_id, p2_id, winner_id, p1_elo_before,   
 p2_elo_before, p1_elo_after, p2_elo_after, p1_team, p2_team, started_at,       
 ended_at, replay_log)                                                          
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), 
  ?)                                                                            
   `).run(match.id, match.format, match.p1Id, match.p2Id, match.winnerId,       
 match.p1EloBefore, match.p2EloBefore, match.p1EloAfter, match.p2EloAfter,      
 match.p1Team, match.p2Team, match.replayLog);                                  
 }                                                                              
                                                                                
 export function getLeaderboard(format: string, limit: number = 20): { name:    
 string; elo: number; wins: number; losses: number }[] {                        
   return db.prepare(`                                                          
     SELECT p.name, r.elo, r.wins, r.losses                                     
     FROM ratings r                                                             
     JOIN players p ON r.player_id = p.id                                       
     WHERE r.format = ?                                                         
     ORDER BY r.elo DESC                                                        
     LIMIT ?                                                                    
   `).all(format, limit) as any[];                                              
 }                                                                              
                                                                                
 2.3 Elo Calculator (src/server/leaderboard.ts)                                 
                                                                                
 export function calculateEloChange(                                            
   winnerElo: number,                                                           
   loserElo: number,                                                            
   isDraw: boolean,                                                             
   winnerGames: number,                                                         
   loserGames: number                                                           
 ): { winnerDelta: number; loserDelta: number } {                               
   // K-factor: 64 for provisional (< 20 games), 32 otherwise                   
   const winnerK = winnerGames < 20 ? 64 : 32;                                  
   const loserK = loserGames < 20 ? 64 : 32;                                    
                                                                                
   // Expected scores                                                           
   const expectedWinner = 1 / (1 + Math.pow(10, (loserElo - winnerElo) / 400)); 
   const expectedLoser = 1 - expectedWinner;                                    
                                                                                
   // Actual scores                                                             
   const actualWinner = isDraw ? 0.5 : 1;                                       
   const actualLoser = isDraw ? 0.5 : 0;                                        
                                                                                
   const winnerDelta = Math.round(winnerK * (actualWinner - expectedWinner));   
   const loserDelta = Math.round(loserK * (actualLoser - expectedLoser));       
                                                                                
   return { winnerDelta, loserDelta };                                          
 }                                                                              
                                                                                
 2.4 WebSocket Protocol (src/server/protocol.ts)                                
                                                                                
 // Client → Server messages                                                    
 export type ClientMessage =                                                    
   | { type: 'register'; name: string }                                         
   | { type: 'auth'; playerId: string; token: string }                          
   | { type: 'join_queue'; format: string }                                     
   | { type: 'leave_queue' }                                                    
   | { type: 'action'; battleId: string; action: string }                       
   | { type: 'forfeit'; battleId: string }                                      
   | { type: 'get_leaderboard'; format?: string; limit?: number }               
   | { type: 'get_my_stats' };                                                  
                                                                                
 // Server → Client messages                                                    
 export type ServerMessage =                                                    
   | { type: 'registered'; playerId: string; token: string }                    
   | { type: 'auth_success'; playerId: string; name: string }                   
   | { type: 'auth_failed'; reason: string }                                    
   | { type: 'queue_joined'; format: string; position: number }                 
   | { type: 'queue_left' }                                                     
   | { type: 'battle_start'; battleId: string; opponent: string; yourSide: 'p1' 
  | 'p2'; yourTeam: string }                                                    
   | { type: 'battle_state'; battleId: string; state: any; waitingForAction:    
 boolean; timeRemaining: number }                                               
   | { type: 'action_accepted' }                                                
   | { type: 'action_rejected'; reason: string }                                
   | { type: 'battle_end'; battleId: string; winner: string | null; eloChange:  
 number; newElo: number }                                                       
   | { type: 'leaderboard'; entries: { rank: number; name: string; elo: number; 
  wins: number; losses: number }[] }                                            
   | { type: 'my_stats'; elo: number; rank: number; wins: number; losses:       
 number; draws: number }                                                        
   | { type: 'error'; message: string };                                        
                                                                                
 2.5 Matchmaking (src/server/matchmaking.ts)                                    
                                                                                
 import { getRating } from '../db';                                             
                                                                                
 interface QueueEntry {                                                         
   playerId: string;                                                            
   socketId: string;                                                            
   format: string;                                                              
   elo: number;                                                                 
   joinedAt: number;                                                            
 }                                                                              
                                                                                
 export class MatchmakingQueue {                                                
   private queue: QueueEntry[] = [];                                            
   private matchCallback: (p1: QueueEntry, p2: QueueEntry) => void;             
                                                                                
   constructor(onMatch: (p1: QueueEntry, p2: QueueEntry) => void) {             
     this.matchCallback = onMatch;                                              
     // Check for matches every second                                          
     setInterval(() => this.processQueue(), 1000);                              
   }                                                                            
                                                                                
   join(playerId: string, socketId: string, format: string): number {           
     const rating = getRating(playerId, format);                                
     const entry: QueueEntry = {                                                
       playerId,                                                                
       socketId,                                                                
       format,                                                                  
       elo: rating.elo,                                                         
       joinedAt: Date.now()                                                     
     };                                                                         
                                                                                
     this.queue.push(entry);                                                    
     return this.queue.filter(e => e.format === format).length;                 
   }                                                                            
                                                                                
   leave(playerId: string): void {                                              
     this.queue = this.queue.filter(e => e.playerId !== playerId);              
   }                                                                            
                                                                                
   private processQueue(): void {                                               
     const formats = [...new Set(this.queue.map(e => e.format))];               
                                                                                
     for (const format of formats) {                                            
       const formatQueue = this.queue.filter(e => e.format === format);         
       if (formatQueue.length < 2) continue;                                    
                                                                                
       // Sort by join time to prioritize longer waits                          
       formatQueue.sort((a, b) => a.joinedAt - b.joinedAt);                     
                                                                                
       for (const entry of formatQueue) {                                       
         const match = this.findMatch(entry, formatQueue);                      
         if (match) {                                                           
           // Remove both from queue                                            
           this.queue = this.queue.filter(e =>                                  
             e.playerId !== entry.playerId && e.playerId !== match.playerId     
           );                                                                   
           this.matchCallback(entry, match);                                    
           break;  // Process one match at a time                               
         }                                                                      
       }                                                                        
     }                                                                          
   }                                                                            
                                                                                
   private findMatch(entry: QueueEntry, queue: QueueEntry[]): QueueEntry | null 
  {                                                                             
     const waitTime = Date.now() - entry.joinedAt;                              
     // Elo range widens over time: starts at 200, increases by 50 every 10     
 seconds                                                                        
     const eloRange = 200 + Math.floor(waitTime / 10000) * 50;                  
                                                                                
     return queue.find(other =>                                                 
       other.playerId !== entry.playerId &&                                     
       other.format === entry.format &&                                         
       Math.abs(other.elo - entry.elo) <= eloRange                              
     ) ?? null;                                                                 
   }                                                                            
                                                                                
   getPosition(playerId: string, format: string): number {                      
     const formatQueue = this.queue.filter(e => e.format === format);           
     const index = formatQueue.findIndex(e => e.playerId === playerId);         
     return index + 1;                                                          
   }                                                                            
 }                                                                              
                                                                                
 2.6 Battle Manager (src/server/battle-manager.ts)                              
                                                                                
 import { BattleRunner } from '../simulator/battle-runner';                     
 import { TeamPool } from '../simulator/team-pool';                             
 import { parseState } from '../simulator/state-parser';                        
 import { randomBytes } from 'crypto';                                          
                                                                                
 interface ActiveBattle {                                                       
   id: string;                                                                  
   runner: BattleRunner;                                                        
   p1Id: string;                                                                
   p2Id: string;                                                                
   p1SocketId: string;                                                          
   p2SocketId: string;                                                          
   p1Team: string;                                                              
   p2Team: string;                                                              
   format: string;                                                              
   turnTimer: NodeJS.Timeout | null;                                            
   turnStartTime: number;                                                       
 }                                                                              
                                                                                
 const TURN_TIMEOUT_MS = 3 * 60 * 1000;  // 3 minutes                           
                                                                                
 export class BattleManager {                                                   
   private battles: Map<string, ActiveBattle> = new Map();                      
   private playerBattles: Map<string, string> = new Map();  // playerId ->      
 battleId                                                                       
                                                                                
   constructor(                                                                 
     private teamPool: TeamPool,                                                
     private sendToSocket: (socketId: string, message: any) => void,            
     private onBattleEnd: (battleId: string, winnerId: string | null, p1Id:     
 string, p2Id: string) => void                                                  
   ) {}                                                                         
                                                                                
   startBattle(                                                                 
     format: string,                                                            
     p1Id: string, p1SocketId: string, p1Name: string,                          
     p2Id: string, p2SocketId: string, p2Name: string                           
   ): string {                                                                  
     const battleId = randomBytes(8).toString('hex');                           
                                                                                
     const runner = new BattleRunner({                                          
       format,                                                                  
       p1Name,                                                                  
       p2Name,                                                                  
       teamPool: this.teamPool                                                  
     });                                                                        
                                                                                
     const p1Team = this.teamPool.getRandomTeam();                              
     const p2Team = this.teamPool.getRandomTeam();                              
                                                                                
     const battle: ActiveBattle = {                                             
       id: battleId,                                                            
       runner,                                                                  
       p1Id, p2Id,                                                              
       p1SocketId, p2SocketId,                                                  
       p1Team: p1Team.name,                                                     
       p2Team: p2Team.name,                                                     
       format,                                                                  
       turnTimer: null,                                                         
       turnStartTime: 0                                                         
     };                                                                         
                                                                                
     this.battles.set(battleId, battle);                                        
     this.playerBattles.set(p1Id, battleId);                                    
     this.playerBattles.set(p2Id, battleId);                                    
                                                                                
     // Set up event handlers                                                   
     runner.on('request', (player: 'p1' | 'p2', request: any) => {              
       const socketId = player === 'p1' ? battle.p1SocketId :                   
 battle.p2SocketId;                                                             
       const state = parseState(request, runner.getLog());                      
                                                                                
       this.sendToSocket(socketId, {                                            
         type: 'battle_state',                                                  
         battleId,                                                              
         state,                                                                 
         waitingForAction: true,                                                
         timeRemaining: TURN_TIMEOUT_MS                                         
       });                                                                      
                                                                                
       this.startTurnTimer(battle, player);                                     
     });                                                                        
                                                                                
     runner.on('end', (result: { winner: string | null }) => {                  
       this.endBattle(battleId, result.winner);                                 
     });                                                                        
                                                                                
     // Notify players                                                          
     this.sendToSocket(p1SocketId, {                                            
       type: 'battle_start',                                                    
       battleId,                                                                
       opponent: p2Name,                                                        
       yourSide: 'p1',                                                          
       yourTeam: p1Team.name                                                    
     });                                                                        
                                                                                
     this.sendToSocket(p2SocketId, {                                            
       type: 'battle_start',                                                    
       battleId,                                                                
       opponent: p1Name,                                                        
       yourSide: 'p2',                                                          
       yourTeam: p2Team.name                                                    
     });                                                                        
                                                                                
     runner.start();                                                            
     return battleId;                                                           
   }                                                                            
                                                                                
   submitAction(battleId: string, playerId: string, action: string): boolean {  
     const battle = this.battles.get(battleId);                                 
     if (!battle) return false;                                                 
                                                                                
     const player = battle.p1Id === playerId ? 'p1' : battle.p2Id === playerId  
 ? 'p2' : null;                                                                 
     if (!player) return false;                                                 
                                                                                
     const success = battle.runner.submitAction(player, action);                
     if (success) {                                                             
       this.clearTurnTimer(battle);                                             
     }                                                                          
     return success;                                                            
   }                                                                            
                                                                                
   forfeit(battleId: string, playerId: string): void {                          
     const battle = this.battles.get(battleId);                                 
     if (!battle) return;                                                       
                                                                                
     const winnerId = battle.p1Id === playerId ? battle.p2Id : battle.p1Id;     
     const winnerName = battle.p1Id === playerId ? 'p2' : 'p1';                 
     this.endBattle(battleId, winnerName === 'p1' ?                             
 battle.runner.getState('p1')?.side?.name :                                     
 battle.runner.getState('p2')?.side?.name);                                     
   }                                                                            
                                                                                
   private startTurnTimer(battle: ActiveBattle, player: 'p1' | 'p2'): void {    
     this.clearTurnTimer(battle);                                               
     battle.turnStartTime = Date.now();                                         
                                                                                
     battle.turnTimer = setTimeout(() => {                                      
       // Auto-select random move on timeout                                    
       const state = battle.runner.getState(player);                            
       if (state?.active?.[0]?.moves?.length > 0) {                             
         const randomMove = Math.floor(Math.random() *                          
 state.active[0].moves.length) + 1;                                             
         battle.runner.submitAction(player, `move ${randomMove}`);              
       } else if (state?.side?.pokemon?.some((p: any) => !p.active &&           
 p.condition !== '0 fnt')) {                                                    
         // Force switch to first available                                     
         const available = state.side.pokemon.findIndex((p: any) => !p.active   
 && p.condition !== '0 fnt');                                                   
         if (available >= 0) {                                                  
           battle.runner.submitAction(player, `switch ${available + 1}`);       
         }                                                                      
       }                                                                        
     }, TURN_TIMEOUT_MS);                                                       
   }                                                                            
                                                                                
   private clearTurnTimer(battle: ActiveBattle): void {                         
     if (battle.turnTimer) {                                                    
       clearTimeout(battle.turnTimer);                                          
       battle.turnTimer = null;                                                 
     }                                                                          
   }                                                                            
                                                                                
   private endBattle(battleId: string, winnerName: string | null): void {       
     const battle = this.battles.get(battleId);                                 
     if (!battle) return;                                                       
                                                                                
     this.clearTurnTimer(battle);                                               
                                                                                
     // Determine winner ID                                                     
     let winnerId: string | null = null;                                        
     if (winnerName) {                                                          
       const p1Name = battle.runner.getState('p1')?.side?.name;                 
       winnerId = winnerName === p1Name ? battle.p1Id : battle.p2Id;            
     }                                                                          
                                                                                
     // Clean up                                                                
     this.battles.delete(battleId);                                             
     this.playerBattles.delete(battle.p1Id);                                    
     this.playerBattles.delete(battle.p2Id);                                    
                                                                                
     // Callback for Elo update                                                 
     this.onBattleEnd(battleId, winnerId, battle.p1Id, battle.p2Id);            
   }                                                                            
                                                                                
   getBattleForPlayer(playerId: string): ActiveBattle | null {                  
     const battleId = this.playerBattles.get(playerId);                         
     return battleId ? this.battles.get(battleId) || null : null;               
   }                                                                            
 }                                                                              
                                                                                
 2.7 WebSocket Server (src/server/index.ts)                                     
                                                                                
 import { WebSocketServer, WebSocket } from 'ws';                               
 import { TeamPool } from '../simulator/team-pool';                             
 import { MatchmakingQueue } from './matchmaking';                              
 import { BattleManager } from './battle-manager';                              
 import { ClientMessage, ServerMessage } from './protocol';                     
 import { calculateEloChange } from './leaderboard';                            
 import * as db from '../db';                                                   
 import { join } from 'path';                                                   
                                                                                
 const PORT = parseInt(process.env.PORT || '3000');                             
                                                                                
 const teamPool = new TeamPool(join(__dirname, '../../Raw-Teams'));             
 console.log(`Loaded ${teamPool.getTeamCount()} teams`);                        
                                                                                
 const wss = new WebSocketServer({ port: PORT });                               
                                                                                
 // Socket management                                                           
 const sockets: Map<string, WebSocket> = new Map();                             
 const socketPlayers: Map<string, string> = new Map();  // socketId -> playerId 
 let socketIdCounter = 0;                                                       
                                                                                
 function generateSocketId(): string {                                          
   return `socket_${++socketIdCounter}`;                                        
 }                                                                              
                                                                                
 function send(socketId: string, message: ServerMessage): void {                
   const ws = sockets.get(socketId);                                            
   if (ws && ws.readyState === WebSocket.OPEN) {                                
     ws.send(JSON.stringify(message));                                          
   }                                                                            
 }                                                                              
                                                                                
 // Battle end handler                                                          
 function handleBattleEnd(battleId: string, winnerId: string | null, p1Id:      
 string, p2Id: string): void {                                                  
   const format = 'gen4ou';                                                     
   const p1Rating = db.getRating(p1Id, format);                                 
   const p2Rating = db.getRating(p2Id, format);                                 
                                                                                
   const isDraw = winnerId === null;                                            
   const { winnerDelta, loserDelta } = calculateEloChange(                      
     winnerId === p1Id ? p1Rating.elo : p2Rating.elo,                           
     winnerId === p1Id ? p2Rating.elo : p1Rating.elo,                           
     isDraw,                                                                    
     winnerId === p1Id ? p1Rating.gamesPlayed : p2Rating.gamesPlayed,           
     winnerId === p1Id ? p2Rating.gamesPlayed : p1Rating.gamesPlayed            
   );                                                                           
                                                                                
   const p1Delta = winnerId === p1Id ? winnerDelta : winnerId === p2Id ?        
 loserDelta : winnerDelta;                                                      
   const p2Delta = winnerId === p2Id ? winnerDelta : winnerId === p1Id ?        
 loserDelta : loserDelta;                                                       
                                                                                
   const p1NewElo = p1Rating.elo + p1Delta;                                     
   const p2NewElo = p2Rating.elo + p2Delta;                                     
                                                                                
   db.updateRating(p1Id, format, p1NewElo, winnerId === p1Id ? 'win' : winnerId 
  === p2Id ? 'loss' : 'draw');                                                  
   db.updateRating(p2Id, format, p2NewElo, winnerId === p2Id ? 'win' : winnerId 
  === p1Id ? 'loss' : 'draw');                                                  
                                                                                
   // Notify players                                                            
   const p1SocketId = [...socketPlayers.entries()].find(([_, pid]) => pid ===   
 p1Id)?.[0];                                                                    
   const p2SocketId = [...socketPlayers.entries()].find(([_, pid]) => pid ===   
 p2Id)?.[0];                                                                    
                                                                                
   if (p1SocketId) {                                                            
     send(p1SocketId, { type: 'battle_end', battleId, winner: winnerId === p1Id 
  ? 'you' : winnerId === p2Id ? 'opponent' : null, eloChange: p1Delta, newElo:  
 p1NewElo });                                                                   
   }                                                                            
   if (p2SocketId) {                                                            
     send(p2SocketId, { type: 'battle_end', battleId, winner: winnerId === p2Id 
  ? 'you' : winnerId === p1Id ? 'opponent' : null, eloChange: p2Delta, newElo:  
 p2NewElo });                                                                   
   }                                                                            
 }                                                                              
                                                                                
 const battleManager = new BattleManager(teamPool, send, handleBattleEnd);      
                                                                                
 const matchmaking = new MatchmakingQueue((p1, p2) => {                         
   const p1Player = db.getPlayerByName(p1.playerId) || { name: 'Unknown' };     
   const p2Player = db.getPlayerByName(p2.playerId) || { name: 'Unknown' };     
                                                                                
   battleManager.startBattle(                                                   
     p1.format,                                                                 
     p1.playerId, p1.socketId, p1Player.name,                                   
     p2.playerId, p2.socketId, p2Player.name                                    
   );                                                                           
 });                                                                            
                                                                                
 // Connection handler                                                          
 wss.on('connection', (ws) => {                                                 
   const socketId = generateSocketId();                                         
   sockets.set(socketId, ws);                                                   
                                                                                
   ws.on('message', (data) => {                                                 
     try {                                                                      
       const message: ClientMessage = JSON.parse(data.toString());              
       handleMessage(socketId, message);                                        
     } catch (e) {                                                              
       send(socketId, { type: 'error', message: 'Invalid message format' });    
     }                                                                          
   });                                                                          
                                                                                
   ws.on('close', () => {                                                       
     const playerId = socketPlayers.get(socketId);                              
     if (playerId) {                                                            
       matchmaking.leave(playerId);                                             
       // Handle disconnection during battle if needed                          
     }                                                                          
     sockets.delete(socketId);                                                  
     socketPlayers.delete(socketId);                                            
   });                                                                          
 });                                                                            
                                                                                
 function handleMessage(socketId: string, message: ClientMessage): void {       
   switch (message.type) {                                                      
     case 'register': {                                                         
       const existing = db.getPlayerByName(message.name);                       
       if (existing) {                                                          
         send(socketId, { type: 'error', message: 'Name already taken' });      
         return;                                                                
       }                                                                        
       const { id, token } = db.createPlayer(message.name);                     
       socketPlayers.set(socketId, id);                                         
       send(socketId, { type: 'registered', playerId: id, token });             
       break;                                                                   
     }                                                                          
                                                                                
     case 'auth': {                                                             
       if (db.verifyToken(message.playerId, message.token)) {                   
         socketPlayers.set(socketId, message.playerId);                         
         const player = db.getPlayerByName(message.playerId);                   
         send(socketId, { type: 'auth_success', playerId: message.playerId,     
 name: player?.name || 'Unknown' });                                            
       } else {                                                                 
         send(socketId, { type: 'auth_failed', reason: 'Invalid credentials'    
 });                                                                            
       }                                                                        
       break;                                                                   
     }                                                                          
                                                                                
     case 'join_queue': {                                                       
       const playerId = socketPlayers.get(socketId);                            
       if (!playerId) {                                                         
         send(socketId, { type: 'error', message: 'Not authenticated' });       
         return;                                                                
       }                                                                        
       const position = matchmaking.join(playerId, socketId, message.format);   
       send(socketId, { type: 'queue_joined', format: message.format, position  
 });                                                                            
       break;                                                                   
     }                                                                          
                                                                                
     case 'leave_queue': {                                                      
       const playerId = socketPlayers.get(socketId);                            
       if (playerId) matchmaking.leave(playerId);                               
       send(socketId, { type: 'queue_left' });                                  
       break;                                                                   
     }                                                                          
                                                                                
     case 'action': {                                                           
       const playerId = socketPlayers.get(socketId);                            
       if (!playerId) {                                                         
         send(socketId, { type: 'action_rejected', reason: 'Not authenticated'  
 });                                                                            
         return;                                                                
       }                                                                        
       const success = battleManager.submitAction(message.battleId, playerId,   
 message.action);                                                               
       send(socketId, success ? { type: 'action_accepted' } : { type:           
 'action_rejected', reason: 'Invalid action' });                                
       break;                                                                   
     }                                                                          
                                                                                
     case 'forfeit': {                                                          
       const playerId = socketPlayers.get(socketId);                            
       if (playerId) battleManager.forfeit(message.battleId, playerId);         
       break;                                                                   
     }                                                                          
                                                                                
     case 'get_leaderboard': {                                                  
       const entries = db.getLeaderboard(message.format || 'gen4ou',            
 message.limit || 20);                                                          
       send(socketId, {                                                         
         type: 'leaderboard',                                                   
         entries: entries.map((e, i) => ({ rank: i + 1, ...e }))                
       });                                                                      
       break;                                                                   
     }                                                                          
                                                                                
     case 'get_my_stats': {                                                     
       const playerId = socketPlayers.get(socketId);                            
       if (!playerId) {                                                         
         send(socketId, { type: 'error', message: 'Not authenticated' });       
         return;                                                                
       }                                                                        
       const rating = db.getRating(playerId, 'gen4ou');                         
       const leaderboard = db.getLeaderboard('gen4ou', 1000);                   
       const rank = leaderboard.findIndex(e => e.elo <= rating.elo) + 1;        
       send(socketId, {                                                         
         type: 'my_stats',                                                      
         elo: rating.elo,                                                       
         rank: rank || leaderboard.length + 1,                                  
         wins: rating.wins,                                                     
         losses: rating.losses,                                                 
         draws: rating.draws                                                    
       });                                                                      
       break;                                                                   
     }                                                                          
   }                                                                            
 }                                                                              
                                                                                
 console.log(`Battle server listening on ws://localhost:${PORT}`);              
                                                                                
 ---                                                                            
 Phase 3: MCP Server                                                            
                                                                                
 Goal: MCP server that LLMs use to interact with the battle server.             
                                                                                
 3.1 MCP Client (src/mcp/client.ts)                                             
                                                                                
 import WebSocket from 'ws';                                                    
 import { EventEmitter } from 'events';                                         
                                                                                
 export class ArenaClient extends EventEmitter {                                
   private ws: WebSocket | null = null;                                         
   private connected = false;                                                   
   private playerId: string | null = null;                                      
   private token: string | null = null;                                         
   private currentBattleId: string | null = null;                               
   private pendingResponses: Map<string, (data: any) => void> = new Map();      
   private messageId = 0;                                                       
                                                                                
   constructor(private serverUrl: string) {                                     
     super();                                                                   
   }                                                                            
                                                                                
   async connect(): Promise<void> {                                             
     return new Promise((resolve, reject) => {                                  
       this.ws = new WebSocket(this.serverUrl);                                 
                                                                                
       this.ws.on('open', () => {                                               
         this.connected = true;                                                 
         resolve();                                                             
       });                                                                      
                                                                                
       this.ws.on('message', (data) => {                                        
         const message = JSON.parse(data.toString());                           
         this.handleMessage(message);                                           
       });                                                                      
                                                                                
       this.ws.on('close', () => {                                              
         this.connected = false;                                                
         this.emit('disconnected');                                             
       });                                                                      
                                                                                
       this.ws.on('error', reject);                                             
     });                                                                        
   }                                                                            
                                                                                
   private handleMessage(message: any): void {                                  
     // Store credentials on registration                                       
     if (message.type === 'registered') {                                       
       this.playerId = message.playerId;                                        
       this.token = message.token;                                              
     }                                                                          
                                                                                
     if (message.type === 'auth_success') {                                     
       this.playerId = message.playerId;                                        
     }                                                                          
                                                                                
     if (message.type === 'battle_start') {                                     
       this.currentBattleId = message.battleId;                                 
     }                                                                          
                                                                                
     if (message.type === 'battle_end') {                                       
       this.currentBattleId = null;                                             
     }                                                                          
                                                                                
     this.emit('message', message);                                             
   }                                                                            
                                                                                
   send(message: any): void {                                                   
     if (this.ws && this.connected) {                                           
       this.ws.send(JSON.stringify(message));                                   
     }                                                                          
   }                                                                            
                                                                                
   async waitForMessage(type: string, timeout = 30000): Promise<any> {          
     return new Promise((resolve, reject) => {                                  
       const timer = setTimeout(() => reject(new Error('Timeout')), timeout);   
                                                                                
       const handler = (message: any) => {                                      
         if (message.type === type) {                                           
           clearTimeout(timer);                                                 
           this.removeListener('message', handler);                             
           resolve(message);                                                    
         }                                                                      
       };                                                                       
                                                                                
       this.on('message', handler);                                             
     });                                                                        
   }                                                                            
                                                                                
   getPlayerId(): string | null { return this.playerId; }                       
   getToken(): string | null { return this.token; }                             
   getCurrentBattleId(): string | null { return this.currentBattleId; }         
   isConnected(): boolean { return this.connected; }                            
 }                                                                              
                                                                                
 3.2 State Formatter (src/mcp/state-formatter.ts)                               
                                                                                
 export function formatStateForLLM(state: any, yourSide: 'p1' | 'p2'): string { 
   const lines: string[] = [];                                                  
                                                                                
   lines.push(`## Turn ${state.turn}`);                                         
   lines.push('');                                                              
                                                                                
   // Your active Pokemon                                                       
   if (state.yourSide.active) {                                                 
     const p = state.yourSide.active;                                           
     lines.push('### Your Active Pokemon');                                     
     lines.push(`**${p.name}** (${p.species})`);                                
     lines.push(`- HP: ${p.hp}/${p.maxHp} (${p.hpPercent}%)`);                  
     if (p.status) lines.push(`- Status: ${p.status}`);                         
     lines.push(`- Item: ${p.item || 'None'}`);                                 
     lines.push(`- Ability: ${p.ability}`);                                     
     if (Object.keys(p.boosts || {}).length > 0) {                              
       const boostStr = Object.entries(p.boosts)                                
         .filter(([_, v]) => v !== 0)                                           
         .map(([stat, v]) => `${stat}: ${v > 0 ? '+' : ''}${v}`)                
         .join(', ');                                                           
       lines.push(`- Stat changes: ${boostStr}`);                               
     }                                                                          
     lines.push('');                                                            
   }                                                                            
                                                                                
   // Opponent's active Pokemon                                                 
   if (state.opponentSide.active) {                                             
     const p = state.opponentSide.active;                                       
     lines.push('### Opponent Active Pokemon');                                 
     lines.push(`**${p.name}** (${p.species})`);                                
     lines.push(`- HP: ~${p.hpPercent}%`);                                      
     if (p.status) lines.push(`- Status: ${p.status}`);                         
     if (p.revealedAbility) lines.push(`- Known ability:                        
 ${p.revealedAbility}`);                                                        
     if (p.revealedItem) lines.push(`- Known item: ${p.revealedItem}`);         
     if (p.revealedMoves?.length > 0) {                                         
       lines.push(`- Known moves: ${p.revealedMoves.join(', ')}`);              
     }                                                                          
     lines.push('');                                                            
   }                                                                            
                                                                                
   // Field conditions                                                          
   const field = state.field;                                                   
   if (field.weather || field.terrain || field.hazards?.p1?.length ||           
 field.hazards?.p2?.length) {                                                   
     lines.push('### Field Conditions');                                        
     if (field.weather) lines.push(`- Weather: ${field.weather}`);              
     if (field.terrain) lines.push(`- Terrain: ${field.terrain}`);              
     if (field.hazards?.[yourSide]?.length) {                                   
       lines.push(`- Your hazards: ${field.hazards[yourSide].join(', ')}`);     
     }                                                                          
     const oppSide = yourSide === 'p1' ? 'p2' : 'p1';                           
     if (field.hazards?.[oppSide]?.length) {                                    
       lines.push(`- Opponent hazards: ${field.hazards[oppSide].join(', ')}`);  
     }                                                                          
     lines.push('');                                                            
   }                                                                            
                                                                                
   // Available actions                                                         
   lines.push('### Available Actions');                                         
                                                                                
   if (state.availableActions.canMove && state.availableActions.moves.length >  
 0) {                                                                           
     lines.push('**Moves:**');                                                  
     for (const m of state.availableActions.moves) {                            
       const disabled = m.disabled ? ' (DISABLED)' : '';                        
       lines.push(`- ${m.name} [${m.type}] - ${m.pp}/${m.maxPp}                 
 PP${disabled}`);                                                               
     }                                                                          
     lines.push('');                                                            
   }                                                                            
                                                                                
   if (state.availableActions.canSwitch &&                                      
 state.availableActions.switches.length > 0) {                                  
     lines.push('**Available Switches:**');                                     
     for (const s of state.availableActions.switches) {                         
       const statusStr = s.status ? ` [${s.status}]` : '';                      
       lines.push(`- ${s.name}: ${s.hpPercent}% HP${statusStr}`);               
     }                                                                          
     lines.push('');                                                            
   }                                                                            
                                                                                
   // Your bench                                                                
   if (state.yourSide.bench.length > 0) {                                       
     lines.push('### Your Bench');                                              
     for (const p of state.yourSide.bench) {                                    
       const statusStr = p.status ? ` [${p.status}]` : '';                      
       lines.push(`- ${p.name}: ${p.hpPercent}% HP${statusStr}`);               
     }                                                                          
     lines.push('');                                                            
   }                                                                            
                                                                                
   // Opponent's revealed Pokemon                                               
   if (state.opponentSide.revealedPokemon.length > 0) {                         
     lines.push('### Opponent Revealed Pokemon');                               
     for (const p of state.opponentSide.revealedPokemon) {                      
       const statusStr = p.status ? ` [${p.status}]` : '';                      
       const moves = p.revealedMoves?.length > 0 ? ` (knows:                    
 ${p.revealedMoves.join(', ')})` : '';                                          
       lines.push(`- ${p.name}: ~${p.hpPercent}% HP${statusStr}${moves}`);      
     }                                                                          
     lines.push('');                                                            
   }                                                                            
                                                                                
   // Last turn events                                                          
   if (state.lastTurnEvents?.length > 0) {                                      
     lines.push('### Last Turn');                                               
     for (const event of state.lastTurnEvents) {                                
       lines.push(`- ${event}`);                                                
     }                                                                          
   }                                                                            
                                                                                
   return lines.join('\n');                                                     
 }                                                                              
                                                                                
 3.3 MCP Tools (src/mcp/tools.ts)                                               
                                                                                
 import { Tool } from '@modelcontextprotocol/sdk/types.js';                     
                                                                                
 export const tools: Tool[] = [                                                 
   {                                                                            
     name: 'pokemon_register',                                                  
     description: 'Register as a new player on the Pokemon Battle Arena.        
 Required before joining battles. Returns your player ID and auth token (save   
 the token to reconnect later).',                                               
     inputSchema: {                                                             
       type: 'object',                                                          
       properties: {                                                            
         name: {                                                                
           type: 'string',                                                      
           description: 'Your player name (visible to opponents, must be        
 unique)'                                                                       
         }                                                                      
       },                                                                       
       required: ['name']                                                       
     }                                                                          
   },                                                                           
                                                                                
   {                                                                            
     name: 'pokemon_auth',                                                      
     description: 'Authenticate with an existing player ID and token. Use this  
 to reconnect as a previously registered player.',                              
     inputSchema: {                                                             
       type: 'object',                                                          
       properties: {                                                            
         player_id: {                                                           
           type: 'string',                                                      
           description: 'Your player ID from registration'                      
         },                                                                     
         token: {                                                               
           type: 'string',                                                      
           description: 'Your auth token from registration'                     
         }                                                                      
       },                                                                       
       required: ['player_id', 'token']                                         
     }                                                                          
   },                                                                           
                                                                                
   {                                                                            
     name: 'pokemon_join_queue',                                                
     description: 'Join the matchmaking queue to find an opponent. You will be  
 matched with another player of similar Elo rating. The battle starts           
 automatically when matched.',                                                  
     inputSchema: {                                                             
       type: 'object',                                                          
       properties: {                                                            
         format: {                                                              
           type: 'string',                                                      
           enum: ['gen4ou'],                                                    
           description: 'Battle format. Currently only gen4ou (DPP OU) is       
 supported.'                                                                    
         }                                                                      
       },                                                                       
       required: ['format']                                                     
     }                                                                          
   },                                                                           
                                                                                
   {                                                                            
     name: 'pokemon_leave_queue',                                               
     description: 'Leave the matchmaking queue without finding a match.',       
     inputSchema: {                                                             
       type: 'object',                                                          
       properties: {}                                                           
     }                                                                          
   },                                                                           
                                                                                
   {                                                                            
     name: 'pokemon_get_battle_state',                                          
     description: 'Get the current state of your active battle. Returns your    
 Pokemon, opponent\'s revealed Pokemon, field conditions, and available         
 actions. Call this at the start of each turn to see what\'s happening.',       
     inputSchema: {                                                             
       type: 'object',                                                          
       properties: {}                                                           
     }                                                                          
   },                                                                           
                                                                                
   {                                                                            
     name: 'pokemon_choose_action',                                             
     description: 'Choose your action for the current turn. Either use a move   
 or switch to another Pokemon.',                                                
     inputSchema: {                                                             
       type: 'object',                                                          
       properties: {                                                            
         action_type: {                                                         
           type: 'string',                                                      
           enum: ['move', 'switch'],                                            
           description: 'Whether to use a move or switch Pokemon'               
         },                                                                     
         target: {                                                              
           type: 'string',                                                      
           description: 'For moves: the move name or number (1-4). For          
 switches: the Pokemon name.'                                                   
         }                                                                      
       },                                                                       
       required: ['action_type', 'target']                                      
     }                                                                          
   },                                                                           
                                                                                
   {                                                                            
     name: 'pokemon_forfeit',                                                   
     description: 'Forfeit the current battle. This counts as a loss and will   
 decrease your Elo rating.',                                                    
     inputSchema: {                                                             
       type: 'object',                                                          
       properties: {}                                                           
     }                                                                          
   },                                                                           
                                                                                
   {                                                                            
     name: 'pokemon_get_leaderboard',                                           
     description: 'View the current leaderboard rankings showing top players by 
  Elo.',                                                                        
     inputSchema: {                                                             
       type: 'object',                                                          
       properties: {                                                            
         limit: {                                                               
           type: 'number',                                                      
           description: 'Number of entries to return (default 20, max 100)'     
         }                                                                      
       }                                                                        
     }                                                                          
   },                                                                           
                                                                                
   {                                                                            
     name: 'pokemon_get_my_stats',                                              
     description: 'Get your own ranking, Elo rating, and win/loss record.',     
     inputSchema: {                                                             
       type: 'object',                                                          
       properties: {}                                                           
     }                                                                          
   }                                                                            
 ];                                                                             
                                                                                
 3.4 MCP Server (src/mcp/index.ts)                                              
                                                                                
 import { Server } from '@modelcontextprotocol/sdk/server/index.js';            
 import { StdioServerTransport } from                                           
 '@modelcontextprotocol/sdk/server/stdio.js';                                   
 import { CallToolRequestSchema, ListToolsRequestSchema } from                  
 '@modelcontextprotocol/sdk/types.js';                                          
 import { tools } from './tools';                                               
 import { ArenaClient } from './client';                                        
 import { formatStateForLLM } from './state-formatter';                         
                                                                                
 const ARENA_SERVER = process.env.POKEMON_ARENA_SERVER ||                       
 'ws://localhost:3000';                                                         
 const SAVED_PLAYER_ID = process.env.POKEMON_ARENA_PLAYER_ID;                   
 const SAVED_TOKEN = process.env.POKEMON_ARENA_TOKEN;                           
                                                                                
 class PokemonArenaMCP {                                                        
   private server: Server;                                                      
   private client: ArenaClient;                                                 
   private yourSide: 'p1' | 'p2' | null = null;                                 
   private latestState: any = null;                                             
                                                                                
   constructor() {                                                              
     this.server = new Server(                                                  
       { name: 'pokemon-arena', version: '1.0.0' },                             
       { capabilities: { tools: {} } }                                          
     );                                                                         
                                                                                
     this.client = new ArenaClient(ARENA_SERVER);                               
     this.setupHandlers();                                                      
   }                                                                            
                                                                                
   private setupHandlers(): void {                                              
     this.server.setRequestHandler(ListToolsRequestSchema, async () => ({       
       tools                                                                    
     }));                                                                       
                                                                                
     this.server.setRequestHandler(CallToolRequestSchema, async (request) => {  
       return this.handleToolCall(request.params.name, request.params.arguments 
  || {});                                                                       
     });                                                                        
                                                                                
     // Listen for battle state updates                                         
     this.client.on('message', (msg) => {                                       
       if (msg.type === 'battle_start') {                                       
         this.yourSide = msg.yourSide;                                          
       }                                                                        
       if (msg.type === 'battle_state') {                                       
         this.latestState = msg.state;                                          
       }                                                                        
       if (msg.type === 'battle_end') {                                         
         this.yourSide = null;                                                  
         this.latestState = null;                                               
       }                                                                        
     });                                                                        
   }                                                                            
                                                                                
   private async handleToolCall(name: string, args: any): Promise<any> {        
     // Ensure connected                                                        
     if (!this.client.isConnected()) {                                          
       await this.client.connect();                                             
                                                                                
       // Auto-auth if credentials saved                                        
       if (SAVED_PLAYER_ID && SAVED_TOKEN) {                                    
         this.client.send({ type: 'auth', playerId: SAVED_PLAYER_ID, token:     
 SAVED_TOKEN });                                                                
         await this.client.waitForMessage('auth_success');                      
       }                                                                        
     }                                                                          
                                                                                
     switch (name) {                                                            
       case 'pokemon_register': {                                               
         this.client.send({ type: 'register', name: args.name });               
         const response = await this.client.waitForMessage('registered');       
         return {                                                               
           content: [{                                                          
             type: 'text',                                                      
             text: `Registered successfully!\nPlayer ID:                        
 ${response.playerId}\nToken: ${response.token}\n\nSave these credentials to    
 reconnect later.`                                                              
           }]                                                                   
         };                                                                     
       }                                                                        
                                                                                
       case 'pokemon_auth': {                                                   
         this.client.send({ type: 'auth', playerId: args.player_id, token:      
 args.token });                                                                 
         try {                                                                  
           const response = await this.client.waitForMessage('auth_success');   
           return {                                                             
             content: [{ type: 'text', text: `Authenticated as                  
 ${response.name}` }]                                                           
           };                                                                   
         } catch {                                                              
           return {                                                             
             content: [{ type: 'text', text: 'Authentication failed. Check your 
  credentials.' }],                                                             
             isError: true                                                      
           };                                                                   
         }                                                                      
       }                                                                        
                                                                                
       case 'pokemon_join_queue': {                                             
         this.client.send({ type: 'join_queue', format: args.format });         
         const response = await this.client.waitForMessage('queue_joined');     
                                                                                
         // Wait for battle start (could take a while)                          
         return {                                                               
           content: [{                                                          
             type: 'text',                                                      
             text: `Joined ${response.format} queue (position                   
 ${response.position}). Waiting for opponent...\n\nCall                         
 pokemon_get_battle_state periodically to check if a battle has started.`       
           }]                                                                   
         };                                                                     
       }                                                                        
                                                                                
       case 'pokemon_leave_queue': {                                            
         this.client.send({ type: 'leave_queue' });                             
         return { content: [{ type: 'text', text: 'Left the matchmaking queue.' 
  }] };                                                                         
       }                                                                        
                                                                                
       case 'pokemon_get_battle_state': {                                       
         if (!this.latestState) {                                               
           // Check if battle has started                                       
           const battle = this.client.getCurrentBattleId();                     
           if (!battle) {                                                       
             return {                                                           
               content: [{ type: 'text', text: 'No active battle. Join the      
 queue to find an opponent.' }]                                                 
             };                                                                 
           }                                                                    
           return {                                                             
             content: [{ type: 'text', text: 'Waiting for battle state...' }]   
           };                                                                   
         }                                                                      
                                                                                
         const formatted = formatStateForLLM(this.latestState, this.yourSide!); 
         return { content: [{ type: 'text', text: formatted }] };               
       }                                                                        
                                                                                
       case 'pokemon_choose_action': {                                          
         const battleId = this.client.getCurrentBattleId();                     
         if (!battleId) {                                                       
           return {                                                             
             content: [{ type: 'text', text: 'No active battle.' }],            
             isError: true                                                      
           };                                                                   
         }                                                                      
                                                                                
         let action: string;                                                    
         if (args.action_type === 'move') {                                     
           // Try to match move name or number                                  
           const moveNum = parseInt(args.target);                               
           if (!isNaN(moveNum) && moveNum >= 1 && moveNum <= 4) {               
             action = `move ${moveNum}`;                                        
           } else {                                                             
             // Find move by name                                               
             const moveIndex =                                                  
 this.latestState?.availableActions?.moves?.findIndex(                          
               (m: any) => m.name.toLowerCase() === args.target.toLowerCase()   
             );                                                                 
             if (moveIndex >= 0) {                                              
               action = `move ${moveIndex + 1}`;                                
             } else {                                                           
               action = `move ${args.target}`;  // Let server handle it         
             }                                                                  
           }                                                                    
         } else {                                                               
           // Switch                                                            
           const switchIndex =                                                  
 this.latestState?.availableActions?.switches?.findIndex(                       
             (s: any) => s.name.toLowerCase() === args.target.toLowerCase()     
           );                                                                   
           if (switchIndex >= 0) {                                              
             action = `switch ${switchIndex + 2}`;  // +2 because index 1 is    
 active                                                                         
           } else {                                                             
             action = `switch ${args.target}`;                                  
           }                                                                    
         }                                                                      
                                                                                
         this.client.send({ type: 'action', battleId, action });                
                                                                                
         try {                                                                  
           await this.client.waitForMessage('action_accepted', 5000);           
           return { content: [{ type: 'text', text: `Action submitted:          
 ${action}. Waiting for opponent...` }] };                                      
         } catch {                                                              
           const rejected = await this.client.waitForMessage('action_rejected', 
  1000).catch(() => null);                                                      
           return {                                                             
             content: [{ type: 'text', text: `Action rejected:                  
 ${rejected?.reason || 'Unknown error'}` }],                                    
             isError: true                                                      
           };                                                                   
         }                                                                      
       }                                                                        
                                                                                
       case 'pokemon_forfeit': {                                                
         const battleId = this.client.getCurrentBattleId();                     
         if (!battleId) {                                                       
           return { content: [{ type: 'text', text: 'No active battle to        
 forfeit.' }] };                                                                
         }                                                                      
         this.client.send({ type: 'forfeit', battleId });                       
         return { content: [{ type: 'text', text: 'Battle forfeited.' }] };     
       }                                                                        
                                                                                
       case 'pokemon_get_leaderboard': {                                        
         this.client.send({ type: 'get_leaderboard', format: 'gen4ou', limit:   
 args.limit || 20 });                                                           
         const response = await this.client.waitForMessage('leaderboard');      
                                                                                
         const lines = ['# Leaderboard (Gen 4 OU)', ''];                        
         for (const entry of response.entries) {                                
           lines.push(`${entry.rank}. **${entry.name}** - ${entry.elo} Elo      
 (${entry.wins}W/${entry.losses}L)`);                                           
         }                                                                      
                                                                                
         return { content: [{ type: 'text', text: lines.join('\n') }] };        
       }                                                                        
                                                                                
       case 'pokemon_get_my_stats': {                                           
         this.client.send({ type: 'get_my_stats' });                            
         const response = await this.client.waitForMessage('my_stats');         
                                                                                
         return {                                                               
           content: [{                                                          
             type: 'text',                                                      
             text: `# Your Stats\n\n- **Rank**: #${response.rank}\n- **Elo**:   
 ${response.elo}\n- **Record**: ${response.wins}W / ${response.losses}L /       
 ${response.draws}D`                                                            
           }]                                                                   
         };                                                                     
       }                                                                        
                                                                                
       default:                                                                 
         return {                                                               
           content: [{ type: 'text', text: `Unknown tool: ${name}` }],          
           isError: true                                                        
         };                                                                     
     }                                                                          
   }                                                                            
                                                                                
   async run(): Promise<void> {                                                 
     const transport = new StdioServerTransport();                              
     await this.server.connect(transport);                                      
     console.error('Pokemon Arena MCP server running');                         
   }                                                                            
 }                                                                              
                                                                                
 const mcp = new PokemonArenaMCP();                                             
 mcp.run().catch(console.error);                                                
                                                                                
 3.5 MCP Configuration                                                          
                                                                                
 Users add to their Claude Code MCP config (~/.claude/config.json):             
                                                                                
 {                                                                              
   "mcpServers": {                                                              
     "pokemon-arena": {                                                         
       "command": "npx",                                                        
       "args": ["ts-node", "/path/to/llm-pokemon-arena/src/mcp/index.ts"],      
       "env": {                                                                 
         "POKEMON_ARENA_SERVER": "ws://localhost:3000"                          
       }                                                                        
     }                                                                          
   }                                                                            
 }                                                                              
                                                                                
 Or after npm publish:                                                          
 {                                                                              
   "mcpServers": {                                                              
     "pokemon-arena": {                                                         
       "command": "npx",                                                        
       "args": ["llm-pokemon-arena"],                                           
       "env": {                                                                 
         "POKEMON_ARENA_SERVER": "ws://localhost:3000",                         
         "POKEMON_ARENA_PLAYER_ID": "optional-saved-id",                        
         "POKEMON_ARENA_TOKEN": "optional-saved-token"                          
       }                                                                        
     }                                                                          
   }                                                                            
 }                                                                              
                                                                                
 ---                                                                            
 Verification Plan                                                              
                                                                                
 Phase 1 Verification                                                           
                                                                                
 # 1. Build succeeds                                                            
 npm run build                                                                  
                                                                                
 # 2. Teams load correctly                                                      
 npm run battle:local                                                           
 # Should print "Loaded 6 teams"                                                
                                                                                
 # 3. Manual CLI battle works                                                   
 # Play through a full battle manually, verify moves work                       
                                                                                
 Phase 2 Verification                                                           
                                                                                
 # 1. Start server                                                              
 npm run server:start                                                           
                                                                                
 # 2. Connect two WebSocket clients (using wscat or similar)                    
 wscat -c ws://localhost:3000                                                   
                                                                                
 # 3. In client 1:                                                              
 {"type":"register","name":"Player1"}                                           
 {"type":"join_queue","format":"gen4ou"}                                        
                                                                                
 # 4. In client 2:                                                              
 {"type":"register","name":"Player2"}                                           
 {"type":"join_queue","format":"gen4ou"}                                        
                                                                                
 # 5. Both should receive battle_start, then battle_state                       
 # 6. Submit moves and verify battle progresses                                 
                                                                                
 Phase 3 Verification                                                           
                                                                                
 # 1. Configure MCP server in Claude Code                                       
 # 2. Start a conversation with Claude Code                                     
 # 3. Ask Claude to register and join a battle:                                 
                                                                                
 "Register as a player called 'ClaudeTest' on the Pokemon arena"                
 # Claude uses pokemon_register tool                                            
                                                                                
 "Join the gen4ou battle queue"                                                 
 # Claude uses pokemon_join_queue tool                                          
                                                                                
 # 4. In another terminal, have a second player join                            
 # 5. Battle should start, Claude receives state                                
 # 6. Play through a full battle with Claude making decisions                   
                                                                                
 End-to-End Test                                                                
                                                                                
 Have two separate Claude Code instances battle each other:                     
 1. Start server                                                                
 2. Configure MCP in both Claude Code instances                                 
 3. Ask each Claude to register with different names                            
 4. Ask both to join queue                                                      
 5. They should match and battle                                                
 6. Observe battle progress and final Elo updates                               
                                                                                
 ---                                                                            
 Dependencies                                                                   
                                                                                
 {                                                                              
   "dependencies": {                                                            
     "pokemon-showdown": "^0.11.0",                                             
     "ws": "^8.16.0",                                                           
     "better-sqlite3": "^9.4.0",                                                
     "@modelcontextprotocol/sdk": "^0.6.0"                                      
   },                                                                           
   "devDependencies": {                                                         
     "typescript": "^5.3.0",                                                    
     "@types/node": "^20.0.0",                                                  
     "@types/ws": "^8.5.0",                                                     
     "@types/better-sqlite3": "^7.6.0",                                         
     "ts-node": "^10.9.0",                                                      
     "vitest": "^1.2.0"                                                         
   }                                                                            
 }                                                                              
                                                                                
 ---                                                                            
 Notes for Implementing Agent                                                   
                                                                                
 1. Start with Phase 1 - Get the battle runner and state parser working first   
 2. Test incrementally - Verify each component works before moving on           
 3. The team files are already in place at Raw-Teams/ in Showdown paste format  
 4. Format is gen4ou (DPP OU)                    
 5. Turn timeout is 3 minutes with random move fallback, no harsh penalties     
 6. No anti-cheat needed - LLMs using simulators is fine                        
 7. SQLite for storage - Simple, no external database needed                    
 8. MCP uses stdio transport - Standard for Claude Code integration  