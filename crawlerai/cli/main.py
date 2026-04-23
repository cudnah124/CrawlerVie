"""
crawlerai CLI — command-line interface for the crawlerai library.

Install CLI support::

    pip install "crawlerai[cli]"

Then use::

    crawlerai llm      <URL> [options]
    crawlerai schema   <URL> --schema schemas/example.json [options]
    crawlerai gen      <URL> --query "..." [options]
    crawlerai nhatot   <URL>
    crawlerai nhatot-list <URL> [--limit N]

Or run directly (no install)::

    python -m crawlerai.cli.main llm https://example.com --instruction "Extract products"
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

try:
    import click
except ImportError:
    print(
        "The CLI requires 'click'. Install it with:\n"
        '  pip install "crawlerai[cli]"',
        file=sys.stderr,
    )
    sys.exit(1)

from crawlerai import crawl_llm, crawl_schema, generate_schema
from crawlerai.exporters.csv_exporter import export_to_csv
from crawlerai.config.settings import get_default_provider


# ── Shared options ─────────────────────────────────────────────────────────────

_url_arg = click.argument("url")

def _shared_options(f):
    """Decorator: attach common options to any sub-command."""
    f = click.option("--output", "-o", default=None, help="Output CSV/JSON path.")(f)
    f = click.option("--antibot", is_flag=True, help="Enable stealth + anti-bot mode.")(f)
    f = click.option("--proxy", default=None, metavar="URL",
                     help="Proxy URL, e.g. http://user:pass@host:port")(f)
    f = click.option("--wait-for", default=None, metavar="SELECTOR",
                     help="CSS selector or JS expression to wait for before extracting.")(f)
    return f

def _llm_options(f):
    f = click.option("--provider", default=None,
                     help=f"LLM provider (default: {get_default_provider()})")(f)
    f = click.option("--api-key", default=None, help="LLM API key.")(f)
    return f


# ── CLI root ───────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(package_name="crawlerai")
def cli():
    """crawlerai — Lightweight web crawling with LLM and CSS schema extraction."""


# ── llm command ────────────────────────────────────────────────────────────────

@cli.command("llm")
@_url_arg
@click.option("--instruction", "-i",
              default="Extract all meaningful items from this page.",
              show_default=True,
              help="Natural language extraction instruction for the LLM.")
@click.option("--schema", "schema_path", default=None, metavar="FILE",
              help="Path to JSON schema file (uses built-in generic schema if omitted).")
@_llm_options
@_shared_options
def cmd_llm(url, instruction, schema_path, provider, api_key, output, antibot, proxy, wait_for):
    """Crawl URL using an LLM to extract structured data (no selectors needed)."""
    from crawl4ai import ProxyConfig
    schema = _load_json(schema_path) if schema_path else None
    proxy_cfg = ProxyConfig(server=proxy) if proxy else None

    click.echo(f"LLM crawl → {url}")
    try:
        data = asyncio.run(crawl_llm(
            url=url,
            instruction=instruction,
            schema=schema,
            provider=provider,
            api_key=api_key,
            wait_for=wait_for,
            antibot=antibot,
            proxy_config=proxy_cfg,
        ))
    except (RuntimeError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    _output_results(data, output)


# ── schema command ─────────────────────────────────────────────────────────────

@cli.command("schema")
@_url_arg
@click.option("--schema", "schema_path", default=None, metavar="FILE",
              help="Path to CSS schema JSON file.")
@click.option("--js", "js_code", default=None, metavar="CODE",
              help="JavaScript snippet to execute before extraction.")
@_shared_options
def cmd_schema(url, schema_path, js_code, output, antibot, proxy, wait_for):
    """Crawl URL using a CSS selector schema (fast, free, deterministic)."""
    from crawl4ai import ProxyConfig
    proxy_cfg = ProxyConfig(server=proxy) if proxy else None

    click.echo(f"Schema crawl → {url}")
    try:
        data = asyncio.run(crawl_schema(
            url=url,
            schema_path=schema_path,
            wait_for=wait_for,
            js_code=js_code,
            antibot=antibot,
            proxy_config=proxy_cfg,
        ))
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    _output_results(data, output)


# ── gen command ────────────────────────────────────────────────────────────────

@cli.command("gen")
@_url_arg
@click.option("--query", "-q", required=True,
              help='Describe data to extract, e.g. "product names, prices, and links".')
@click.option("--save-to", default=None, metavar="FILE",
              help="Path to save the generated schema (default: schemas/<hostname>_css.json).")
@_llm_options
@_shared_options
def cmd_gen(url, query, save_to, provider, api_key, output, antibot, proxy, wait_for):
    """Generate a CSS selector schema for URL using an LLM (run once, reuse forever)."""
    from crawl4ai import ProxyConfig
    proxy_cfg = ProxyConfig(server=proxy) if proxy else None

    click.echo(f"Generating schema for {url} …")
    try:
        schema = asyncio.run(generate_schema(
            url=url,
            query=query,
            save_to=save_to,
            provider=provider,
            api_key=api_key,
            antibot=antibot,
            proxy_config=proxy_cfg,
        ))
    except RuntimeError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo("\nGenerated schema:")
    click.echo(json.dumps(schema, indent=2, ensure_ascii=False))


# ── nhatot commands ────────────────────────────────────────────────────────────

@cli.command("nhatot")
@_url_arg
@click.option("--output", "-o", default=None, help="Output JSON path.")
def cmd_nhatot(url, output):
    """Scrape a single NhaTot.com real-estate ad."""
    from crawlerai.sites.nhatot import scrape_ad

    click.echo(f"Scraping NhaTot ad → {url}")
    ad_data = scrape_ad(url)
    if not ad_data:
        click.echo("Failed to scrape ad.", err=True)
        sys.exit(1)

    if output is None:
        ad_id = ad_data.get("id", {}).get("ad_id") if isinstance(ad_data, dict) else None
        if ad_id:
            output = f"output/nhatot_{ad_id}.json"
        else:
            slug = urlparse(url).path.rstrip("/").split("/")[-1].replace(".htm", "")
            output = f"output/nhatot_{slug or datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ad_data, indent=2, ensure_ascii=False), encoding="utf-8")
    click.echo(f"Saved → {out}")


@cli.command("nhatot-list")
@_url_arg
@click.option("--limit", default=10, show_default=True, help="Number of ads to scrape.")
@click.option("--output-dir", default="output", show_default=True,
              help="Directory to save per-ad JSON files.")
def cmd_nhatot_list(url, limit, output_dir):
    """Scrape multiple NhaTot.com ads from a listing page."""
    from crawlerai.sites.nhatot import scrape_listings

    click.echo(f"Scraping up to {limit} ads from {url} …")
    ads = scrape_listings(url, limit)
    if not ads:
        click.echo("No ads scraped.", err=True)
        sys.exit(1)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for ad in ads:
        ad_id = ad.get("id", {}).get("ad_id") if isinstance(ad, dict) else None
        fname = f"nhatot_{ad_id}.json" if ad_id else \
                f"nhatot_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        (out_dir / fname).write_text(json.dumps(ad, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
        click.echo(f"  Saved → {out_dir / fname}")


# ── helpers ────────────────────────────────────────────────────────────────────

def _load_json(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        click.echo(f"Schema file not found: {p}", err=True)
        sys.exit(1)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        click.echo(f"Invalid JSON in {p}: {exc}", err=True)
        sys.exit(1)


def _output_results(data: list[dict], output_path: str | None) -> None:
    if not data:
        click.echo("No data extracted. Check your URL, schema, or selectors.")
        return
    try:
        export_to_csv(data, output_path=output_path)
    except ValueError as exc:
        click.echo(f"Export error: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
