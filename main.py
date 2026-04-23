#!/usr/bin/env python3
"""
Simple web crawler CLI → CSV output.

Six modes:
  ai         — uses an LLM to understand and extract data without selectors
  css        — uses hand-written CSS selectors for fast, deterministic extraction
  schema-gen — auto-generates a CSS schema for a URL using LLM (run once, reuse forever)
    nhatot     — scrape a single NhaTot ad (Playwright)
    nhatot-list — scrape multiple NhaTot ads from a listing page
    nhatot-csv — merge nhatot JSON files into a single CSV

Usage examples:
    python main.py ai  https://example.com/products --instruction "Extract all products"
    python main.py css https://example.com/products --schema schemas/products.json
    python main.py schema-gen https://example.com --query "article titles, dates, and authors"
    python main.py nhatot https://www.nhatot.com/.../131328316.htm
    python main.py nhatot-list https://www.nhatot.com/mua-ban-bat-dong-san --limit 10
    python main.py nhatot-csv output --output output/nhatot_all.csv
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

from crawl4ai import LLMConfig, ProxyConfig

from crawlers.ai_crawler import crawl_with_ai
from crawlers.traditional_crawler import crawl_with_selectors
from crawlers.schema_generator import generate_schema
from exporters.csv_exporter import export_to_csv
from web.nhatot_scraper import scrape_nhatot_ad, scrape_nhatot_listings
import config
from config import get_api_key


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
        {"name": "title",       "selector": "h1, h2, h3",  "type": "text"},
        {"name": "description", "selector": "p",            "type": "text"},
        {"name": "link",        "selector": "a",            "type": "attribute", "attribute": "href"},
    ],
}


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Web crawler → CSV  |  modes: ai | css | schema-gen",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("mode", choices=["ai", "css", "schema-gen", "nhatot", "nhatot-list", "nhatot-csv"],
                   help="ai: LLM extraction  |  css: selector extraction  |  schema-gen: auto-build CSS schema  |  nhatot: NhaTot ad  |  nhatot-list: listing page  |  nhatot-csv: merge nhatot JSON")
    p.add_argument("url", help="URL to crawl")
    p.add_argument("--output", "-o", metavar="FILE",
                   help="Output CSV path (default: output/crawl_<timestamp>.csv)")
    p.add_argument("--schema", metavar="FILE",
                   help="Path to JSON schema file (uses built-in demo if omitted)")
    p.add_argument("--wait-for", metavar="SELECTOR", default=None,
                   help="CSS selector to wait for before extracting (useful for SPAs)")
    p.add_argument("--antibot", action="store_true",
                   help="Enable anti-bot bypass (stealth, magic mode, simulate_user). "
                        "Use for sites protected by Cloudflare or similar.")
    p.add_argument("--proxy", metavar="URL", default=None,
                   help="Proxy URL to route requests through, e.g. "
                        "http://user:pass@host:port  (residential proxy bypasses Cloudflare on cloud)")

    # Shared LLM options (ai + schema-gen)
    llm_group = p.add_argument_group("LLM options (used by 'ai' and 'schema-gen' modes)")
    llm_group.add_argument("--provider", default=config.DEFAULT_LLM_PROVIDER,
                           metavar="PROVIDER",
                           help=f"LLM provider string (default: {config.DEFAULT_LLM_PROVIDER})")
    llm_group.add_argument("--api-key", default="", metavar="KEY",
                           help="API key (auto-detected from env if omitted)")
    llm_group.add_argument("--instruction", default="Extract all meaningful items from this page.",
                           help="[ai mode] Natural language extraction instruction for the LLM")

    # schema-gen specific
    sg_group = p.add_argument_group("schema-gen mode options")
    sg_group.add_argument("--query", default="",
                          help='Describe the data to extract, e.g. "product names, prices and ratings"')
    sg_group.add_argument("--schema-output", metavar="FILE", default=None,
                          help="Where to save the generated schema (default: schemas/<hostname>_css.json)")

    # CSS-mode specific
    css_group = p.add_argument_group("CSS mode options")
    css_group.add_argument("--js", metavar="CODE",
                           help="JavaScript snippet to execute before extraction")

    nhatot_group = p.add_argument_group("nhatot-list options")
    nhatot_group.add_argument("--limit", type=int, default=10,
                              help="Number of ads to scrape from the listing page")
    nhatot_csv_group = p.add_argument_group("nhatot-csv options")
    nhatot_csv_group.add_argument("--input-dir", default=None,
                                  help="Directory with nhatot_*.json files (default: first positional URL arg or output)")

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
    api_key = args.api_key or get_api_key(args.provider)
    proxy_cfg = ProxyConfig(server=args.proxy) if args.proxy else None

    # nhatot: scrape a single ad and print JSON
    if args.mode == "nhatot":
        ad_data = await asyncio.to_thread(scrape_nhatot_ad, args.url)
        if not ad_data:
            sys.exit("Failed to scrape NhaTot ad data.")
        output_path = args.output
        if not output_path:
            ad_id = None
            if isinstance(ad_data, dict):
                ad_id = ad_data.get("id", {}).get("ad_id")
            if ad_id:
                output_path = f"output/nhatot_{ad_id}.json"
            else:
                parsed = urlparse(args.url)
                slug = parsed.path.rstrip("/").split("/")[-1]
                slug = slug.replace(".htm", "").replace(".html", "")
                if not slug:
                    slug = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = f"output/nhatot_{slug}.json"
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(ad_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote nhatot output to: {out_file}")
        return

    # nhatot-list: scrape multiple ads and save per-ad JSON files
    if args.mode == "nhatot-list":
        ads = await asyncio.to_thread(scrape_nhatot_listings, args.url, args.limit)
        if not ads:
            sys.exit("Failed to scrape NhaTot listing.")
        output_dir = Path(args.output) if args.output else Path("output")
        if output_dir.suffix == ".json":
            output_dir = output_dir.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        for ad in ads:
            ad_id = ad.get("id", {}).get("ad_id") if isinstance(ad, dict) else None
            if ad_id:
                filename = f"nhatot_{ad_id}.json"
            else:
                filename = f"nhatot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            out_file = output_dir / filename
            out_file.write_text(json.dumps(ad, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Wrote nhatot output to: {out_file}")
        return

    # nhatot-csv: merge nhatot JSON files in a directory
    if args.mode == "nhatot-csv":
        input_dir = Path(args.input_dir or args.url or "output")
        if not input_dir.exists() or not input_dir.is_dir():
            sys.exit(f"Input directory not found: {input_dir}")
        json_files = sorted(input_dir.glob("nhatot_*.json"))
        if not json_files:
            sys.exit(f"No nhatot_*.json files found in: {input_dir}")

        rows = []
        for file_path in json_files:
            try:
                rows.append(json.loads(file_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON: {file_path}")

        if not rows:
            sys.exit("No valid nhatot JSON files to export.")

        output_csv = args.output or (Path("output") / "nhatot_all.csv")
        export_to_csv(rows, output_path=output_csv)
        return

    # schema-gen: generate a schema and print/save it — no CSV output
    if args.mode == "schema-gen":
        if not api_key and "ollama" not in args.provider:
            sys.exit("schema-gen requires an LLM. Set --api-key or the matching env variable.")
        if not args.query:
            sys.exit("schema-gen requires --query  (describe the data you want to extract).")

        llm_cfg = LLMConfig(provider=args.provider, api_token=api_key)
        try:
            schema = await generate_schema(
                url=args.url,
                query=args.query,
                llm_config=llm_cfg,
                output_path=args.schema_output,
                antibot=args.antibot,
                proxy_config=proxy_cfg,
            )
        except RuntimeError as e:
            sys.exit(f"schema-gen error: {e}")

        print("\nGenerated schema:")
        print(json.dumps(schema, indent=2, ensure_ascii=False))
        return

    # ai / css modes
    schema = _load_schema(args.schema, args.mode)

    try:
        if args.mode == "ai":
            if not api_key and "ollama" not in args.provider:
                print(
                    "Warning: no API key provided and provider is not Ollama. "
                    "Set --api-key or the matching env variable.",
                    file=sys.stderr,
                )
            llm_cfg = LLMConfig(provider=args.provider, api_token=api_key or "no-token")
            data = await crawl_with_ai(
                url=args.url,
                schema=schema,
                instruction=args.instruction,
                llm_config=llm_cfg,
                wait_for=args.wait_for,
                antibot=args.antibot,
                proxy_config=proxy_cfg,
            )

        else:  # css
            data = await crawl_with_selectors(
                url=args.url,
                schema=schema,
                wait_for=args.wait_for,
                js_code=args.js,
                antibot=args.antibot,
                proxy_config=proxy_cfg,
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
