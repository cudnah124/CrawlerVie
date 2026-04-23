"""
crawlerai.schema_gen.generator — Auto-generate a CSS extraction schema from a live URL.

Uses an LLM to analyse the HTML of a page and produce a
``JsonCssExtractionStrategy``-compatible schema. Run this **once** per
new target site and save the output as a JSON file; then reuse it
with :func:`crawlerai.crawl_schema` indefinitely for zero-cost crawling.

Typical use::

    from crawlerai import generate_schema, crawl_schema

    # Step 1 — generate (costs 1 LLM call)
    schema = await generate_schema(
        url="https://example.com/listings",
        query="product names, prices, and links",
        save_to="schemas/example_css.json",
    )

    # Step 2 — reuse forever (free)
    results = await crawl_schema(url="https://example.com/listings", schema=schema)
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from crawl4ai import (
    AsyncWebCrawler,
    CrawlerRunConfig,
    CacheMode,
    JsonCssExtractionStrategy,
    LLMConfig,
    ProxyConfig,
)

from crawlerai.core.browser import make_browser_config
from crawlerai.config.settings import (
    get_api_key,
    get_default_provider,
    get_headless,
    get_page_timeout,
)

# JS guard: resolves True once the page has meaningful repeating content.
# Avoids generating a schema from skeleton HTML that hasn't hydrated yet.
_SPA_CONTENT_READY = """js:() => {
    const selectors = [
        'article', '[class*="item"]', '[class*="card"]',
        '[class*="listing"]', '[class*="product"]', '[class*="result"]',
        'li[class]', '.post', '.entry',
    ];
    for (const sel of selectors) {
        if (document.querySelectorAll(sel).length >= 3) return true;
    }
    return document.body.innerText.trim().length > 1000;
}"""

# Pre-scroll to trigger lazy-loaded images and infinite-scroll placeholders.
_SCROLL_JS = """
window.scrollTo(0, document.body.scrollHeight / 3);
await new Promise(r => setTimeout(r, 400));
window.scrollTo(0, document.body.scrollHeight * 2 / 3);
await new Promise(r => setTimeout(r, 400));
window.scrollTo(0, document.body.scrollHeight);
"""


async def generate_schema(
    url: str,
    query: str,
    *,
    save_to: str | Path | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    headless: bool | None = None,
    antibot: bool = False,
    proxy_config: ProxyConfig | None = None,
) -> dict:
    """
    Fetch *url* (with full SPA rendering), then ask an LLM to analyse the
    HTML and produce a :class:`crawl4ai.JsonCssExtractionStrategy` schema.

    Args:
        url:          Target URL.
        query:        Natural language description of the data to extract.
                      E.g. ``"real estate listing title, price, area, and link"``.
        save_to:      Path to save the generated schema JSON. If omitted, the
                      file is saved to ``schemas/<hostname>_css.json`` in the
                      current working directory.
        provider:     LLM provider string. Defaults to ``$LLM_PROVIDER`` env var.
        api_key:      API key. Auto-resolved from env if omitted.
        headless:     Browser headless mode. Defaults to ``$HEADLESS`` env var.
        antibot:      Enable stealth mode for protected pages.
        proxy_config: Optional proxy configuration.

    Returns:
        The generated schema dict (also written to *save_to*).

    Raises:
        RuntimeError: If the page could not be fetched.
    """
    resolved_provider = provider or get_default_provider()
    resolved_api_key = api_key or get_api_key(resolved_provider)
    resolved_headless = headless if headless is not None else get_headless()

    llm_cfg = LLMConfig(
        provider=resolved_provider,
        api_token=resolved_api_key or "no-token",
    )

    browser_cfg = make_browser_config(
        headless=resolved_headless,
        antibot=antibot,
        proxy_config=proxy_config,
    )

    # Use a plain CrawlerRunConfig here (no extraction strategy) — we only
    # need the raw HTML to feed to agenerate_schema().
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=max(get_page_timeout(), 45_000),  # SPAs need extra time
        # SPA handling — always enabled for schema-gen because we need real HTML
        wait_until="load",
        delay_before_return_html=2.5,
        wait_for=_SPA_CONTENT_READY,
        scan_full_page=True,
        scroll_delay=0.3,
        js_code=_SCROLL_JS,
        # Overlay/popup cleanup so the LLM sees actual content
        remove_overlay_elements=True,
        remove_consent_popups=True,
        # Anti-bot
        magic=antibot,
        simulate_user=antibot,
        override_navigator=antibot,
    )

    print(f"Fetching {url} with full SPA rendering …")
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)

    if not result.success:
        raise RuntimeError(f"Failed to fetch '{url}': {result.error_message}")

    text_len = len((result.markdown or "").strip())
    if text_len < 200:
        print(
            f"Warning: page content is very short ({text_len} chars). "
            "The site may require authentication or a residential proxy. "
            "Schema quality may be poor."
        )
    print(f"Got {text_len} chars of content. Analysing with LLM …")

    schema = await JsonCssExtractionStrategy.agenerate_schema(
        html=result.html,
        schema_type="CSS",
        query=query,
        llm_config=llm_cfg,
    )

    # Persist schema
    output_path = _resolve_save_path(save_to, url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Schema saved → {output_path}")

    return schema


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_save_path(save_to: str | Path | None, url: str) -> Path:
    if save_to is not None:
        return Path(save_to)
    hostname = urlparse(url).hostname or "site"
    safe_name = hostname.replace(".", "_")
    return Path("schemas") / f"{safe_name}_css.json"
