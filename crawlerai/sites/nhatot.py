"""
crawlerai.sites.nhatot — Site-specific crawler for NhaTot.com.

NhaTot is a Vietnamese real-estate marketplace (Next.js SPA) that requires:
  - A visible Playwright browser (headless detection is active)
  - playwright-stealth to pass fingerprint checks
  - Manual "Hiện số" button interaction to reveal phone numbers
  - Extracting structured data from the ``__NEXT_DATA__`` JSON payload

Public API::

    from crawlerai.sites.nhatot import scrape_ad, scrape_listings

    # Single ad (synchronous)
    ad = scrape_ad("https://www.nhatot.com/.../131328316.htm")

    # Multiple ads from a listing page
    ads = scrape_listings("https://www.nhatot.com/mua-ban-bat-dong-san", limit=10)

    # From an async context
    import asyncio
    ad = await asyncio.to_thread(scrape_ad, url)
"""
from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

try:
    from playwright_stealth import stealth_sync as _stealth_fn
except ImportError:
    try:
        from playwright_stealth import stealth as _stealth_fn  # type: ignore[no-redef]
    except ImportError:
        _stealth_fn = None  # type: ignore[assignment]


# ── Stealth helper ─────────────────────────────────────────────────────────────

def _apply_stealth(page) -> None:
    if _stealth_fn is None:
        return
    try:
        _stealth_fn(page)
    except Exception:
        pass


# ── Page-level helpers ─────────────────────────────────────────────────────────

def _wait_for_next_data(page, max_wait_ms: int = 180_000) -> bool:
    """Poll until ``__NEXT_DATA__`` appears in the DOM or timeout."""
    start = datetime.now()
    notified = False
    while True:
        if page.locator("#__NEXT_DATA__").count() > 0:
            return True
        title = page.title()
        if ("Just a moment" in title or "ShieldSquare" in title) and not notified:
            print("Captcha detected. Please solve it in the opened browser. Waiting…")
            notified = True
        elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
        if elapsed_ms >= max_wait_ms:
            return False
        page.wait_for_timeout(2000)


def _try_reveal_phone(page) -> bool:
    """Click the 'Hiện số' button and return True if a phone number appeared."""
    css_selectors = [
        "button.b1b6q6wa.primary.r-normal.large.w-bold",
        "[class*='LeadButton__showPhoneButton__'] button",
        "[class*='ShowPhoneButton_wrapper__'] button",
        ".InlineShowPhoneButton_linkContact__U_lEr",
        ".InlineShowPhoneButton_phoneHidden__4KcON",
        "button.b14cwtpv.link.r-normal.small.w-bold.t-link",
        ".b14cwtpv.link.r-normal.small.w-bold.t-link",
        "a.b14cwtpv.link.r-normal.small.w-bold.t-link",
    ]
    text_candidates = ["Hiện số", "Hiện số điện thoại", "Xem số", "Liên hệ"]

    for _ in range(5):
        for sel in css_selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    loc.first.scroll_into_view_if_needed(timeout=2000)
                    loc.first.click(timeout=2000, force=True)
                    page.wait_for_timeout(800)
                    if _wait_for_revealed_phone(page, timeout_ms=1500):
                        return True
            except Exception:
                continue

    for _ in range(3):
        for text in text_candidates:
            try:
                loc = page.get_by_text(text, exact=False)
                if loc.count() > 0:
                    loc.first.scroll_into_view_if_needed(timeout=2000)
                    loc.first.click(timeout=2000, force=True)
                    page.wait_for_timeout(800)
                    if _wait_for_revealed_phone(page, timeout_ms=1500):
                        return True
            except Exception:
                continue

    # Last resort: dispatch click via JS
    try:
        page.evaluate(r"""() => {
            const el = document.querySelector('button.b1b6q6wa.primary.r-normal.large.w-bold')
                || document.querySelector("[class*='LeadButton__showPhoneButton__'] button")
                || document.querySelector("[class*='ShowPhoneButton_wrapper__'] button")
                || document.querySelector('.b14cwtpv.link.r-normal.small.w-bold.t-link');
            if (el) { el.click(); return true; }
            return false;
        }""")
        page.wait_for_timeout(1000)
        return True
    except Exception:
        return False


def _wait_for_revealed_phone(page, timeout_ms: int = 8000) -> bool:
    """Wait until the phone button text contains a valid 10-or-11-digit number."""
    try:
        page.wait_for_function(
            r"""() => {
                const btn = document.querySelector('button.b1b6q6wa.primary.r-normal.large.w-bold')
                    || document.querySelector("[class*='LeadButton__showPhoneButton__'] button")
                    || document.querySelector("[class*='ShowPhoneButton_wrapper__'] button")
                    || document.querySelector('.InlineShowPhoneButton_linkContact__U_lEr')
                    || document.querySelector('.b14cwtpv.link.r-normal.small.w-bold.t-link');
                if (!btn) return false;
                const digits = (btn.textContent || '').replace(/\D/g, '');
                return digits.length >= 10 && digits.length <= 11 && !digits.startsWith('1900');
            }""",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


def _extract_phone_from_dom(page) -> dict | None:
    """Return ``{phone, candidates}`` extracted from the DOM."""
    try:
        return page.evaluate(r"""() => {
            const root = document;
            const candidates = [];

            const tel = root.querySelector('a[href^="tel:"]');
            if (tel) {
                candidates.push(tel.getAttribute('href').replace('tel:', '').replace(/\D/g, ''));
            }

            const btn = root.querySelector('button.b1b6q6wa.primary.r-normal.large.w-bold')
                || root.querySelector("[class*='LeadButton__showPhoneButton__'] button")
                || root.querySelector("[class*='ShowPhoneButton_wrapper__'] button")
                || root.querySelector('.InlineShowPhoneButton_linkContact__U_lEr')
                || root.querySelector('.b14cwtpv.link.r-normal.small.w-bold.t-link');
            if (btn) {
                const raw = (btn.textContent || '').replace(/Sao\s*ch[ée]p/gi, ' ');
                candidates.push(raw.replace(/\D/g, ''));
                const dataPhone = btn.getAttribute('data-phone') || btn.getAttribute('data-number');
                if (dataPhone) candidates.push(dataPhone.replace(/\D/g, ''));
            }

            const unique = [...new Set(candidates.filter(Boolean))];
            const phone = unique.find(p => p.length >= 10 && p.length <= 11 && !p.startsWith('1900')) || null;
            return { phone, candidates: unique };
        }""")
    except Exception:
        return None


# ── Data parsing helpers ───────────────────────────────────────────────────────

def _find_ad_data(data: dict) -> dict | None:
    """Walk the __NEXT_DATA__ tree to find the ad payload."""
    well_known_paths = [
        ("props", "pageProps", "ad"),
        ("props", "pageProps", "initialProps", "ad"),
        ("props", "pageProps", "data", "ad"),
        ("props", "pageProps", "detail", "ad"),
    ]
    for path in well_known_paths:
        node = data
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                node = None
                break
        if isinstance(node, dict) and node:
            return node

    # Fallback: walk the whole tree looking for a dict with known ad keys
    primary = {"subject", "price_str", "images"}
    secondary = {"ad_id", "list_time", "area_name", "region_name"}

    def _walk(obj):
        if isinstance(obj, dict):
            if primary.issubset(obj) or (primary & obj and secondary & obj):
                return obj
            for v in obj.values():
                found = _walk(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _walk(item)
                if found:
                    return found
        return None

    return _walk(data)


def _dedupe(items: list) -> list:
    seen: set[str] = set()
    result = []
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else str(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _collect_params(ad_data: dict) -> list[dict]:
    """Merge and normalise all parameter fields into a unified list."""
    raw: list[dict] = []
    for key in ("params", "parameters", "pty_characteristics", "ad_features"):
        val = ad_data.get(key)
        if isinstance(val, list):
            raw.extend(val)

    normalized: list[dict] = []
    existing_labels: set[str] = set()

    for item in raw:
        if not isinstance(item, dict):
            continue
        label = item.get("label") or item.get("name") or item.get("title")
        value = item.get("value") or item.get("val") or item.get("text")
        param_id = item.get("id") or item.get("key") or item.get("code")
        if label is None and value is None:
            continue
        key_str = str(label).strip().lower()
        if key_str in existing_labels:
            continue
        existing_labels.add(key_str)
        normalized.append({"id": param_id, "label": label, "value": value})

    def _add(label: str, value, param_id=None):
        if value is None:
            return
        if label.strip().lower() in existing_labels:
            return
        existing_labels.add(label.strip().lower())
        normalized.append({"id": param_id, "label": label, "value": value})

    size = ad_data.get("size")
    size_unit = ad_data.get("size_unit_string")
    if size is not None and size_unit:
        _add("Diện tích đất", f"{size} {size_unit}", "size")

    price_m2 = ad_data.get("price_million_per_m2")
    if price_m2 is not None:
        _add("Giá/m²", f"{price_m2} triệu/m²", "price_m2")

    legal_map = {1: "Đã có sổ", 2: "Đang chờ sổ", 3: "Giấy tờ khác", 4: "Vi bằng", 5: "Sổ chung"}
    legal_code = ad_data.get("property_legal_document")
    if legal_code in legal_map:
        _add("Giấy tờ pháp lý", legal_map[legal_code], "property_legal_document")

    direction_map = {1: "Đông", 2: "Tây", 3: "Nam", 4: "Bắc",
                     5: "Đông Bắc", 6: "Tây Bắc", 7: "Đông Nam", 8: "Tây Nam"}
    direction = ad_data.get("direction") or ad_data.get("direction_name")
    if isinstance(direction, int):
        direction = direction_map.get(direction)
    if direction:
        _add("Hướng đất", direction, "direction")

    if (w := ad_data.get("width")) is not None:
        _add("Chiều ngang", f"{w} m", "width")
    if (l := ad_data.get("length")) is not None:
        _add("Chiều dài", f"{l} m", "length")

    return _dedupe(normalized)


def _parse_timestamp(list_time) -> str | None:
    if list_time is None:
        return None
    try:
        if isinstance(list_time, (int, float)):
            ts = list_time / 1000.0 if list_time > 1_000_000_000_000 else list_time
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        return datetime.fromisoformat(str(list_time).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def scrape_ad(url: str) -> dict | None:
    """
    Scrape a single NhaTot real-estate ad and return structured data.

    Opens a **visible** Chromium window because NhaTot detects headless
    browsers. The scraper will:

    1. Navigate to *url* and wait for ``__NEXT_DATA__``.
    2. Click "Hiện số" to reveal the phone number.
    3. Parse and return all ad fields.

    Args:
        url: Full URL to a NhaTot ad, e.g.
             ``"https://www.nhatot.com/.../131328316.htm"``

    Returns:
        Dict with keys ``id``, ``title``, ``description``, ``category``,
        ``price``, ``size``, ``rooms``, ``legal``, ``location``, ``seller``,
        ``media``, ``meta``, ``params``, ``posting_date``.
        Returns ``None`` if fetching or parsing fails.
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        _apply_stealth(page)

        next_data = None
        phone_text = None
        html_content = ""

        try:
            print(f"Navigating to {url} …")
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)

            if not _wait_for_next_data(page, max_wait_ms=180_000):
                raise PlaywrightTimeoutError("Timeout waiting for __NEXT_DATA__")

            page.wait_for_timeout(3000)
            _try_reveal_phone(page)
            _wait_for_revealed_phone(page, timeout_ms=8000)
            page.wait_for_timeout(500)

            for _ in range(6):
                result = _extract_phone_from_dom(page)
                if isinstance(result, dict):
                    phone_text = result.get("phone")
                if phone_text and not phone_text.startswith("1900"):
                    break
                page.wait_for_timeout(500)

            print(f"Revealed phone: {phone_text}")
            next_data = page.evaluate("() => window.__NEXT_DATA__ || null")
            html_content = page.content()
        except Exception as exc:
            print(f"Error fetching {url}: {exc}")
            browser.close()
            return None
        finally:
            browser.close()

    # --- Parse __NEXT_DATA__ ---
    try:
        if next_data:
            data = next_data
        else:
            soup = BeautifulSoup(html_content, "html.parser")
            tag = soup.find("script", {"id": "__NEXT_DATA__"})
            if not tag:
                print("Could not find __NEXT_DATA__ in HTML.")
                return None
            data = json.loads(tag.string or tag.text)

        ad_data = _find_ad_data(data) or {}
        if not ad_data:
            print("Could not locate ad payload in __NEXT_DATA__.")
            return None
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"JSON parse error: {exc}")
        return None

    info: dict = {
        "id": {
            "ad_id":      ad_data.get("ad_id"),
            "list_id":    ad_data.get("list_id"),
            "account_id": ad_data.get("account_id"),
        },
        "title":       ad_data.get("subject"),
        "description": ad_data.get("body"),
        "category": {
            "category":      ad_data.get("category"),
            "category_name": ad_data.get("category_name"),
        },
        "price": {
            "price":               ad_data.get("price"),
            "price_string":        ad_data.get("price_string") or ad_data.get("price_str"),
            "price_million_per_m2": ad_data.get("price_million_per_m2"),
        },
        "size": {
            "size":        ad_data.get("size"),
            "size_unit":   ad_data.get("size_unit_string"),
            "width":       ad_data.get("width"),
            "length":      ad_data.get("length"),
            "living_size": ad_data.get("living_size"),
        },
        "rooms": {
            "rooms":          ad_data.get("rooms"),
            "toilets":        ad_data.get("toilets"),
            "floors":         ad_data.get("floors"),
            "house_type":     ad_data.get("house_type"),
            "furnishing_sell": ad_data.get("furnishing_sell"),
        },
        "legal": {
            "property_legal_document": ad_data.get("property_legal_document"),
        },
        "location": {
            "street_number": ad_data.get("street_number"),
            "street_name":   ad_data.get("street_name"),
            "ward_name":     ad_data.get("ward_name"),
            "area_name":     ad_data.get("area_name"),
            "region_name":   ad_data.get("region_name"),
            "latitude":      ad_data.get("latitude"),
            "longitude":     ad_data.get("longitude"),
        },
        "seller": {
            "account_name": ad_data.get("account_name") or ad_data.get("full_name"),
            "avatar":       ad_data.get("avatar"),
            "phone":        ad_data.get("phone"),
            "company_ad":   ad_data.get("company_ad"),
        },
        "media": {
            "images": _dedupe(ad_data.get("images", [])),
            "videos": ad_data.get("videos", []),
        },
        "meta": {
            "list_time": ad_data.get("list_time"),
            "state":     ad_data.get("state"),
            "status":    ad_data.get("status"),
            "type":      ad_data.get("type"),
        },
        "params":       _collect_params(ad_data),
        "posting_date": _parse_timestamp(ad_data.get("list_time")),
    }

    # Use the DOM-revealed phone if it's more complete
    if phone_text and not phone_text.startswith("1900"):
        info["seller"]["phone"] = phone_text

    return info


def scrape_listings(list_url: str, limit: int = 10) -> list[dict]:
    """
    Scrape multiple NhaTot ads from a listing page.

    Collects up to *limit* individual ad links from *list_url*, then calls
    :func:`scrape_ad` on each one.

    Args:
        list_url: URL of a NhaTot listing page.
        limit:    Max number of ads to scrape (default 10).

    Returns:
        List of ad dicts. Ads that fail to scrape are skipped.
    """
    links: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        _apply_stealth(page)

        try:
            print(f"Loading listing page: {list_url} …")
            page.goto(list_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3000)

            for _ in range(8):
                hrefs = page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))"
                )
                for href in hrefs:
                    if not href or ".htm" not in href:
                        continue
                    if "nhatot.com" not in href:
                        href = urljoin(list_url, href)
                    if "/mua-ban" not in href:
                        continue
                    if href not in links:
                        links.append(href)
                if len(links) >= limit:
                    break
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
        except Exception as exc:
            print(f"Error loading listing page: {exc}")
        finally:
            browser.close()

    results = []
    for href in links[:limit]:
        ad = scrape_ad(href)
        if ad:
            results.append(ad)
    return results


__all__ = ["scrape_ad", "scrape_listings"]
