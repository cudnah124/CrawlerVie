import asyncio
import os
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
from playwright.async_api import Page as AsyncPage

from crawlerai.core.engine import BaseAsyncCrawler
from crawlerai.utils.antibot import AntiBotManager
from crawlerai.utils.exporter import DataExporter
from crawlerai.utils.downloader import MediaDownloader


def _strip_fragment(url: str) -> str:
    """Loại bỏ fragment khỏi URL."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=''))


def _find_ad_data(next_data: dict) -> dict | None:
    """Tìm ad_data trong Next.js payload (adView.adInfo)."""
    try:
        pp = next_data.get("props", {}).get("pageProps", {})
        adview = pp.get("initialState", {}).get("adView", {})

        ad_info = adview.get("adInfo", {})
        if isinstance(ad_info, dict):
            if ad_info.get("ad_id"):
                return ad_info
            ad = ad_info.get("ad")
            if isinstance(ad, dict) and ad.get("ad_id"):
                return ad

        for key in ["adData", "ad", "data"]:
            val = pp.get(key)
            if isinstance(val, dict) and val.get("ad_id"):
                return val

        return None
    except Exception:
        return None


def _build_info(ad_data: dict, phone: str | None, ad_url: str) -> dict:
    """Build output dictionary từ ad_data payload."""
    list_time = ad_data.get("list_time")
    try:
        posting_date = datetime.fromtimestamp(list_time / 1000).strftime("%Y-%m-%d %H:%M:%S") if list_time else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        posting_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    seller_data = ad_data.get("seller", {})
    account_name = ad_data.get("account_name") or seller_data.get("account_name")
    avatar = ad_data.get("avatar") or seller_data.get("avatar")
    company_ad = ad_data.get("company_ad") or seller_data.get("company_ad")
    
    final_phone = phone or ad_data.get("phone") or seller_data.get("phone")
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
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def _log_phase(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _log_page(page: int, found: int, total: int, limit: int):
    pct = min(100, int(total / limit * 100))
    bar = _bar(total, limit)
    print(f"  Page {page:>2} | +{found:>3} links | {bar} {total:>3}/{limit} ({pct}%)")


def _log_batch(batch_idx: int, total_batches: int, batch_size: int, scraped: int, total_urls: int):
    bar = _bar(batch_idx, total_batches)
    print(f"  Batch {batch_idx:>2}/{total_batches} {bar}  scraped={scraped:>3}/{total_urls}")


def _log_item(idx: int, total: int, title: str, status: str = "v"):
    short = (title[:45] + "...") if title and len(title) > 46 else (title or "-")
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
        except Exception:
            return None

        if not await self._wait_for_next_data(page):
            return None

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
                if await btns.count() > 0:
                    await btns.first.click(timeout=3000, force=True)
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                continue

        phone = None
        try:
            phone = await page.evaluate(r"""() => {
                const tel = document.querySelector('a[href^="tel:"]');
                if (tel) {
                    const d = tel.getAttribute('href').replace('tel:', '').replace(/\D/g, '');
                    if (d.length >= 9 && d.length <= 11) return d;
                }
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
        except Exception:
            pass

        try:
            next_data = await page.evaluate("() => window.__NEXT_DATA__ || null")
        except Exception:
            return None

        ad_data = _find_ad_data(next_data) if next_data else {}
        if not ad_data:
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

    async def scrape_many_batched(self, urls: list[str], batch_size: int = 5, 
                                 download_images: bool = False, image_dir: str = "downloads") -> list[dict]:
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

            if download_images:
                for r in results:
                    ad_id = r.get("id", {}).get("ad_id")
                    img_urls = r.get("media", {}).get("images", [])
                    if ad_id and img_urls:
                        ad_image_dir = os.path.join(image_dir, str(ad_id))
                        await MediaDownloader.download_batch(img_urls, ad_image_dir)

            if i + batch_size < len(urls):
                await asyncio.sleep(2)

        success = len(all_results)
        pct = int(success / len(urls) * 100) if urls else 0
        print(f"\n  Done  | {success}/{len(urls)} scraped ({pct}%)")
        return all_results

    async def scrape_listings_today(self, list_url: str, max_pages: int = 5, limit: int = 50, 
                                   batch_size: int = 5, download_images: bool = False, image_dir: str = "downloads") -> list[dict]:
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
                        full = _strip_fragment(urljoin(list_url, h))
                        if full not in all_urls:
                            all_urls.append(full)
                            page_found += 1
                    if len(all_urls) >= limit:
                        break
            except Exception:
                pass
            finally:
                await page.close()
                _log_page(current_page, page_found, len(all_urls), limit)
                current_page += 1

        print(f"\n  Done  | {len(all_urls)} URLs collected")
        return await self.scrape_many_batched(all_urls, batch_size=batch_size, 
                                              download_images=download_images, image_dir=image_dir)

    async def crawl_to_csv(self, list_url: str, output_file: str = "nhatot_exported.csv",
                           max_pages: int = 5, limit: int = 50, batch_size: int = 5,
                           download_images: bool = False, image_dir: str = "downloads"):
        start_time = datetime.now()
        print(f"\n{'+' + '=' * 58 + '+'}")
        print(f"|  NhaTot Crawler  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<36}|")
        print(f"|  URL: {list_url[:50]:<51}|")
        print(f"|  Limit={limit}  Batch={batch_size}  MaxPages={max_pages:<27}|")
        print(f"|  Download Images: {'ON' if download_images else 'OFF':<41}|")
        print(f"{'+' + '=' * 58 + '+'}")

        results = await self.scrape_listings_today(list_url, max_pages, limit, batch_size, 
                                                   download_images=download_images, image_dir=image_dir)

        if not results:
            return []

        seen_ids: set = set()
        unique_results = []
        dup_count = 0
        for ad in results:
            aid = ad.get("id", {}).get("ad_id")
            if aid and aid in seen_ids:
                dup_count += 1
                continue
            if aid:
                seen_ids.add(aid)
            unique_results.append(ad)

        BASE_COLS = [
            "ID Ad", "Title", "Property Type",
            "Price Value", "Price String", "Price/m2 (trieu)",
            "Area (m2)", "Width", "Length", "Living Area",
            "Ward", "District", "City", "Street",
            "Latitude", "Longitude",
            "Rooms", "Toilets", "Floors", "House Type",
            "Legal Document", "Furnishing",
            "Phone", "Seller", "Company",
            "Views", "Posting Date", "Link",
        ]

        def _flatten_ad(ad: dict) -> dict:
            """Tra ve dict phang: base fields + moi truong tu params."""
            loc  = ad.get("location", {})
            sz   = ad.get("size", {})
            rm   = ad.get("rooms", {})
            pr   = ad.get("price", {})
            sl   = ad.get("seller", {})
            mt   = ad.get("meta", {})
            cat  = ad.get("category", {})
            lg   = ad.get("legal", {})

            street_parts = [loc.get("street_number"), loc.get("street_name")]
            street = " ".join(p for p in street_parts if p) or None

            row = {
                "ID Ad":           ad.get("id", {}).get("ad_id"),
                "Title":           ad.get("title"),
                "Property Type":   cat.get("category_name"),
                "Price Value":     pr.get("price"),
                "Price String":    pr.get("price_string"),
                "Price/m2 (trieu)": pr.get("price_million_per_m2"),
                "Area (m2)":       sz.get("size"),
                "Width":           sz.get("width"),
                "Length":          sz.get("length"),
                "Living Area":     sz.get("living_size"),
                "Ward":            loc.get("ward_name"),
                "District":        loc.get("area_name"),
                "City":            loc.get("region_name"),
                "Street":          street,
                "Latitude":        loc.get("latitude"),
                "Longitude":       loc.get("longitude"),
                "Rooms":           rm.get("rooms"),
                "Toilets":         rm.get("toilets"),
                "Floors":          rm.get("floors"),
                "House Type":      rm.get("house_type"),
                "Legal Document":  lg.get("property_legal_document"),
                "Furnishing":      rm.get("furnishing_sell"),
                "Phone":           sl.get("phone"),
                "Seller":          sl.get("account_name"),
                "Company":         sl.get("company_ad"),
                "Views":           mt.get("view_count"),
                "Posting Date":    ad.get("posting_date"),
                "Link":            mt.get("ad_url"),
            }

            # Thêm các trường động từ params (label làm tên cột, prefix [P])
            raw_params = ad.get("params") or []
            for p in raw_params:
                if not isinstance(p, dict):
                    continue
                label = p.get("label") or p.get("key") or ""
                if not label:
                    continue
                col_name = f"[P] {label}"
                value = p.get("value")
                # Neu value la list thi join lai
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value)
                # Không ghi đè nếu cột đã có giá trị từ base
                if col_name not in row:
                    row[col_name] = value

            return row

        flattened = [_flatten_ad(ad) for ad in unique_results]

        # Hợp nhất tất cả các header (base trước, params sau)
        all_param_cols: list[str] = []
        seen_param_cols: set[str] = set()
        for row in flattened:
            for col in row:
                if col not in seen_param_cols and col not in BASE_COLS:
                    seen_param_cols.add(col)
                    all_param_cols.append(col)

        final_headers = BASE_COLS + all_param_cols

        # Xuất ra file CSV
        DataExporter.to_csv(flattened, output_file, headers=final_headers)

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n{'=' * 60}")
        print(f"  v Saved {len(flattened)} rows  ({len(all_param_cols)} dynamic param cols) -> {output_file}")
        print(f"  t Elapsed: {elapsed:.1f}s")
        print(f"{'=' * 60}\n")
        return results
