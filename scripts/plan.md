LLM Arena: Code Review & Architecture Plan                                                                                                
                                                                                                                                          
Executive Summary                                                                                                                         
                                                                                                                                          
The battle engine (src/) is fundamentally sound — the LLM-tool integration, battle state formatting, logging, and player abstractions all 
work. The main problems are: (1) error handling in llm_player.py treats all API errors identically, (2) the tournament scripts are a     
mess of duplicated code with no resumability, and (3) there's no shared config module. The fix is surgical: patch error handling, extract 
shared config, and replace the tournament scripts with a single manifest-based runner.                                                   
                                                                                                                                          
Design Principles                                                                                                                         
                                                                                                                                          
These are the properties that matter for a project you'd demo to Ramp:                                                                    
                                                                                                                                          
- Idempotency: Running the same script twice must not break things. generate checks for existing matches. run skips completed matches.    
- Failure isolation: One match crashing must not take down the tournament. Errors are classified, recorded per-match, and the runner      
moves on.                                                                                                                                 
- Resumability: Stop the script at any time (Ctrl-C, laptop sleep, API outage). Restart it. It picks up where it left off.                
- Observability: Every match has structured logs (JSONL), the manifest is human-readable JSON you can cat, and status gives you a         
dashboard.                                                                                                                                
                                                                                                                                          
---                                                                                                                                       
Part 1: Code Review                                                                                                                       
                                                                                                                                          
src/ — Verdict: Keep, with targeted fixes                                                                                                 
                                                                                                                                          
Files that are good as-is (no changes needed):                                                                                            
- src/agent_player.py — Clean base class. Decision history, logging hooks, fallback handling all work.                                    
- src/battle_logger.py — JSONL crash-safe logging with incremental protocol writes. Solid.                                                
- src/team_pool.py — Simple, functional.                                                                                                  
- src/state_formatter.py — Converts battle state to structured text for LLMs. Works.                                                      
- src/event_formatter.py — Ports Showdown protocol to readable text. Works.                                                               
- src/response_parser.py — Fuzzy action parsing. Works well enough; edge cases are tolerable.                                             
- src/player_factory.py — Good factory pattern with auto-fallback.                                                                        
- src/env_manager.py — API key management. Works.                                                                                         
- src/results.py — SQLite Elo tracking. Works.                                                                                            
- src/human_player.py — Interactive testing. Works.                                                                                       
                                                                                                                                          
Files that need changes:                                                                                                                  
                                                                                                                                          
src/llm_player.py — Critical: error classification                                                                                        
                                                                                                                                          
The _execute_generation method (lines 146-262) has a while True loop that catches all exceptions identically:                             
except Exception as e:                                                                                                                    
    print(f"[{self.username}] API Error: {e}. Retrying in 60s...")                                                                        
    await asyncio.sleep(60)                                                                                                               
    continue                                                                                                                              
This is the root cause of your rate-limiting concern. A rate limit error should back off and retry (it's transient). A context window     
error should fail immediately (it's structural). A timeout mid-battle is different from a connection timeout. Currently they all just     
sleep 60s and retry forever.                                                                                                              
                                                                                                                                          
Bug on line 206: Tool call ID concatenation appends to itself (entry["id"] += tc.id) — should be = not += since the ID comes in one       
chunk, not streamed in pieces. In practice this works because IDs usually arrive in a single chunk, but it's wrong.                       
                                                                                                                                          
Dead code on line 282: plan_text = "" with the actual call commented out. Should be removed or restored.                                  
                                                                                                                                          
src/tournament.py — Minor: extract ModelConfig                                                                                            
                                                                                                                                          
ModelConfig is defined here AND in 3 scripts. Should live in one shared place. The run_tournament function uses poke-env's                
cross_evaluate() which runs battles sequentially — fine for small tournaments but not for the parallel execution you want.                
                                                                                                                                          
src/tools/ — Verdict: Keep as-is                                                                                                          
                                                                                                                                          
The tool system (registry, damage calc, type matchups, speed, field analysis, team info) is architecturally clean. There are minor        
calculation inaccuracies (speed formula in speed_tools.py:86, weather loop in field_tools.py:25-26) but these affect LLM advice quality,  
not system correctness. Not worth touching now.                                                                                           
                                                                                                                                          
scripts/ — Verdict: Replace tournament scripts                                                                                            
Script: run_tournament.py                                                                                                                 
Status: Replace                                                                                                                           
Issue: Thin wrapper around sequential cross_evaluate(). No parallelism, no resume, no error classification.                               
────────────────────────────────────────                                                                                                  
Script: llm_round_robin.py                                                                                                                
Status: Replace                                                                                                                           
Issue: Has parallelism and deadlock prevention (good ideas), but: infinite retry loop, token tracking never populated, hardcoded model    
  list, duplicate imports, no resume.                                                                                                     
────────────────────────────────────────                                                                                                  
Script: llm_vs_llm.py                                                                                                                     
Status: Keep                                                                                                                              
Issue: Useful for ad-hoc 1v1 testing. Works.                                                                                              
────────────────────────────────────────                                                                                                  
Script: benchmark_vs_heuristic.py                                                                                                         
Status: Keep                                                                                                                              
Issue: Useful for baseline testing. Has a debug print to remove.                                                                          
────────────────────────────────────────                                                                                                  
Script: heuristic_round_robin.py                                                                                                          
Status: Keep                                                                                                                              
Issue: Useful for team balance testing.                                                                                                   
────────────────────────────────────────                                                                                                  
Script: human_vs_heuristic.py                                                                                                             
Status: Keep                                                                                                                              
Issue: Useful for interactive testing.                                                                                                    
────────────────────────────────────────                                                                                                  
Script: check_model_availability.py                                                                                                       
Status: Keep                                                                                                                              
Issue: Useful diagnostic.                                                                                                                 
Core duplication problem: ModelConfig and load_models_from_yaml() are copy-pasted across run_tournament.py, llm_round_robin.py,           
llm_vs_llm.py, and benchmark_vs_heuristic.py — each with slightly different fields.                                                       
                                                                                                                                          
---                                                                                                                                       
Part 2: Architecture Plan                                                                                                                 
                                                                                                                                          
Changes Required (4 files modified, 2 files created)                                                                                      
                                                                                                                                          
1. NEW: src/config.py — Shared model configuration                                                                                        
                                                                                                                                          
Single source of truth for ModelConfig and YAML loading. All scripts import from here.                                                    
                                                                                                                                          
@dataclass                                                                                                                                
class ModelConfig:                                                                                                                        
    name: str                                                                                                                             
    model: str           # LiteLLM model ID                                                                                               
    temperature: float = 0.7                                                                                                              
    max_tokens: int = 4096                                                                                                                
    timeout: float = 60.0                                                                                                                 
    team: str | None = None                                                                                                               
    force_fallback: bool = False                                                                                                          
    api_price_input: float = 0.0                                                                                                          
    api_price_output: float = 0.0                                                                                                         
                                                                                                                                          
def load_models_from_yaml(path: str) -> list[ModelConfig]: ...                                                                            
def find_model(query: str, models: list[ModelConfig]) -> ModelConfig | None: ...                                                          
                                                                                                                                          
This eliminates the 4-way duplication. src/tournament.py re-exports it for backward compat.                                               
                                                                                                                                          
2. MODIFY: src/llm_player.py — Classified error handling                                                                                  
                                                                                                                                          
Replace the catch-all in _execute_generation (lines 258-262) with:                                                                        
                                                                                                                                          
except litellm.RateLimitError as e:                                                                                                       
    retry_count += 1                                                                                                                      
    if retry_count > 15:                                                                                                                  
        raise                                                                                                                             
    wait = min(10 * (2 ** retry_count) + random.uniform(0, 5), 300)                                                                       
    print(f"[{self.username}] Rate limited. Retry {retry_count}/15 in {wait:.0f}s")                                                       
    await asyncio.sleep(wait)                                                                                                             
    continue                                                                                                                              
                                                                                                                                          
except litellm.Timeout as e:                                                                                                              
    retry_count += 1                                                                                                                      
    if retry_count > 2:                                                                                                                   
        raise                                                                                                                             
    print(f"[{self.username}] Timeout. Retry {retry_count}/2...")                                                                         
    continue                                                                                                                              
                                                                                                                                          
except (litellm.APIConnectionError, litellm.ServiceUnavailableError) as e:                                                                
    retry_count += 1                                                                                                                      
    if retry_count > 3:                                                                                                                   
        raise                                                                                                                             
    wait = 15 * retry_count                                                                                                               
    print(f"[{self.username}] Connection error. Retry {retry_count}/3 in {wait}s")                                                        
    await asyncio.sleep(wait)                                                                                                             
    continue                                                                                                                              
                                                                                                                                          
except litellm.ContextWindowExceededError:                                                                                                
    raise  # Structural — don't retry                                                                                                     
                                                                                                                                          
except Exception as e:                                                                                                                    
    retry_count += 1                                                                                                                      
    if retry_count > 2:                                                                                                                   
        raise                                                                                                                             
    print(f"[{self.username}] Unexpected error: {e}. Retry {retry_count}/2...")                                                           
    await asyncio.sleep(10)                                                                                                               
    continue                                                                                                                              
                                                                                                                                          
Also fix: tool call ID concatenation (line 206), remove dead plan_text code (line 282).                                                   
                                                                                                                                          
3. NEW: src/mock_player.py — Mock player for testing                                                                                      
                                                                                                                                          
Extends AgentPlayer (same base as LLMPlayer). Picks random moves but goes through the full choose_move pipeline (logging, decision        
history, etc.). Supports configurable error injection to test the tournament runner's error handling without burning API credits.         
                                                                                                                                          
4. NEW: scripts/run_round_robin.py — Manifest-based tournament runner                                                                     
                                                                                                                                          
Three subcommands:                                                                                                                        
                                                                                                                                          
generate — Create match manifest                                                                                                          
python scripts/run_round_robin.py generate \                                                                                              
  --models Gemini-3-Flash GPT-5-Mini Claude-Haiku-4.5 GPT-4.1 \                                                                           
  --games-per-pair 3 \                                                                                                                    
  --output tournament.json                                                                                                                
- Reads config/models.yaml, validates API keys                                                                                            
- Generates all C(n,2) pairings                                                                                                           
- Assigns teams: each model rotates through teams so no model plays the same team twice (when possible). Ensures no match has both sides  
using the same team.                                                                                                                      
- Writes manifest JSON to disk                                                                                                            
                                                                                                                                          
run — Execute matches from manifest                                                                                                       
python scripts/run_round_robin.py run \                                                                                                   
  --manifest tournament.json \                                                                                                            
  --concurrent 6 \                                                                                                                        
  --per-model-concurrent 3                                                                                                                
- Loads manifest, filters to pending or failed matches (skip completed)                                                                   
- Two-layer concurrency: global semaphore + per-model semaphores (sorted lock acquisition to prevent deadlocks, same pattern as           
llm_round_robin.py but done correctly)                                                                                                    
- On completion: updates manifest entry with {status: "completed", winner, battle_id}                                                     
- On failure (exception propagated from classified error handling): marks {status: "failed", error, attempts++}                           
- Atomic manifest writes: write to .tmp then os.replace()                                                                                 
- SIGINT handler: saves manifest state before exit                                                                                        
- Prints progress and results summary                                                                                                     
                                                                                                                                          
status — Show tournament progress                                                                                                         
python scripts/run_round_robin.py status --manifest tournament.json                                                                       
- Shows completed/pending/failed counts                                                                                                   
- Per-model win rates                                                                                                                     
- Lists failed matches for investigation                                                                                                  
                                                                                                                                          
Manifest JSON format:                                                                                                                     
{                                                                                                                                         
  "tournament": {                                                                                                                         
    "name": "round-robin-2026-01-26",                                                                                                     
    "format": "gen4ou",                                                                                                                   
    "models": ["Gemini-3-Flash", "GPT-5-Mini", "Claude-Haiku-4.5", "GPT-4.1"],                                                            
    "games_per_pair": 3,                                                                                                                  
    "created_at": "2026-01-26T10:00:00Z"                                                                                                  
  },                                                                                                                                      
  "matches": [                                                                                                                            
    {                                                                                                                                     
      "id": 1,                                                                                                                            
      "model_a": "Gemini-3-Flash",                                                                                                        
      "model_b": "GPT-5-Mini",                                                                                                            
      "team_a": "Dragonite-Lead-Boom-Offense",                                                                                            
      "team_b": "Forretress-Zapdos-Balance",                                                                                              
      "status": "pending",                                                                                                                
      "result": null,                                                                                                                     
      "winner": null,                                                                                                                     
      "error": null,                                                                                                                      
      "attempts": 0,                                                                                                                      
      "battle_id": null                                                                                                                   
    }                                                                                                                                     
  ]                                                                                                                                       
}                                                                                                                                         
                                                                                                                                          
Status lifecycle: pending → running → completed | failed                                                                                  
                                                                                                                                          
On startup, the runner resets any running matches back to pending (they were interrupted mid-execution). This makes the runner crash-safe 
without needing heartbeats or process locks.                                                                                             
                                                                                                                                          
5. MODIFY: scripts/llm_vs_llm.py — Use shared config                                                                                      
                                                                                                                                          
Import ModelConfig and load_models_from_yaml from src.config instead of defining locally. Otherwise keep as-is.                           
                                                                                                                                          
6. MODIFY: scripts/benchmark_vs_heuristic.py — Use shared config + remove debug print                                                     
                                                                                                                                          
Import from src.config, remove the debug print on line 272.                                                                               
                                                                                                                                          
---                                                                                                                                       
Part 3: What NOT to Change                                                                                                                
                                                                                                                                          
- src/tools/ — All tool files stay as-is. Calculation bugs are cosmetic.                                                                  
- src/agent_player.py — Works.                                                                                                            
- src/battle_logger.py — Works. The filename sanitization gap (no : or * handling) doesn't matter on macOS/Linux.                         
- src/response_parser.py — Fuzzy matching is a feature, not a bug. LLMs produce varied output.                                            
- scripts/llm_vs_llm.py — Keep for ad-hoc 1v1 testing (just update imports).                                                              
- scripts/run_tournament.py, scripts/llm_round_robin.py — Leave in place, superseded by run_round_robin.py. Can delete later.             
                                                                                                                                          
---                                                                                                                                       
Part 4: Design Tradeoffs — Why This and Not That                                                                                          
                                                                                                                                          
An alternative review suggested a heavier architecture: SQLite as the manifest store, Pydantic models, tenacity for retries, an injected  
SafeLLMClient, and a src/core/ + src/engine/ + src/agents/ directory restructure. Here's why I'm not recommending those:                  
Suggestion: SQLite manifest                                                                                                               
Verdict: Skip                                                                                                                             
Reasoning: For 18 matches, JSON is simpler, more inspectable (cat tournament.json), and git-friendly. os.replace() gives atomic writes.   
  You already have results.py with SQLite for Elo tracking — that's where persistent analytics belong. The manifest is ephemeral          
  per-tournament.                                                                                                                         
────────────────────────────────────────                                                                                                  
Suggestion: Pydantic models                                                                                                               
Verdict: Skip                                                                                                                             
Reasoning: Adds a dependency. Dataclasses are sufficient for ~5 config fields. Pydantic's validation benefits don't justify the import    
  cost for a project this size.                                                                                                           
────────────────────────────────────────                                                                                                  
Suggestion: tenacity library                                                                                                              
Verdict: Skip                                                                                                                             
Reasoning: The retry logic wraps an async streaming generator with accumulated partial state. Hand-rolling 20 lines of classified except  
  blocks is cleaner than configuring tenacity decorators around that. tenacity shines for simple request/response calls, not              
  streaming accumulation loops.                                                                                                           
────────────────────────────────────────                                                                                                  
Suggestion: Injected SafeLLMClient                                                                                                        
Verdict: Skip                                                                                                                             
Reasoning: The retry logic lives naturally inside _execute_generation where it already is. Adding a separate client class creates         
  indirection without benefit. The current architecture (player owns its generation method) is fine.                                      
────────────────────────────────────────                                                                                                  
Suggestion: Directory restructure                                                                                                         
Verdict: Skip                                                                                                                             
Reasoning: 15 source files don't need subdirectories. src/core/schemas.py with 2 dataclasses in it is worse than src/config.py. Flat      
  structure keeps imports simple.                                                                                                         
────────────────────────────────────────                                                                                                  
Suggestion: Separate tournament_cfg.yaml                                                                                                  
Verdict: Skip                                                                                                                             
Reasoning: CLI args + models.yaml is sufficient. Another YAML file adds friction for no gain.                                             
What I did integrate from that review:                                                                                                    
- Idempotency as an explicit design principle — generate is idempotent, run is resumable                                                  
- running status — matches marked running are reset to pending on restart (crash safety)                                                  
- Failure isolation framing — each match is an independent unit of work; failures don't cascade                                           
- OpenAI Evals / LMSYS Chatbot Arena as reference architectures (see Research section)                                                    
                                                                                                                                          
The overall philosophy: this is a 15-file project running 18 matches. The right amount of architecture is "manifest file + classified     
error handling + two-layer semaphores." Not a job queue framework.                                                                        
                                                                                                                                          
---                                                                                                                                       
Part 5: Research — Relevant Projects & Articles                                                                                           
                                                                                                                                          
Directly Relevant Pokemon LLM Projects                                                                                                    
                                                                                                                                          
- PokeLLMon (Georgia Tech) — First LLM agent to hit human-parity in Pokemon battles. Uses in-context reinforcement learning and           
knowledge-augmented generation. GPT-4 alone gets 26% win rate; their framework gets 49%. Paper: https://arxiv.org/abs/2402.01118          
- PokeChamp — Combines LLM with minimax tree search. 76% win rate vs best LLM bot, Elo 1300-1500 on Showdown ladder.                      
https://sites.google.com/view/pokechamp-llm                                                                                               
- LLM Pokemon League — Multi-agent tournament framework for Pokemon, published Aug 2025. Very similar to your project.                    
https://arxiv.org/abs/2508.01623                                                                                                          
                                                                                                                                          
Ramp Labs                                                                                                                                 
                                                                                                                                          
- LLM Games — Ramp Labs built a project where LLMs play Connect Four against each other. Conceptually identical to your project.          
https://labs.ramp.com/llm-games                                                                                                           
- Ramp Labs overview — 17-person Applied AI team, they do experiments with RL and LLM agents.                                             
https://ramp.com/velocity/an-inside-look-at-ramp-labs                                                                                     
                                                                                                                                          
LLM Agent Evaluation                                                                                                                      
                                                                                                                                          
- Qi Town — Round-robin tournament framework for LLMs playing board games, with Elo ratings and Performance Loop Graphs.                  
https://arxiv.org/html/2508.04720v1                                                                                                       
- AgentBench — Multi-dimensional benchmark with 8 environments (including a card game). https://arxiv.org/abs/2308.03688                  
                                                                                                                                          
API Rate Limiting                                                                                                                         
                                                                                                                                          
- Portkey — Practical strategies: exponential backoff, caching, request batching, automatic fallback to alternative providers.            
https://portkey.ai/blog/tackling-rate-limiting-for-llm-apps/                                                                              
- Nordic APIs — "Adaptive Rate Limiting" trend for AI agents with spiky traffic.                                                          
https://nordicapis.com/how-ai-agents-are-changing-api-rate-limit-approaches/                                                              
                                                                                                                                          
Reference Architectures                                                                                                                   
                                                                                                                                          
- OpenAI Evals — Similar pattern: define a registry of evaluations (manifest), run them, record results to JSONL, compute metrics. Your   
project is essentially "evals but the eval is a Pokemon battle."                                                                          
- LMSYS Chatbot Arena — The canonical "Elo rating from pairwise LLM matches" system. Your round-robin is a controlled version of their    
approach.                                                                                                                                 
                                                                                                                                          
---                                                                                                                                       
Part 6: Verification Plan                                                                                                                 
                                                                                                                                          
1. Unit test error classification: Run src/mock_player.py with each error type, verify correct retry/propagation behavior                 
2. Generate manifest: python scripts/run_round_robin.py generate --models Gemini-3-Flash GPT-5-Mini --games-per-pair 1 --output test.json 
— inspect JSON, verify team uniqueness                                                                                                   
3. Run with mock (no errors): python scripts/run_round_robin.py run --manifest test.json --mock — verify all matches complete, manifest   
updates                                                                                                                                   
4. Run with mock (errors): python scripts/run_round_robin.py run --manifest test.json --mock --error-rate 0.3 — verify failed matches     
recorded, soft errors trigger fallback                                                                                                    
5. Resume: Re-run step 4 — verify completed matches skipped, only pending/failed re-run                                                   
6. Status: python scripts/run_round_robin.py status --manifest test.json — verify display                                                 
7. Full mock tournament: 4 models, 3 games/pair, concurrency 6 — verify all 18 matches complete                                           
8. Real 1v1 smoke test: python scripts/llm_vs_llm.py --a Gemini-3-Flash --b GPT-5-Mini --battles 1 — verify error classification works    
with real APIs                                                                                                                            
                                                                                                                                          
---                                                                                                                                       
File Summary                                                                                                                              
┌───────────────────────────────────┬────────┬──────────────────────────────────────────────────────────────┐                             
│               File                │ Action │                           Purpose                            │                             
├───────────────────────────────────┼────────┼──────────────────────────────────────────────────────────────┤                             
│ src/config.py                     │ CREATE │ Shared ModelConfig, YAML loading, model lookup               │                             
├───────────────────────────────────┼────────┼──────────────────────────────────────────────────────────────┤                             
│ src/llm_player.py                 │ MODIFY │ Classified error handling, fix tool ID bug, remove dead code │                             
├───────────────────────────────────┼────────┼──────────────────────────────────────────────────────────────┤                             
│ src/mock_player.py                │ CREATE │ Mock player for testing without API calls                    │                             
├───────────────────────────────────┼────────┼──────────────────────────────────────────────────────────────┤                             
│ src/tournament.py                 │ MODIFY │ Import ModelConfig from src.config (backward compat)         │                             
├───────────────────────────────────┼────────┼──────────────────────────────────────────────────────────────┤                             
│ scripts/run_round_robin.py        │ CREATE │ Manifest-based tournament: generate/run/status               │                             
├───────────────────────────────────┼────────┼──────────────────────────────────────────────────────────────┤                             
│ scripts/llm_vs_llm.py             │ MODIFY │ Import from src.config                                       │                             
├───────────────────────────────────┼────────┼──────────────────────────────────────────────────────────────┤                             
│ scripts/benchmark_vs_heuristic.py │ MODIFY │ Import from src.config, remove debug print                   │                             
└───────────────────────────────────┴────────┴──────────────────────────────────────────────────────────────┘  