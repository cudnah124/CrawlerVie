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
crawl4ai-setup            # cài Playwright browser (~300MB, chỉ chạy một lần)

cp .env.example .env
# Điền OPENAI_API_KEY vào .env (chỉ cần cho mode 'ai')
```

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
