"""
Global configuration and shared defaults for the crawler.
Override via environment variables or pass directly at runtime.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── LLM ─────────────────────────────────────────────────────────────────────
DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai/gpt-4o-mini")
DEFAULT_API_KEY      = os.getenv("OPENAI_API_KEY", "")

# Tokens per chunk sent to the LLM. Lower = more calls but cheaper per call.
CHUNK_TOKEN_THRESHOLD = int(os.getenv("CHUNK_TOKEN_THRESHOLD", "3000"))

# ── Browser ──────────────────────────────────────────────────────────────────
HEADLESS   = os.getenv("HEADLESS", "true").lower() != "false"
PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "30000"))  # ms

# ── Output ───────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
OUTPUT_DIR.mkdir(exist_ok=True)
