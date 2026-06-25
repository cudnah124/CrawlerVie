import asyncio
import csv
import json
import os
import re
import sys
import unicodedata
from collections.abc import Callable
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
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


def _extract_all_params(ad_data: dict) -> list:
    """Gom tat ca params tu moi ngoc ngach trong ad_data và lọc trùng thông minh."""
    results = []
    
    # 1. Cac key pho bien
    for key in ["ad_params", "params", "parameters"]:
        p = ad_data.get(key)
        if isinstance(p, list):
            results.extend(p)
            
    # 2. Neu co object 'ad' ben trong (hay gap o chung cu)
    inner_ad = ad_data.get("ad")
    if isinstance(inner_ad, dict):
        for key in ["ad_params", "params", "parameters"]:
            p = inner_ad.get(key)
            if isinstance(p, list):
                results.extend(p)
                
    # 3. Lọc trùng theo ID. Nếu trùng ID, ưu tiên cái có Label đẹp (tiếng Việt) và Value là text.
    # Sử dụng dict để giữ lại item tốt nhất cho mỗi ID
    best_params = {}
    
    for p in results:
        if not isinstance(p, dict): continue
        pid = p.get("id") or p.get("key")
        if not pid: continue
        
        lbl = p.get("label") or ""
        val = p.get("value")
        
        if pid not in best_params:
            best_params[pid] = p
            continue
            
        # Tiêu chí chọn item tốt hơn:
        current_best = best_params[pid]
        current_lbl = current_best.get("label") or ""
        current_val = current_best.get("value")
        
        # Nếu cái hiện tại có label là ID (kém), mà cái mới có label khác ID (tốt hơn)
        if current_lbl == pid and lbl != pid:
            best_params[pid] = p
        # Hoặc nếu cái hiện tại có value là số (ID), mà cái mới có value là string (text)
        elif isinstance(current_val, (int, float)) and isinstance(val, str) and not val.isdigit():
            best_params[pid] = p
        # Hoặc ưu tiên label tiếng Việt (có dấu hoặc dài hơn)
        elif len(lbl) > len(current_lbl):
            best_params[pid] = p
            
    return list(best_params.values())


def _build_info(ad_data: dict, phone: str | None, ad_url: str,
                og_image: str | None = None) -> dict:
    """Build output dictionary từ ad_data payload."""
    list_time = ad_data.get("list_time") or ad_data.get("ad", {}).get("list_time")
    
    # Extract posting date
    try:
        posting_date = datetime.fromtimestamp(list_time / 1000).strftime("%Y-%m-%d %H:%M:%S") if list_time else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        posting_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    seller_data = ad_data.get("seller") or ad_data.get("ad", {}).get("seller", {})
    account_name = ad_data.get("account_name") or seller_data.get("account_name")
    avatar = ad_data.get("avatar") or seller_data.get("avatar")
    company_ad = ad_data.get("company_ad") or seller_data.get("company_ad")
    
    final_phone = phone or ad_data.get("phone") or seller_data.get("phone")
    if final_phone and "*" in str(final_phone):
        final_phone = None

    # Timestamp helpers
    def _fmt_ts(ts):
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    def _fmt_ts_s(ts):
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    # Map system IDs to labels for cleaner standard objects
    all_params = _extract_all_params(ad_data)
    id_to_val = {p.get("id"): p.get("value") for p in all_params if p.get("id")}

    # Clean description: replace all newlines and multiple spaces with a single space
    raw_desc = ad_data.get("body") or ad_data.get("ad", {}).get("body") or ""
    clean_desc = re.sub(r'\s+', ' ', raw_desc).strip()

    return {
        "id": {
            "ad_id": ad_data.get("ad_id"),
            "list_id": ad_data.get("list_id"),
            "account_id": ad_data.get("account_id"),
        },
        "title": ad_data.get("title") or ad_data.get("ad", {}).get("title") or ad_data.get("subject"),
        "description": clean_desc,
        "category": {
            "category": ad_data.get("category"),
            "category_name": ad_data.get("category_name"),
        },
        "price": {
            "price": ad_data.get("price"),
            "price_string": ad_data.get("price_string"),
            "price_million_per_m2": ad_data.get("price_million_per_m2"),
            "currency": ad_data.get("currency") or "VND",
            "is_negotiable": ad_data.get("is_negotiable"),
        },
        "size": {
            "size": ad_data.get("size"),
            "size_unit": id_to_val.get("size") or ad_data.get("size_unit"),
            "width": ad_data.get("width"),
            "length": ad_data.get("length"),
            "living_size": ad_data.get("living_size"),
        },
        "rooms": {
            "rooms":           id_to_val.get("rooms") or ad_data.get("rooms"),
            "toilets":         id_to_val.get("toilets") or ad_data.get("toilets"),
            "floors":          id_to_val.get("floors") or ad_data.get("floors"),
            "house_type":      id_to_val.get("apartment_type") or id_to_val.get("house_type") or ad_data.get("house_type"),
            "furnishing_sell": id_to_val.get("furnishing_sell") or ad_data.get("furnishing_sell"),
        },
        "legal": {
            "property_legal_document": id_to_val.get("property_legal_document") or ad_data.get("property_legal_document"),
        },
        "location": {
            "street_number": ad_data.get("street_number"),
            "street_name": ad_data.get("street_name"),
            "ward_name": ad_data.get("ward_name"),
            "area_name": ad_data.get("area_name"),
            "region_name": ad_data.get("region_name"),
            "latitude": ad_data.get("latitude"),
            "longitude": ad_data.get("longitude"),
        },
        "seller": {
            "account_name":   account_name,
            "avatar":         avatar,
            "phone":          final_phone,
            "company_ad":     company_ad,
            "seller_type":    ad_data.get("seller_type") or seller_data.get("seller_type") or seller_data.get("user_type"),
            "is_verified":    ad_data.get("is_verified") or seller_data.get("is_verified") or seller_data.get("business_verified"),
            "response_rate":  seller_data.get("response_rate"),
            "last_online":    _fmt_ts(seller_data.get("last_online") or seller_data.get("last_seen")),
        },
        "media": {
            "images":        ad_data.get("images") or ad_data.get("ad", {}).get("images") or [],
            "videos":        ad_data.get("videos") or ad_data.get("ad", {}).get("videos") or [],
            "og_image":      og_image,
            "virtual_3d_url": ad_data.get("virtual_3d_url") or ad_data.get("virtual_tour_url") or ad_data.get("panorama_url"),
            "floorplan_images": ad_data.get("floorplan_images") or ad_data.get("floor_plan") or [],
        },
        "meta": {
            "ad_url":         ad_url,
            "list_time":      list_time,
            "view_count":     ad_data.get("view_count", 0),
            "state":          ad_data.get("state"),
            "status":         ad_data.get("status"),
            "type":           ad_data.get("type"),
            "expire_time":    _fmt_ts(ad_data.get("expire_time") or ad_data.get("expire_date")),
            "refresh_date":   _fmt_ts_s(ad_data.get("refresh_date") or ad_data.get("last_refresh")),
            "is_featured":    ad_data.get("is_featured") or ad_data.get("is_top"),
            "is_urgent":      ad_data.get("is_urgent"),
            "is_top":         ad_data.get("is_top"),
            "favorite_count": ad_data.get("favorite_count") or ad_data.get("like_count"),
        },
        "params": all_params,
        "posting_date": posting_date,
    }


def _parse_html(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, 'html.parser')

    script = soup.find('script', id='__NEXT_DATA__')
    if not script:
        return None

    try:
        next_data = json.loads(script.string)
    except (json.JSONDecodeError, TypeError):
        return None

    ad_data = _find_ad_data(next_data)
    if not ad_data:
        return None

    phone = None
    tel = soup.select_one('a[href^="tel:"]')
    if tel:
        href = tel.get('href', '')
        digits = re.sub(r'\D', '', href.replace('tel:', ''))
        if 9 <= len(digits) <= 11 and not digits.startswith('1900'):
            phone = digits

    if not phone:
        inp = soup.select_one('input#phoneNumberInput')
        if inp:
            digits = re.sub(r'\D', '', inp.get('value', ''))
            if 9 <= len(digits) <= 11 and not digits.startswith('1900'):
                phone = digits

    if not phone:
        for link_div in soup.select('.InlineShowPhoneButton_linkContact__U_lEr'):
            digits = re.sub(r'\D', '', link_div.get_text(strip=True))
            if 9 <= len(digits) <= 11 and not digits.startswith('1900'):
                phone = digits
                break

    _phone_fallback_selectors = [
        '.b14cwtpv.link.r-normal.small.w-bold.t-link span',
        '.ShowPhoneButton_phone__18a_n',
        '.InlineShowPhoneButton_phoneHidden__4KcON',
        '[class*="phoneNumber"]',
        '[class*="phoneHidden"]',
        '[class*="phoneShow"]',
    ]
    if not phone:
        for sel in _phone_fallback_selectors:
            el = soup.select_one(sel)
            if el:
                digits = re.sub(r'\D', '', el.get_text(strip=True))
                if 9 <= len(digits) <= 11 and not digits.startswith('1900'):
                    phone = digits
                    break

    for el in soup.select('[itemprop]'):
        p = el.get('itemprop')
        v = el.get_text(strip=True)
        if p and v and len(v) < 100:
            ad_data.setdefault("params", [])
            ad_data["params"].append({"id": p, "label": p, "value": v})

    og_image = None
    meta_og = soup.select_one('meta[property="og:image"]')
    if meta_og:
        og_image = meta_og.get("content")

    return _build_info(ad_data, phone, url, og_image=og_image)


# ── Logging helpers ────────────────────────────────────────────────────────────

def _bar(done: int, total: int, width: int = 30) -> str:
    filled = int(width * done / total) if total else 0
    pct = done / total * 100 if total else 0
    return f"[{'#' * filled}{'-' * (width - filled)}] {done:>3}/{total} ({pct:5.1f}%)"


def _log_phase(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _log_page(page: int, found: int, total: int, limit: int):
    bar = _bar(total, limit)
    text = f"\r  Page {page:>2} | +{found:>3} links | {bar}"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    sys.stdout.flush()


def _log_batch(batch_idx: int, total_batches: int, batch_size: int, scraped: int, total_urls: int):
    bar = _bar(batch_idx, total_batches)
    pct = scraped / total_urls * 100 if total_urls else 0
    print(f"  Batch {batch_idx:>2}/{total_batches} {bar}  |  scraped={scraped:>3}/{total_urls} ({pct:5.1f}%)")


def _log_item(idx: int, total: int, title: str, status: str = "v"):
    short = (title[:55] + "...") if title and len(title) > 58 else (title or "-")
    mark = "+" if status == "v" else "x"
    text = f"\r    [{idx:>3}/{total}] {mark} {short:<58}"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    sys.stdout.flush()


# ── API helpers ────────────────────────────────────────────────────────────────

def _read_known_ids(csv_path: str) -> set[int]:
    """??c existing CSV, tr? v? set các ad_id ?ã quét (d? tránh quét l?i)."""
    known: set[int] = set()
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                aid = row.get("ID Ad")
                if aid:
                    try:
                        known.add(int(aid))
                    except ValueError:
                        pass
    except (FileNotFoundError, OSError):
        pass
    return known


def _today_storage_dir() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return f"storages/{today}"


CITY_REGION_MAP: dict[str, int] = {
    "tp-ho-chi-minh": 13000, "ho-chi-minh": 13000, "tphcm": 13000, "saigon": 13000,
    "tp-ha-noi": 12000, "ha-noi": 12000, "hanoi": 12000,
    "tp-da-nang": 15000, "da-nang": 15000, "danang": 15000,
    "tp-hai-phong": 16000, "hai-phong": 16000, "haiphong": 16000,
    "tp-can-tho": 17000, "can-tho": 17000, "cantho": 17000,
    "tp-bien-hoa": 18000, "bien-hoa": 18000, "bienhoa": 18000,
    "tp-hue": 19000, "hue": 19000,
    "tp-nha-trang": 20000, "nha-trang": 20000, "nhatrang": 20000,
    "tp-vung-tau": 21000, "vung-tau": 21000, "vungtau": 21000,
}

def _extract_region_v2(url: str | None) -> int | None:
    """Trích region_v2 từ nhatot listing URL."""
    if not url:
        return None
    path = urlparse(url).path.lower()
    for slug, code in CITY_REGION_MAP.items():
        if slug in path:
            return code
    return None


def _strip_vietnamese(text: str) -> str:
    """Chuy?n text ti?ng Vi?t sang ASCII (b? d?u, gi? nguyên ??/d)."""
    s = unicodedata.normalize('NFKD', text)
    s = s.replace('\u0110', 'D').replace('\u0111', 'd')
    return s.encode('ascii', 'ignore').decode('ascii')


def _slugify(text: str) -> str:
    """Chuy?n text thành URL slug (h? tr? ti?ng Vi?t)."""
    s = _strip_vietnamese(text).lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')

CATEGORY_SLUG_MAP: dict[str, str] = {
    "căn hộ/chung cư": "can-ho-chung-cu",
    "căn hộ mini": "can-ho-mini",
    "nhà ở": "nha-dat",
    "nhà nguyên căn": "nha-dat",
    "đất": "dat",
    "văn phòng, mặt bằng kinh doanh": "van-phong",
    "phòng trọ": "phong-tro",
}


def _category_to_slug(category_name: str) -> str:
    """Map category name sang slug URL."""
    key = category_name.lower().strip()
    for pattern, slug in CATEGORY_SLUG_MAP.items():
        if pattern in key or key in pattern:
            return slug
    return _slugify(category_name)


def _area_to_slug(area_name: str) -> str:
    """Chuy?n area name (VD: 'Qu?n Bình Tân') thành slug (VD: 'quan-binh-tan')."""
    prefix_map = {
        "quận": "quan", "huyện": "huyen",
        "thành phố": "thanh-pho", "thị xã": "thi-xa",
    }
    parts = area_name.strip().split(maxsplit=1)
    if len(parts) == 2:
        prefix_vn, rest = parts
        prefix_en = prefix_map.get(prefix_vn.lower(), _slugify(prefix_vn))
        return f"{prefix_en}-{_slugify(rest)}"
    return _slugify(area_name)


def _city_to_slug(region_name: str) -> str:
    """Chuy?n region name (VD: 'Tp H? Chí Minh') thành slug (VD: 'tp-ho-chi-minh')."""
    return _slugify(region_name)


def _build_ad_url_from_api(ad: dict) -> str | None:
    """T?o nhatot ad URL t? API response data."""
    list_id = ad.get("list_id")
    if not list_id:
        return None

    category_slug = _category_to_slug(ad.get("category_name", ""))
    area_slug = _area_to_slug(ad.get("area_name", ""))
    city_slug = _city_to_slug(ad.get("region_name", ""))

    path = f"mua-ban-{category_slug}-{area_slug}-{city_slug}"
    path = re.sub(r'-+', '-', path).strip('-')
    return f"https://www.nhatot.com/{path}/{list_id}.htm"


# ── Crawler ────────────────────────────────────────────────────────────────────

BASE_COLS = [
    "List ID", "ID Ad", "Title", "Property Type",
    "Price Value", "Price String", "Price/m2 (trieu)",
    "Area (m2)", "Width", "Length", "Living Area",
    "Ward", "District", "City", "Street",
    "Latitude", "Longitude",
    "Rooms", "Toilets", "Floors", "Floor Number",
    "House Type", "Legal Document", "Furnishing",
    "Direction", "Balcony Direction", "Project",
    "Phone", "Seller", "Company",
    "Seller Type", "Verified", "Response Rate", "Last Online",
    "Posting Date", "Expire Date", "Refresh Date",
    "Link", "Description",
    "Images", "OG Image",
    "Currency", "Negotiable",
    "Featured", "Urgent", "Top Ad", "Favorites",
    "Virtual Tour", "Floor Plan",
]

_HANDLED_KEYS = {
    "rooms", "toilets", "floors", "floor_number", "apartment_type", "house_type",
    "property_legal_document", "furnishing_sell", "direction", "balcony_direction",
    "projectid", "size", "width", "length", "living_size", "price", "price_million_per_m2",
    "Số phòng ngủ", "Số phòng vệ sinh", "Tổng số tầng", "Tầng số", "Loại hình",
    "Giấy tờ pháp lý", "Tình trạng nội thất", "Hướng cửa chính", "Hướng ban công",
    "Dự án", "Diện tích", "Chiều ngang", "Chiều dài", "Diện tích sử dụng",
    "property_status", "new_project", "category", "region", "area", "ward",
    "price_string", "ad_params", "params", "parameters", "initialState", "adView", "description", "description_en",
    "price_m2", "seller", "size_unit", "pty_characteristics", "unit", "region_v2", "area_v2", "ward_v2",
}

_BLOCKED_KEYS = {str(k).lower().strip() for k in _HANDLED_KEYS if k}


def _flatten_ad(ad: dict) -> dict:
    loc = ad.get("location", {})
    sz = ad.get("size", {})
    rm = ad.get("rooms", {})
    pr = ad.get("price", {})
    sl = ad.get("seller", {})
    mt = ad.get("meta", {})
    cat = ad.get("category", {})
    lg = ad.get("legal", {})

    street_parts = [loc.get("street_number"), loc.get("street_name")]
    street = " ".join(p for p in street_parts if p) or None

    raw_params = ad.get("params") or []
    id_map = {}
    label_map = {}
    for p in raw_params:
        if not isinstance(p, dict): continue
        pid = p.get("id")
        lbl = p.get("label")
        val = p.get("value")
        if pid: id_map[pid] = val
        if lbl: label_map[lbl] = val

    desc = ad.get("description") or ""
    md = ad.get("media", {})

    row = {
        "List ID":         ad.get("id", {}).get("list_id"),
        "ID Ad":           ad.get("id", {}).get("ad_id"),
        "Title":           ad.get("title"),
        "Description":     desc,
        "Property Type":   cat.get("category_name"),
        "Price Value":     pr.get("price"),
        "Price String":    pr.get("price_string"),
        "Price/m2 (trieu)": pr.get("price_million_per_m2"),
        "Area (m2)":       sz.get("size") or id_map.get("size"),
        "Width":           sz.get("width") or id_map.get("width"),
        "Length":          sz.get("length") or id_map.get("length"),
        "Living Area":     sz.get("living_size") or id_map.get("living_size"),
        "Ward":            loc.get("ward_name"),
        "District":        loc.get("area_name"),
        "City":            loc.get("region_name"),
        "Street":          street,
        "Latitude":        loc.get("latitude"),
        "Longitude":       loc.get("longitude"),

        "Rooms":           id_map.get("rooms") or label_map.get("Số phòng ngủ") or rm.get("rooms"),
        "Toilets":         id_map.get("toilets") or label_map.get("Số phòng vệ sinh") or rm.get("toilets"),
        "Floors":          id_map.get("floors") or label_map.get("Tổng số tầng") or rm.get("floors"),
        "Floor Number":    id_map.get("floor_number") or label_map.get("Tầng số"),
        "House Type":      id_map.get("apartment_type") or id_map.get("house_type") or label_map.get("Loại hình") or rm.get("house_type"),
        "Legal Document":  id_map.get("property_legal_document") or label_map.get("Giấy tờ pháp lý") or lg.get("property_legal_document"),
        "Furnishing":      id_map.get("furnishing_sell") or label_map.get("Tình trạng nội thất") or rm.get("furnishing_sell"),
        "Direction":       id_map.get("direction") or label_map.get("Hướng cửa chính"),
        "Balcony Direction": id_map.get("balcony_direction") or label_map.get("Hướng ban công"),
        "Project":         id_map.get("projectid") or label_map.get("Dự án"),

        "Phone":           sl.get("phone"),
        "Seller":          sl.get("account_name"),
        "Company":         sl.get("company_ad"),
        "Seller Type":     sl.get("seller_type"),
        "Verified":        sl.get("is_verified"),
        "Response Rate":   sl.get("response_rate"),
        "Last Online":     sl.get("last_online"),
        "Posting Date":    ad.get("posting_date"),
        "Expire Date":     mt.get("expire_time"),
        "Refresh Date":    mt.get("refresh_date"),
        "Link":            mt.get("ad_url"),
        "Images":          "; ".join(md.get("images", [])),
        "OG Image":        md.get("og_image"),
        "Currency":        pr.get("currency"),
        "Negotiable":      pr.get("is_negotiable"),
        "Featured":        mt.get("is_featured"),
        "Urgent":          mt.get("is_urgent"),
        "Top Ad":          mt.get("is_top"),
        "Favorites":       mt.get("favorite_count"),
        "Virtual Tour":    md.get("virtual_3d_url"),
        "Floor Plan":      "; ".join(md.get("floorplan_images", [])),
    }

    for p in raw_params:
        if not isinstance(p, dict): continue
        pid = str(p.get("id") or "").strip().lower()
        lbl = str(p.get("label") or "").strip().lower()
        val = p.get("value")

        if pid in _BLOCKED_KEYS or lbl in _BLOCKED_KEYS:
            continue

        col_name = f"[P] {lbl or pid}"
        if isinstance(val, list):
            val = ", ".join(str(v) for v in val)

        if col_name not in row:
            row[col_name] = val

    for k, v in row.items():
        if isinstance(v, str):
            row[k] = re.sub(r'\s+', ' ', v).strip()

    return row


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

    async def _parse_page(self, page: AsyncPage, url: str) -> str | None:
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

        await page.wait_for_timeout(1500)
        return await page.content()


    async def scrape_many(self, urls: list[str], concurrency: int = 5) -> list[dict]:
        sem = asyncio.Semaphore(concurrency)

        async def _bounded(url):
            async with sem:
                page = await self.get_new_page()
                try:
                    html = await self._parse_page(page, url)
                    return _parse_html(html, url) if html else None
                finally:
                    await page.close()

        results = await asyncio.gather(*[_bounded(u) for u in urls])
        return [r for r in results if r and r.get("meta", {}).get("status") == "active"]

    async def scrape_many_batched(self, urls: list[str], batch_size: int = 5, 
                                 download_images: bool = False, image_dir: str = "downloads",
                                 on_batch_callback: Callable[[list[dict]], None] | None = None) -> list[dict]:
        if not urls:
            return []

        start_time = datetime.now()
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
                status = "v" if r else "x"
                _log_item(i + j + 1, len(urls), title, status)
            sys.stdout.write("\n")
            sys.stdout.flush()

            if download_images:
                for r in results:
                    ad_id = r.get("id", {}).get("ad_id")
                    img_urls = r.get("media", {}).get("images", [])
                    if ad_id and img_urls:
                        ad_image_dir = os.path.join(image_dir, str(ad_id))
                        downloaded = await MediaDownloader.download_batch(img_urls, ad_image_dir)
                        if downloaded:
                            r["media"]["images"] = downloaded

            if on_batch_callback:
                flat_batch = [_flatten_ad(ad) for ad in results if ad]
                on_batch_callback(flat_batch)

            if i + batch_size < len(urls):
                await asyncio.sleep(2)

        success = len(all_results)
        pct = int(success / len(urls) * 100) if urls else 0
        elapsed = (datetime.now() - start_time).total_seconds()
        speed = success / (elapsed / 60) if elapsed else 0
        print(f"\n  Done  | {success}/{len(urls)} scraped ({pct}%)  |  {elapsed:.0f}s  |  {speed:.1f} ads/min")
        return all_results

    async def _fetch_urls_via_api(self, region_v2: int, category: str = "1000",
                                  max_pages: int = 50, limit: int = 50,
                                  from_date: date | None = None,
                                  to_date: date | None = None,
                                  skip_ad_ids: set[int] | None = None) -> list[str]:
        """L?y danh sách ad URLs t? ChoTot gateway API, l?c theo kho?ng ngày."""
        if skip_ad_ids is None:
            skip_ad_ids = set()
        all_urls: list[str] = []
        offset = 0
        page_size = 50  # API max per page, d? ??t depth s?m

        def _date_to_ms(d: date, end_of_day: bool = False) -> int:
            if end_of_day:
                dt = datetime.combine(d, datetime.max.time())
            else:
                dt = datetime.combine(d, datetime.min.time())
            return int(dt.timestamp() * 1000)

        from_ms = _date_to_ms(from_date) if from_date else None
        to_ms = _date_to_ms(to_date, end_of_day=True) if to_date else None

        for page in range(1, max_pages + 1):
            if len(all_urls) >= limit:
                break
            try:
                resp = await asyncio.to_thread(
                    requests.get,
                    "https://gateway.chotot.com/v1/public/ad-listing",
                    params={
                        "region_v2": region_v2,
                        "cg": category,
                        "w": "1",
                        "limit": page_size,
                        "o": offset,
                        "st": "s",
                        "f": "p",
                    },
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=15,
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                ads = data.get("ads", [])
                if not ads:
                    break

                all_older_than_from = True
                page_found = 0
                for ad in ads:
                    if len(all_urls) >= limit:
                        break
                    ad_id = ad.get("ad_id")
                    status = ad.get("status")
                    if not ad_id or status != "active":
                        continue
                    if ad_id in skip_ad_ids:
                        continue

                    list_time = ad.get("list_time", 0)
                    if list_time and from_ms is not None:
                        if list_time >= from_ms:
                            all_older_than_from = False
                    if to_ms is not None and list_time and list_time > to_ms:
                        continue
                    if from_ms is not None and list_time:
                        if list_time < from_ms:
                            continue

                    url = _build_ad_url_from_api(ad)
                    if not url:
                        continue
                    if url not in all_urls:
                        all_urls.append(url)
                        page_found += 1

                _log_page(page, page_found, len(all_urls), limit)
                offset += page_size

                if all_older_than_from and from_ms is not None:
                    break
            except Exception:
                break

        skipped = len(skip_ad_ids)
        if skipped:
            text = f"\n  {_bar(0, 0)} Skipped {skipped} ads already in storage"
            try:
                sys.stdout.write(text)
            except UnicodeEncodeError:
                sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
            sys.stdout.flush()

        sys.stdout.write("\n")
        sys.stdout.flush()
        return all_urls

    async def scrape_listings_today(self, list_url: str | None = None, max_pages: int = 50, limit: int = 50, 
                                   batch_size: int = 5, download_images: bool = False,
                                   image_dir: str = "downloads",
                                   from_date: date | None = None,
                                   to_date: date | None = None,
                                   skip_ad_ids: set[int] | None = None,
                                   on_batch_callback: Callable[[list[dict]], None] | None = None) -> list[dict]:
        _log_phase(f"PHASE 1 — Collecting Links  (limit={limit}, max_pages={max_pages})")
        if from_date:
            _log_phase(f"  From {from_date.isoformat()}")
        if to_date:
            _log_phase(f"  To {to_date.isoformat()}")

        start_time = datetime.now()

        # Try API first (fast, no browser needed)
        region_v2 = _extract_region_v2(list_url)
        use_api = region_v2 is not None
        if list_url is None:
            region_v2 = 13000  # default HCM
            use_api = True
        all_urls: list[str] = []

        if use_api:
            all_urls = await self._fetch_urls_via_api(
                region_v2, max_pages=max_pages, limit=limit,
                from_date=from_date, to_date=to_date,
                skip_ad_ids=skip_ad_ids,
            )

        # Fallback: Playwright n?u API failed ho?c region unknown
        # Không fallback n?u ã skip IDs (ngh?a là ?ã có h?t bài trong t?m ngày)
        need_fallback = not use_api
        if use_api and not all_urls and max_pages > 0:
            if not skip_ad_ids:
                need_fallback = True
            else:
                _log_phase("All ads in range already scraped, skipping Playwright fallback")

        if need_fallback:
            if use_api:
                _log_phase("API returned no results, falling back to Playwright...")
            pw_max_pages = min(max_pages, 5)  # Playwright listing b? Cloudflare ch?n, limit s? trang
            current_page = 1
            while current_page <= pw_max_pages and len(all_urls) < limit:
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

        elapsed = (datetime.now() - start_time).total_seconds()
        speed = len(all_urls) / (elapsed / 60) if elapsed else 0
        sys.stdout.write("\n")
        method = "API" if use_api else "Playwright"
        print(f"\n  Done  | {len(all_urls)} URLs collected ({method})  |  {elapsed:.0f}s  |  {speed:.1f} URLs/min")
        return await self.scrape_many_batched(all_urls, batch_size=batch_size, 
                                              download_images=download_images, image_dir=image_dir,
                                              on_batch_callback=on_batch_callback)

    async def crawl_to_csv(self, list_url: str | None = None,
                           output_file: str | None = None,
                           max_pages: int = 50, limit: int = 50, batch_size: int = 5,
                           download_images: bool = False,
                           image_dir: str | None = None,
                           from_date: date | None = None,
                           to_date: date | None = None):

        async def _crawl_day(day: date) -> list[dict]:
            day_str = day.isoformat()
            storage_dir = os.path.join("storages", day_str)
            day_output = os.path.join(storage_dir, f"nhatot_{day_str}.csv")
            day_image_dir = os.path.join(storage_dir, "images")
            os.makedirs(storage_dir, exist_ok=True)

            known_ids = _read_known_ids(day_output)

            print(f"\n{'=' * 58}")
            print(f"  Crawling day: {day_str}")
            print(f"  CSV: {day_output}")
            if known_ids:
                print(f"  Resume: {len(known_ids)} known ads")
            print(f"{'=' * 58}")

            all_param_cols: list[str] = []
            seen_param_cols: set[str] = set()
            flattened_ids: set[int] = set()
            all_flattened: list[dict] = []
            new_count = 0

            def _flush_batch(flat_batch: list[dict]) -> None:
                nonlocal new_count

                if not flat_batch:
                    return

                seen_ids_local: set[int] = set()
                for row in flat_batch:
                    aid = row.get("ID Ad")
                    if aid:
                        try:
                            aid_int = int(aid)
                            if aid_int in flattened_ids or aid_int in seen_ids_local:
                                continue
                            seen_ids_local.add(aid_int)
                        except ValueError:
                            pass

                new_rows = [r for r in flat_batch if r.get("ID Ad") and int(r["ID Ad"]) in seen_ids_local]

                for row in new_rows:
                    for col in row:
                        if col not in seen_param_cols and col not in BASE_COLS:
                            seen_param_cols.add(col)
                            all_param_cols.append(col)

                flattened_ids.update(seen_ids_local)
                all_flattened.extend(new_rows)
                new_count += len(new_rows)

                old_rows: list[dict] = []
                try:
                    with open(day_output, encoding="utf-8-sig", newline="") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            old_rows.append(row)
                except (FileNotFoundError, OSError):
                    pass

                old_rows_keep = []
                for row in old_rows:
                    aid = row.get("ID Ad")
                    keep = True
                    if aid:
                        try:
                            if int(aid) in flattened_ids:
                                keep = False
                        except ValueError:
                            pass
                    if keep:
                        old_rows_keep.append(row)

                merged = old_rows_keep + all_flattened
                final_headers = BASE_COLS + all_param_cols
                DataExporter.to_csv(merged, day_output, headers=final_headers)

            day_start = datetime.now()
            day_results = await self.scrape_listings_today(
                list_url, max_pages, limit, batch_size,
                download_images=download_images,
                image_dir=day_image_dir,
                from_date=day, to_date=day,
                skip_ad_ids=known_ids,
                on_batch_callback=_flush_batch,
            )

            if all_flattened:
                elapsed = (datetime.now() - day_start).total_seconds()
                print(f"\n  v Day {day_str}: {len(all_flattened)} rows ({new_count} new)  "
                      f"({len(all_param_cols)} param cols)  in {elapsed:.1f}s")

            return day_results

        if from_date and to_date:
            num_days = (to_date - from_date).days + 1
            if isinstance(from_date, datetime):
                fd = from_date.date()
            else:
                fd = from_date
            if isinstance(to_date, datetime):
                td = to_date.date()
            else:
                td = to_date
            dates = [fd + timedelta(days=i) for i in range((td - fd).days + 1)]
        elif from_date:
            if isinstance(from_date, date):
                dates = [from_date.date() if isinstance(from_date, datetime) else from_date]
            else:
                dates = [from_date]
        else:
            dates = [datetime.now().date()]

        print(f"\n{'#' * 60}")
        print(f"#  NhaTot Crawler  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):>40}#")
        print(f"#  Range: {dates[0].isoformat()} → {dates[-1].isoformat()} ({len(dates)} days)          #")
        print(f"#  Limit/day={limit}  Batch={batch_size}  MaxPages={max_pages}  Images={'ON' if download_images else 'OFF':<4}  #")
        print(f"{'#' * 60}\n")

        grand_start = datetime.now()
        all_results: list[dict] = []
        for day in dates:
            day_results = await _crawl_day(day)
            all_results.extend(day_results)

        total_elapsed = (datetime.now() - grand_start).total_seconds()
        print(f"\n{'#' * 60}")
        print(f"#  Complete: {len(dates)} days, {len(all_results)} total ads  in {total_elapsed:.0f}s  #")
        print(f"{'#' * 60}\n")
        return all_results


def scrape_ad(url: str, headless: bool = True) -> dict | None:
    async def _run():
        async with AsyncNhaTotCrawler(headless=headless) as c:
            r = await c.scrape_many([url])
            return r[0] if r else None
    return asyncio.run(_run())


def scrape_listings(list_url: str, limit: int = 10, max_pages: int = 5,
                    batch_size: int = 5) -> list[dict]:
    async def _run():
        async with AsyncNhaTotCrawler(headless=True) as c:
            return await c.scrape_listings_today(
                list_url, max_pages=max_pages, limit=limit, batch_size=batch_size)
    return asyncio.run(_run())
