"""Tool harness for LLM Pokemon players.

Provides tools for type analysis, damage calculation,
team information, and battle history queries.

The unified registry in registry.py is the single source of truth
for all tools, used by both human and LLM players.
"""

# Individual tool modules (for direct access if needed)
from . import type_tools
from . import damage_tools
from . import team_tools
from . import battle_log_tools
from . import plan_tools
from . import field_tools
from . import info_tools

# Unified registry (primary interface)
from .registry import (
    execute_tool,
    parse_command,
    get_llm_tool_definitions,
    get_help_text,
    TOOLS,
)

__all__ = [
    # Tool modules
    "type_tools",
    "damage_tools",
    "team_tools",
    "battle_log_tools",
    "plan_tools",
    "field_tools",
    "info_tools",
    # Registry interface
    "execute_tool",
    "parse_command",
    "get_llm_tool_definitions",
    "get_help_text",
    "TOOLS",
]
