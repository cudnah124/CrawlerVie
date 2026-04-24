"""
crawlerai.sites.nhatot — Site-specific crawler for NhaTot.com.

Hai kiến trúc crawl được hỗ trợ (học từ crawl4ai):

**Sync + Headed** (mặc định, cho trang khó):
  - Dùng ``sync_playwright`` + ``headless=False``
  - Vượt qua anti-bot tốt nhất (browser thật, có stealth)
  - Phù hợp khi site yêu cầu giải captcha thủ công

  ::

      from crawlerai.sites.nhatot import scrape_ad, scrape_listings
      ad  = scrape_ad(url)
      ads = scrape_listings(list_url, limit=10)

**Async + Headless** (nhanh hơn, cho batch):
  - Dùng ``async_playwright`` + ``headless=True`` + stealth
  - Chạy nhiều URL đồng thời với ``asyncio.gather``
  - Dùng context-manager pattern giống crawl4ai ``AsyncWebCrawler``

  ::

      import asyncio
      from crawlerai.sites.nhatot import AsyncNhaTotCrawler

      # Single ad
      async with AsyncNhaTotCrawler() as crawler:
          ad = await crawler.scrape_ad(url)

      # Concurrent batch (nhanh ~Nx so với tuần tự)
      async with AsyncNhaTotCrawler() as crawler:
          ads = await crawler.scrape_many([url1, url2, url3], concurrency=3)

      # Listings page
      async with AsyncNhaTotCrawler() as crawler:
          ads = await crawler.scrape_listings(list_url, limit=10)
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import re
import shutil
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright, Page as AsyncPage


try:
    from playwright_stealth import stealth_sync as _stealth_sync_fn
except ImportError:
    try:
        from playwright_stealth import stealth as _stealth_sync_fn  # type: ignore[no-redef]
    except ImportError:
        _stealth_sync_fn = None  # type: ignore[assignment]

try:
    from playwright_stealth import stealth_async as _stealth_async_fn
except ImportError:
    _stealth_async_fn = None  # type: ignore[assignment]

def parse_vietnamese_time(time_str: str | None) -> datetime | None:
    """
    Hàm tiện ích trích xuất datetime từ chuỗi tiếng Việt như '5 phút trước', 'Hôm qua'...
    """
    if not time_str:
        return None
    time_str = time_str.lower()
    now = datetime.now()
    if 'vừa xong' in time_str:
        return now
    match = re.search(r'(\d+)\s+phút\s+trước', time_str)
    if match:
        return now - timedelta(minutes=int(match.group(1)))
    match = re.search(r'(\d+)\s+giờ\s+trước', time_str)
    if match:
        return now - timedelta(hours=int(match.group(1)))
    if 'hôm qua' in time_str:
        return now - timedelta(days=1)
    match = re.search(r'(\d+)\s+ngày\s+trước', time_str)
    if match:
        return now - timedelta(days=int(match.group(1)))
    match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', time_str)
    if match:
        try:
            from datetime import datetime as dt
            return dt.strptime(match.group(1), '%d/%m/%Y')
        except ValueError:
            pass
    return None
    return None


def clean_text(text: str | None) -> str:
    """
    Xóa các icon, emoji và ký tự đặc biệt gây nhiễu khỏi chuỗi văn bản.
    """
    if not text:
        return ""
    emoji_pattern = re.compile(
        "["
        "\U00010000-\U0010FFFF" # Emojis (non-BMP)
        "\u2600-\u27BF"         # Miscellaneous symbols
        "\u2300-\u23FF"         # Technical symbols
        "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text).strip()


# ── Stealth helpers ────────────────────────────────────────────────────────────

def _apply_stealth(page) -> None:
    """Apply stealth to a sync Playwright page."""
    if _stealth_sync_fn is None:
        return
    try:
        _stealth_sync_fn(page)
    except Exception:
        pass


async def _apply_stealth_async(page: AsyncPage) -> None:
    """Apply stealth to an async Playwright page."""
    if _stealth_async_fn is None:
        return
    try:
        await _stealth_async_fn(page)
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
            # Dùng intersection (giao tập hợp) thay vì toán tử & để tránh lỗi với dict
            if primary.issubset(obj) or (primary.intersection(obj) and secondary.intersection(obj)):
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
    if (length_val := ad_data.get("length")) is not None:
        _add("Chiều dài", f"{length_val} m", "length")

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

# Shared between sync scrape_ad and AsyncNhaTotCrawler._parse_page
def _build_info(ad_data: dict, phone_text: str | None = None) -> dict:
    """Build the unified output dict from a parsed ad_data payload."""
    info: dict = {
        "id": {
            "ad_id":      ad_data.get("ad_id"),
            "list_id":    ad_data.get("list_id"),
            "account_id": ad_data.get("account_id"),
        },
        "title":       clean_text(ad_data.get("subject")),
        "description": ad_data.get("body"),
        "category": {
            "category":      ad_data.get("category"),
            "category_name": ad_data.get("category_name"),
        },
        "price": {
            "price":                ad_data.get("price"),
            "price_string":         ad_data.get("price_string") or ad_data.get("price_str"),
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
            "rooms":           ad_data.get("rooms"),
            "toilets":         ad_data.get("toilets"),
            "floors":          ad_data.get("floors"),
            "house_type":      ad_data.get("house_type"),
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
            "ad_url":    ad_url,
            "list_time": ad_data.get("list_time"),
            "view_count": ad_data.get("view_count") or ad_data.get("total_views") or 0,
            "state":     ad_data.get("state"),
            "status":    ad_data.get("status"),
            "type":      ad_data.get("type"),
        },
        "params":       _collect_params(ad_data),
        "posting_date": _parse_timestamp(ad_data.get("list_time")),
    }
    if phone_text and not phone_text.startswith("1900"):
        info["seller"]["phone"] = phone_text
    return info

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

    return _build_info(ad_data, phone_text)


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


__all__ = ["scrape_ad", "scrape_listings", "AsyncNhaTotCrawler"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Async + Headless architecture — học từ crawl4ai AsyncWebCrawler pattern
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AsyncNhaTotCrawler:
    """
    Async + Headless crawler cho NhaTot.com.

    Học theo kiến trúc ``AsyncWebCrawler`` của crawl4ai:
    - Dùng ``async_playwright`` với browser pool được chia sẻ giữa các lần crawl.
    - Dùng context manager (``async with``) để tự start/close browser.
    - Hỗ trợ concurrent crawl qua :meth:`scrape_many`.

    Khi nào dùng kiến trúc này vs Sync+Headed:

    ===========================  =============================================
    Async + Headless (class này) Sync + Headed (scrape_ad / scrape_listings)
    ===========================  =============================================
    Headless=True                Headless=False (browser thật)
    Nhanh hơn, batch            Chậm hơn, tương tác người dùng
    Ít RAM hơn                  Cần RAM cho GUI
    Phù hợp server/CI           Phù hợp captcha/site khó
    ===========================  =============================================

    Cách dùng::

        import asyncio
        from crawlerai.sites.nhatot import AsyncNhaTotCrawler

        async def main():
            # Dùng context manager — browser tự đóng khi ra khỏi block
            async with AsyncNhaTotCrawler() as crawler:
                # Crawl 1 ad
                ad = await crawler.scrape_ad(url)

                # Crawl nhiều ad đồng thời (mặc định 5 concurrent)
                ads = await crawler.scrape_many([url1, url2, url3])

                # Crawl từ listing page
                ads = await crawler.scrape_listings(list_url, limit=10)

        asyncio.run(main())

        # Hoặc dùng explicit lifecycle (giống crawl4ai):
        crawler = AsyncNhaTotCrawler(headless=True)
        await crawler.start()
        ad = await crawler.scrape_ad(url)
        await crawler.close()
    """

    def __init__(self, headless: bool = True, timeout: int = 60_000,
                 user_data_dir: str | None = None):
        """
        Args:
            headless:      Chạy browser headless (mặc định True).
            timeout:       Page navigation timeout tính bằng ms (mặc định 60_000).
            user_data_dir: Thư mục lưu profile (cookies, cache) — giống crawl4ai.
                           Nếu None, tạo temp dir (xóa khi close).
                           Truyền vào đường dẫn cố định để CF cookies tồn tại
                           giữa các lần chạy script.
        """
        self.headless = headless
        self.timeout = timeout
        self._pw = None        # async_playwright instance
        self._browser = None   # persistent context acts as browser
        self._context = None   # launch_persistent_context (= browser + context)
        self._user_data_dir: str | None = user_data_dir
        self._tmp_dir_owned = (user_data_dir is None)  # True → tự dọn khi close
        self.ready = False


    # ── Lifecycle (giống crawl4ai AsyncWebCrawler.start/close) ─────────────────

    async def start(self) -> "AsyncNhaTotCrawler":
        """
        Khởi động browser với **persistent context** — học từ crawl4ai.

        Crawl4ai dùng ``launch_persistent_context(user_data_dir)`` để lưu
        cookies/cache xuống đĩa, giúp Cloudflare nhận ra browser "quen biết"
        thay vì thấy một fresh browser mỗi lần. Đây là lý do tại sao
        ``new_context()`` bị block còn persistent thì không.
        """
        self._pw = await async_playwright().start()

        # Tạo (hoặc reuse) user_data_dir — nếu không truyền vào thì tạo temp
        if not self._user_data_dir:
            self._user_data_dir = tempfile.mkdtemp(prefix="crawlerai-nhatot-")
            self._tmp_dir_owned = True

        _ARGS = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-renderer-backgrounding",
            "--disable-ipc-flooding-protection",
            "--window-size=1920,1080",
        ]
        _UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        # launch_persistent_context = browser + context trong 1 — giống crawl4ai
        self._context = await self._pw.chromium.launch_persistent_context(
            self._user_data_dir,
            headless=self.headless,
            args=_ARGS,
            user_agent=_UA,
            viewport={"width": 1920, "height": 1080},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            extra_http_headers={
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )
        # Navigator override ở init script — tương tự crawl4ai navigator_overrider.js
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined, configurable: true,
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5], configurable: true,
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['vi-VN', 'vi', 'en-US', 'en'], configurable: true,
            });
            window.chrome = { runtime: {} };
        """)
        self.ready = True
        print(f"[AsyncNhaTotCrawler] Persistent browser started "
              f"(headless={self.headless}, profile={self._user_data_dir})")
        return self

    async def close(self) -> None:
        """Đóng browser và giải phóng resources."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self.ready = False

    async def restart_session(self) -> None:
        """
        Đóng session cũ, xóa sạch profile rác trên đĩa và khởi động session mới.
        Chiến thuật này cực kỳ hiệu quả để bypass Cloudflare khi scrape nhiều trang.
        """
        # 1. Close current context/pw
        if self._context:
            await self._context.close()
        if self._pw:
            await self._pw.stop()
        
        # 2. Delete profile directory if exists
        if self._user_data_dir and os.path.exists(self._user_data_dir):
            try:
                shutil.rmtree(self._user_data_dir)
            except Exception:
                pass
        
        # 3. Start fresh
        await self.start()

    async def __aenter__(self) -> "AsyncNhaTotCrawler":
        return await self.start()

    async def __aexit__(self, *_) -> None:
        await self.close()

    # ── Internal page helpers (async versions) ─────────────────────────────────

    async def _new_page(self) -> AsyncPage:
        """Tạo page mới từ shared context (UA + viewport + navigator override đã set sẵn)."""
        if not self.ready:
            await self.start()
        page = await self._context.new_page()
        # Stealth ở page level — bổ sung thêm cho init_script ở context level
        await _apply_stealth_async(page)
        return page

    async def _wait_for_next_data(self, page: AsyncPage, max_wait_ms: int = 60_000) -> bool:
        """Poll async cho đến khi ``__NEXT_DATA__`` xuất hiện.

        Dùng JS eval thay vì DOM locator để nhanh và chính xác hơn —
        vì locator của Playwright phụ thuộc vào selector engine có thể bị
        chặn khi browser detect automation.
        """
        start = datetime.now()
        while True:
            try:
                ok = await page.evaluate(
                    "() => !!(window.__NEXT_DATA__ && window.__NEXT_DATA__.props)"
                )
                if ok:
                    return True
            except Exception:
                pass
            elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
            if elapsed_ms >= max_wait_ms:
                return False
            await page.wait_for_timeout(1000)

    async def _try_reveal_phone_async(self, page: AsyncPage) -> None:
        """Thử click nút hiện số bất đồng bộ (best-effort)."""
        css_selectors = [
            "button.b1b6q6wa.primary.r-normal.large.w-bold",
            "[class*='LeadButton__showPhoneButton__'] button",
            "[class*='ShowPhoneButton_wrapper__'] button",
            ".InlineShowPhoneButton_phoneHidden__4KcON",
            "button.b14cwtpv.link.r-normal.small.w-bold.t-link",
        ]
        for sel in css_selectors:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    await loc.first.click(timeout=3000, force=True)
                    await page.wait_for_timeout(800)
                    return
            except Exception:
                continue
        # Last resort: JS click
        try:
            await page.evaluate(r"""() => {
                const el = document.querySelector('button.b1b6q6wa.primary.r-normal.large.w-bold')
                    || document.querySelector("[class*='LeadButton__showPhoneButton__'] button")
                    || document.querySelector('.b14cwtpv.link.r-normal.small.w-bold.t-link');
                if (el) el.click();
            }""")
            await page.wait_for_timeout(1000)
        except Exception:
            pass

    async def _extract_phone_async(self, page: AsyncPage) -> str | None:
        """Trích phone từ DOM sau khi click nút hiện số."""
        try:
            result = await page.evaluate(r"""() => {
                const tel = document.querySelector('a[href^="tel:"]');
                if (tel) {
                    const d = tel.getAttribute('href').replace('tel:', '').replace(/\D/g, '');
                    if (d.length >= 10 && d.length <= 11 && !d.startsWith('1900')) return d;
                }
                const btn = document.querySelector('button.b1b6q6wa.primary.r-normal.large.w-bold')
                    || document.querySelector("[class*='LeadButton__showPhoneButton__'] button")
                    || document.querySelector('.InlineShowPhoneButton_linkContact__U_lEr')
                    || document.querySelector('.b14cwtpv.link.r-normal.small.w-bold.t-link');
                if (!btn) return null;
                const digits = (btn.textContent || '').replace(/\D/g, '');
                return (digits.length >= 10 && digits.length <= 11 && !digits.startsWith('1900'))
                    ? digits : null;
            }""")
            return result
        except Exception:
            return None

    async def _parse_page(self, page: AsyncPage, url: str) -> dict | None:
        """Điều phối: navigate → wait __NEXT_DATA__ → reveal phone → parse."""
        try:
            # Dùng 'load' thay vì 'domcontentloaded' để Next.js kịp hydrate
            await page.goto(url, wait_until="load", timeout=self.timeout)
        except Exception as exc:
            print(f"[AsyncNhaTotCrawler] Navigate error {url}: {exc}")
            return None

        # Poll tối đa timeout ms, nhưng thường xong sau 2-5s
        if not await self._wait_for_next_data(page, max_wait_ms=min(self.timeout, 30_000)):
            print(f"[AsyncNhaTotCrawler] __NEXT_DATA__ not found: {url}")
            # Debug: in title để biết có bị block không
            try:
                title = await page.title()
                print(f"[AsyncNhaTotCrawler] Page title: '{title}'")
            except Exception:
                pass
            return None

        await page.wait_for_timeout(1000)
        await self._try_reveal_phone_async(page)
        await page.wait_for_timeout(500)
        phone = await self._extract_phone_async(page)

        try:
            next_data = await page.evaluate("() => window.__NEXT_DATA__ || null")
        except Exception:
            next_data = None

        if not next_data:
            html_content = await page.content()
            soup = BeautifulSoup(html_content, "html.parser")
            tag = soup.find("script", {"id": "__NEXT_DATA__"})
            if not tag:
                return None
            try:
                next_data = json.loads(tag.string or tag.text)
            except json.JSONDecodeError:
                return None

        ad_data = _find_ad_data(next_data) or {}
        if not ad_data:
            return None

        return _build_info(ad_data, phone)

    # ── Public async API ───────────────────────────────────────────────────────

    async def scrape_ad(self, url: str) -> dict | None:
        """
        Crawl một NhaTot ad bất đồng bộ (headless).

        Args:
            url: URL của ad NhaTot.

        Returns:
            Dict có cấu trúc giống :func:`scrape_ad` (sync), hoặc ``None``.
        """
        page = await self._new_page()
        try:
            return await self._parse_page(page, url)
        finally:
            await page.close()

    async def scrape_many(
        self,
        urls: list[str],
        concurrency: int = 5,
    ) -> list[dict]:
        """
        Crawl nhiều ad đồng thời — không thể làm với Sync+Headed.

        Dùng semaphore để giới hạn số tab mở cùng lúc (giống crawl4ai
        ``MemoryAdaptiveDispatcher`` nhưng đơn giản hơn).

        Args:
            urls:        Danh sách URL cần crawl.
            concurrency: Số tab chạy song song (mặc định 5).

        Returns:
            Danh sách dict ad (bỏ qua các URL lỗi).

        Example::

            async with AsyncNhaTotCrawler() as crawler:
                ads = await crawler.scrape_many(
                    [url1, url2, url3, url4, url5],
                    concurrency=3,
                )
        """
        sem = asyncio.Semaphore(concurrency)

        async def _bounded(url: str) -> dict | None:
            async with sem:
                page = await self._new_page()
                try:
                    return await self._parse_page(page, url)
                finally:
                    await page.close()

        results = await asyncio.gather(*[_bounded(u) for u in urls])
        return [r for r in results if r is not None]

    async def scrape_many_batched(
        self,
        urls: list[str],
        batch_size: int = 5,
        delay_between_batches: float = 3.0,
    ) -> list[dict]:
        """
        Crawl hàng loạt tin đăng theo batch, mỗi batch khởi động lại session mới.
        Đây là chức năng chính giúp tránh bị Cloudflare tracking khi crawl số lượng lớn.
        """
        all_results = []
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i+batch_size]
            # Restart session trước mỗi batch
            await self.restart_session()
            print(f"[AsyncNhaTotCrawler] Batch {i//batch_size + 1}: Scraping {len(batch)} URLs...")
            
            # Scrape batch này concurrently
            results = await self.scrape_many(batch, concurrency=batch_size)
            all_results.extend(results)
            
            if i + batch_size < len(urls):
                await asyncio.sleep(delay_between_batches)
        
        return all_results

    async def scrape_listings(
        self,
        list_url: str,
        limit: int = 10,
        concurrency: int = 5,
    ) -> list[dict]:
        """
        Crawl listing page (lấy links) rồi scrape các ad đồng thời.

        Args:
            list_url:    URL trang danh sách.
            limit:       Số ad tối đa.
            concurrency: Số tab song song khi scrape ad.

        Returns:
            Danh sách dict ad.
        """
        links: list[str] = []
        page = await self._new_page()
        try:
            print(f"[AsyncNhaTotCrawler] Loading listing: {list_url} ...")
            # Dùng 'load' để đảm bảo các script của Next.js đã khởi chạy
            await page.goto(list_url, wait_until="load", timeout=self.timeout)
            
            # Đợi cho đến khi dữ liệu Next.js xuất hiện (dấu hiệu trang đã render xong)
            if not await self._wait_for_next_data(page, max_wait_ms=15000):
                print("[AsyncNhaTotCrawler] Warning: __NEXT_DATA__ not found on listing page. Trying to find links anyway...")
            
            await page.wait_for_timeout(3000)

            for i in range(8):
                hrefs = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))"
                )
                new_links_found = 0
                for href in hrefs:
                    if not href or ".htm" not in href:
                        continue
                    if "nhatot.com" not in href:
                        href = urljoin(list_url, href)
                    if "/mua-ban" not in href or href in links:
                        continue
                    links.append(href)
                    new_links_found += 1
                
                print(f"[AsyncNhaTotCrawler] Scroll {i+1}: Found {len(links)} links so far...")
                
                if len(links) >= limit:
                    break
                
                # Cuộn xuống để load thêm tin (lazy loading)
                await page.evaluate("window.scrollBy(0, 1000)")
                await page.wait_for_timeout(2000)
        except Exception as exc:
            print(f"[AsyncNhaTotCrawler] Listing error: {exc}")
        finally:
            await page.close()

        return await self.scrape_many(links[:limit], concurrency=concurrency)

    async def scrape_listings_today(
        self,
        list_url: str,
        max_pages: int = 5,
        limit: int = 50,
        batch_size: int = 5,
    ) -> list[dict]:
        """
        Crawl các tin đăng từ trang danh sách với giới hạn số lượng tin và batching.
        Sử dụng chiến thuật reset session cho mỗi trang listing để bypass CF.
        """
        all_filtered_urls = []
        current_page = 1
        keep_paging = True
        
        while current_page <= max_pages and keep_paging:
            # 1. Fresh start cho mỗi trang listing
            await self.restart_session()
            page_url = f"{list_url}?page={current_page}" if current_page > 1 else list_url
            print(f"[AsyncNhaTotCrawler] Listing: Page {current_page} - {page_url}")
            
            page = await self._new_page()
            try:
                ads = []
                # Thử load trang, nếu 0 links thì retry 1 lần với load kĩ hơn
                for attempt in range(2):
                    wait_type = "domcontentloaded" if attempt == 0 else "load"
                    try:
                        await page.goto(page_url, wait_until=wait_type, timeout=60000)
                    except Exception as e:
                        print(f"[AsyncNhaTotCrawler] Page {current_page} navigation error: {e}")
                        continue
                    
                    # Cuộn 2 lần để đảm bảo tin load đủ
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(2000)
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(2000)
                    
                    # Trích xuất links với selector rộng hơn
                    ads = await page.evaluate(r"""() => {
                        const results = [];
                        // Tìm tất cả anchor có thuộc tính itemprop="item" HOẶC chứa link .htm có dạng mua bán
                        const anchors = Array.from(document.querySelectorAll('a'));
                        anchors.forEach(a => {
                            const href = a.getAttribute('href');
                            if (!href || !href.includes('.htm')) return;
                            if (!href.includes('/mua-ban-')) return;
                            
                            // Tránh lấy nhầm link logo hay link footer
                            if (href.length < 20) return; 

                            let text = '';
                            // Ưu tiên lấy text từ container bọc ngoài (li hoặc div chứa tin)
                            let container = a.closest('li') || a.closest('[class*="AdItem"]') || a.parentElement;
                            if (container) text = container.innerText;
                            
                            // Kiểm tra lại nếu kết quả đã tồn tại
                            if (!results.find(r => r.url === href)) {
                                results.push({ url: href, innerText: text });
                            }
                        });
                        return results;
                    }""")
                    
                    if len(ads) > 0:
                        break
                    print(f"[AsyncNhaTotCrawler] Page {current_page} attempt {attempt+1}: 0 ads found. Retrying...")

                page_found = 0
                for ad in ads:
                    url = urljoin(list_url, ad['url'])
                    if url not in all_filtered_urls:
                        all_filtered_urls.append(url)
                        page_found += 1
                        
                    # Dừng nếu đã lấy đủ số lượng yêu cầu (cộng thêm 10% để trừ hao)
                    if len(all_filtered_urls) >= limit:
                        keep_paging = False
                        break
                
                print(f"[AsyncNhaTotCrawler] Page {current_page}: Found {page_found} links. Total: {len(all_filtered_urls)}")
                if len(ads) == 0:
                     print(f"[AsyncNhaTotCrawler] Warning: Page {current_page} returned 0 ads.")
                     keep_paging = False
            except Exception as e:
                print(f"[AsyncNhaTotCrawler] Error: {e}")
                break
            finally:
                await page.close()
                current_page += 1
        
        return await self.scrape_many_batched(all_filtered_urls, batch_size=batch_size)

    async def crawl_to_csv(
        self,
        list_url: str,
        output_file: str = "nhatot_exported.csv",
        max_pages: int = 5,
        limit: int = 50,
        batch_size: int = 5
    ) -> list[dict]:
        """
        Phương thức TẤT-CẢ-TRONG-MỘT:
        Quét danh sách -> Scrape chi tiết -> Xuất toàn bộ dữ liệu ra CSV.
        """
        print(f"[AsyncNhaTotCrawler] Starting full crawl to CSV: {output_file}")
        
        # 1. Scrape data
        results = await self.scrape_listings_today(list_url, max_pages=max_pages, limit=limit, batch_size=batch_size)
        
        if not results:
            print("[AsyncNhaTotCrawler] No results to export.")
            return []

        # 2. Định nghĩa toàn bộ headers khả thi (Flat schema)
        headers = [
            "ad_id", "list_id", "ad_url", "title", "category_name",
            "price", "price_string", "price_per_m2",
            "area", "area_unit", "width", "length",
            "rooms", "toilets", "floors", "house_type", "furnishing", "legal",
            "street_name", "ward_name", "area_name", "region_name",
            "latitude", "longitude",
            "seller_name", "seller_phone", "is_company",
            "view_count", "posting_date", "status", "images"
        ]

        try:
            with open(output_file, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                
                for ad in results:
                    # Flattening data
                    row = [
                        ad.get("id", {}).get("ad_id"),
                        ad.get("id", {}).get("list_id"),
                        ad.get("meta", {}).get("ad_url"),
                        ad.get("title"),
                        ad.get("category", {}).get("category_name"),
                        ad.get("price", {}).get("price"),
                        ad.get("price", {}).get("price_string"),
                        ad.get("price", {}).get("price_million_per_m2"),
                        ad.get("size", {}).get("size"),
                        ad.get("size", {}).get("size_unit"),
                        ad.get("size", {}).get("width"),
                        ad.get("size", {}).get("length"),
                        ad.get("rooms", {}).get("rooms"),
                        ad.get("rooms", {}).get("toilets"),
                        ad.get("rooms", {}).get("floors"),
                        ad.get("rooms", {}).get("house_type"),
                        ad.get("rooms", {}).get("furnishing_sell"),
                        ad.get("legal", {}).get("property_legal_document"),
                        ad.get("location", {}).get("street_name"),
                        ad.get("location", {}).get("ward_name"),
                        ad.get("location", {}).get("area_name"),
                        ad.get("location", {}).get("region_name"),
                        ad.get("location", {}).get("latitude"),
                        ad.get("location", {}).get("longitude"),
                        ad.get("seller", {}).get("account_name"),
                        ad.get("seller", {}).get("phone"),
                        ad.get("seller", {}).get("company_ad"),
                        ad.get("meta", {}).get("view_count"),
                        ad.get("posting_date"),
                        ad.get("meta", {}).get("status"),
                        ",".join(ad.get("media", {}).get("images", []))
                    ]
                    writer.writerow(row)
            
            print(f"[AsyncNhaTotCrawler] Successfully exported {len(results)} items to {output_file}")
        except Exception as e:
            print(f"[AsyncNhaTotCrawler] Export error: {e}")
            
        return results

