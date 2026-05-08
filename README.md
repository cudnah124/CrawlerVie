# 🚀🤖 crawlerAI: CLI-first Web Scraper with AI Support & Site-Specific Logic.

<div align="center">

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Powered by Crawl4AI](https://img.shields.io/badge/Powered%20by-Crawl4AI-orange)](https://github.com/unclecode/crawl4ai)

---

**crawlerAI** turns any website into clean, structured CSV data. Whether you need the power of **LLMs** for unstructured pages or the speed of **CSS selectors** for scale, crawlerAI has you covered. Built on top of the battle-tested Crawl4AI engine with added "secret sauce" for challenging sites.

</div>

---

<details>
  <summary>💡 <strong>Why use crawlerAI?</strong></summary>

- **AI-Native Extraction**: Extract data using natural language instructions. No more Inspect Element.
- **Hybrid Performance**: Switch between AI (intelligent) and CSS (fast) modes seamlessly.
- **Site-Specific Superpowers**: Specialized modules for complex sites like **NhaTot.com** (reveals hidden phone numbers, parses internal JSON).
- **Stealth by Default**: Integrated anti-bot bypass, user simulation, and proxy support.
- **Excel-Ready Export**: One-click CSV output with proper UTF-8-BOM encoding for perfect Vietnamese font support.
</details>

## 🚀 Quick Start

1. **Clone and Install**:

```bash
git clone https://github.com/your-repo/crawlerAI.git
cd crawlerAI

# Install dependencies
pip install -r requirements.txt

# Setup Playwright browsers
playwright install chromium
```

2. **Setup Environment**:

```bash
cp .env.example .env
# Add your OPENAI_API_KEY or GEMINI_API_KEY
```

3. **Run your first crawl**:

```bash
# AI Mode: Just describe what you want
crawlerai llm https://news.ycombinator.com --instruction "Extract titles and URLs of all stories"

# CSS Mode: Fast and repeatable
crawlerai schema https://news.ycombinator.com --schema schemas/hackernews_css.json
```

## ✨ Core Features

<details>
<summary>🤖 <strong>AI-Driven Extraction</strong></summary>

- **Instruction-Based**: Pass natural language prompts like "Extract all property prices and area" to the LLM.
- **Multi-Provider Support**: Works with OpenAI, Gemini (Flash recommended), Anthropic, OpenRouter, and Ollama (local).
- **Markdown Optimization**: Uses `fit_markdown` to strip noise and reduce token costs by up to 80%.
</details>

<details>
<summary>🔎 <strong>Traditional CSS Mode</strong></summary>

- **Deterministic & Free**: Zero LLM costs. Sub-second extraction for high-volume tasks.
- **Advanced Schemas**: Supports nested fields, lists, and attribute extraction.
- **Schema-Gen Utility**: Use the `schema-gen` mode to let AI write the CSS selectors once, then run them indefinitely for free.
</details>

<details>
<summary>🏠 <strong>Specialized: NhaTot.com Scraper</strong></summary>

- **Phone Reveal Technology**: Automatically clicks and interacts with "Show Phone" buttons using a multi-strategy approach.
- ****NEXT_DATA** Parsing**: Directly extracts deeply nested JSON objects from the site's internal state for 100% accuracy.
- **Captcha Awareness**: Detects and asks for manual intervention when Cloudflare checks appear.
</details>

<details>
<summary>🛡️ <strong>Anti-Bot & Stealth</strong></summary>

- **Playwright Stealth**: Mimics real browser behavior to bypass basic detection.
- **Magic Mode**: Crawl4AI's "magic" flags enabled for challenging Cloudflare protected sites.
- **Proxy Support**: Route requests through residential proxies using the `--proxy` flag.
</details>

## 🔬 Usage Examples

<details>
<summary>📝 <strong>Generate a CSS Schema automatically</strong></summary>

Dont want to write JSON selectors? Let the LLM do it once:

```bash
crawlerai gen https://example.com/listings \
  --query "All product names, prices and image links" \
  --save-to schemas/my_new_site.json
```

</details>

<details>
<summary>🏠 <strong>Scraping Real Estate (NhaTot)</strong></summary>

Get all details including the hidden seller phone number:

```bash
# Single ad
crawlerai nhatot https://www.nhatot.com/.../ad_id.htm

# Listing page (scrapes multiple)
crawlerai nhatot-list https://www.nhatot.com/mua-ban-bat-dong-san --limit 20
```

</details>

<details>
<summary>🛠️ <strong>Wait for dynamic content (SPA)</strong></summary>

For React/Vue sites that need time to render:

```bash
crawlerai schema https://myspa.com --wait-for "div.results-list"
```

</details>

## 📦 Run Example: Crawl NhaTot.com to CSV

You can run the included example script to crawl NhaTot.com listings and export to CSV:

```bash
cd examples/nhatot
python example_crawl_nhatot.py
```

**Parameters in the script:**

- `URL`: The listing page to crawl (default: TP.HCM real estate)
- `FILE_NAME`: Output CSV file name
- `LIMIT`: Max number of listings to crawl
- `BATCH`: Number of concurrent tabs per batch
- `MAX_PAGES`: Max pages to scan

You can edit these parameters at the top of `examples/nhatot/example_crawl_nhatot.py`.

> The script will automatically reveal phone numbers, parse all details, and export a clean CSV ready for analysis.

---

> **💡 Pro Tip:** Use `gemini/gemini-2.0-flash` as your provider for the best speed/cost ratio in AI mode. It's incredibly fast and well-supported by crawlerAI!

## 🤝 Contributing

We welcome contributions! Feel free to open issues or PRs for new site-specific modules or generic crawler improvements.

---

<div align="center">
Built with ❤️ by the DM Research Team. Powered by <a href="https://github.com/unclecode/crawl4ai">Crawl4AI</a>.
</div>
