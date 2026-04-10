"""
Global configuration and shared defaults for the crawler.
Override via environment variables or pass directly at runtime.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

_PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

# ── LLM ─────────────────────────────────────────────────────────────────────
DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai/gpt-4o-mini")

# Tokens per chunk sent to the LLM. Lower = more calls but cheaper per call.
CHUNK_TOKEN_THRESHOLD = int(os.getenv("CHUNK_TOKEN_THRESHOLD", "3000"))

# ── Browser ──────────────────────────────────────────────────────────────────
HEADLESS   = os.getenv("HEADLESS", "true").lower() != "false"
PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "30000"))  # ms

# ── Output ───────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
OUTPUT_DIR.mkdir(exist_ok=True)

<<<<<<< HEAD
=======

_PROVIDER_KEY_MAP = {
    "openai":     "OPENAI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "gemini":     "GEMINI_API_KEY",
    "google":     "GEMINI_API_KEY",
    "cohere":     "COHERE_API_KEY",
    "groq":       "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
>>>>>>> c25e62c736ce29ec617ea0e079b55e84dfb5f09f
def get_api_key(provider: str = DEFAULT_LLM_PROVIDER) -> str:
    vendor = provider.split("/")[0].lower()
    if vendor == "ollama":
        return "no-token"
    env_var = _PROVIDER_KEY_MAP.get(vendor, "OPENAI_API_KEY")
<<<<<<< HEAD

    # For OpenRouter, keep OPENAI_API_KEY as compatibility fallback because
    # many tools/users still store sk-or-v1 there.
    if vendor == "openrouter":
        return os.getenv("OPENROUTER_API_KEY", os.getenv("OPENAI_API_KEY", ""))

    return os.getenv(env_var, os.getenv("OPENAI_API_KEY", ""))


DEFAULT_API_KEY = get_api_key(DEFAULT_LLM_PROVIDER)
=======
    return os.getenv(env_var, os.getenv("OPENAI_API_KEY", ""))
>>>>>>> c25e62c736ce29ec617ea0e079b55e84dfb5f09f
