"""Validate generated search index sizes and event counts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IndexSpec:
    filename: str
    label: str
    min_events: int
    max_events: int
    max_json_mb: float
    max_js_mb: float | None = None


DEFAULT_SPECS = [
    IndexSpec("search-data.json", "Polymarket active", 3000, 8000, 12, 12),
    IndexSpec("search-data-archived.json", "Polymarket archived", 5000, 25000, 12, 12),
    IndexSpec("search-data-kalshi.json", "Kalshi active", 4000, 15000, 16, 16),
    IndexSpec("search-data-kalshi-archived.json", "Kalshi archived", 10000, 30000, 30, 30),
]


def mb(size: int) -> float:
    return size / 1024 / 1024


def event_count(data: dict[str, Any]) -> int:
    value = data.get("n")
    if isinstance(value, int):
        return value
    docs = data.get("docs")
    if isinstance(docs, list):
        return len(docs)
    return 0


def check_index(root: Path, spec: IndexSpec) -> tuple[dict[str, Any], list[str]]:
    path = root / spec.filename
    errors: list[str] = []
    result: dict[str, Any] = {
        "label": spec.label,
        "file": spec.filename,
        "events": 0,
        "json_mb": 0.0,
        "js_mb": None,
    }

    if not path.exists():
        return result, [f"{spec.label}: missing {path}"]

    size_mb = mb(path.stat().st_size)
    result["json_mb"] = size_mb
    if size_mb > spec.max_json_mb:
        errors.append(
            f"{spec.label}: {spec.filename} is {size_mb:.2f} MB; max is {spec.max_json_mb:.2f} MB"
        )

    with path.open() as f:
        data = json.load(f)
    count = event_count(data)
    result["events"] = count
    if count < spec.min_events:
        errors.append(
            f"{spec.label}: indexed {count} events; expected at least {spec.min_events}"
        )
    if count > spec.max_events:
        errors.append(
            f"{spec.label}: indexed {count} events; expected at most {spec.max_events}"
        )

    js_path = path.with_suffix(".js")
    if js_path.exists():
        js_size_mb = mb(js_path.stat().st_size)
        result["js_mb"] = js_size_mb
        max_js_mb = spec.max_js_mb or spec.max_json_mb
        if js_size_mb > max_js_mb:
            errors.append(
                f"{spec.label}: {js_path.name} is {js_size_mb:.2f} MB; max is {max_js_mb:.2f} MB"
            )

    return result, errors


def check_all(root: Path, specs: list[IndexSpec] = DEFAULT_SPECS) -> tuple[list[dict[str, Any]], list[str]]:
    results = []
    errors = []
    for spec in specs:
        result, index_errors = check_index(root, spec)
        results.append(result)
        errors.extend(index_errors)
    return results, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="public", help="Directory containing generated index files")
    args = parser.parse_args()

    results, errors = check_all(Path(args.root))
    for result in results:
        js_text = ""
        if result["js_mb"] is not None:
            js_text = f", js={result['js_mb']:.2f} MB"
        print(
            f"{result['label']}: events={result['events']}, json={result['json_mb']:.2f} MB{js_text}"
        )

    if errors:
        print("\nIndex health check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        raise SystemExit(1)

    print("Index health check passed.")


if __name__ == "__main__":
    main()
