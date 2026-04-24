import asyncio
import json
import os
import csv
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.async_api import Page as AsyncPage

from crawlerai.core.engine import BaseAsyncCrawler
from crawlerai.utils.antibot import AntiBotManager
from crawlerai.utils.exporter import DataExporter


def _find_ad_data(next_data: dict) -> dict | None:
    try:
        props = next_data.get("props", {})
        page_props = props.get("pageProps", {})
        return page_props.get("initialState", {}).get("adView", {}).get("ad", {}) or page_props.get("adData", {})
    except:
        return None


def _build_info(ad_data: dict, phone: str | None, ad_url: str) -> dict:
    return {
        "id":    {"ad_id": ad_data.get("ad_id"), "list_id": ad_data.get("list_id")},
        "title": AntiBotManager.clean_emojis(ad_data.get("subject")),
        "price": {
            "price":                ad_data.get("price"),
            "price_string":         ad_data.get("price_string"),
            "price_million_per_m2": ad_data.get("price_million_per_m2"),
        },
        "size": {
            "size":      ad_data.get("size"),
            "size_unit": ad_data.get("size_unit_string"),
            "width":     ad_data.get("width"),
            "length":    ad_data.get("length"),
        },
        "rooms": {
            "rooms":           ad_data.get("rooms"),
            "toilets":         ad_data.get("toilets"),
            "floors":          ad_data.get("floors"),
            "house_type":      ad_data.get("house_type"),
            "furnishing_sell": ad_data.get("furnishing_sell"),
        },
        "legal":    {"property_legal_document": ad_data.get("property_legal_document")},
        "location": {
            "ward_name":   ad_data.get("ward_name"),
            "area_name":   ad_data.get("area_name"),
            "region_name": ad_data.get("region_name"),
            "latitude":    ad_data.get("latitude"),
            "longitude":   ad_data.get("longitude"),
        },
        "seller": {
            "account_name": ad_data.get("account_name"),
            "phone":        phone or ad_data.get("phone"),
            "company_ad":   ad_data.get("company_ad"),
        },
        "meta": {
            "ad_url":     ad_url,
            "view_count": ad_data.get("view_count") or 0,
            "status":     ad_data.get("status"),
        },
        "posting_date": ad_data.get("list_time") or datetime.now().strftime("%Y-%m-%d"),
        "media": {"images": ad_data.get("images", [])},
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
        try:
            await page.goto(url, wait_until="load", timeout=self.timeout)
            if not await self._wait_for_next_data(page):
                return None
            for sel in ["button.b1b6q6wa.primary.r-normal.large.w-bold", ".ShowPhoneButton_phone__18a_n"]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible():
                        await btn.click(timeout=3000)
                        break
                except:
                    continue
            await page.wait_for_timeout(500)
            phone = None
            try:
                phone = await page.inner_text(".b14cwtpv.link.r-normal.small.w-bold.t-link span", timeout=2000)
            except:
                pass
            next_data = await page.evaluate("() => window.__NEXT_DATA__ || null")
            ad_data = _find_ad_data(next_data) if next_data else {}
            return _build_info(ad_data, phone, url) if ad_data else None
        except:
            return None

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
                        full = urljoin(list_url, h)
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
                "ad_id":         ad.get("id", {}).get("ad_id"),
                "url":           ad.get("meta", {}).get("ad_url"),
                "title":         ad.get("title"),
                "price":         ad.get("price", {}).get("price"),
                "price_string":  ad.get("price", {}).get("price_string"),
                "price_per_m2":  ad.get("price", {}).get("price_million_per_m2"),
                "area":          ad.get("size", {}).get("size"),
                "area_unit":     ad.get("size", {}).get("size_unit"),
                "rooms":         ad.get("rooms", {}).get("rooms"),
                "toilets":       ad.get("rooms", {}).get("toilets"),
                "floors":        ad.get("rooms", {}).get("floors"),
                "ward":          ad.get("location", {}).get("ward_name"),
                "district":      ad.get("location", {}).get("area_name"),
                "city":          ad.get("location", {}).get("region_name"),
                "phone":         ad.get("seller", {}).get("phone"),
                "views":         ad.get("meta", {}).get("view_count"),
                "date":          ad.get("posting_date"),
            })

        DataExporter.to_csv(flattened, output_file)

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n{'═' * 60}")
        print(f"  ✓ Saved {len(flattened)} rows → {output_file}")
        print(f"  ⏱ Elapsed: {elapsed:.1f}s")
        print(f"{'═' * 60}\n")
        return results
