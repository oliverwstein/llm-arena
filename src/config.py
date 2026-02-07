"""Shared configuration for LLM Arena models."""

import yaml
from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""
    name: str           # Display name
    model: str          # LiteLLM model ID
    temperature: float = 0.7
    max_tokens: int = 16384
    timeout: float = 180.0
    team: Optional[str] = None    # Specific team path (optional)
    force_fallback: bool = False  # Force use of fallback bot
    api_price_input: float = 0.0  # Price per 1M input tokens
    api_price_output: float = 0.0  # Price per 1M output tokens
    reasoning_effort: Optional[str] = None  # For reasoning models: "low", "medium", "high"


def load_models_from_yaml(path: str) -> list[ModelConfig]:
    """Load model configurations from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    models = []
    for m in data["models"]:
        models.append(ModelConfig(
            name=m["name"],
            model=m["model"],
            temperature=m.get("temperature", 0.7),
            max_tokens=m.get("max_tokens", 16384),
            timeout=m.get("timeout", 180.0),
            team=m.get("team"),
            force_fallback=m.get("force_fallback", False),
            api_price_input=float(m.get("api_price_input", 0.0)),
            api_price_output=float(m.get("api_price_output", 0.0)),
            reasoning_effort=m.get("reasoning_effort"),
        ))
    return models


def find_model(query: str, models: list[ModelConfig]) -> Optional[ModelConfig]:
    """Find a model by name or model ID (exact or partial match)."""
    # Exact match first
    for m in models:
        if m.name == query or m.model == query:
            return m
    # Partial match (case-insensitive)
    for m in models:
        if query.lower() in m.name.lower() or query.lower() in m.model.lower():
            return m
    return None
