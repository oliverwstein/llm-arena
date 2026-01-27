Round Robin Tournament Restructuring Plan                                                                                                 
                                                                                                                                          
Rationale                                                                                                                                 
                                                                                                                                          
The current round robin system has several structural problems that make it hard to work with:                                            
                                                                                                                                          
1. Scattered outputs: tournament.json is written to the repo root while logs go to logs/tournament/battles/. There's no single            
self-contained directory for a tournament run.                                                                                            
2. Opaque naming: Log directories are named by Showdown's auto-assigned battle tag (e.g., battle-gen4ou-1886), which has no relation to   
the match number in the manifest. Player JSONL files use UUID-based player IDs (e.g., gemini_gemini-3-flash-preview-9bdb3197.jsonl).      
There's no easy way to map from a manifest entry to its log files.                                                                        
3. Fragile username scheme: Showdown usernames are {model_name}-{uuid[:8]} truncated to 18 chars, with a hacky collision workaround for   
mirror matches (flip the last char to "2"). The UUIDs serve no purpose — they exist only to avoid name collisions that could be solved    
more simply.                                                                                                                              
4. No live match tracking: metadata.json only records start and end state, not the current turn during a battle. The manifest stores a    
session_id as battle_id that doesn't correspond to anything useful.                                                                       
                                                                                                                                          
The fix: make the tournament a single self-contained directory under logs/, with match folders named by match number, player files named  
by readable usernames (model-A/model-B), and per-match metadata that tracks live progress.                                                
                                                                                                                                          
All changes are confined to scripts/run_round_robin.py. The src/ layer provides neutral building blocks (BattleLogger, AgentPlayer, etc.) 
and shouldn't be modified to serve script-level concerns. Instead, the script defines a MatchLogger subclass that adapts BattleLogger's  
directory behavior, and controls filenames by setting player_id to the showdown username at construction time.                            
                                                                                                                                          
Goal                                                                                                                                      
                                                                                                                                          
Clean up the tournament directory structure, naming, and logging so everything is self-contained under logs/{tournament-name}/ with       
sensible match folder and file names. No changes to src/ — the script adapts to what src/ provides.                                       
                                                                                                                                          
New Directory Structure                                                                                                                   
                                                                                                                                          
logs/{tournament-name}/                                                                                                                   
  manifest.json                                                                                                                           
  match-0001/                                                                                                                             
    metadata.json                                                                                                                         
    protocol.jsonl                                                                                                                        
    {model-name}-A.jsonl                                                                                                                  
    {model-name}-B.jsonl                                                                                                                  
  match-0002/                                                                                                                             
    ...                                                                                                                                   
                                                                                                                                          
Changes — all in scripts/run_round_robin.py                                                                                               
                                                                                                                                          
New: MatchLogger subclass (defined in the script)                                                                                         
                                                                                                                                          
Subclass BattleLogger to write files flat into a match directory instead of battles/{battle_tag}/:                                        
class MatchLogger(BattleLogger):                                                                                                          
    def _battle_dir(self, battle_id: str) -> Path:                                                                                        
        """Write all files directly to log_dir (the match directory)."""                                                                  
        self.log_dir.mkdir(parents=True, exist_ok=True)                                                                                   
        return self.log_dir                                                                                                               
- Override __init__ to avoid creating the default battles/ subdirectory                                                                   
- Override log_action to also update metadata.json with current_turn on each action                                                       
- One MatchLogger instance created per match, pointed at match-XXXX/                                                                      
                                                                                                                                          
generate_manifest()                                                                                                                       
                                                                                                                                          
- Create logs/{tournament-name}/ directory                                                                                                
- Create empty match-XXXX/ subdirectories for each match                                                                                  
- Write manifest.json inside the tournament directory                                                                                     
- Remove the --output CLI arg; replace with --log-dir (default logs/)                                                                     
- Tournament name (auto-generated or --name) determines folder name                                                                       
                                                                                                                                          
run_match()                                                                                                                               
                                                                                                                                          
- Username format: Always preserve -A/-B suffix by truncating the model name:                                                             
max_name = 18 - 2  # room for "-A" / "-B"                                                                                                 
username_a = f"{model_a.name[:max_name]}-A"                                                                                               
username_b = f"{model_b.name[:max_name]}-B"                                                                                               
- Player ID = username: Set player_id=username_a / player_id=username_b — this makes BattleLogger name the JSONL files {username}.jsonl   
automatically                                                                                                                             
- Remove session_id / UUID generation entirely                                                                                            
- Per-match logger: Create a MatchLogger(match_dir=str(match_dir)) for each match instead of sharing one global logger                    
- Store Showdown battle tag in manifest as battle_tag (get it from player_a.battles after the match) — useful for debugging               
- Remove the old battle_id: session_id field                                                                                              
                                                                                                                                          
run_tournament()                                                                                                                          
                                                                                                                                          
- Derive tournament directory from manifest path (its parent)                                                                             
- Remove global BattleLogger creation (each match creates its own MatchLogger)                                                            
- Remove log_dir = Path("logs/tournament") hardcoding                                                                                     
                                                                                                                                          
cmd_generate() CLI                                                                                                                        
                                                                                                                                          
- Remove --output / -o                                                                                                                    
- Add --log-dir (default: logs/)                                                                                                          
- Output path: {log-dir}/{tournament-name}/manifest.json                                                                                  
- Print the manifest path so run knows where to find it                                                                                   
                                                                                                                                          
cmd_run() CLI                                                                                                                             
                                                                                                                                          
- --manifest now points to logs/{name}/manifest.json                                                                                      
                                                                                                                                          
Misc cleanup                                                                                                                              
                                                                                                                                          
- Move import random to top of file                                                                                                       
- Remove the result field from match entries (redundant with winner + status)                                                             
                                                                                                                                          
What does NOT change                                                                                                                      
                                                                                                                                          
- src/battle_logger.py — untouched                                                                                                        
- src/agent_player.py — untouched                                                                                                         
- src/llm_player.py — untouched                                                                                                           
- src/mock_player.py — untouched                                                                                                          
- Non-tournament usage of BattleLogger continues to work as before                                                                        
                                                                                                                                          
Cleanup                                                                                                                                   
                                                                                                                                          
- Delete logs/tournament/ (old logs, user confirmed disposable)                                                                           
- Delete stale tournament.json in repo root                                                                                               
                                                                                                                                          
Verification                                                                                                                              
                                                                                                                                          
1. python3 scripts/run_round_robin.py generate --models Grok-4 DeepSeek-Reasoner Gemini-3-Flash GPT-5-Mini --games-per-pair 3             
2. Check logs/{name}/manifest.json exists and match-0001/ through match-0018/ directories created                                         
3. python3 scripts/run_round_robin.py run --manifest logs/{name}/manifest.json --mock                                                     
4. Verify per-match directories contain {model}-A.jsonl, {model}-B.jsonl, protocol.jsonl, metadata.json                                   
5. Verify metadata.json tracks current_turn, started_at, completed_at                                                                     
6. Test Ctrl+C pause and resume — manifest picks up pending matches   