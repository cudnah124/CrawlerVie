📘 CrawlerAI – Tài liệu kiến trúc & chức năng (Refactored Library)

## 1. Tổng quan dự án

**CrawlerAI** là một thư viện Python nhẹ và mạnh mẽ được xây dựng dựa trên [Crawl4AI](https://github.com/unclecode/crawl4ai). Dự án đã được refactor thành cấu trúc package chuyên nghiệp, hỗ trợ cả việc sử dụng như một thư viện (library) và công cụ dòng lệnh (CLI).

Dự án cung cấp hai phương thức trích xuất chính:
- 🔹 **LLM Mode**: Sử dụng AI để hiểu và trích xuất dữ liệu không cần bộ chọn (selectors).
- 🔹 **Schema Mode**: Sử dụng CSS Selectors để trích xuất nhanh, ổn định và miễn phí.

---

## 2. Các chức năng chính (Public API)

Dưới đây là các hàm chính được export trực tiếp từ package `crawlerai`.

### 2.1 🤖 Trích xuất bằng AI
- **Hàm**: `crawlerai.crawl_llm()`
- **Mô tả**: Gửi nội dung trang web (dạng Markdown rút gọn) tới LLM để trích xuất JSON theo yêu cầu.
- **Tính năng**: Tự động chia nhỏ nội dung (chunking), hỗ trợ nhiều provider (OpenAI, Gemini, Ollama...).

### 2.2 ⚡ Trích xuất bằng Schema (CSS)
- **Hàm**: `crawlerai.crawl_schema()`
- **Mô tả**: Sử dụng CSS/XPath selectors để lấy dữ liệu với tốc độ cực nhanh.
- **Tính năng**: Hỗ trợ lặp lại các phần tử (lists), trích xuất thuộc tính (attributes), và xử lý SPA.

### 2.3 🧠 Tự động tạo Schema
- **Hàm**: `crawlerai.generate_schema()`
- **Mô tả**: Sử dụng LLM để phân tích cấu trúc HTML của một URL và tự động sinh ra file JSON chứa các bộ chọn CSS tối ưu.

### 2.4 🏠 Scraper chuyên biệt NhaTot
- **Hàm**: `crawlerai.sites.nhatot.scrape_ad()`, `scrape_listings()`
- **Tính năng nâng cao**:
    - **📞 Reveal Phone**: Click và giải mã số điện thoại ẩn.
    - **🔍 Deep Extraction**: Parse trực tiếp từ `__NEXT_DATA__` của trang web.

---

## 3. Cấu trúc thư mục (New Project Structure)

| Module / Thư mục | Vai trò | Mô tả |
| :--- | :--- | :--- |
| `crawlerai/core/` | **Core Factories** | Tạo cấu hình Browser và RunConfig chuẩn hóa cho Crawl4AI. |
| `crawlerai/config/` | **Settings** | Quản lý API keys và cấu hình hệ thống từ `.env`. |
| `crawlerai/strategies/` | **Scraping Logic** | Triển khai các chiến lược LLMExtraction và CSS/Schema. |
| `crawlerai/sites/` | **Site Specific** | Các scraper tùy biến cho website phức tạp (VD: NhaTot). |
| `crawlerai/schema_gen/` | **Utility** | Công cụ sinh Schema tự động bằng AI. |
| `crawlerai/exporters/` | **Output** | Xuất dữ liệu ra CSV (Excel-friendly) hoặc JSON. |
| `crawlerai/cli/` | **CLI Interface** | Xử lý các lệnh từ command line (llm, schema, gen, nhatot). |
| `crawlerai/__init__.py` | **Public API** | Đầu mối export các hàm chính để sử dụng như một thư viện. |
| `schemas/` | **Knowledge** | Nơi lưu trữ các schema JSON đã tạo. |
| `output/` | **Data** | Thư mục mặc định chứa kết quả crawl. |

---

## 4. Workflows & Công nghệ

### 🔄 Data Pipeline
`Input (CLI/API) → Browser Config → Page Loading → Extraction Strategy → Normalization → Export (CSV/JSON)`

### 🛠 Công nghệ cốt lõi
1. **Crawl4AI**: Engine xử lý crawl và lọc Markdown.
2. **Playwright**: Điều khiển trình duyệt, xử lý JavaScript và bypass bot.
3. **LiteLLM**: Giao tiếp với đa dạng các mô hình ngôn ngữ (OpenAI, Gemini, v.v.).
4. **BeautifulSoup4**: Hỗ trợ parse DOM trong các site-specific scrapers.
5. **Click**: Xây dựng giao diện dòng lệnh mạnh mẽ.

---

## 5. Hướng dẫn sử dụng CLI mới

Dự án hiện hỗ trợ lệnh `crawlerai` trực tiếp (sau khi cài đặt):

- **LLM Crawl**: `crawlerai llm <URL> -i "Extract products"`
- **Schema Crawl**: `crawlerai schema <URL> --schema schemas/mysite.json`
- **Gen Schema**: `crawlerai gen <URL> -q "all prices and titles"`
- **NhaTot**: `crawlerai nhatot <URL>`
- **NhaTot List**: `crawlerai nhatot-list <URL> --limit 10`

---
<div align="center">
Tài liệu cập nhật ngày: 23/04/2026.
</div>