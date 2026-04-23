"""
crawlerai.strategies.schema_strategy — CSS selector-based web extraction.

Uses crawl4ai's JsonCssExtractionStrategy to extract structured data
using a hand-written (or auto-generated) CSS schema. No LLM needed —
fast, free, and 100 % deterministic.

Typical use::

    from crawlerai import crawl_schema

    results = await crawl_schema(
        url="https://news.ycombinator.com",
        schema={
            "name": "HN Stories",
            "baseSelector": "tr.athing",
            "fields": [
                {"name": "title", "selector": ".titleline a", "type": "text"},
                {"name": "link",  "selector": ".titleline a", "type": "attribute",
                 "attribute": "href"},
            ],
        },
    )

Schema format (JsonCssExtractionStrategy)::

    {
        "name":         "My Schema",          # human-readable label
        "baseSelector": "div.item",           # CSS selector for each repeated row
        "fields": [
            {"name": "title",   "selector": "h2",  "type": "text"},
            {"name": "link",    "selector": "a",   "type": "attribute",
             "attribute": "href"},
            {"name": "summary", "selector": "p",   "type": "text"},
        ]
    }

Supported field types: ``text``, ``html``, ``attribute``, ``regex``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crawl4ai import AsyncWebCrawler, JsonCssExtractionStrategy, ProxyConfig

from crawlerai.core.browser import make_browser_config
from crawlerai.core.run_config import make_run_config
from crawlerai.config.settings import get_headless, get_page_timeout

# Demo schema used when neither schema nor schema_path is provided.
_DEFAULT_SCHEMA: dict[str, Any] = {
    "name": "Generic list items",
    "baseSelector": "article, li.item, div.card, div.product",
    "fields": [
        {"name": "title",       "selector": "h1, h2, h3", "type": "text"},
        {"name": "description", "selector": "p",           "type": "text"},
        {"name": "link",        "selector": "a",           "type": "attribute",
         "attribute": "href"},
    ],
}


async def crawl_schema(
    url: str,
    *,
    schema: dict[str, Any] | None = None,
    schema_path: str | Path | None = None,
    wait_for: str | None = None,
    js_code: str | None = None,
    headless: bool | None = None,
    antibot: bool = False,
    proxy_config: ProxyConfig | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch *url* and extract structured data using a CSS selector schema.

    Provide either *schema* (a dict) or *schema_path* (path to a JSON file).
    If neither is given, a generic fallback schema is used (works on
    simple HTML pages; may not produce useful results on complex SPAs).

    Args:
        url:         Target URL to crawl.
        schema:      CSS extraction schema dict. See module docstring for format.
        schema_path: Path to a JSON file containing the schema. Loaded at call time.
                     *schema* takes precedence if both are given.
        wait_for:    CSS selector or JS expression to wait for before reading the DOM.
                     E.g. ``"css:li.product-card"`` for a React listing page.
        js_code:     JavaScript snippet executed **before** extraction. Useful for
                     scrolling to trigger lazy-loaded content.
                     E.g. ``"window.scrollTo(0, document.body.scrollHeight);"``
        headless:    Run browser without a visible window. Defaults to ``$HEADLESS``.
        antibot:     Enable stealth mode + anti-bot triad (magic, simulate_user,
                     override_navigator, random user-agent). Use for Cloudflare sites.
        proxy_config: Optional :class:`crawl4ai.ProxyConfig` proxy configuration.

    Returns:
        List of dicts, one per matched ``baseSelector`` element. Empty list if
        nothing matched or the page returned no content.

    Raises:
        FileNotFoundError: If *schema_path* is given but does not exist.
        ValueError:        If *schema_path* contains invalid JSON, or if the
                           extracted content cannot be parsed.
        RuntimeError:      If the page could not be fetched.
    """
    resolved_schema = _resolve_schema(schema, schema_path)
    resolved_headless = headless if headless is not None else get_headless()

    strategy = JsonCssExtractionStrategy(schema=resolved_schema)

    browser_cfg = make_browser_config(
        headless=resolved_headless,
        antibot=antibot,
        proxy_config=proxy_config,
        light_mode=True,  # schema mode doesn't need full rendering
    )
    run_cfg = make_run_config(
        strategy=strategy,
        wait_for=wait_for,
        js_code=js_code,
        antibot=antibot,
        page_timeout=get_page_timeout(),
        use_markdown_filter=False,  # CSS extraction reads from DOM, not markdown
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)

    if not result.success:
        raise RuntimeError(f"Failed to fetch '{url}': {result.error_message}")

    if not result.extracted_content:
        return []

    try:
        data = json.loads(result.extracted_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse extracted content as JSON: {exc}") from exc

    if isinstance(data, dict):
        data = [data]

    return [item for item in data if isinstance(item, dict)]


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_schema(
    schema: dict[str, Any] | None,
    schema_path: str | Path | None,
) -> dict[str, Any]:
    """Return the effective schema, loading from file if needed."""
    if schema is not None:
        return schema

    if schema_path is not None:
        path = Path(schema_path)
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in schema file '{path}': {exc}") from exc

    return _DEFAULT_SCHEMA
