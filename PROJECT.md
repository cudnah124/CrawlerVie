📘 CrawlerAI – Tài liệu kiến trúc & chức năng
1. Tổng quan dự án

CrawlerAI là hệ thống thu thập dữ liệu web (Web Scraper) mạnh mẽ, hỗ trợ hai phương thức chính:

🔹 AI Mode (LLM)
Sử dụng mô hình ngôn ngữ lớn để hiểu nội dung trang web
Không cần viết CSS Selector
Chỉ cần:
URL
Instruction (mô tả dữ liệu cần lấy)
Schema mục tiêu
🔹 Traditional Mode (CSS)
Crawl bằng CSS Selectors
Nhanh, ổn định, không tốn chi phí API
Yêu cầu schema JSON định nghĩa selector
🧱 Nền tảng sử dụng
Crawl4AI: xử lý crawl tổng quát
Playwright: xử lý các case phức tạp (anti-bot, dynamic web)
2. Các chức năng chính (Core Functions)
2.1 🤖 Crawl bằng AI

Tên: crawl_with_ai
Module: crawlers/ai_crawler.py

Mô tả:
Trích xuất dữ liệu có cấu trúc từ bất kỳ website nào bằng LLM

Luồng xử lý:

Khởi tạo browser (Headless / Stealth)
Convert HTML → Markdown (giảm token)
Gửi Markdown + Schema + Instruction → LLM
Nhận JSON và xử lý lỗi
2.2 ⚡ Crawl bằng CSS Selector

Tên: crawl_with_selectors
Module: crawlers/traditional_crawler.py

Mô tả:
Phương pháp crawl truyền thống, nhanh và miễn phí

Luồng xử lý:

Load trang web
Dùng JsonCssExtractionStrategy (Crawl4AI)
Map DOM → JSON theo schema
Trả dữ liệu ngay lập tức
2.3 🧠 Tự động tạo Schema

Tên: generate_schema
Module: crawlers/schema_generator.py

Mô tả:
Dùng LLM để phân tích HTML và sinh CSS selectors

Mục đích:

Không cần mở DevTools
Tạo nhanh crawler cho site mới
2.4 🏠 Scraper chuyên biệt NhaTot

Tên:

scrape_nhatot_ad
scrape_nhatot_listings

Module: web/nhatot_scraper.py

Tính năng nâng cao:

📞 Reveal Phone
Click "Hiện số" bằng nhiều chiến thuật:
CSS selector
Text matching
Mouse events
🔍 Deep JSON Extraction
Parse dữ liệu từ __NEXT_DATA__
Lấy chính xác:
Giá
Diện tích
Pháp lý
GPS
🧩 Captcha Handling
Detect captcha
Cho phép user xử lý thủ công
3. Các chức năng hỗ trợ (Utilities)
3.1 📄 Export CSV

Tên: export_to_csv
Module: exporters/csv_exporter.py

Đặc điểm:

Flatten JSON lồng nhau
Encoding: utf-8-sig (Excel-friendly)
Auto generate column headers
3.2 ⚙️ Configuration

Module: config.py

Chức năng:

Đọc .env
Quản lý API Keys (OpenAI, Gemini, Ollama…)
Cấu hình browser:
Timeout
Headless
Proxy
3.3 🛡️ Anti-bot & SPA Handling

Áp dụng: cả AI & CSS mode

Cơ chế:

🕵️ Stealth Mode (bypass Cloudflare)
⏳ Wait for Selector (SPA)
📜 Auto Scroll (lazy loading)
🌐 Proxy Support (rotate IP)
4. Cấu trúc thư mục (Project Structure)
Module / File	Vai trò	Mô tả
main.py	CLI Entry Point	Chạy các mode: ai, css, schema-gen, nhatot
config.py	Settings	API keys, browser config
crawlers/	Core Logic	AI crawler, CSS crawler, schema generator
web/	Specialized Scrapers	Scraper riêng cho từng website
exporters/	Data Output	Xuất CSV
schemas/	Knowledge Base	Lưu JSON schema
5. Workflow xử lý dữ liệu
🔄 Pipeline tổng thể
Input → Browser → Page Load → Extraction → Normalization → Export
Chi tiết từng bước
1. Input
User chạy lệnh qua CLI:
python main.py --mode ai --url ... --prompt ...
2. Browser Initialization
AI/CSS: Crawl4AI
NhaTot: Playwright + Stealth
3. Page Loading
Load trang
Wait selector
Scroll
Remove popup/cookie
4. Extraction

AI Mode:

HTML → Markdown → LLM → JSON

CSS Mode:

HTML → CSS Selectors → JSON

NhaTot Mode:

Click Reveal Phone → Parse __NEXT_DATA__ → JSON
5. Normalization
Chuẩn hóa dữ liệu
Xử lý null
Flatten nested fields
6. Export
Ghi file CSV vào:
output/