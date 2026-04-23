"""
crawlerai — Lightweight web crawling library.

Two core modes:
  - LLM crawling:    AI understands and extracts data without selectors
  - Schema crawling: CSS selector schema for fast, free, deterministic extraction

Site-specific crawlers:
  - crawlerai.sites.nhatot — NhaTot.com real estate ads

Quick start::

    import asyncio
    from crawlerai import crawl_llm, crawl_schema, generate_schema

    # LLM extraction (needs API key)
    results = asyncio.run(crawl_llm(
        url="https://quotes.toscrape.com",
        instruction="Extract all quotes and author names",
    ))

    # CSS schema extraction (free, deterministic)
    results = asyncio.run(crawl_schema(
        url="https://quotes.toscrape.com",
        schema={
            "name": "Quotes",
            "baseSelector": ".quote",
            "fields": [
                {"name": "text",   "selector": ".text",   "type": "text"},
                {"name": "author", "selector": ".author", "type": "text"},
            ],
        },
    ))

    # Auto-generate a schema once, reuse forever
    schema = asyncio.run(generate_schema(
        url="https://example.com/listings",
        query="product names, prices, and links",
        save_to="schemas/example_css.json",
    ))
"""

from crawlerai.__version__ import __version__
from crawlerai.strategies.llm_strategy import crawl_llm
from crawlerai.strategies.schema_strategy import crawl_schema
from crawlerai.schema_gen.generator import generate_schema
from crawlerai.exporters.csv_exporter import export_to_csv

__all__ = [
    "crawl_llm",
    "crawl_schema",
    "generate_schema",
    "export_to_csv",
]

# version is imported from __version__.py above
