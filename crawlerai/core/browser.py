"""
crawlerai.core.browser — Shared BrowserConfig factory.

Both LLM and Schema strategies call this to build a consistent
BrowserConfig without duplicating arguments.
"""
from crawl4ai import BrowserConfig, ProxyConfig


def make_browser_config(
    headless: bool = True,
    antibot: bool = False,
    proxy_config: ProxyConfig | None = None,
    light_mode: bool = True,
) -> BrowserConfig:
    """
    Build a BrowserConfig shared by all crawling strategies.

    Args:
        headless:     Run browser without a visible window.
        antibot:      Enable stealth mode and random user-agent to bypass bot detection.
        proxy_config: Optional proxy (e.g. residential proxy to bypass Cloudflare).
        light_mode:   Disable images/CSS for faster loads. Auto-disabled when antibot=True
                      because some anti-bot JS checks for rendered content.

    Returns:
        A configured :class:`crawl4ai.BrowserConfig` instance.
    """
    return BrowserConfig(
        headless=headless,
        # Stealth: randomises browser fingerprint to avoid bot detection
        enable_stealth=antibot,
        user_agent_mode="random" if antibot else "",
        avoid_ads=True,
        # light_mode speeds up non-antibot runs; disable when antibot=True so
        # the page renders fully and anti-bot JS sees a "real" browser.
        light_mode=light_mode and not antibot,
        verbose=False,
        proxy_config=proxy_config,
    )
