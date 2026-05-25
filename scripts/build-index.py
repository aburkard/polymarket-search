"""Build the search index from Polymarket's Gamma API.

Fetches all active events, filters closed/dead markets, tokenizes,
builds an inverted index with IDF, and writes public/search-data.json.

Can also run against a local snapshot file for development:
    python scripts/build-index.py --local data/events_active.jsonl
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://gamma-api.polymarket.com"
OUT = Path(__file__).parent.parent / "public" / "search-data.json"

USER_AGENT = "polymarket-search-indexer/0.1 (andrewburkard@gmail.com)"


def tokenize(text: str) -> list[str]:
    text = text.lower()
    text = text.replace("$", "").replace("%", "").replace(",", "")
    text = re.sub(r"[^a-z0-9.]", " ", text)
    tokens = text.split()
    tokens = [t.strip(".") for t in tokens]
    return [t for t in tokens if len(t) >= 2]


def fetch_all_events() -> list[dict]:
    events = []
    offset = 0
    while True:
        qs = urllib.parse.urlencode({
            "active": "true",
            "closed": "false",
            "limit": 500,
            "offset": offset,
        })
        url = f"{BASE}/events?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                page = json.loads(resp.read())
        except Exception as e:
            print(f"  ERROR at offset={offset}: {e}", file=sys.stderr)
            if not events:
                raise
            print(f"  Stopping early with {len(events)} events", file=sys.stderr)
            break

        if not isinstance(page, list) or not page:
            break

        events.extend(page)
        print(f"  fetched offset={offset} got={len(page)} total={len(events)}")

        if len(page) < 500:
            break
        offset += 500

    return events


def load_local_events(path: str) -> list[dict]:
    events = []
    with open(path) as f:
        for line in f:
            events.append(json.loads(line))
    return events


def parse_outcome_prices(raw: str | None) -> list[float]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return [round(float(p), 4) for p in parsed]
    except (json.JSONDecodeError, ValueError, TypeError):
        return []


def build_index(events: list[dict]) -> dict:
    docs = []
    idx: dict[str, list[int]] = {}
    df: dict[str, int] = {}

    for ev in events:
        event_title = ev.get("title", "")
        event_slug = ev.get("slug", "")
        tag_labels = " ".join(
            t.get("label", "") if isinstance(t, dict) else str(t)
            for t in (ev.get("tags") or [])
        )

        for m in ev.get("markets") or []:
            if m.get("closed"):
                continue
            vol = float(m.get("volume") or 0)
            vol24 = float(m.get("volume24hr") or 0)
            if vol == 0 and vol24 == 0:
                continue

            doc_idx = len(docs)

            question = m.get("question", "")
            text = f"{question} {event_title} {tag_labels}"
            terms = set(tokenize(text))

            for t in terms:
                if t not in idx:
                    idx[t] = []
                idx[t].append(doc_idx)
                df[t] = df.get(t, 0) + 1

            docs.append({
                "q": question,
                "s": m.get("slug", ""),
                "es": event_slug,
                "ed": (m.get("endDate") or "")[:10],
                "im": m.get("image", ""),
                "op": parse_outcome_prices(m.get("outcomePrices")),
                "v": round(vol24),
                "vt": round(vol),
                "tg": tag_labels[:100],
            })

    n = len(docs)
    idf = {}
    for term, freq in df.items():
        idf[term] = round(math.log(n / freq), 4)

    return {
        "v": 1,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n": n,
        "idf": idf,
        "idx": idx,
        "docs": docs,
    }


def main():
    local_path = None
    if "--local" in sys.argv:
        i = sys.argv.index("--local")
        if i + 1 < len(sys.argv):
            local_path = sys.argv[i + 1]

    print("Building search index...")

    if local_path:
        print(f"  Loading from local file: {local_path}")
        events = load_local_events(local_path)
    else:
        print("  Fetching from Polymarket API...")
        events = fetch_all_events()

    print(f"  Total events: {len(events)}")

    data = build_index(events)
    print(f"  Indexed: {data['n']} markets, {len(data['idf'])} unique terms")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, separators=(",", ":"))
    OUT.write_text(raw)

    size_mb = len(raw) / 1024 / 1024
    print(f"  Written: {OUT} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
