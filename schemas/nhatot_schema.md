# NhaTot Data Schema

## 1. Tổng quan

- **Mục đích**: Crawl dữ liệu bất động sản từ nhatot.com
- **Method**: Playwright `page.content()` → BeautifulSoup parse offline
- **Output**: CSV + JSON + ảnh local (`nhatot_images/<ad_id>/`)
- **Filter**: Chỉ lưu ad có `status == "active"`

### Flow xử lý

```
Browser → navigate → click phone → page.content()
                                            ↓
                                    _parse_html() (BeautifulSoup)
                                    ├── <script id="__NEXT_DATA__"> → JSON
                                    ├── <a href="tel:..."> → phone
                                    ├── <input id="phoneNumberInput"> → phone
                                    ├── .InlineShowPhoneButton_linkContact → phone
                                    ├── [itemprop] → dynamic params
                                    └── <meta property="og:image"> → thumbnail
                                            ↓
                                    _build_info() → dict
                                            ↓
                          ┌───────────┴───────────┐
                          ↓                       ↓
                       JSON file               CSV export
                     (per ad)               (flatten + merge)
                          ↓
                   nhatot_images/<ad_id>/
                   (nếu download_images=True)
```

---

## 2. Cấu trúc dữ liệu (`_build_info`)

### id

| Field | Type | Source | Description |
|---|---|---|---|
| `ad_id` | int | `__NEXT_DATA__` | Unique ad identifier |
| `list_id` | int | `__NEXT_DATA__` | Listing ID (trong URL) |
| `account_id` | int | `__NEXT_DATA__` | Seller account ID |

### title

| Field | Type | Source | Fallback |
|---|---|---|---|
| `title` | string | `__NEXT_DATA__` | `subject` |

### description

| Field | Type | Source | Xử lý |
|---|---|---|---|
| `description` | string | `body` (API) | `re.sub(r'\s+', ' ', ...)` |

### category

| Field | Type | Source | Example |
|---|---|---|---|
| `category` | int | `__NEXT_DATA__` | 1010 |
| `category_name` | string | `__NEXT_DATA__` | "Căn hộ/Chung cư" |

### price

| Field | Type | Default | Example |
|---|---|---|---|
| `price` | int | - | 13900000000 |
| `price_string` | string | - | "13,9 tỷ" |
| `price_million_per_m2` | float | - | 117.8 |
| `currency` | string | `"VND"` | "USD" |
| `is_negotiable` | bool? | `null` | `true` |

### size

| Field | Type | Example |
|---|---|---|
| `size` | float | 118.0 |
| `size_unit` | string | "118 m²" |
| `width` | float? | `null` |
| `length` | float? | `null` |
| `living_size` | float? | `null` |

### rooms

| Field | Type | Example |
|---|---|---|
| `rooms` | string | "3 PN" |
| `toilets` | string? | "1 phòng" |
| `floors` | string? | `null` |
| `house_type` | string? | "Chung cư" |
| `furnishing_sell` | string? | "Nội thất đầy đủ" |

### legal

| Field | Type | Example |
|---|---|---|
| `property_legal_document` | string? | "Sổ hồng riêng" |

### location

| Field | Type | Example |
|---|---|---|
| `street_number` | string? | "208" |
| `street_name` | string? | "Nguyễn Hữu Cảnh" |
| `ward_name` | string | "Phường 22" |
| `area_name` | string | "Quận Bình Thạnh" |
| `region_name` | string | "Tp Hồ Chí Minh" |
| `latitude` | float | 10.79387 |
| `longitude` | float | 106.72032 |

### seller

| Field | Type | Source | Ghi chú |
|---|---|---|---|
| `account_name` | string | `__NEXT_DATA__` | Tên người bán |
| `avatar` | string (URL) | `__NEXT_DATA__` | Avatar CDN URL |
| `phone` | string? | Click phone → DOM | `null` nếu không reveal được |
| `company_ad` | bool? | `__NEXT_DATA__` | `true` nếu là môi giới/cty |
| `seller_type` | string? | `__NEXT_DATA__` | `"personal"`, `"broker"`, `"agency"` |
| `is_verified` | bool? | `__NEXT_DATA__` | Đã xác thực? |
| `response_rate` | int? | `seller` object | 0-100 |
| `last_online` | datetime? | `seller` object | Convert từ timestamp |

### media

| Field | Type | Ghi chú |
|---|---|---|
| `images` | `list[str]` | CDN URLs → local paths nếu `download_images=True` |
| `videos` | `list[str]` | Rất hiếm |
| `og_image` | string? | `<meta property="og:image">` — thumbnail đại diện |
| `virtual_3d_url` | string? | Tour ảo 360° (virtual_tour_url, panorama_url fallback) |
| `floorplan_images` | `list[str]` | Hình mặt bằng (floor_plan fallback) |

### meta

| Field | Type | Default | Ghi chú |
|---|---|---|---|
| `ad_url` | string | - | URL gốc của ad |
| `list_time` | int | - | Unix timestamp (ms) — dùng tính `posting_date` |
| `view_count` | int | 0 | Lượt xem |
| `state` | string | - | `"accepted"`, `"pending"` |
| `status` | string | - | **`"active"`** / `"deleted"` — filter lấy active |
| `type` | string | - | `"s"` (sell), `"r"` (rent) |
| `expire_time` | datetime? | `null` | Ngày hết hạn (expire_date fallback) |
| `refresh_date` | datetime? | `null` | Lần cuối làm mới (last_refresh fallback) |
| `is_featured` | bool? | `null` | Tin nổi bật (is_top fallback) |
| `is_urgent` | bool? | `null` | Tin gấp |
| `is_top` | bool? | `null` | Tin top |
| `favorite_count` | int? | `null` | Lượt yêu thích (like_count fallback) |

### params

```
list[dict]  — dynamic params từ __NEXT_DATA__
Mỗi item: { id: string, label: string, value: string }
Ví dụ: { id: "rooms", label: "Số phòng ngủ", value: "3 PN" }

Quy tắc:
- Gom từ ad_params / params / parameters + inner ad object
- Lọc trùng theo ID, ưu tiên label tiếng Việt
```

### posting_date

| Field | Type | Format |
|---|---|---|
| `posting_date` | string | `"2026-06-20 15:53:30"` (từ `list_time / 1000`) |

---

## 3. CSV Columns (`_flatten_ad` → `crawl_to_csv`)

### Base columns (49 columns)

| # | Column | Source field | Type |
|---|---|---|---|
| 1 | `ID Ad` | `id.ad_id` | int |
| 2 | `Title` | `title` | string |
| 3 | `Description` | `description` | string |
| 4 | `Property Type` | `category.category_name` | string |
| 5 | `Price Value` | `price.price` | int |
| 6 | `Price String` | `price.price_string` | string |
| 7 | `Price/m2 (trieu)` | `price.price_million_per_m2` | float |
| 8 | `Area (m2)` | `size.size` | float |
| 9 | `Width` | `size.width` | float? |
| 10 | `Length` | `size.length` | float? |
| 11 | `Living Area` | `size.living_size` | float? |
| 12 | `Ward` | `location.ward_name` | string |
| 13 | `District` | `location.area_name` | string |
| 14 | `City` | `location.region_name` | string |
| 15 | `Street` | `street_number + street_name` | string |
| 16 | `Latitude` | `location.latitude` | float |
| 17 | `Longitude` | `location.longitude` | float |
| 18 | `Rooms` | `rooms.rooms` / params | string |
| 19 | `Toilets` | `rooms.toilets` / params | string? |
| 20 | `Floors` | `rooms.floors` / params | string? |
| 21 | `Floor Number` | params `floor_number` | string? |
| 22 | `House Type` | `rooms.house_type` / params | string? |
| 23 | `Legal Document` | `legal.property_legal_document` / params | string? |
| 24 | `Furnishing` | `rooms.furnishing_sell` / params | string? |
| 25 | `Direction` | params `direction` | string? |
| 26 | `Balcony Direction` | params `balcony_direction` | string? |
| 27 | `Project` | params `projectid` | string? |
| 28 | `Phone` | `seller.phone` | string? |
| 29 | `Seller` | `seller.account_name` | string |
| 30 | `Company` | `seller.company_ad` | bool? |
| 31 | `Seller Type` | `seller.seller_type` | string? |
| 32 | `Verified` | `seller.is_verified` | bool? |
| 33 | `Response Rate` | `seller.response_rate` | int? |
| 34 | `Last Online` | `seller.last_online` | datetime? |
| 35 | `Posting Date` | `posting_date` | datetime |
| 36 | `Expire Date` | `meta.expire_time` | datetime? |
| 37 | `Refresh Date` | `meta.refresh_date` | datetime? |
| 38 | `Link` | `meta.ad_url` | string (URL) |
| 39 | `Images` | `media.images` | string (join "; ") |
| 40 | `OG Image` | `media.og_image` | string (URL)? |
| 41 | `Currency` | `price.currency` | string |
| 42 | `Negotiable` | `price.is_negotiable` | bool? |
| 43 | `Featured` | `meta.is_featured` | bool? |
| 44 | `Urgent` | `meta.is_urgent` | bool? |
| 45 | `Top Ad` | `meta.is_top` | bool? |
| 46 | `Favorites` | `meta.favorite_count` | int? |
| 47 | `Virtual Tour` | `media.virtual_3d_url` | string (URL)? |
| 48 | `Floor Plan` | `media.floorplan_images` | string (join "; ") |

### Dynamic columns (`[P] ...`)

Các params không nằm trong `handled_keys` sẽ được thêm với prefix `[P]`:

| Column | Example value |
|---|---|
| `[P] balconydirection` | "Nam" |
| `[P] floornumber` | "6" |
| `[P] block` | "Park 3" |
| `[P] apartment_feature` | "Căn góc" |
| `[P] unitnumber` | "1205" |
| ... | (tuỳ category) |

---

## 4. Edge Cases

| Case | Xử lý |
|---|---|
| **Phone ẩn `***`** | Nếu text chứa `*` → `null`. Thường xảy ra khi status != active |
| **Hotline 1900...** | Filter: `digits.startswith('1900')` → bỏ qua |
| **Deleted ad** | `meta.status != "active"` → `scrape_many()` lọc bỏ |
| **currency null** | Default `"VND"` |
| **price_million_per_m2** | Chỉ tính khi cả price và size đều có |
| **images** | List URL CDN. Nếu `download_images=True` → ghi đè bằng local paths |
| **og_image** | Lấy từ `<meta property="og:image">` — không có trong `__NEXT_DATA__` |
| **seller response_rate** | Có ~15% ads, lấy từ `seller` object con |
| **virtual_3d_url** | < 5% ads cao cấp |
| **floorplan_images** | < 2% ads |
| **ad_params trùng** | Gom từ nhiều ngóc ngách JSON, lọc trùng theo ID, ưu tiên label tiếng Việt |

---

## 5. File paths

| Asset | Path | Ghi chú |
|---|---|---|
| Crawler code | `crawlerai/sites/nhatot.py` | AsyncNhaTotCrawler class |
| Config | `.env` | `HEADLESS`, `PAGE_TIMEOUT` |
| CSV output | `nhatot_<count>.csv` | utf-8-sig BOM |
| JSON per ad | `output/nhatot_<ad_id>.json` | CLI single mode |
| Images | `nhatot_images/<ad_id>/` | Organised by ad_id |
| Schema này | `schemas/nhatot_schema.md` | Tài liệu |
