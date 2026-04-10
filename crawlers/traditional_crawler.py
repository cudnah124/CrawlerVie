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
    ProxyConfig,
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
    proxy_config: ProxyConfig | None = None,
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
        light_mode=not antibot,
        verbose=False,
        proxy_config=proxy_config,
    )
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=JsonCssExtractionStrategy(schema=schema),
        page_timeout=max(PAGE_TIMEOUT, 45_000) if antibot else PAGE_TIMEOUT,
        wait_for=wait_for,
        js_code=js_code,
        # SPA handling (Crawl4AI recipe) — enabled when antibot=True
        wait_until="load" if antibot else "domcontentloaded",
        delay_before_return_html=2.5 if antibot else 0.1,
        scan_full_page=antibot,
        scroll_delay=0.3,
        remove_overlay_elements=antibot,
        remove_consent_popups=antibot,
        # Anti-bot triad
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


async def main():
    """
    Crawl nhatot.com real estate listings using selectors derived from the real HTML.

    Selector notes:
      - li.ard7gu7            → regular listing items
      - li[itemprop=...] → featured/sticky items (both covered by baseSelector)
      - div.sqqmhlc / s1v12a2e → price row container (regular vs featured)
      - span.c1u6gyxh         → location text
      - span.bwq0cbs          → property type label (e.g. "Nhà ngõ, hẻm")
    These are atomic CSS utility classes in nhatot's design system (NOT Next.js
    module hashes), so they are stable across deployments.
    """
    import json as _json
    import pathlib
    import csv

    url = "https://www.nhatot.com/mua-ban-bat-dong-san"

    schema = {
        "name": "NhaTot Real Estate Listings",
        "baseSelector": "li.ard7gu7, li[itemprop='itemListElement']",
        "fields": [
            {
                "name": "title",
                "selector": "h2",
                "type": "text",
            },
            {
                "name": "price",
                # First span in the price row is always the total price (in red)
                "selector": "div.sqqmhlc span:first-child, div.s1v12a2e span:first-child",
                "type": "text",
            },
            {
                "name": "area_m2",
                # Last span in the price row is always the area
                "selector": "div.sqqmhlc span:last-child, div.s1v12a2e span:last-child",
                "type": "text",
            },
            {
                "name": "property_type",
                "selector": "span.bwq0cbs",
                "type": "text",
            },
            {
                "name": "location",
                "selector": "span.c1u6gyxh",
                "type": "text",
            },
            {
                "name": "link",
                "selector": "a.cqzlgv9, a[itemprop='item']",
                "type": "attribute",
                "attribute": "href",
            },
        ],
    }

    # Also persist the schema for reuse via main.py --schema
    schema_path = pathlib.Path(__file__).parent.parent / "schemas" / "www_nhatot_com_css.json"
    schema_path.parent.mkdir(exist_ok=True)
    schema_path.write_text(_json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Schema saved → {schema_path}")

    print(f"\nCrawling {url} …")
    try:
        results = await crawl_with_selectors(
            url, schema,
            wait_for=None,   # antibot=True already waits via wait_until=load + delay
            headless=True,
            antibot=True,
        )
        if results:
            print(f"✓ Extracted {len(results)} listings\n")
            for i, item in enumerate(results[:5]):
                print(f"--- #{i + 1} ---")
                print(_json.dumps(item, indent=2, ensure_ascii=False))

            # Save to CSV
            csv_path = pathlib.Path(__file__).parent.parent / "output" / "nhatot_listings.csv"
            csv_path.parent.mkdir(exist_ok=True)
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=results[0].keys())
                writer.writeheader()
                writer.writerows(results)
            print(f"\n✓ CSV saved → {csv_path}")
        else:
            print("No items extracted. Inspect debug_nhatot.html to verify selectors.")
    except (RuntimeError, ValueError) as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())



