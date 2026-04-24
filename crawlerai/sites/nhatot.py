import asyncio
import json
import os
import csv
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup
from playwright.async_api import Page as AsyncPage

from crawlerai.core.engine import BaseAsyncCrawler
from crawlerai.utils.antibot import AntiBotManager
from crawlerai.utils.exporter import DataExporter


def _strip_fragment(url: str) -> str:
    """Bỏ fragment (#...) khỏi URL để tránh tracking params phá vỡ Next.js."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=''))


def _find_ad_data(next_data: dict) -> dict | None:
    """Tìm ad_data trong Next.js payload. Key đúng là adView.adInfo."""
    try:
        pp = next_data.get("props", {}).get("pageProps", {})
        adview = pp.get("initialState", {}).get("adView", {})

        # Đường dẫn chính xác: initialState -> adView -> adInfo
        ad_info = adview.get("adInfo", {})
        if isinstance(ad_info, dict):
            # adInfo có thể chứa 'ad' hoặc chính là ad object
            if ad_info.get("ad_id"):
                return ad_info
            ad = ad_info.get("ad")
            if isinstance(ad, dict) and ad.get("ad_id"):
                return ad

        # Fallback: tìm trong các key khác của pageProps
        for key in ["adData", "ad", "data"]:
            val = pp.get(key)
            if isinstance(val, dict) and val.get("ad_id"):
                return val

        return None
    except:
        return None


def _build_info(ad_data: dict, phone: str | None, ad_url: str) -> dict:
    """Build output dictionary đầy đủ từ ad_data payload — khớp schema phiên bản cũ."""
    # Chuyển list_time (ms timestamp) → chuỗi ngày giờ
    list_time = ad_data.get("list_time")
    try:
        posting_date = datetime.fromtimestamp(list_time / 1000).strftime("%Y-%m-%d %H:%M:%S") if list_time else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except:
        posting_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Xử lý seller (có thể là key con hoặc nằm trực tiếp trong ad_data)
    seller_data = ad_data.get("seller", {})
    account_name = ad_data.get("account_name") or seller_data.get("account_name")
    avatar = ad_data.get("avatar") or seller_data.get("avatar")
    company_ad = ad_data.get("company_ad") or seller_data.get("company_ad")
    
    # Ưu tiên phone từ scraping (UI), sau đó tới trong ad_data, cuối cùng là trong seller_data
    final_phone = phone or ad_data.get("phone") or seller_data.get("phone")
    # Nếu vẫn dính dấu * thì coi như chưa lấy được số thật
    if final_phone and "*" in str(final_phone):
        final_phone = None

    return {
        "id": {
            "ad_id":      ad_data.get("ad_id"),
            "list_id":    ad_data.get("list_id"),
            "account_id": ad_data.get("account_id") or seller_data.get("account_id"),
        },
        "title":       AntiBotManager.clean_emojis(ad_data.get("subject")),
        "description": ad_data.get("body"),
        "category": {
            "category":      ad_data.get("category"),
            "category_name": ad_data.get("category_name"),
        },
        "price": {
            "price":                ad_data.get("price"),
            "price_string":         ad_data.get("price_string"),
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
            "account_name": account_name,
            "avatar":       avatar,
            "phone":        final_phone,
            "company_ad":   company_ad,
        },
        "media": {
            "images": ad_data.get("images", []),
            "videos": ad_data.get("videos", []),
        },
        "meta": {
            "ad_url":     ad_url,
            "list_time":  list_time,
            "view_count": ad_data.get("view_count") or ad_data.get("total_views") or 0,
            "state":      ad_data.get("state"),
            "status":     ad_data.get("status"),
            "type":       ad_data.get("type"),
        },
        "params":       ad_data.get("ad_params") or ad_data.get("params") or [],
        "posting_date": posting_date,
    }



# ── Logging helpers ────────────────────────────────────────────────────────────

def _bar(done: int, total: int, width: int = 30) -> str:
    filled = int(width * done / total) if total else 0
    return f"[{'█' * filled}{'░' * (width - filled)}]"


def _log_phase(title: str):
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


def _log_page(page: int, found: int, total: int, limit: int):
    pct = min(100, int(total / limit * 100))
    bar = _bar(total, limit)
    print(f"  Page {page:>2} │ +{found:>3} links │ {bar} {total:>3}/{limit} ({pct}%)")


def _log_batch(batch_idx: int, total_batches: int, batch_size: int, scraped: int, total_urls: int):
    bar = _bar(batch_idx, total_batches)
    print(f"  Batch {batch_idx:>2}/{total_batches} {bar}  scraped={scraped:>3}/{total_urls}")


def _log_item(idx: int, total: int, title: str, status: str = "✓"):
    short = (title[:45] + "…") if title and len(title) > 46 else (title or "—")
    print(f"    [{idx:>3}/{total}] {status}  {short}")


# ── Crawler ────────────────────────────────────────────────────────────────────

class AsyncNhaTotCrawler(BaseAsyncCrawler):
    """Crawler chuyên biệt cho NhaTot.com kế thừa BaseAsyncCrawler."""

    async def _wait_for_next_data(self, page, max_wait_ms: int = 30000) -> bool:
        start = datetime.now()
        while True:
            if await page.locator("#__NEXT_DATA__").count() > 0:
                return True
            elapsed = (datetime.now() - start).total_seconds() * 1000
            if elapsed >= max_wait_ms:
                return False
            await page.wait_for_timeout(1000)

    async def _parse_page(self, page: AsyncPage, url: str) -> dict | None:
        # Step 1: Navigate
        try:
            await page.goto(url, wait_until="load", timeout=self.timeout)
        except Exception as e:
            print(f"    ✗ goto failed: {e}")
            return None

        # Step 2: Wait for __NEXT_DATA__
        if not await self._wait_for_next_data(page):
            try:
                title = await page.title()
            except:
                title = "?"
            print(f"    ✗ __NEXT_DATA__ not found — title: '{title}'")
            return None

        # Step 3: Reveal phone — click nút "Hiện số" với nhiều selector
        _phone_btn_selectors = [
            "button.b1b6q6wa.primary.r-normal.large.w-bold",
            "button[data-testid='lead-button']",
            "[class*='LeadButton__showPhoneButton__'] button",
            "[class*='ShowPhoneButton_wrapper__'] button",
            ".InlineShowPhoneButton_linkContact__U_lEr",
            "button.b14cwtpv.link.r-normal.small.w-bold.t-link",
        ]
        for sel in _phone_btn_selectors:
            try:
                btns = page.locator(sel)
                count = await btns.count()
                if count > 0:
                    btn = btns.first
                    # Thử click — một số button có thể bị ẩn nhưng vẫn clickable hoặc cần force
                    await btn.click(timeout=3000, force=True)
                    await page.wait_for_timeout(1000)
                    break
            except:
                continue

        # Step 3b: JS fallback — tìm tel: link hoặc text số điện thoại
        phone = None
        try:
            phone = await page.evaluate(r"""() => {
                // 1. Tìm thẻ a href="tel:..."
                const tel = document.querySelector('a[href^="tel:"]');
                if (tel) {
                    const d = tel.getAttribute('href').replace('tel:', '').replace(/\D/g, '');
                    if (d.length >= 9 && d.length <= 11) return d;
                }
                // 2. Tìm trong các class phổ biến của Chợ Tốt / Nhà Tốt
                const selectors = [
                    '.b14cwtpv.link.r-normal.small.w-bold.t-link span',
                    '.ShowPhoneButton_phone__18a_n',
                    '.InlineShowPhoneButton_phoneHidden__4KcON',
                    '[class*="phone"]',
                    '[class*="phoneNumber"]'
                ];
                for (const s of selectors) {
                    const elements = document.querySelectorAll(s);
                    for (const el of elements) {
                        const digits = (el.textContent || '').replace(/\D/g, '');
                        if (digits.length >= 9 && digits.length <= 11 && !digits.startsWith('1900'))
                            return digits;
                    }
                }
                return null;
            }""")
        except:
            pass

        # Step 4: Extract __NEXT_DATA__
        try:
            next_data = await page.evaluate("() => window.__NEXT_DATA__ || null")
        except Exception as e:
            print(f"    ✗ evaluate failed: {e}")
            return None

        # Step 5: Parse ad_data
        ad_data = _find_ad_data(next_data) if next_data else {}
        if not ad_data:
            if next_data:
                pp = next_data.get("props", {}).get("pageProps", {})
                init = pp.get("initialState", {})
                adview = init.get("adView", {})
                print(f"    ✗ ad_data not found: {url.split('/')[-1][:50]}")
            return None

        return _build_info(ad_data, phone, url)


    async def scrape_many(self, urls: list[str], concurrency: int = 5) -> list[dict]:
        sem = asyncio.Semaphore(concurrency)

        async def _bounded(url):
            async with sem:
                page = await self.get_new_page()
                try:
                    return await self._parse_page(page, url)
                finally:
                    await page.close()

        results = await asyncio.gather(*[_bounded(u) for u in urls])
        return [r for r in results if r]

    async def scrape_many_batched(self, urls: list[str], batch_size: int = 5) -> list[dict]:
        if not urls:
            return []

        total_batches = (len(urls) + batch_size - 1) // batch_size
        all_results = []

        _log_phase(f"PHASE 2 — Scraping Details  ({len(urls)} listings, {total_batches} batches × {batch_size})")

        for i in range(0, len(urls), batch_size):
            batch_idx = i // batch_size + 1
            batch = urls[i:i + batch_size]

            await self.restart_session()
            results = await self.scrape_many(batch, concurrency=batch_size)
            all_results.extend(results)

            _log_batch(batch_idx, total_batches, len(batch), len(all_results), len(urls))
            for j, r in enumerate(results):
                title = r.get("title", "") if r else ""
                status = "✓" if r else "✗"
                _log_item(i + j + 1, len(urls), title, status)

            if i + batch_size < len(urls):
                await asyncio.sleep(2)

        success = len(all_results)
        pct = int(success / len(urls) * 100) if urls else 0
        print(f"\n  Done  │ {success}/{len(urls)} scraped ({pct}%)")
        return all_results

    async def scrape_listings_today(self, list_url: str, max_pages: int = 5, limit: int = 50, batch_size: int = 5) -> list[dict]:
        _log_phase(f"PHASE 1 — Collecting Links  (limit={limit}, max_pages={max_pages})")

        all_urls = []
        current_page = 1

        while current_page <= max_pages and len(all_urls) < limit:
            await self.restart_session()
            url = f"{list_url}?page={current_page}" if current_page > 1 else list_url
            page = await self.get_new_page()

            page_found = 0
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await AntiBotManager.human_like_scroll(page)
                hrefs = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))"
                )
                for h in hrefs:
                    if h and ".htm" in h and "/mua-ban" in h:
                        # Strip fragment (#px=...) trước khi lưu
                        full = _strip_fragment(urljoin(list_url, h))
                        if full not in all_urls:
                            all_urls.append(full)
                            page_found += 1
                    if len(all_urls) >= limit:
                        break
            except Exception as e:
                print(f"  ✗ Page {current_page} error: {e}")
            finally:
                await page.close()
                _log_page(current_page, page_found, len(all_urls), limit)
                current_page += 1

        print(f"\n  Done  │ {len(all_urls)} URLs collected")
        return await self.scrape_many_batched(all_urls, batch_size=batch_size)

    async def crawl_to_csv(self, list_url: str, output_file: str = "nhatot_exported.csv",
                           max_pages: int = 5, limit: int = 50, batch_size: int = 5):
        start_time = datetime.now()
        print(f"\n{'╔' + '═' * 58 + '╗'}")
        print(f"║  NhaTot Crawler  │  {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<36}║")
        print(f"║  URL: {list_url[:50]:<51}║")
        print(f"║  Limit={limit}  Batch={batch_size}  MaxPages={max_pages:<27}║")
        print(f"{'╚' + '═' * 58 + '╝'}")

        results = await self.scrape_listings_today(list_url, max_pages, limit, batch_size)

        if not results:
            print("\n  ✗ No results to export.")
            return []

        # Flatten and export
        flattened = []
        for ad in results:
            flattened.append({
                "ID Ad":         ad.get("id", {}).get("ad_id"),
                "Title":         ad.get("title"),
                "Property Type": ad.get("category", {}).get("category_name"),
                "Price Value":   ad.get("price", {}).get("price"),
                "Area (m2)":     ad.get("size", {}).get("size"),
                "Price_per_m2":  ad.get("price", {}).get("price_million_per_m2"),
                "Ward":          ad.get("location", {}).get("ward_name"),
                "District":      ad.get("location", {}).get("area_name"),
                "City":          ad.get("location", {}).get("region_name"),
                "Rooms":         ad.get("rooms", {}).get("rooms"),
                "Toilets":       ad.get("rooms", {}).get("toilets"),
                "Floors":        ad.get("rooms", {}).get("floors"),
                "Views":         ad.get("meta", {}).get("view_count"),
                "Posting Date":  ad.get("posting_date"),
                "Link":          ad.get("meta", {}).get("ad_url"),
                "Phone":         ad.get("seller", {}).get("phone"), # Thêm cả phone vì hữu ích
            })

        DataExporter.to_csv(flattened, output_file)

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n{'═' * 60}")
        print(f"  ✓ Saved {len(flattened)} rows → {output_file}")
        print(f"  ⏱ Elapsed: {elapsed:.1f}s")
        print(f"{'═' * 60}\n")
        return results
