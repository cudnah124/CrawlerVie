"""
crawlerai.strategies.llm_strategy — LLM-powered web extraction.

Uses crawl4ai's LLMExtractionStrategy to let an AI model read the page
and pull out structured data without needing hand-written selectors.

Typical use::

    from crawlerai import crawl_llm

    results = await crawl_llm(
        url="https://example.com/products",
        instruction="Extract all products with name, price, and URL",
        provider="openai/gpt-4o-mini",   # or any litellm-compatible string
    )
    # results → list[dict]
"""
from __future__ import annotations

import json
from typing import Any

from crawl4ai import AsyncWebCrawler, LLMExtractionStrategy, LLMConfig, ProxyConfig

from crawlerai.core.browser import make_browser_config
from crawlerai.core.run_config import make_run_config
from crawlerai.config.settings import (
    get_api_key,
    get_default_provider,
    get_headless,
    get_page_timeout,
    get_chunk_token_threshold,
)

# Default schema — used when the caller does not provide one.
# Covers the most common "list of items" use-case out of the box.
_DEFAULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title":       {"type": "string", "description": "Title or name of the item"},
        "description": {"type": "string", "description": "Short description or summary"},
        "price":       {"type": "string", "description": "Price including currency symbol"},
        "url":         {"type": "string", "description": "Link to the item detail page"},
    },
}


async def crawl_llm(
    url: str,
    *,
    instruction: str = "Extract all meaningful items from this page.",
    schema: dict[str, Any] | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    wait_for: str | None = None,
    headless: bool | None = None,
    antibot: bool = False,
    proxy_config: ProxyConfig | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch *url* and extract structured data using an LLM.

    The LLM receives the page content as markdown (filtered to remove noise)
    and returns JSON matching *schema*. No CSS selectors needed.

    Args:
        url:          Target URL to crawl.
        instruction:  Natural language hint telling the LLM what to extract.
                      E.g. ``"Extract all job listings with title, company, and salary"``.
        schema:       JSON Schema dict describing the expected output structure.
                      Defaults to a generic ``{title, description, price, url}`` schema.
        provider:     LLM provider string in litellm format, e.g.
                      ``"openai/gpt-4o-mini"`` or ``"gemini/gemini-2.0-flash"``.
                      Defaults to ``$LLM_PROVIDER`` env var or ``openai/gpt-4o-mini``.
        api_key:      API key for the provider. Auto-resolved from env if omitted.
        wait_for:     CSS selector or JS expression to wait for before reading the DOM.
                      Useful for SPAs. E.g. ``"css:div.product-list"``.
        headless:     Run browser without a visible window. Defaults to ``$HEADLESS`` env.
        antibot:      Enable stealth mode (random user-agent, magic mode,
                      simulate_user, override_navigator). Use for Cloudflare-protected sites.
        proxy_config: Optional :class:`crawl4ai.ProxyConfig` for routing through a proxy.

    Returns:
        List of dicts. Each dict is one extracted item matching *schema*.
        Empty list if nothing was extracted or LLM returned no usable content.

    Raises:
        RuntimeError: If the page could not be fetched.
        ValueError:   If the LLM response is not valid JSON.
    """
    resolved_provider = provider or get_default_provider()
    resolved_api_key = api_key or get_api_key(resolved_provider)
    resolved_headless = headless if headless is not None else get_headless()
    resolved_schema = schema or _DEFAULT_SCHEMA

    llm_cfg = LLMConfig(
        provider=resolved_provider,
        api_token=resolved_api_key or "no-token",
    )

    strategy = LLMExtractionStrategy(
        llm_config=llm_cfg,
        schema=resolved_schema,
        extraction_type="schema",
        instruction=instruction,
        # fit_markdown = pruned markdown → cheaper on tokens than raw HTML
        input_format="fit_markdown",
        chunk_token_threshold=get_chunk_token_threshold(),
        verbose=True,
    )

    browser_cfg = make_browser_config(
        headless=resolved_headless,
        antibot=antibot,
        proxy_config=proxy_config,
    )
    run_cfg = make_run_config(
        strategy=strategy,
        wait_for=wait_for,
        antibot=antibot,
        page_timeout=get_page_timeout(),
        use_markdown_filter=True,   # prune noise before sending to LLM
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
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    # Normalise to list
    if isinstance(data, dict):
        data = [data]

    # Drop crawl4ai error-marker objects (injected when a chunk fails)
    return [item for item in data if isinstance(item, dict) and not item.get("error")]
