"""
crawlerai.config.settings — Global defaults.

All settings are loaded lazily (no side-effects at import time).
Override via environment variables or pass directly at call sites.
"""
import os
from functools import lru_cache
from pathlib import Path


# ── Provider → env-var mapping ────────────────────────────────────────────────
_PROVIDER_KEY_MAP: dict[str, str] = {
    "openai":      "OPENAI_API_KEY",
    "openrouter":  "OPENROUTER_API_KEY",
    "gemini":      "GEMINI_API_KEY",
    "google":      "GEMINI_API_KEY",
    "anthropic":   "ANTHROPIC_API_KEY",
}


@lru_cache(maxsize=1)
def _load_dotenv_once() -> None:
    """Load .env file exactly once, only when settings are first accessed."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # python-dotenv is optional


def get_api_key(provider: str) -> str:
    """
    Resolve the API key for *provider* from environment variables.

    Falls back to OPENAI_API_KEY for unknown providers.
    Returns "no-token" for Ollama (no key needed).
    """
    _load_dotenv_once()
    vendor = provider.split("/")[0].lower()
    if vendor == "ollama":
        return "no-token"
    if vendor == "openrouter":
        return os.getenv("OPENROUTER_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    env_var = _PROVIDER_KEY_MAP.get(vendor, "OPENAI_API_KEY")
    return os.getenv(env_var, os.getenv("OPENAI_API_KEY", ""))


# ── Runtime defaults (read lazily) ────────────────────────────────────────────

def get_default_provider() -> str:
    _load_dotenv_once()
    return os.getenv("LLM_PROVIDER", "openai/gpt-4o-mini")


def get_chunk_token_threshold() -> int:
    _load_dotenv_once()
    return int(os.getenv("CHUNK_TOKEN_THRESHOLD", "3000"))


def get_headless() -> bool:
    _load_dotenv_once()
    return os.getenv("HEADLESS", "true").lower() != "false"


def get_page_timeout() -> int:
    """Page load timeout in milliseconds."""
    _load_dotenv_once()
    return int(os.getenv("PAGE_TIMEOUT", "30000"))


def get_output_dir() -> Path:
    _load_dotenv_once()
    p = Path(os.getenv("OUTPUT_DIR", "output"))
    p.mkdir(parents=True, exist_ok=True)
    return p
