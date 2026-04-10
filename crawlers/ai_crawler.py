"""
AI-powered crawler using LLMExtractionStrategy.

Uses Crawl4AI's AsyncWebCrawler to fetch pages and an LLM to intelligently
extract structured data without needing hand-written selectors.
"""
import json
import asyncio
from typing import Any

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
    LLMExtractionStrategy,
    LLMConfig,
)
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import HEADLESS, PAGE_TIMEOUT, CHUNK_TOKEN_THRESHOLD


def _make_browser_config(headless: bool) -> BrowserConfig:
    return BrowserConfig(
        headless=headless,
        enable_stealth=True,
        avoid_ads=True,
        verbose=False,
    )


def _make_run_config(strategy: LLMExtractionStrategy, wait_for: str | None) -> CrawlerRunConfig:
    # Use pruning filter so the LLM only sees meaningful text, not boilerplate.
    pruning_filter = PruningContentFilter(threshold=0.45, threshold_type="fixed")
    markdown_gen = DefaultMarkdownGenerator(content_filter=pruning_filter)

    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=strategy,
        markdown_generator=markdown_gen,
        page_timeout=PAGE_TIMEOUT,
        wait_for=wait_for,
    )


async def crawl_with_ai(
    url: str,
    schema: dict[str, Any],
    instruction: str,
    llm_config: LLMConfig,
    wait_for: str | None = None,
    headless: bool = HEADLESS,
) -> list[dict[str, Any]]:
    """
    Fetch a page and extract structured data using an LLM.

    Args:
        url:         Target URL.
        schema:      Dict describing the fields to extract (Pydantic JSON schema).
        instruction: Natural language hint for the LLM (e.g. "Extract all products").
        llm_config:  LLM provider + credentials.
        wait_for:    Optional CSS selector to wait for before extracting.
        headless:    Run browser headlessly.

    Returns:
        List of dicts, each representing one extracted item.

    Raises:
        RuntimeError: If the page could not be fetched.
        ValueError:   If the LLM response cannot be parsed.
    """
    strategy = LLMExtractionStrategy(
        llm_config=llm_config,
        schema=schema,
        extraction_type="schema",
        instruction=instruction,
        input_format="fit_markdown",  # cheaper on tokens than raw HTML
        chunk_token_threshold=CHUNK_TOKEN_THRESHOLD,
        verbose=True,
    )

    browser_cfg = _make_browser_config(headless)
    run_cfg = _make_run_config(strategy, wait_for)

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)

    if not result.success:
        raise RuntimeError(f"Failed to fetch '{url}': {result.error_message}")

    if not result.extracted_content:
        return []

    try:
        data = json.loads(result.extracted_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse LLM response as JSON: {e}") from e

    # The strategy can return a list or a single dict depending on the page.
    if isinstance(data, dict):
        data = [data]

    # Drop items that are entirely error markers (Crawl4AI injects these).
    return [item for item in data if isinstance(item, dict) and not item.get("error")]
