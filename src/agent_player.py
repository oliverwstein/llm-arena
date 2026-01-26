"""Base agent player with shared state management and context content."""

import random
from typing import Optional, TYPE_CHECKING
from poke_env.player import Player
from poke_env.player.player import AbstractBattle

from .state_formatter import format_battle_state
from .event_formatter import get_recent_events
from .tools.registry import execute_tool

if TYPE_CHECKING:
    from .battle_logger import BattleLogger


class AgentPlayer(Player):
    """
    Base class for agents (Human or LLM) that maintain persistent state
    (plans, history) and operate on a structured turn context.
    """

    def __init__(
        self,
        battle_logger: Optional["BattleLogger"] = None,
        verbose: bool = False,
        team_name: str = "unknown",
        **kwargs
    ):
        super().__init__(**kwargs)
        self.battle_logger = battle_logger
        self.verbose = verbose
        self.team_name = team_name
        
        # Per-battle state
        self.decision_history: dict[str, list[dict]] = {}  # battle_id -> decisions
        self.battle_plans: dict[str, dict] = {}  # battle_id -> {goals: [], predictions: {}}
        self.known_opponents: dict[str, str] = {}  # username -> model_id

    def register_opponent(self, username: str, model: str) -> None:
        """
        Register a known opponent model.
        Useful when we know who we are playing against (e.g. competitive matching).
        """
        self.known_opponents[username] = model

    async def choose_move(self, battle: AbstractBattle) -> str:
        """
        Main choice loop.
        1. Initialize state
        2. Gather context (Events, State, History, Plan)
        3. Make decision (Abstract - implemented by subclasses)
        4. Record decision
        5. Log
        6. Return order
        """
        battle_id = battle.battle_tag
        
        # 1. Initialize state if new battle
        self._ensure_battle_state(battle)
        
        # 2. Update previous turn's outcome (did prediction match reality?)
        prev_events = get_recent_events(battle)
        self._update_previous_outcome(battle_id, prev_events)
        
        # 3. Prepare Context
        current_state = format_battle_state(battle)
        decision_history_str = self._format_decision_history(battle_id)
        battle_plan = self.battle_plans[battle_id]
        
        # Context dict to pass to decision maker
        turn_context = {
            "battle": battle,
            "battle_id": battle_id,
            "prev_events": prev_events,
            "current_state": current_state,
            "decision_history_str": decision_history_str,
            "battle_plan": battle_plan,
        }
        
        # 4. Make Decision (Abstract)
        # Should return dict with keys: action, reasoning, prediction, (optional) log_data
        decision_result = await self._make_decision(turn_context)
        
        action_string = decision_result.get("action", "")
        reasoning = decision_result.get("reasoning", "")
        prediction = decision_result.get("prediction", "")
        
        # 5. Record decision
        self._record_decision(battle_id, battle.turn, action_string, reasoning, prediction)
        
        # 6. Log if logger active
        if self.battle_logger:
            self.battle_logger.log_turn(
                battle_id=battle_id,
                player_name=self.username,
                turn=battle.turn,
                observation=prev_events or "(Battle just started)",
                state=current_state,
                raw_response=decision_result.get("raw_response", ""),
                tool_calls=decision_result.get("tool_calls", []),
                parsed={
                    "action": action_string,
                    "reasoning": reasoning,
                    "prediction": prediction
                },
                tokens=decision_result.get("tokens", {}),
                latency_ms=decision_result.get("latency_ms", 0),
                battle_plan=battle_plan.get("goals", [])
            )
            
        # 7. Convert action to order
        # Subclasses or specific parsing logic might be needed if action_string isn't direct
        if not action_string:
            # Fallback to random move - log the reason
            fallback_reason = decision_result.get("fallback_reason", "unknown_error")
            if "ERROR" in decision_result.get("raw_response", ""):
                if "timeout" in decision_result.get("raw_response", "").lower():
                    fallback_reason = "timeout"
                else:
                    fallback_reason = "api_error"
            
            random_order, random_action_desc = self._choose_random_move_with_description(battle)
            
            # Log the fallback
            if self.battle_logger:
                self.battle_logger.log_fallback(
                    battle_id=battle_id,
                    player_name=self.username,
                    turn=battle.turn,
                    reason=fallback_reason,
                    random_action=random_action_desc
                )
            
            if self.verbose:
                print(f"[{self.username}] FALLBACK ({fallback_reason}): {random_action_desc}")
            
            return random_order
            
        return self.create_order(self._parse_action(action_string, battle))

    async def _make_decision(self, context: dict) -> dict:
        """
        Produce a decision based on context.
        Must be implemented by subclasses.
        Returns dict with: action, reasoning, prediction, etc.
        """
        raise NotImplementedError

    def _parse_action(self, action_str: str, battle: AbstractBattle) -> str:
        """
        Parse the action string into a poke-env compliant order.
        Can be overridden or use shared parser.
        """
        from .response_parser import parse_llm_response
        return parse_llm_response(action_str, battle)

    def _ensure_battle_state(self, battle: AbstractBattle):
        """Initialize per-battle structures."""
        battle_id = battle.battle_tag
        if battle_id not in self.decision_history:
            self.decision_history[battle_id] = []
            self.battle_plans[battle_id] = {"goals": [], "predictions": {}}
            
            if self.battle_logger:
                opponent_name = "opponent"
                for player in [battle.player_username, battle.opponent_username]:
                    if player and player != self.username:
                        opponent_name = player
                        break
                
                # Check if we know this opponent's model
                opponent_model = self.known_opponents.get(opponent_name)
                
                self.battle_logger.start_battle(
                    battle_id=battle_id,
                    player_name=self.username,
                    model=getattr(self, "model", "human"),
                    opponent_name=opponent_name,
                    opponent_model=opponent_model,
                    player_team=self.team_name,
                    opponent_team="unknown"
                )
                
    def _update_previous_outcome(self, battle_id: str, prev_events: str):
        """Update last turn's outcome with reality."""
        if not self.decision_history[battle_id]:
            return
            
        last_decision = self.decision_history[battle_id][-1]
        if last_decision["outcome"] is None:
            last_decision["outcome"] = prev_events[:100] if prev_events else "no events"
            
    def _record_decision(self, battle_id: str, turn: int, action: str, reasoning: str, prediction: str):
        """Append decision to history."""
        self.decision_history[battle_id].append({
            "turn": turn,
            "action": action,
            "reasoning": reasoning,
            "prediction": prediction,
            "outcome": None  # Filled next turn
        })
        
    def _format_decision_history(self, battle_id: str) -> str:
        """Format history for context."""
        lines = []
        for d in self.decision_history[battle_id][-3:]: 
            line = f"T{d['turn']}: {d['action']}"
            if d.get('reasoning'):
                line += f" | {d['reasoning']}"
            if d.get('prediction') and d.get('outcome'):
                line += f" → {d['outcome']}"
            lines.append(line)
        return "\n".join(lines)

    def _format_battle_plan(self, plan: dict) -> str:
        """Format battle plan for context."""
        lines = []
        for goal in plan.get("goals", []):
            if goal["status"] == "completed":
                status = "✓"
            elif goal["status"] == "abandoned":
                status = "✗"
            else:
                status = "○"
            lines.append(f"{status} {goal['goal']}")
            if goal.get("notes"):
                lines.append(f"   └─ {goal['notes']}")
        return "\n".join(lines) if lines else ""

    def _choose_random_move_only(self, battle: AbstractBattle) -> str:
        """Fallback random move (without description)."""
        order, _ = self._choose_random_move_with_description(battle)
        return order
    
    def _choose_random_move_with_description(self, battle: AbstractBattle) -> tuple[str, str]:
        """Fallback random move with description of what was chosen."""
        if battle.available_moves:
            move = random.choice(battle.available_moves)
            return self.create_order(move), f"move {move.id}"
        elif battle.available_switches:
            pokemon = random.choice(battle.available_switches)
            return self.create_order(pokemon), f"switch {pokemon.species}"
        else:
            return self.choose_default_move(), "default"

    def _battle_finished_callback(self, battle: AbstractBattle) -> None:
        """Clean up."""
        battle_id = battle.battle_tag
        if self.battle_logger:
            won = battle.won if battle.won is not None else False
            self.battle_logger.end_battle(
                battle_id=battle_id,
                player_name=self.username,
                won=won,
                total_turns=battle.turn,
                forfeit=False  # poke-env 0.11.0 battle object doesn't track forfeit
            )
        
        if battle_id in self.decision_history:
            del self.decision_history[battle_id]
        if battle_id in self.battle_plans:
            del self.battle_plans[battle_id]
