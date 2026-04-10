"""
Traditional CSS-selector-based crawler using JsonCssExtractionStrategy.

Faster and cheaper than the AI path: zero LLM calls, sub-second extraction.
Requires a hand-written schema describing the CSS selectors, but is 100%
deterministic and costs nothing to run repeatedly.
"""
import json
from typing import Any

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
    JsonCssExtractionStrategy,
)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import HEADLESS, PAGE_TIMEOUT


async def crawl_with_selectors(
    url: str,
    schema: dict[str, Any],
    wait_for: str | None = None,
    js_code: str | None = None,
    headless: bool = HEADLESS,
    antibot: bool = False,
) -> list[dict[str, Any]]:
    """
    Fetch a page and extract data using CSS selectors defined in `schema`.

    The schema must follow Crawl4AI's JsonCssExtractionStrategy format:
        {
            "name": "My schema",
            "baseSelector": "div.item",   # repeated container element
            "fields": [
                {"name": "title", "selector": "h2", "type": "text"},
                {"name": "link",  "selector": "a",  "type": "attribute", "attribute": "href"},
            ]
        }

    Args:
        url:       Target URL.
        schema:    Extraction schema with baseSelector + fields.
        wait_for:  Optional CSS selector to wait for before extracting.
                   Useful for JS-rendered pages (e.g. "css:div.results").
        js_code:   Optional JS snippet to run before extraction
                   (e.g. scrolling to load lazy content).
        headless:  Run browser headlessly.
        antibot:   Enable stealth + magic + simulate_user + override_navigator
                   to bypass Cloudflare and similar protections.

    Returns:
        List of dicts, each representing one matched base element.

    Raises:
        RuntimeError: If the page could not be fetched.
        ValueError:   If the extracted content cannot be parsed.
    """
    browser_cfg = BrowserConfig(
        headless=headless,
        enable_stealth=antibot,
        user_agent_mode="random" if antibot else "",
        avoid_ads=True,
        light_mode=not antibot,  # light_mode conflicts with some stealth scripts
        verbose=False,
    )
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=JsonCssExtractionStrategy(schema=schema),
        page_timeout=PAGE_TIMEOUT,
        wait_for=wait_for,
        js_code=js_code,
        magic=antibot,
        simulate_user=antibot,
        override_navigator=antibot,
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)

    if not result.success:
        raise RuntimeError(f"Failed to fetch '{url}': {result.error_message}")

    if not result.extracted_content:
        return []

    try:
        data = json.loads(result.extracted_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse extracted content as JSON: {e}") from e

    if isinstance(data, dict):
        data = [data]

    return [item for item in data if isinstance(item, dict)]
