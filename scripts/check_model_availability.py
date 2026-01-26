#!/usr/bin/env python3
"""
Check availability of configured models and discover other available models.
"""

import os
import sys
import yaml
import asyncio
from pathlib import Path
import litellm

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_manager import load_env_file, has_api_key
load_env_file()

# Disable verbose logging unless needed
litellm.set_verbose = False
litellm.suppress_debug_info = True

CONFIG_PATH = "config/models.yaml"

async def check_model(model_id: str, provider: str = None) -> dict:
    """Check if a single model is available."""
    try:
        # Simple probing message
        response = await litellm.acompletion(
            model=model_id,
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=1
        )
        return {"status": "Available", "reason": "OK"}
    except Exception as e:
        err = str(e)
        if "404" in err or "not found" in err.lower():
            return {"status": "NotFound", "reason": "404 Not Found"}
        elif "429" in err or "quota" in err.lower():
            return {"status": "RateLimited", "reason": "Quota/Rate Limit Exceeded (Model Exists)"}
        elif "401" in err or "403" in err.lower():
            return {"status": "AuthError", "reason": "Auth/Permission Error"}
        else:
            return {"status": "Error", "reason": f"{err[:100]}..."}

def get_configured_models():
    """Load models from config/models.yaml."""
    if not os.path.exists(CONFIG_PATH):
        print(f"Config file not found: {CONFIG_PATH}")
        return []
    
    with open(CONFIG_PATH) as f:
        data = yaml.safe_load(f)
    
    return data.get("models", [])

async def discover_openai_models():
    """Discover models available via OpenAI API."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return []
    
    try:
        import openai
        client = openai.AsyncOpenAI(api_key=api_key)
        models = await client.models.list()
        return [m.id for m in models.data if "gpt" in m.id]
    except Exception as e:
        print(f"  Available OpenAI models discovery failed: {e}")
        return []

async def discover_google_models():
    """Discover models available via Google Gemini API."""
    # We use google-generativeai for listing if available
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return []

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        models = []
        for m in genai.list_models():
            # Include generateContent models
            if "generateContent" in m.supported_generation_methods:
                name = m.name
                if name.startswith("models/"):
                    short_name = name.replace("models/", "")
                    # litellm expects 'gemini/' prefix usually
                    models.append(f"gemini/{short_name}")
        return models
    except ImportError:
        print("  google-generativeai not installed, skipping discovery")
        return []
    except Exception as e:
        print(f"  Google model discovery failed: {e}")
        return []

async def discover_deepseek_models():
    """Discover DeepSeek models (OpenAI compatible)."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return []
    
    try:
        import openai
        client = openai.AsyncOpenAI(
            api_key=api_key, 
            base_url="https://api.deepseek.com"
        )
        models = await client.models.list()
        return [f"deepseek/{m.id}" for m in models.data]
    except Exception as e:
        print(f"  DeepSeek discovery failed: {e}")
        return []

async def discover_xai_models():
    """Discover xAI models (OpenAI compatible)."""
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        return []
    
    try:
        import openai
        client = openai.AsyncOpenAI(
            api_key=api_key, 
            base_url="https://api.x.ai/v1"
        )
        models = await client.models.list()
        return [f"xai/{m.id}" for m in models.data]
    except Exception as e:
        print(f"  xAI discovery failed: {e}")
        return []

async def main():
    print(f"Checking configured models in {CONFIG_PATH}...")
    configured_models = get_configured_models()
    
    configured_ids = set()
    
    print(f"\n{'='*80}")
    print(f"{'Model Name':<25} {'Model ID':<35} {'Status':<15} {'Reason'}")
    print(f"{'-'*80}")
    
    # 1. Check Configured Models
    for cm in configured_models:
        name = cm.get("name", "Unknown")
        mid = cm.get("model", "")
        configured_ids.add(mid)
        
        if not mid or cm.get("force_fallback"):
            print(f"{name:<25} {mid:<35} {'Skipped':<15} {'Fallback/Empty'}")
            continue
            
        result = await check_model(mid)
        print(f"{name:<25} {mid:<35} {result['status']:<15} {result['reason']}")

    print(f"{'='*80}\n")
    
    print("Discovering other available models from providers...")
    
    discovered = {}
    
    # OpenAI
    print("  Probing OpenAI...")
    discovered["OpenAI"] = await discover_openai_models()
    
    # Google
    print("  Probing Google Gemini...")
    discovered["Google"] = await discover_google_models()
    
    # DeepSeek
    print("  Probing DeepSeek...")
    discovered["DeepSeek"] = await discover_deepseek_models()
    
    # xAI
    print("  Probing xAI...")
    discovered["xAI"] = await discover_xai_models()
    
    # Anthropic (No list API, hardcode common ones to check)
    print("  Probing Anthropic (Manual check of common models)...")
    anthropic_candidates = [
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
        "claude-3-5-sonnet-20240620",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022"
    ]
    anthropic_found = []
    if os.getenv("ANTHROPIC_API_KEY"):
        for m in anthropic_candidates:
            res = await check_model(m)
            if res["status"] in ["Available", "RateLimited"]:
                anthropic_found.append(m)
    discovered["Anthropic"] = anthropic_found

    print(f"\n{'='*80}")
    print("AVAILABLE UNCONFIGURED MODELS")
    print("These models are available on your keys but not in models.yaml")
    print(f"{'='*80}")
    
    found_any = False
    for provider, models in discovered.items():
        # filter out models that are already in config (ignoring prefix nuances if possible, but strict match for now)
        # litellm config uses 'provider/model' often, discovery might return just 'model'.
        
        # Helper to normalize for check
        def normalize(m):
            if "/" in m: return m.split("/")[-1]
            return m
            
        unique_models = []
        for m in models:
            # Check if this model ID is effectively in configured_ids
            is_configured = False
            for cid in configured_ids:
                if m == cid or normalize(m) == normalize(cid):
                    is_configured = True
                    break
            
            if not is_configured:
                # Double check availability for discovered ones just to be sure? 
                # (For list APIs, existence implies availability usually, but good to be safe? 
                # No, list is enough.)
                unique_models.append(m)
        
        if unique_models:
            found_any = True
            print(f"\n{provider}:")
            for m in sorted(unique_models):
                print(f"  - {m}")
    
    if not found_any:
        print("No additional models found.")
    print(f"{'='*80}")

if __name__ == "__main__":
    asyncio.run(main())
