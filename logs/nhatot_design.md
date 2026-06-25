# NhaTot Crawler Design

## Overview
- Async crawler base: `AsyncNhaTotCrawler(BaseAsyncCrawler)`
- Source: NhaTot.com (ChoTot platform) — bất động sản
- Output: CSV per day + optional images

## Architecture Flow

1. **URL Collection** (Phase 1)
   - **API**: `_fetch_urls_via_api()` — ChoTot gateway, lọc `from_date`/`to_date`, skip `known_ids`
   - **Fallback**: Playwright listing page nếu API fail / region unknown (giới hạn 5 pages)
   - Mỗi ngày crawl riêng → chỉ lấy URL của đúng ngày đó

2. **Scraping Details** (Phase 2) — batch concurrent
   - `scrape_many_batched()` — từng batch `batch_size` ads, restart browser session mỗi batch
   - `_parse_page()` → click phone button → lấy HTML DOM sau khi React render
   - `_parse_html()` → parse Next.js `__NEXT_DATA__` + BeautifulSoup + JSON-LD → ad dict

3. **Data Flattening** — `_flatten_ad()` module-level
   - Map system ID / label từ `params` array → BASE_COLS (48 cột cố định)
   - Dynamic `[P]` params: field không nằm trong `_BLOCKED_KEYS` → thêm cột động
   - Xử lý: dedup ID, map location/size/price/rooms/seller/meta/media

4. **Incremental CSV Saving** — sau mỗi batch
   - `on_batch_callback=_flush_batch()`: flatten batch → merge với CSV cũ → rewrite
   - Dedup: `flattened_ids` set tracking toàn bộ session
   - Mất tối đa `batch_size` tin nếu crash giữa chừng

5. **Per-Day Looping** — `crawl_to_csv` iterate từng ngày
   - `_crawl_day(day)`: tạo storage path → read known IDs → scrape → save
   - Resume: đọc `ID Ad` từ CSV cũ → skip khi collect URLs (tránh trùng)

## Key Components

| Component | Description |
|-----------|-------------|
| `_flatten_ad(ad)` | Module-level, ad dict → flat row dict (BASE_COLS + [P] cols) |
| `_parse_html(html, url)` | Extract từ `__NEXT_DATA__` + JSON-LD + DOM selectors |
| `_build_info(ad_data, page_html, url)` | Hợp nhất API data + page parse → chuẩn hóa |
| `BASE_COLS` | 48 cột cố định (List ID, ID Ad, Title, Phone, Price, ...) |
| `_BLOCKED_KEYS` | Param keys không tạo cột [P] vì đã có trong BASE_COLS |
| `_flush_batch(flat_batch)` | Closure ghi CSV incremental sau mỗi batch |

## Storage Layout
```
storages/
  YYYY-MM-DD/
    nhatot_YYYY-MM-DD.csv   # CSV data cho ngày đó
    images/
      <ad_id>/
        <hash>.jpg          # ảnh đã tải (nếu --download-images)
```

## Running

```bash
# Crawl date range, per-day folders
python -m crawlerai.cli.main nhatot-crawl \
  --from-date 2026-06-14 --to-date 2026-06-24 \
  --limit 500 --max-pages 50 --download-images

# Single ad
python -m crawlerai.cli.main nhatot <url>

# List + scrape
python -m crawlerai.cli.main nhatot-list <list_url> --limit 10
```
