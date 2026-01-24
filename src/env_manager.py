"""Environment and API key management for LLM Pokemon Battle Arena."""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


# Map of model prefixes to their required environment variables
MODEL_API_KEYS = {
    # OpenAI models
    "gpt-": "OPENAI_API_KEY",
    "o1-": "OPENAI_API_KEY",
    "o3-": "OPENAI_API_KEY",
    
    # Anthropic models
    "claude-": "ANTHROPIC_API_KEY",
    
    # Google models
    "gemini/": "GOOGLE_API_KEY",
    "gemini-": "GOOGLE_API_KEY",
    
    # xAI models
    "xai/": "XAI_API_KEY",
    "grok-": "XAI_API_KEY",

    # DeepSeek models
    "deepseek/": "DEEPSEEK_API_KEY",
    "deepseek-": "DEEPSEEK_API_KEY",

    # Together AI models
    "together_ai/": "TOGETHER_API_KEY",
    "together/": "TOGETHER_API_KEY",
    
    # Groq models
    "groq/": "GROQ_API_KEY",
    
    # Mistral models
    "mistral/": "MISTRAL_API_KEY",
    
    # Cohere models
    "cohere/": "COHERE_API_KEY",
    "command-": "COHERE_API_KEY",
    
    # Azure OpenAI
    "azure/": "AZURE_API_KEY",
    
    # AWS Bedrock
    "bedrock/": "AWS_ACCESS_KEY_ID",
    
    # Ollama (local - no key needed)
    "ollama/": None,
}


def load_env_file(env_path: Optional[str] = None) -> bool:
    """
    Load environment variables from .env file.
    
    Args:
        env_path: Path to .env file. If None, searches in standard locations.
        
    Returns:
        True if a .env file was loaded, False otherwise.
    """
    if env_path:
        env_file = Path(env_path)
        if env_file.exists():
            load_dotenv(env_file)
            return True
        return False
    
    # Search in standard locations
    search_paths = [
        Path("env/.env"),
        Path(".env"),
        Path("~/.llm-arena/.env").expanduser(),
    ]
    
    for path in search_paths:
        if path.exists():
            load_dotenv(path)
            print(f"Loaded environment from: {path}")
            return True
    
    return False


def get_api_key_for_model(model: str) -> Optional[str]:
    """
    Get the required API key environment variable name for a model.
    
    Args:
        model: LiteLLM model identifier
        
    Returns:
        Environment variable name, or None if no key is needed (e.g., Ollama)
    """
    model_lower = model.lower()
    
    for prefix, env_var in MODEL_API_KEYS.items():
        if model_lower.startswith(prefix):
            return env_var
    
    # Default to OpenAI for unrecognized models
    return "OPENAI_API_KEY"


def has_api_key(model: str) -> bool:
    """
    Check if the required API key for a model is available.
    
    Args:
        model: LiteLLM model identifier
        
    Returns:
        True if the API key is set (or not needed), False otherwise.
    """
    env_var = get_api_key_for_model(model)
    
    # No key needed (e.g., Ollama)
    if env_var is None:
        return True
    
    # Check if the key is set and non-empty
    key = os.environ.get(env_var, "").strip()
    return bool(key)


def get_available_models(models: list[str]) -> tuple[list[str], list[str]]:
    """
    Separate models into those with available API keys and those without.
    
    Args:
        models: List of model identifiers
        
    Returns:
        Tuple of (available_models, unavailable_models)
    """
    available = []
    unavailable = []
    
    for model in models:
        if has_api_key(model):
            available.append(model)
        else:
            unavailable.append(model)
    
    return available, unavailable


def print_api_key_status():
    """Print the status of all known API keys."""
    print("\n=== API Key Status ===")
    
    checked = set()
    for prefix, env_var in sorted(MODEL_API_KEYS.items(), key=lambda x: x[1] or ""):
        if env_var is None:
            continue
        if env_var in checked:
            continue
        checked.add(env_var)
        
        key = os.environ.get(env_var, "").strip()
        if key:
            # Show first/last few chars for verification
            masked = f"{key[:4]}...{key[-4:]}" if len(key) > 12 else "****"
            print(f"  ✓ {env_var}: {masked}")
        else:
            print(f"  ✗ {env_var}: not set")
    
    print()


# Initialize environment on module import
_env_loaded = load_env_file()
