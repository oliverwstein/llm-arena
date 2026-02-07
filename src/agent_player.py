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
        player_id: Optional[str] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.battle_logger = battle_logger
        self.verbose = verbose
        self.team_name = team_name
        self.player_id = player_id or self.username

        # Per-battle state
        self.decision_history: dict[str, list[dict]] = {}  # battle_id -> decisions
        self.battle_plans: dict[str, dict] = {}  # battle_id -> {goals: [], predictions: {}}
        self.known_opponents: dict[str, str] = {}  # username -> model_id
        self.known_opponent_ids: dict[str, str] = {}  # username -> player_id

    async def forfeit(self, battle_tag: str) -> None:
        """Forfeit a battle."""
        await self.ps_client.send_message("/forfeit", room=battle_tag)


    def register_opponent(self, username: str, model: str, player_id: Optional[str] = None) -> None:
        """
        Register a known opponent model.
        Useful when we know who we are playing against (e.g. competitive matching).
        """
        self.known_opponents[username] = model
        if player_id:
            self.known_opponent_ids[username] = player_id

    def prepare_for_battle(self, team: str, team_name: str, battle_logger: Optional["BattleLogger"] = None) -> None:
        """
        Prepare this player for a new battle (used by player pools).
        
        Sets the team, team name, and optionally the battle logger for the upcoming match.
        Called before each match when reusing players from a pool.
        """
        self.update_team(team)
        self.team_name = team_name
        if battle_logger is not None:
            self.battle_logger = battle_logger

    def clear_opponent_registry(self) -> None:
        """
        Clear the opponent registry (used by player pools).
        
        Needed because pool players face different opponents each match.
        """
        self.known_opponents.clear()
        self.known_opponent_ids.clear()

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

        # 1b. Log protocol events incrementally
        if self.battle_logger and hasattr(battle, 'observations'):
            self.battle_logger.log_protocol(battle_id, battle.observations)

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
        # Should return dict with keys: action, reasoning, prediction, confidence, (optional) log_data
        decision_result = await self._make_decision(turn_context)

        action_string = decision_result.get("action", "")
        reasoning = decision_result.get("reasoning", "")
        prediction = decision_result.get("prediction", "")
        confidence = decision_result.get("confidence", "")

        # 5. Record decision
        self._record_decision(battle_id, battle.turn, action_string, reasoning, prediction, confidence=confidence)

        # 6. Log if logger active
        if self.battle_logger:
            self.battle_logger.log_action(
                battle_id=battle_id,
                player_id=self.player_id,
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
                confidence=confidence,
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
                    player_id=self.player_id,
                    turn=battle.turn,
                    reason=fallback_reason,
                    random_action=random_action_desc
                )

            if self.verbose:
                print(f"[{self.username}] FALLBACK ({fallback_reason}): {random_action_desc}")

            return random_order

        # 8. Parse and validate the action with retry loop
        max_correction_attempts = 2
        current_action = action_string
        
        for attempt in range(max_correction_attempts + 1):
            parsed = self._parse_action(current_action, battle)
            
            if parsed is not None:
                # Valid action found
                return self.create_order(parsed)
            
            # Invalid action - try to get correction if not at max attempts
            if attempt < max_correction_attempts:
                valid_actions = self._format_valid_actions(battle)
                
                if self.verbose:
                    print(f"[{self.username}] Invalid action '{current_action}', requesting correction (attempt {attempt + 1}/{max_correction_attempts})")
                
                # Request correction from LLM (subclasses implement this)
                correction_result = await self._request_action_correction(
                    turn_context,
                    invalid_action=current_action,
                    valid_actions=valid_actions
                )
                
                if correction_result and correction_result.get("action"):
                    current_action = correction_result["action"]
                    # Update reasoning/prediction if provided
                    if correction_result.get("reasoning"):
                        reasoning = correction_result["reasoning"]
                    continue
                else:
                    # Correction failed, break to fallback
                    break
        
        # All attempts failed - use fallback
        random_order, random_action_desc = self._choose_random_move_with_description(battle)
        if self.battle_logger:
            self.battle_logger.log_fallback(
                battle_id=battle_id,
                player_id=self.player_id,
                turn=battle.turn,
                reason=f"invalid_action_after_{max_correction_attempts}_retries: {action_string}",
                random_action=random_action_desc
            )
        if self.verbose:
            print(f"[{self.username}] FALLBACK (invalid action '{action_string}' after {max_correction_attempts} retries): {random_action_desc}")
        return random_order

    async def _make_decision(self, context: dict) -> dict:
        """
        Produce a decision based on context.
        Must be implemented by subclasses.
        Returns dict with: action, reasoning, prediction, confidence, etc.
        """
        raise NotImplementedError

    def _parse_action(self, action_str: str, battle: AbstractBattle) -> str:
        """
        Parse the action string into a poke-env compliant order.
        Can be overridden or use shared parser.
        """
        from .response_parser import parse_llm_response
        return parse_llm_response(action_str, battle)

    async def _request_action_correction(
        self,
        context: dict,
        invalid_action: str,
        valid_actions: str
    ) -> dict:
        """
        Request a corrected action from the decision maker.
        
        Called when the initial action couldn't be parsed.
        Subclasses (like LLMPlayer) can override to call the LLM again.
        
        Args:
            context: The turn context dict
            invalid_action: The action string that failed to parse
            valid_actions: Formatted string of valid actions
            
        Returns:
            Dict with 'action' key, or None/empty dict if correction failed.
        """
        # Default implementation: no correction capability
        return {}

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
                opponent_player_id = self.known_opponent_ids.get(opponent_name)

                self.battle_logger.start_battle(
                    battle_id=battle_id,
                    player_id=self.player_id,
                    model=getattr(self, "model", "human"),
                    showdown_username=self.username,
                    opponent_player_id=opponent_player_id,
                    player_team=self.team_name,
                )

    def _update_previous_outcome(self, battle_id: str, prev_events: str):
        """Update last turn's outcome with reality."""
        if not self.decision_history[battle_id]:
            return

        last_decision = self.decision_history[battle_id][-1]
        if last_decision["outcome"] is None:
            last_decision["outcome"] = prev_events[:100] if prev_events else "no events"

    def _record_decision(self, battle_id: str, turn: int, action: str, reasoning: str, prediction: str, confidence: str = ""):
        """Append decision to history."""
        self.decision_history[battle_id].append({
            "turn": turn,
            "action": action,
            "reasoning": reasoning,
            "prediction": prediction,
            "confidence": confidence,
            "outcome": None  # Filled next turn
        })

    def _format_decision_history(self, battle_id: str) -> str:
        """Format history for context."""
        lines = []
        for d in self.decision_history[battle_id][-3:]:
            line = f"T{d['turn']}: {d['action']}"
            if d.get('confidence'):
                line += f" [confidence: {d['confidence']}%]"
            if d.get('reasoning'):
                line += f" | {d['reasoning']}"
            if d.get('prediction') and d.get('outcome'):
                line += f" -> {d['outcome']}"
            lines.append(line)
        return "\n".join(lines)

    def _format_battle_plan(self, plan: dict) -> str:
        """Format battle plan for context."""
        lines = []
        for goal in plan.get("goals", []):
            if goal["status"] == "completed":
                status = "+"
            elif goal["status"] == "abandoned":
                status = "x"
            else:
                status = "o"
            lines.append(f"{status} {goal['goal']}")
            if goal.get("notes"):
                lines.append(f"   - {goal['notes']}")
        return "\n".join(lines) if lines else ""

    def _format_valid_actions(self, battle: AbstractBattle) -> str:
        """Format available moves and switches as a readable list for LLM correction."""
        lines = []
        
        if battle.available_moves:
            move_strs = []
            for move in battle.available_moves:
                # Include PP info if available
                if hasattr(move, 'current_pp') and move.current_pp is not None:
                    move_strs.append(f"move {move.id} (PP: {move.current_pp}/{move.max_pp})")
                else:
                    move_strs.append(f"move {move.id}")
            lines.append("Available moves: " + ", ".join(move_strs))
        
        if battle.available_switches:
            switch_strs = []
            for pokemon in battle.available_switches:
                hp_pct = pokemon.current_hp_fraction * 100 if pokemon.current_hp_fraction else 0
                switch_strs.append(f"switch {pokemon.species} ({hp_pct:.0f}% HP)")
            lines.append("Available switches: " + ", ".join(switch_strs))
        
        if not lines:
            lines.append("No actions available (forced to use Struggle or default)")
        
        return "\n".join(lines)

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
                player_id=self.player_id,
                won=won,
                total_turns=battle.turn,
                forfeit=False,
                battle_observations=getattr(battle, 'observations', None),
            )

        if battle_id in self.decision_history:
            del self.decision_history[battle_id]
        if battle_id in self.battle_plans:
            del self.battle_plans[battle_id]
