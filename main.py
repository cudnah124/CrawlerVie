#!/usr/bin/env python3
"""
Simple web crawler CLI → CSV output.

Two modes:
  ai   — uses an LLM to understand and extract data without selectors
  css  — uses hand-written CSS selectors for fast, deterministic extraction

Usage examples:
  python main.py ai  https://example.com/products --instruction "Extract all products with name and price"
  python main.py css https://example.com/products --schema schemas/products.json
  python main.py css https://example.com/products --schema schemas/products.json --output output/result.csv
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from crawl4ai import LLMConfig

from crawlers.ai_crawler import crawl_with_ai
from crawlers.traditional_crawler import crawl_with_selectors
from exporters.csv_exporter import export_to_csv
import config


# ── built-in demo schemas (used when --schema is not provided) ────────────────

_DEMO_AI_SCHEMA = {
    "type": "object",
    "properties": {
        "title":       {"type": "string", "description": "Title or name of the item"},
        "description": {"type": "string", "description": "Short description"},
        "price":       {"type": "string", "description": "Price, including currency symbol"},
        "url":         {"type": "string", "description": "Link to the item detail page"},
    },
}

_DEMO_CSS_SCHEMA = {
    "name": "Generic list items",
    "baseSelector": "article, li.item, div.card, div.product",
    "fields": [
        {"name": "title",       "selector": "h1, h2, h3",         "type": "text"},
        {"name": "description", "selector": "p",                    "type": "text"},
        {"name": "link",        "selector": "a",                    "type": "attribute", "attribute": "href"},
    ],
}


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Web crawler → CSV  |  modes: ai | css",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("mode", choices=["ai", "css"],
                   help="Extraction mode: 'ai' (LLM) or 'css' (selectors)")
    p.add_argument("url", help="URL to crawl")
    p.add_argument("--output", "-o", metavar="FILE",
                   help="Output CSV path (default: output/crawl_<timestamp>.csv)")
    p.add_argument("--schema", metavar="FILE",
                   help="Path to JSON schema file (uses built-in demo if omitted)")
    p.add_argument("--wait-for", metavar="SELECTOR", default=None,
                   help="CSS selector to wait for before extracting (useful for SPAs)")

    # AI-mode specific
    ai_group = p.add_argument_group("AI mode options")
    ai_group.add_argument("--instruction", default="Extract all meaningful items from this page.",
                          help="Natural language extraction instruction for the LLM")
    ai_group.add_argument("--provider", default=config.DEFAULT_LLM_PROVIDER,
                          metavar="PROVIDER",
                          help=f"LLM provider string, e.g. openai/gpt-4o-mini  (default: {config.DEFAULT_LLM_PROVIDER})")
    ai_group.add_argument("--api-key", default=config.DEFAULT_API_KEY, metavar="KEY",
                          help="API key for the LLM provider (reads from OPENAI_API_KEY env by default)")

    # CSS-mode specific
    css_group = p.add_argument_group("CSS mode options")
    css_group.add_argument("--js", metavar="CODE",
                           help="JavaScript snippet to execute before extraction (e.g. for infinite scroll)")

    return p


def _load_schema(path: str | None, mode: str) -> dict:
    if path is None:
        return _DEMO_AI_SCHEMA if mode == "ai" else _DEMO_CSS_SCHEMA

    schema_path = Path(path)
    if not schema_path.exists():
        sys.exit(f"Schema file not found: {schema_path}")

    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in schema file: {e}")


async def run(args: argparse.Namespace) -> None:
    schema = _load_schema(args.schema, args.mode)

    try:
        if args.mode == "ai":
            if not args.api_key and "ollama" not in args.provider:
                print(
                    "Warning: no API key provided and provider is not Ollama. "
                    "Set --api-key or OPENAI_API_KEY.",
                    file=sys.stderr,
                )
            llm_cfg = LLMConfig(provider=args.provider, api_token=args.api_key or "no-token")
            data = await crawl_with_ai(
                url=args.url,
                schema=schema,
                instruction=args.instruction,
                llm_config=llm_cfg,
                wait_for=args.wait_for,
            )

        else:  # css
            data = await crawl_with_selectors(
                url=args.url,
                schema=schema,
                wait_for=args.wait_for,
                js_code=args.js,
            )

    except RuntimeError as e:
        sys.exit(f"Crawl error: {e}")
    except ValueError as e:
        sys.exit(f"Parse error: {e}")

    if not data:
        print("No data extracted. Double-check your URL, schema, or selectors.")
        return

    export_to_csv(data, output_path=args.output)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
