"""Enrich events with LLM-generated search aliases.

Reads the search index, finds events without aliases, calls the LLM
to generate them, and writes an enrichment file that the index builder
can merge in.

Usage:
    python scripts/enrich.py                    # enrich all unenriched events
    python scripts/enrich.py --limit 50         # enrich up to 50 events
    python scripts/enrich.py --model google/gemini-3.1-pro-preview
    python scripts/enrich.py --dry-run          # show what would be enriched
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENRICHMENT_FILE = ROOT / "data" / "enrichments.jsonl"
INDEX_FILE = ROOT / "public" / "search-data.json"

DEFAULT_MODEL = "google/gemini-3.1-pro-preview"

SYSTEM_PROMPT = """You help people find prediction markets by generating search aliases.

A user might search for this event using words that DON'T appear in the event text at all. Your job: figure out what those missing words are.

Think about:
1. ABBREVIATIONS someone would type: ticker symbols, acronyms, initialisms
2. NICKNAMES and alternate names
3. HOW someone might DESCRIBE this topic using completely different words
4. PEOPLE involved who aren't named in the text — use the context description to find these

Rules:
- SKIP any word already in the title, market questions, or tags — only add what's MISSING
- 1-3 words per alias, 8-15 aliases total
- Be specific to THIS event, not generic"""

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "search_aliases",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "aliases": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["aliases"],
            "additionalProperties": False,
        },
    },
}


def get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("OPENROUTER_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    return key


def load_existing_enrichments() -> dict[str, list[str]]:
    enrichments: dict[str, list[str]] = {}
    if ENRICHMENT_FILE.exists():
        for line in ENRICHMENT_FILE.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            enrichments[entry["slug"]] = entry["aliases"]
    return enrichments


def load_events_from_snapshot() -> list[dict]:
    snapshot = ROOT / "data" / "events_active.jsonl"
    if not snapshot.exists():
        print(f"No snapshot at {snapshot}. Run build-index.py first.", file=sys.stderr)
        sys.exit(1)
    events = []
    with snapshot.open() as f:
        for line in f:
            events.append(json.loads(line))
    return events


def build_user_message(ev: dict) -> str:
    title = ev.get("title", "")
    tags = " ".join(
        t.get("label", "") if isinstance(t, dict) else str(t)
        for t in (ev.get("tags") or [])
    )
    markets = ev.get("markets") or []
    active = [m for m in markets if not m.get("closed")]
    market_qs = [m.get("question", "") for m in active[:10]]
    context = (ev.get("eventMetadata") or {}).get("context_description", "")

    parts = [f"Event: {title}"]
    if tags:
        parts.append(f"Tags: {tags}")
    if market_qs:
        parts.append("Markets:\n" + "\n".join(f"- {q}" for q in market_qs))
    if context:
        parts.append(f"Context: {context}")
    return "\n".join(parts)


def call_llm(user_msg: str, model: str, api_key: str) -> list[str]:
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 1.0,
        "max_tokens": 4096,
        "response_format": SCHEMA,
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return [str(a).lower().strip() for a in parsed.get("aliases", []) if a]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key and not args.dry_run:
        print("No OPENROUTER_API_KEY found", file=sys.stderr)
        sys.exit(1)

    existing = load_existing_enrichments()
    print(f"Existing enrichments: {len(existing)}")

    events = load_events_from_snapshot()
    print(f"Total events in snapshot: {len(events)}")

    to_enrich = []
    for ev in events:
        slug = ev.get("slug", "")
        if not slug:
            continue
        if slug in existing:
            continue
        active = [m for m in (ev.get("markets") or []) if not m.get("closed")]
        vol = sum(float(m.get("volume") or 0) for m in active)
        vol24 = sum(float(m.get("volume24hr") or 0) for m in active)
        if vol == 0 and vol24 == 0:
            continue
        to_enrich.append(ev)

    to_enrich.sort(
        key=lambda e: sum(float(m.get("volume") or 0) for m in (e.get("markets") or [])),
        reverse=True,
    )

    if args.limit:
        to_enrich = to_enrich[:args.limit]

    print(f"Events to enrich: {len(to_enrich)}")

    if args.dry_run:
        for ev in to_enrich[:20]:
            print(f"  {ev.get('slug', '')[:50]}")
        if len(to_enrich) > 20:
            print(f"  ... +{len(to_enrich) - 20} more")
        return

    print(f"Model: {args.model}")
    print()

    ENRICHMENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    succeeded = 0
    failed = 0
    t0 = time.time()

    with ENRICHMENT_FILE.open("a") as f:
        for i, ev in enumerate(to_enrich):
            slug = ev.get("slug", "")
            title = ev.get("title", "")
            try:
                user_msg = build_user_message(ev)
                aliases = call_llm(user_msg, args.model, api_key)
                entry = {"slug": slug, "aliases": aliases, "model": args.model}
                f.write(json.dumps(entry) + "\n")
                f.flush()
                succeeded += 1
                print(f"  [{i+1}/{len(to_enrich)}] {title[:50]} → {len(aliases)} aliases")
            except Exception as e:
                failed += 1
                print(f"  [{i+1}/{len(to_enrich)}] {title[:50]} → ERROR: {e}")
                time.sleep(2)

            if (i + 1) % 50 == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (len(to_enrich) - i - 1) / rate if rate > 0 else 0
                print(f"  --- {i+1} done, {rate:.1f}/s, ETA {eta/60:.0f}m ---")

    elapsed = time.time() - t0
    print(f"\nDone: {succeeded} enriched, {failed} failed, {elapsed:.0f}s")


if __name__ == "__main__":
    main()
