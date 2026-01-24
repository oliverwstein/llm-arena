"""Strategic planning tools for battle goals."""


def get_battle_plan(battle_plan: dict) -> dict:
    """
    Get the current battle plan.
    
    Args:
        battle_plan: The battle plan dictionary from LLMPlayer
    """
    goals = battle_plan.get("goals", [])
    predictions = battle_plan.get("predictions", {})
    
    active_goals = [g for g in goals if g.get("status") == "active"]
    completed_goals = [g for g in goals if g.get("status") == "completed"]
    abandoned_goals = [g for g in goals if g.get("status") == "abandoned"]
    
    return {
        "active_goals": active_goals,
        "completed_goals": completed_goals,
        "abandoned_goals": abandoned_goals,
        "predictions": predictions,
        "total_goals": len(goals)
    }


def update_battle_plan(battle_plan: dict, action: str, goal_id: int = None, text: str = None) -> dict:
    """
    Update the battle plan.
    
    Args:
        battle_plan: The battle plan dictionary to modify
        action: One of "add_goal", "complete_goal", "abandon_goal", "add_note"
        goal_id: Goal ID (required for complete/abandon/note)
        text: Goal text (for add_goal) or note (for add_note)
    """
    if "goals" not in battle_plan:
        battle_plan["goals"] = []
    if "predictions" not in battle_plan:
        battle_plan["predictions"] = {}
    
    if action == "add_goal":
        if not text:
            return {"error": "text required for add_goal"}
        new_id = len(battle_plan["goals"]) + 1
        battle_plan["goals"].append({
            "id": new_id,
            "goal": text,
            "status": "active",
            "notes": ""
        })
        return {"success": True, "goal_id": new_id, "message": f"Added goal: {text}"}
    
    elif action == "complete_goal":
        if goal_id is None:
            return {"error": "goal_id required for complete_goal"}
        for goal in battle_plan["goals"]:
            if goal["id"] == goal_id:
                goal["status"] = "completed"
                return {"success": True, "message": f"Completed goal {goal_id}"}
        return {"error": f"Goal {goal_id} not found"}
    
    elif action == "abandon_goal":
        if goal_id is None:
            return {"error": "goal_id required for abandon_goal"}
        for goal in battle_plan["goals"]:
            if goal["id"] == goal_id:
                goal["status"] = "abandoned"
                return {"success": True, "message": f"Abandoned goal {goal_id}"}
        return {"error": f"Goal {goal_id} not found"}
    
    elif action == "add_note":
        if goal_id is None:
            return {"error": "goal_id required for add_note"}
        if not text:
            return {"error": "text required for add_note"}
        for goal in battle_plan["goals"]:
            if goal["id"] == goal_id:
                goal["notes"] = text
                return {"success": True, "message": f"Added note to goal {goal_id}"}
        return {"error": f"Goal {goal_id} not found"}
    
    else:
        return {"error": f"Unknown action: {action}"}
