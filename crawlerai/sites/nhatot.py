import asyncio
import json
import os
import csv
import tempfile
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.async_api import Page as AsyncPage

from crawlerai.core.engine import BaseAsyncCrawler
from crawlerai.utils.antibot import AntiBotManager
from crawlerai.utils.exporter import DataExporter

def _find_ad_data(next_data: dict) -> dict | None:
    """Helper map data từ cấu trúc Next.js của NhaTot."""
    try:
        props = next_data.get("props", {})
        page_props = props.get("pageProps", {})
        return page_props.get("initialState", {}).get("adView", {}).get("ad", {}) or page_props.get("adData", {})
    except:
        return None

def _build_info(ad_data: dict, phone: str | None, ad_url: str) -> dict:
    """Build output dictionary từ ad_data payload."""
    return {
        "id": {
            "ad_id":      ad_data.get("ad_id"),
            "list_id":    ad_data.get("list_id"),
        },
        "title":       AntiBotManager.clean_emojis(ad_data.get("subject")),
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
            "ward_name":     ad_data.get("ward_name"),
            "area_name":     ad_data.get("area_name"),
            "region_name":   ad_data.get("region_name"),
            "latitude":      ad_data.get("latitude"),
            "longitude":     ad_data.get("longitude"),
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
        "media": {
            "images": ad_data.get("images", []),
        }
    }

class AsyncNhaTotCrawler(BaseAsyncCrawler):
    """Crawler chuyên biệt cho NhaTot.com kế thừa BaseAsyncCrawler."""

    async def _wait_for_next_data(self, page, max_wait_ms: int = 30000) -> bool:
        start = datetime.now()
        while True:
            if await page.locator("#__NEXT_DATA__").count() > 0:
                return True
            elapsed = (datetime.now() - start).total_seconds() * 1000
            if elapsed >= max_wait_ms: return False
            await page.wait_for_timeout(1000)

    async def _parse_page(self, page: AsyncPage, url: str) -> dict | None:
        try:
            await page.goto(url, wait_until="load", timeout=self.timeout)
            if not await self._wait_for_next_data(page): return None
            
            # Click hiện số
            for sel in ["button.b1b6q6wa.primary.r-normal.large.w-bold", ".ShowPhoneButton_phone__18a_n"]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible():
                        await btn.click(timeout=3000)
                        break
                except: continue
                
            await page.wait_for_timeout(500)
            phone = None
            try:
                phone = await page.inner_text(".b14cwtpv.link.r-normal.small.w-bold.t-link span", timeout=2000)
            except: pass

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
        all_results = []
        for i in range(0, len(urls), batch_size):
            await self.restart_session()
            batch = urls[i:i+batch_size]
            res = await self.scrape_many(batch, concurrency=batch_size)
            all_results.extend(res)
            if i + batch_size < len(urls): await asyncio.sleep(2)
        return all_results

    async def scrape_listings_today(self, list_url: str, max_pages: int = 5, limit: int = 50, batch_size: int = 5) -> list[dict]:
        all_urls = []
        current_page = 1
        while current_page <= max_pages and len(all_urls) < limit:
            await self.restart_session()
            url = f"{list_url}?page={current_page}" if current_page > 1 else list_url
            page = await self.get_new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await AntiBotManager.human_like_scroll(page)
                hrefs = await page.evaluate("() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))")
                for h in hrefs:
                    if h and ".htm" in h and "/mua-ban" in h:
                        full = urljoin(list_url, h)
                        if full not in all_urls: all_urls.append(full)
                    if len(all_urls) >= limit: break
            except: pass
            finally:
                await page.close()
                current_page += 1
        return await self.scrape_many_batched(all_urls, batch_size=batch_size)

    async def crawl_to_csv(self, list_url: str, output_file: str = "nhatot_exported.csv", max_pages: int = 5, limit: int = 50, batch_size: int = 5):
        results = await self.scrape_listings_today(list_url, max_pages, limit, batch_size)
        if not results: return []
        
        flattened = []
        for ad in results:
            flattened.append({
                "ad_id": ad.get("id", {}).get("ad_id"),
                "url": ad.get("meta", {}).get("ad_url"),
                "title": ad.get("title"),
                "price": ad.get("price", {}).get("price"),
                "area": ad.get("size", {}).get("size"),
                "district": ad.get("location", {}).get("area_name"),
                "phone": ad.get("seller", {}).get("phone"),
                "views": ad.get("meta", {}).get("view_count"),
                "date": ad.get("posting_date")
            })
        
        DataExporter.to_csv(flattened, output_file)
        print(f"[AsyncNhaTotCrawler] Saved {len(flattened)} items to {output_file}")
        return results
