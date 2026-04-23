import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
try:
    from playwright_stealth import stealth_sync as _stealth
except ImportError:
    from playwright_stealth import stealth as _stealth


def apply_stealth(page):
    if callable(_stealth):
        _stealth(page)
        return
    if hasattr(_stealth, "stealth_sync"):
        _stealth.stealth_sync(page)
        return
    if hasattr(_stealth, "stealth"):
        _stealth.stealth(page)
        return
    print("Warning: playwright_stealth does not expose a usable stealth function. Continuing without stealth.")


def wait_for_next_data(page, max_wait_ms=180000):
    start = datetime.now()
    notified = False
    while True:
        if page.locator('#__NEXT_DATA__').count() > 0:
            return True
        title = page.title()
        if ("Just a moment" in title or "ShieldSquare" in title) and not notified:
            print("Captcha detected. Please solve it in the opened browser. Waiting...")
            notified = True
        elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
        if elapsed_ms >= max_wait_ms:
            return False
        page.wait_for_timeout(2000)


def try_reveal_phone(page):
    selectors = [
        "button.b1b6q6wa.primary.r-normal.large.w-bold",
        "[class*='LeadButton__showPhoneButton__'] button",
        "[class*='ShowPhoneButton_wrapper__'] button",
        ".InlineShowPhoneButton_linkContact__U_lEr",
        ".InlineShowPhoneButton_phoneHidden__4KcON",
        "button.b14cwtpv.link.r-normal.small.w-bold.t-link",
        ".b14cwtpv.link.r-normal.small.w-bold.t-link",
        "a.b14cwtpv.link.r-normal.small.w-bold.t-link",
    ]
    for _ in range(5):
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() > 0:
                    locator.first.scroll_into_view_if_needed(timeout=2000)
                    locator.first.click(timeout=2000, force=True)
                    page.wait_for_timeout(800)
                    if wait_for_revealed_phone(page, timeout_ms=1500):
                        return True
            except Exception:
                continue

    candidates = [
        "Hiện số",
        "Hiện số điện thoại",
        "Xem số",
        "Liên hệ",
    ]
    for _ in range(3):
        for text in candidates:
            try:
                locator = page.get_by_text(text, exact=False)
                if locator.count() > 0:
                    locator.first.scroll_into_view_if_needed(timeout=2000)
                    locator.first.click(timeout=2000, force=True)
                    page.wait_for_timeout(800)
                    if wait_for_revealed_phone(page, timeout_ms=1500):
                        return True
            except Exception:
                continue

    try:
        page.evaluate(
            r"""() => {
                const el = document.querySelector('button.b1b6q6wa.primary.r-normal.large.w-bold')
                    || document.querySelector("[class*='LeadButton__showPhoneButton__'] button")
                    || document.querySelector("[class*='ShowPhoneButton_wrapper__'] button")
                    || document.querySelector('.b14cwtpv.link.r-normal.small.w-bold.t-link');
                if (el) {
                    el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                    el.click();
                    return true;
                }
                return false;
            }"""
        )
        page.wait_for_timeout(1000)
        return True
    except Exception:
        return False

    try:
        locator = page.locator(
            "button.b1b6q6wa.primary.r-normal.large.w-bold, "
            "[class*='LeadButton__showPhoneButton__'] button, "
            "[class*='ShowPhoneButton_wrapper__'] button"
        )
        if locator.count() > 0:
            box = locator.first.bounding_box()
            if box:
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.wait_for_timeout(1000)
                return True
    except Exception:
        return False


def extract_phone_from_dom(page):
    try:
        return page.evaluate(
            r"""() => {
                const root = document;
                const candidates = [];

                const tel = root.querySelector('a[href^="tel:"]');
                if (tel && tel.getAttribute('href')) {
                    const telValue = tel.getAttribute('href').replace('tel:', '').trim();
                    candidates.push(telValue.replace(/\D/g, ''));
                }

                const btn = root.querySelector('button.b1b6q6wa.primary.r-normal.large.w-bold')
                    || root.querySelector("[class*='LeadButton__showPhoneButton__'] button")
                    || root.querySelector("[class*='ShowPhoneButton_wrapper__'] button")
                    || root.querySelector('.InlineShowPhoneButton_linkContact__U_lEr')
                    || root.querySelector('.InlineShowPhoneButton_phoneHidden__4KcON')
                    || root.querySelector('.b14cwtpv.link.r-normal.small.w-bold.t-link');
                if (btn) {
                    const stretch = btn.querySelector('#stretch');
                    if (stretch) {
                        const stretchDigits = (stretch.textContent || '').replace(/\D/g, '');
                        if (stretchDigits) candidates.push(stretchDigits);
                    }

                    const raw = (btn.textContent || '').replace(/Sao\s*ch[ée]p/gi, ' ');
                    const normalized = raw.replace(/\D/g, '');
                    if (normalized) candidates.push(normalized);

                    const dataPhone = btn.getAttribute('data-phone') || btn.getAttribute('data-number');
                    if (dataPhone) candidates.push(dataPhone.replace(/\D/g, ''));

                    const container = btn.closest('div') || btn.parentElement;
                    if (container) {
                        const text = container.textContent || '';
                        const digits = text.replace(/\D/g, '');
                        if (digits) candidates.push(digits);
                    }
                }

                const unique = Array.from(new Set(candidates.filter(Boolean)));
                const phone = unique.find(p => p.length >= 10 && p.length <= 11 && !p.startsWith('1900')) || null;
                return { phone, candidates: unique };
            }"""
        )
    except Exception:
        return None


def wait_for_revealed_phone(page, timeout_ms=8000):
    try:
        page.wait_for_function(
            r"""() => {
                const btn = document.querySelector('button.b1b6q6wa.primary.r-normal.large.w-bold')
                    || document.querySelector("[class*='LeadButton__showPhoneButton__'] button")
                    || document.querySelector("[class*='ShowPhoneButton_wrapper__'] button")
                    || document.querySelector('.InlineShowPhoneButton_linkContact__U_lEr')
                    || document.querySelector('.InlineShowPhoneButton_phoneHidden__4KcON')
                    || document.querySelector('.b14cwtpv.link.r-normal.small.w-bold.t-link');
                if (!btn) return false;
                const digits = (btn.textContent || '').replace(/\D/g, '');
                return digits.length >= 10 && digits.length <= 11 && !digits.startsWith('1900');
            }""",
            timeout=timeout_ms
        )
        return True
    except Exception:
        return False


DEBUG_DUMP = True
FULL_AD_DUMP = True


def find_ad_data(data):
    candidates = [
        ("props", "pageProps", "ad"),
        ("props", "pageProps", "initialProps", "ad"),
        ("props", "pageProps", "data", "ad"),
        ("props", "pageProps", "detail", "ad"),
    ]
    for path in candidates:
        node = data
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                node = None
                break
        if isinstance(node, dict) and node:
            return node

    primary_keys = {"subject", "price_str", "images"}
    secondary_keys = {"ad_id", "list_time", "area_name", "region_name"}

    def walk(obj):
        if isinstance(obj, dict):
            if primary_keys.issubset(obj.keys()):
                return obj
            if primary_keys.intersection(obj.keys()) and secondary_keys.intersection(obj.keys()):
                return obj
            for value in obj.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = walk(item)
                if found:
                    return found
        return None

    return walk(data)


def dedupe_list(items):
    seen = set()
    result = []
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def normalize_param_item(item):
    if not isinstance(item, dict):
        return None
    label = item.get("label") or item.get("name") or item.get("title")
    value = item.get("value") or item.get("val") or item.get("text")
    param_id = item.get("id") or item.get("key") or item.get("code")
    if label is None and value is None:
        return None
    return {"id": param_id, "label": label, "value": value}


def collect_params(ad_data):
    sources = []
    for key in ["params", "parameters", "pty_characteristics", "ad_features"]:
        value = ad_data.get(key)
        if isinstance(value, list):
            sources.extend(value)
    normalized = []
    for item in sources:
        normalized_item = normalize_param_item(item)
        if normalized_item:
            normalized.append(normalized_item)
    normalized = dedupe_list(normalized)

    existing_labels = {str(p.get("label")).strip().lower() for p in normalized if p.get("label")}

    def add_param(label, value, param_id=None):
        if value is None:
            return
        if label.strip().lower() in existing_labels:
            return
        normalized.append({"id": param_id, "label": label, "value": value})
        existing_labels.add(label.strip().lower())

    size = ad_data.get("size")
    size_unit = ad_data.get("size_unit_string")
    if size is not None and size_unit:
        add_param("Diện tích đất", f"{size} {size_unit}", "size")

    price_m2 = ad_data.get("price_million_per_m2")
    if price_m2 is not None:
        add_param("Giá/m²", f"{price_m2} triệu/m²", "price_m2")

    legal_map = {
        1: "Đã có sổ",
        2: "Đang chờ sổ",
        3: "Giấy tờ khác",
        4: "Vi bằng",
        5: "Sổ chung",
    }
    legal_code = ad_data.get("property_legal_document")
    if legal_code in legal_map:
        add_param("Giấy tờ pháp lý", legal_map[legal_code], "property_legal_document")

    direction = ad_data.get("direction") or ad_data.get("direction_name")
    direction_map = {
        1: "Đông",
        2: "Tây",
        3: "Nam",
        4: "Bắc",
        5: "Đông Bắc",
        6: "Tây Bắc",
        7: "Đông Nam",
        8: "Tây Nam",
    }
    if isinstance(direction, int) and direction in direction_map:
        direction = direction_map[direction]
    if direction:
        add_param("Hướng đất", direction, "direction")

    width = ad_data.get("width")
    if width is not None:
        add_param("Chiều ngang", f"{width} m", "width")

    length = ad_data.get("length")
    if length is not None:
        add_param("Chiều dài", f"{length} m", "length")

    if size_unit:
        add_param("Đơn vị", size_unit, "size_unit")

    return dedupe_list(normalized)


def scrape_nhatot_ad(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        apply_stealth(page)

        next_data = None
        try:
            print(f"Navigating to {url} with Playwright...")
            page.goto(url, wait_until='domcontentloaded', timeout=60000)

            if not wait_for_next_data(page, max_wait_ms=180000):
                raise PlaywrightTimeoutError("Timeout waiting for __NEXT_DATA__ to appear")

            page.wait_for_timeout(3000)

            try_reveal_phone(page)
            wait_for_revealed_phone(page, timeout_ms=8000)
            page.wait_for_timeout(500)

            phone_text = None
            phone_candidates = []
            for _ in range(6):
                result = extract_phone_from_dom(page)
                if isinstance(result, dict):
                    phone_text = result.get("phone")
                    phone_candidates = result.get("candidates") or []
                else:
                    phone_text = result
                if phone_text and not phone_text.startswith("1900"):
                    break
                page.wait_for_timeout(500)
            print(f"Revealed phone text: {phone_text}")
            print(f"Phone candidates: {phone_candidates}")

            try:
                next_data = page.evaluate("() => window.__NEXT_DATA__ || null")
            except Exception:
                next_data = None

            html_content = page.content()
            browser.close()

        except Exception as e:
            print(f"Error fetching the URL with Playwright: {e}")
            browser.close()
            return None

    soup = BeautifulSoup(html_content, 'html.parser')
    
    try:
        if next_data:
            data = next_data
        else:
            script_tag = soup.find('script', {'id': '__NEXT_DATA__'})
            if not script_tag:
                print("Could not find the __NEXT_DATA__ script tag.")
                return None
            script_text = script_tag.string or script_tag.text
            data = json.loads(script_text)
        ad_data = find_ad_data(data) or {}
        if not ad_data:
            print("Could not find 'ad' data in the JSON structure.")
            if DEBUG_DUMP:
                with open("nhatot_next_data_dump.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print("Wrote debug dump to nhatot_next_data_dump.json")
            return None
    except (json.JSONDecodeError, AttributeError) as e:
        print(f"Error parsing JSON data: {e}")
        return None

    if FULL_AD_DUMP:
        with open("nhatot_ad_full.json", "w", encoding="utf-8") as f:
            json.dump(ad_data, f, ensure_ascii=False, indent=2)
        print("Wrote full ad data to nhatot_ad_full.json")

    scraped_info = {
        "id": {
            "ad_id": ad_data.get("ad_id"),
            "list_id": ad_data.get("list_id"),
            "account_id": ad_data.get("account_id"),
            "account_oid": ad_data.get("account_oid"),
        },
        "title": ad_data.get("subject"),
        "description": ad_data.get("body"),
        "category": {
            "category": ad_data.get("category"),
            "category_name": ad_data.get("category_name"),
        },
        "price": {
            "price": ad_data.get("price"),
            "price_string": ad_data.get("price_string") or ad_data.get("price_str"),
            "price_million_per_m2": ad_data.get("price_million_per_m2"),
        },
        "size": {
            "size": ad_data.get("size"),
            "size_unit": ad_data.get("size_unit_string"),
            "width": ad_data.get("width"),
            "length": ad_data.get("length"),
            "living_size": ad_data.get("living_size"),
            "area": ad_data.get("area"),
        },
        "rooms": {
            "rooms": ad_data.get("rooms"),
            "toilets": ad_data.get("toilets"),
            "floors": ad_data.get("floors"),
            "house_type": ad_data.get("house_type"),
            "furnishing_sell": ad_data.get("furnishing_sell"),
        },
        "legal": {
            "property_legal_document": ad_data.get("property_legal_document"),
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
            "account_name": ad_data.get("account_name") or ad_data.get("full_name"),
            "avatar": ad_data.get("avatar"),
            "phone": ad_data.get("phone"),
            "company_ad": ad_data.get("company_ad"),
        },
        "media": {
            "images": dedupe_list(ad_data.get("images", [])),
            "videos": ad_data.get("videos", []),
        },
        "meta": {
            "list_time": ad_data.get("list_time"),
            "orig_list_time": ad_data.get("orig_list_time"),
            "date_text": ad_data.get("date"),
            "state": ad_data.get("state"),
            "status": ad_data.get("status"),
            "type": ad_data.get("type"),
        },
        "params": collect_params(ad_data),
    }

    list_time = ad_data.get('list_time')
    if list_time:
        if isinstance(list_time, (int, float)):
            ts = list_time
            if ts > 1_000_000_000_000:
                ts = ts / 1000.0
            dt_object = datetime.fromtimestamp(ts)
        else:
            dt_object = datetime.fromisoformat(str(list_time).replace('Z', '+00:00'))
        scraped_info['posting_date'] = dt_object.strftime('%Y-%m-%d %H:%M:%S')
    else:
        scraped_info['posting_date'] = None

    if phone_text and not phone_text.startswith("1900"):
        scraped_info["seller"]["phone"] = phone_text

    return scraped_info


def scrape_nhatot_listings(list_url, limit=10):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        apply_stealth(page)

        try:
            print(f"Navigating to {list_url} with Playwright...")
            page.goto(list_url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(3000)

            links = []
            for _ in range(8):
                raw_links = page.evaluate(
                    r"""() => Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.getAttribute('href'))"""
                )
                for href in raw_links:
                    if not href:
                        continue
                    if ".htm" not in href:
                        continue
                    if "nhatot.com" not in href:
                        href = urljoin(list_url, href)
                    if "/mua-ban-" not in href and "/mua-ban" not in href:
                        continue
                    if href not in links:
                        links.append(href)
                if len(links) >= limit:
                    break
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

            browser.close()
        except Exception as e:
            print(f"Error fetching listing page: {e}")
            browser.close()
            return []

    results = []
    for href in links[:limit]:
        ad_data = scrape_nhatot_ad(href)
        if ad_data:
            results.append(ad_data)
    return results


if __name__ == '__main__':
    target_url = "https://www.nhatot.com/mua-ban-nha-dat-quan-12-tp-ho-chi-minh/131328316.htm"
    
    print(f"Scraping URL: {target_url}")
    
    ad_details = scrape_nhatot_ad(target_url)
    
    if ad_details:
        print("\n--- SCRAPED DATA ---")
        print(json.dumps(ad_details, indent=4, ensure_ascii=False))
        print("--------------------\n")
    else:
        print("Failed to scrape the ad details.")
