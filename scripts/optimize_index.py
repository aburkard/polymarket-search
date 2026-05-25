"""Post-process search-data.json to minimize file size.

Optimizations:
1. Strip common image URL prefix
2. Drop outcome 'q' (question) when 'l' (label) exists
3. Drop 'tg' (tags) from docs — indexed but not displayed
4. Reduce IDF precision to 2 decimal places
5. Drop '_n_enriched' metadata key
6. Drop outcome 'v' (24h volume) — not displayed
"""

from __future__ import annotations

import json
from pathlib import Path

IMG_PREFIX = "https://polymarket-upload.s3.us-east-2.amazonaws.com/"
INDEX_FILE = Path(__file__).parent.parent / "public" / "search-data.json"


def optimize():
    raw = INDEX_FILE.read_text()
    data = json.loads(raw)
    original_size = len(raw)

    # Store prefix for frontend reconstruction
    data["imgPfx"] = IMG_PREFIX

    # Strip image prefix from docs and outcomes
    for doc in data["docs"]:
        if doc.get("im", "").startswith(IMG_PREFIX):
            doc["im"] = doc["im"][len(IMG_PREFIX):]

        # Strip tags — indexed but not displayed
        doc.pop("tg", None)

        for mk in doc.get("mk", []):
            # Strip outcome question when label exists
            if mk.get("l"):
                mk.pop("q", None)

            # Strip outcome 24h volume — not displayed
            mk.pop("v", None)

            # Strip outcome image prefix
            if mk.get("im", "").startswith(IMG_PREFIX):
                mk["im"] = mk["im"][len(IMG_PREFIX):]

        # Strip team logo prefix
        for tm in doc.get("tm", []):
            if tm.get("l", "").startswith(IMG_PREFIX):
                tm["l"] = tm["l"][len(IMG_PREFIX):]

    # Reduce IDF precision
    data["idf"] = {k: round(v, 2) for k, v in data["idf"].items()}

    # Delta-encode and pack postings as strings
    for tier in ("idx", "ctx"):
        if tier not in data:
            continue
        packed = {}
        for term, postings in data[tier].items():
            parts = []
            prev = 0
            for doc_idx, tf in postings:
                delta = doc_idx - prev
                prev = doc_idx
                if tf == 1:
                    parts.append(str(delta))
                else:
                    parts.append(f"{delta}:{tf}")
            packed[term] = ",".join(parts)
        data[tier] = packed

    # Drop metadata
    data.pop("_n_enriched", None)

    optimized = json.dumps(data, separators=(",", ":"))

    # Write as JS literal for streaming parse
    js_path = INDEX_FILE.parent / "search-data.js"
    js_content = f"self.__SD__={optimized};"
    js_path.write_text(js_content)

    # Also write JSON for backwards compat / debugging
    INDEX_FILE.write_text(optimized)

    new_size = len(js_content)
    saved = original_size - len(optimized)
    print(f"Original: {original_size / 1024 / 1024:.2f} MB")
    print(f"Optimized: {len(optimized) / 1024 / 1024:.2f} MB")
    print(f"JS literal: {new_size / 1024 / 1024:.2f} MB")
    print(f"Saved: {saved / 1024:.0f} KB ({saved / original_size * 100:.1f}%)")


if __name__ == "__main__":
    optimize()
