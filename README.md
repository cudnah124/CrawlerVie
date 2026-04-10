# crawlerAI

Web scraper với hai mode: AI (LLM) và CSS selector. Đầu ra luôn là file CSV.

```
crawlerAI/
├── config.py                    # Cấu hình chung, đọc từ .env
├── main.py                      # Entry point
├── crawlers/
│   ├── ai_crawler.py            # Crawl dùng LLM
│   └── traditional_crawler.py  # Crawl dùng CSS selector
├── exporters/
│   └── csv_exporter.py         # Xuất kết quả ra CSV
└── schemas/                    # Schema mẫu có thể dùng ngay
    ├── hackernews_css.json
    └── hackernews_ai.json
```

## Setup

```bash
pip install -r requirements.txt
# Cách khuyến nghị (ổn định hơn, không phụ thuộc CLI có nằm trong PATH hay không)
python -c "from crawl4ai.install import post_install; post_install()"

# Nếu máy bạn có sẵn CLI thì vẫn có thể dùng:
# crawl4ai-setup

# Kiểm tra setup đã OK chưa
python -c "from crawl4ai.install import doctor; doctor()"

cp .env.example .env
# Điền OPENAI_API_KEY vào .env (chỉ cần cho mode 'ai')
```

### Troubleshooting nhanh (Linux/Devcontainer)

Nếu `doctor()` báo thiếu browser Playwright:

```bash
python -m playwright install chromium
```

Nếu báo thiếu shared library (ví dụ: `libatk-1.0.so.0`):

```bash
python -m playwright install-deps chromium
```

Nếu `apt` lỗi repo bên thứ 3 (ví dụ Yarn key), tạm disable repo đó rồi chạy lại lệnh trên.

## Sử dụng

### Mode CSS — nhanh, miễn phí, deterministic

```bash
# Dùng schema mẫu có sẵn
python main.py css https://news.ycombinator.com --schema schemas/hackernews_css.json

# Chờ element render trước khi extract (trang SPA)
python main.py css https://example.com --schema schemas/my_schema.json --wait-for "css:div.results"

# Chỉ định file output
python main.py css https://example.com --schema schemas/my_schema.json --output output/data.csv

# Chạy JS trước khi extract (ví dụ scroll để load lazy content)
python main.py css https://example.com --schema schemas/my_schema.json \
  --js "window.scrollTo(0, document.body.scrollHeight)"
```

### Mode AI — không cần biết cấu trúc HTML, tự suy luận

```bash
# Dùng OpenAI (cần API key trong .env)
python main.py ai https://news.ycombinator.com \
  --schema schemas/hackernews_ai.json \
  --instruction "Extract every story: title, URL, score, comment count, and author"

# Dùng Ollama local (miễn phí, chạy offline)
python main.py ai https://example.com \
  --provider ollama/qwen2.5 \
  --instruction "Extract all product names and prices"

# Dùng Gemini Flash (rẻ và nhanh)
python main.py ai https://example.com \
  --provider gemini/gemini-2.0-flash \
  --api-key AIza...
```

## Viết schema CSS

```json
{
  "name": "My schema",
  "baseSelector": "div.product",
  "fields": [
    {"name": "title",  "selector": "h2",         "type": "text"},
    {"name": "price",  "selector": "span.price",  "type": "text"},
    {"name": "url",    "selector": "a",           "type": "attribute", "attribute": "href"},
    {"name": "image",  "selector": "img",         "type": "attribute", "attribute": "src"}
  ]
}
```

`baseSelector` chọn element lặp lại (ví dụ `div.product`). Mỗi field trong `fields` là một selector tương đối bên trong element đó.

## Viết schema AI

```json
{
  "type": "object",
  "properties": {
    "name":  {"type": "string", "description": "Product name"},
    "price": {"type": "string", "description": "Price with currency"},
    "rating":{"type": "number", "description": "Star rating from 1 to 5"}
  }
}
```

Đây là Pydantic/JSON Schema chuẩn. LLM sẽ cố map nội dung trang sang đúng kiểu dữ liệu này.
