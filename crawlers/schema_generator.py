"""
Auto-generates a CSS extraction schema from a live URL using LLM.

This is meant to be run once per new target site. The output schema is saved
as a .json file and then reused with the fast, free 'css' mode indefinitely.
"""
import asyncio
import json
from pathlib import Path

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
    JsonCssExtractionStrategy,
    LLMConfig,
)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import HEADLESS, PAGE_TIMEOUT


async def generate_schema(
    url: str,
    query: str,
    llm_config: LLMConfig,
    output_path: str | Path | None = None,
    headless: bool = HEADLESS,
) -> dict:
    """
    Crawl a URL, then ask an LLM to analyze the HTML and produce a
    JsonCssExtractionStrategy schema describing the repeating data items.

    Args:
        url:         Target URL to analyze.
        query:       Natural language description of what you want to extract.
                     E.g. "article titles, publication dates, and author names".
        llm_config:  LLM provider + credentials for schema generation.
        output_path: Where to save the generated schema JSON.
                     Defaults to schemas/<sanitized_hostname>.json.
        headless:    Browser visibility.

    Returns:
        The generated schema dict, also written to output_path.
    """
    browser_cfg = BrowserConfig(headless=headless, verbose=False)
    run_cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=PAGE_TIMEOUT)

    print(f"Fetching {url} …")
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)

    if not result.success:
        raise RuntimeError(f"Failed to fetch '{url}': {result.error_message}")

    print("Analyzing HTML with LLM — this may take 10–30 seconds …")
    schema = await JsonCssExtractionStrategy.agenerate_schema(
        html=result.html,
        schema_type="CSS",
        query=query,
        llm_config=llm_config,
    )

    # Resolve output path
    if output_path is None:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or "site"
        safe_name = hostname.replace(".", "_")
        output_path = Path("schemas") / f"{safe_name}_css.json"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")

    return schema
