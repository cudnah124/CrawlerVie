"""
Auto-generates a CSS extraction schema from a live URL using LLM.

This is meant to be run once per new target site. The output schema is saved
as a .json file and then reused with the fast, free 'css' mode indefinitely.

SPA handling follows Crawl4AI's documented approach:
  - wait_until="load"         lets anti-bot JS finish before DOM is checked
  - delay_before_return_html  gives React/Next.js time to hydrate after load
  - scan_full_page            scrolls the viewport to trigger lazy-loaded items
  - remove_overlay_elements   dismisses banners/cookie popups blocking content
  - wait_for (JS expression)  waits until actual repeating items appear in DOM
"""
import json
from pathlib import Path
from urllib.parse import urlparse

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
    JsonCssExtractionStrategy,
    LLMConfig,
    ProxyConfig,
)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import HEADLESS, PAGE_TIMEOUT

# JS expression that resolves True once the page has meaningful repeating content.
# Checks for common listing/article/card patterns used by most SPAs.
_SPA_CONTENT_READY = """js:() => {
    const selectors = [
        'article', '[class*="item"]', '[class*="card"]',
        '[class*="listing"]', '[class*="product"]', '[class*="result"]',
        'li[class]', '.post', '.entry',
    ];
    for (const sel of selectors) {
        if (document.querySelectorAll(sel).length >= 3) return true;
    }
    // Fallback: page has enough visible text (JSON-LD pages won't)
    return document.body.innerText.trim().length > 1000;
}"""

# Scroll the full page to trigger lazy-loaded images and infinite-scroll placeholders.
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
    llm_config: LLMConfig,
    output_path: str | Path | None = None,
    headless: bool = HEADLESS,
    antibot: bool = False,
    proxy_config: ProxyConfig | None = None,
) -> dict:
    """
    Fetch a URL (with full SPA rendering), then ask an LLM to analyze the
    HTML and produce a JsonCssExtractionStrategy schema.

    Args:
        url:          Target URL.
        query:        Natural language desc of what to extract.
        llm_config:   LLM provider + credentials.
        output_path:  Where to save schema JSON (auto-named from hostname if None).
        headless:     Browser visibility.
        antibot:      Enable stealth + magic + simulate_user for Cloudflare bypass.
        proxy_config: Residential proxy to route requests through.

    Returns:
        The generated schema dict, also written to output_path.
    """
    browser_cfg = BrowserConfig(
        headless=headless,
        enable_stealth=antibot,
        user_agent_mode="random" if antibot else "",
        verbose=False,
        proxy_config=proxy_config,
    )

    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=max(PAGE_TIMEOUT, 45_000),   # SPAs need more time

        # ── Crawl4AI's SPA handling recipe ──────────────────────────────────
        wait_until="load",                         # wait for full JS execution
        delay_before_return_html=2.5,              # extra buffer for hydration
        wait_for=_SPA_CONTENT_READY,              # don't grab HTML until items exist
        scan_full_page=True,                       # scroll → trigger lazy loading
        scroll_delay=0.3,

        # Clean the page so the LLM sees content, not overlays
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

    # Sanity check: did we get real content or just skeleton HTML?
    text_len = len(result.markdown.strip()) if result.markdown else 0
    if text_len < 200:
        print(
            f"Warning: page text is very short ({text_len} chars). "
            "The site may require a logged-in session or a residential proxy.\n"
            "Proceeding anyway — schema quality may be poor."
        )

    print(f"Got {text_len} chars of content. Analyzing with LLM …")
    schema = await JsonCssExtractionStrategy.agenerate_schema(
        html=result.html,
        schema_type="CSS",
        query=query,
        llm_config=llm_config,
    )

    # Persist schema
    if output_path is None:
        hostname = urlparse(url).hostname or "site"
        safe_name = hostname.replace(".", "_")
        output_path = Path("schemas") / f"{safe_name}_css.json"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Schema saved → {output_path}")

    return schema
