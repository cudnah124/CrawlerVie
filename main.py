"""
Root entry point — forwards to crawlerai.cli.main.

Allows running the CLI directly without installing the package:

    python main.py llm   https://example.com --instruction "Extract products"
    python main.py schema https://example.com --schema schemas/example.json
    python main.py gen   https://example.com --query "product names and prices"
    python main.py nhatot https://www.nhatot.com/.../131328316.htm

For the full CLI reference:
    python main.py --help

After `pip install -e ".[cli]"`, you can also use the `crawlerai` command directly:
    crawlerai --help
"""
from crawlerai.cli.main import cli

if __name__ == "__main__":
    cli()
