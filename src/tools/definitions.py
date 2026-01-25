"""LiteLLM-compatible tool definitions for battle analysis."""

TOOL_DEFINITIONS = [
    # Type Analysis Tools
    {
        "type": "function",
        "function": {
            "name": "get_type_effectiveness",
            "description": "Get the damage multiplier for an attacking type against a Pokemon's types. Returns 0 (immune), 0.25, 0.5, 1, 2, or 4.",
            "parameters": {
                "type": "object",
                "properties": {
                    "attack_type": {
                        "type": "string",
                        "description": "The attacking move's type (e.g., 'fire', 'water', 'electric')"
                    },
                    "defender_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The defending Pokemon's type(s) (e.g., ['grass', 'poison'])"
                    }
                },
                "required": ["attack_type", "defender_types"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_type_matchups",
            "description": "Get complete type matchup analysis for a Pokemon - what types it's weak to, resists, and immune to.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The Pokemon's type(s)"
                    }
                },
                "required": ["pokemon_types"]
            }
        }
    },

    # Damage Calculation Tools
    {
        "type": "function",
        "function": {
            "name": "calculate_damage",
            "description": "Calculate estimated damage for a specific move against the current opponent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "move_name": {
                        "type": "string",
                        "description": "Name of the move to calculate damage for"
                    }
                },
                "required": ["move_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_all_damages",
            "description": "Calculate damage for ALL your available moves at once against the current opponent. More efficient than calling calculate_damage multiple times.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },

    # Move Information Tools
    {
        "type": "function",
        "function": {
            "name": "get_move_details",
            "description": "Get detailed information about a move including effects, priority, accuracy, and secondary effects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "move_name": {
                        "type": "string",
                        "description": "Name of the move to look up"
                    }
                },
                "required": ["move_name"]
            }
        }
    },

    # Pokemon Information Tools
    {
        "type": "function",
        "function": {
            "name": "get_pokemon_info",
            "description": "Get base stats, types, abilities, and typical role for a Pokemon species.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {
                        "type": "string",
                        "description": "Name of the Pokemon to look up"
                    }
                },
                "required": ["pokemon_name"]
            }
        }
    },

    # Field State Tools
    {
        "type": "function",
        "function": {
            "name": "get_field_analysis",
            "description": "Get analysis of current field conditions (weather, hazards, screens) and their tactical implications.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },

    # Team Information Tools
    {
        "type": "function",
        "function": {
            "name": "get_team_pokemon",
            "description": "Get detailed info about one of your team members - moves, item, ability, HP, status, and stat boosts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {
                        "type": "string",
                        "description": "Name of the Pokemon to look up (e.g., 'skarmory')"
                    }
                },
                "required": ["pokemon_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_team_summary",
            "description": "Get HP/status summary of your entire team.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_opponent_pokemon",
            "description": "Get known info about an opponent's Pokemon (only revealed information).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {
                        "type": "string",
                        "description": "Name of the opponent's Pokemon"
                    }
                },
                "required": ["pokemon_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_opponent_team_summary",
            "description": "Get summary of opponent's entire team - revealed Pokemon, their HP/status, known moves, and count of unrevealed Pokemon.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },

    # Battle Log Tools
    {
        "type": "function",
        "function": {
            "name": "get_battle_log",
            "description": "Get the complete objective battle log from the game. Use 'narrative' for readable text, 'detailed' for structured data with exact HP, 'raw' for Showdown protocol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["narrative", "detailed", "raw"],
                        "description": "Output format (default: narrative)"
                    },
                    "from_turn": {
                        "type": "integer",
                        "description": "Start from this turn (default: 1)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_turn_details",
            "description": "Get detailed information about what happened on a specific turn, including exact HP values and all events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "turn": {
                        "type": "integer",
                        "description": "The turn number to examine"
                    }
                },
                "required": ["turn"]
            }
        }
    },

    # Strategic Planning Tools
    {
        "type": "function",
        "function": {
            "name": "update_battle_plan",
            "description": "Update your strategic plan. Add goals, mark complete, abandon goals, or add notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add_goal", "complete_goal", "abandon_goal", "add_note"],
                        "description": "Action to perform on the plan"
                    },
                    "goal_id": {
                        "type": "integer",
                        "description": "Goal ID (required for complete_goal, abandon_goal, add_note)"
                    },
                    "text": {
                        "type": "string",
                        "description": "Goal text (for add_goal) or note text (for add_note)"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_battle_plan",
            "description": "Review your current strategic plan and goals.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
]
