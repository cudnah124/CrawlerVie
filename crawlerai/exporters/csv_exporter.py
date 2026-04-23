"""
crawlerai.exporters.csv_exporter — Write a list of dicts to CSV.

Design notes:
- utf-8-sig encoding so Excel opens the file correctly without manual BOM.
- Nested dicts/lists are JSON-stringified rather than silently dropped.
- fieldnames are inferred from the union of all row keys, preserving insertion
  order, so sparse rows don't shift columns around.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def export_to_csv(
    data: list[dict[str, Any]],
    output_path: str | Path | None = None,
    fieldnames: list[str] | None = None,
) -> Path:
    """
    Write *data* to a CSV file and return the resolved path.

    Args:
        data:        Rows to write — each must be a dict.
        output_path: Destination file. Auto-generated with a timestamp if None.
        fieldnames:  Column order. Inferred from *data* keys if not provided.

    Returns:
        :class:`pathlib.Path` pointing to the written file.

    Raises:
        ValueError: If *data* is empty or contains no usable rows.
    """
    rows = [r for r in data if isinstance(r, dict)]
    if not rows:
        raise ValueError("No usable rows to export (data is empty or contains no dicts).")

    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path("output") / f"crawl_{ts}.csv"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fieldnames is None:
        fieldnames = _collect_fieldnames(rows)

    flat_rows = [_flatten_row(r) for r in rows]

    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_rows)

    print(f"Exported {len(flat_rows)} rows → {output_path}")
    return output_path


# ── helpers ───────────────────────────────────────────────────────────────────

def _collect_fieldnames(rows: list[dict]) -> list[str]:
    """Return ordered union of all keys across every row."""
    seen: set[str] = set()
    keys: list[str] = []
    for row in rows:
        for k in row:
            if k not in seen:
                keys.append(k)
                seen.add(k)
    return keys


def _flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    """Serialize nested values so csv.DictWriter doesn't choke on them."""
    return {
        k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        for k, v in row.items()
    }
