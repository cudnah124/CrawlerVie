"""
crawlerai.core.run_config — Shared CrawlerRunConfig factory.

Centralises the SPA-handling and anti-bot settings that every
crawling strategy needs. Strategies pass their own extraction
strategy object; everything else is handled here.
"""
from crawl4ai import CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator


def make_run_config(
    strategy,
    wait_for: str | None = None,
    js_code: str | None = None,
    antibot: bool = False,
    page_timeout: int = 30_000,
    use_markdown_filter: bool = False,
) -> CrawlerRunConfig:
    """
    Build a CrawlerRunConfig with all SPA- and anti-bot settings applied.

    Args:
        strategy:             An extraction strategy (LLMExtractionStrategy or
                              JsonCssExtractionStrategy).
        wait_for:             CSS selector or JS expression to wait for before
                              reading the DOM. E.g. ``"css:div.results"``.
        js_code:              JavaScript snippet to execute **before** extraction.
                              Useful for triggering lazy-loaded content.
        antibot:              Enable the full anti-bot triad:
                              ``magic``, ``simulate_user``, ``override_navigator``.
        page_timeout:         Maximum time (ms) to wait for the page to load.
        use_markdown_filter:  When True, apply PruningContentFilter to reduce
                              the markdown sent to the LLM (saves tokens).
                              Enable this for LLM strategies; leave False for CSS.

    Returns:
        A configured :class:`crawl4ai.CrawlerRunConfig` instance.
    """
    markdown_gen = None
    if use_markdown_filter:
        pruning_filter = PruningContentFilter(threshold=0.45, threshold_type="fixed")
        markdown_gen = DefaultMarkdownGenerator(content_filter=pruning_filter)

    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=strategy,
        markdown_generator=markdown_gen,

        # ── Timing ────────────────────────────────────────────────────────────
        page_timeout=max(page_timeout, 45_000) if antibot else page_timeout,
        wait_for=wait_for,
        js_code=js_code,

        # ── SPA handling (Crawl4AI recipe) ────────────────────────────────────
        # wait_until="load"          → wait for all JS to finish executing
        # delay_before_return_html  → extra buffer for React/Next.js hydration
        # scan_full_page             → scroll to trigger lazy-loaded items
        wait_until="load" if antibot else "domcontentloaded",
        delay_before_return_html=2.5 if antibot else 0.1,
        scan_full_page=antibot,
        scroll_delay=0.3,

        # ── UI cleanup ────────────────────────────────────────────────────────
        remove_overlay_elements=antibot,
        remove_consent_popups=antibot,

        # ── Anti-bot triad ────────────────────────────────────────────────────
        magic=antibot,
        simulate_user=antibot,
        override_navigator=antibot,
    )
