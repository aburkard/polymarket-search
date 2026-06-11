"""Enrich events with LLM-generated search aliases.

Reads the search index, finds events without aliases, calls the LLM
to generate them, and writes an enrichment file that the index builder
can merge in.

Usage:
    python scripts/enrich.py                    # enrich all unenriched events
    python scripts/enrich.py --provider kalshi  # enrich Kalshi events
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
PROVIDER_CONFIG = {
    "polymarket": {
        "enrichment_file": ROOT / "data" / "enrichments.jsonl",
        "snapshot": ROOT / "data" / "events_active.jsonl",
    },
    "kalshi": {
        "enrichment_file": ROOT / "data" / "kalshi_enrichments.jsonl",
        "snapshot": ROOT / "data" / "kalshi_events_open.jsonl",
    },
}

DEFAULT_MODEL = "deepseek/deepseek-v4-pro"

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


def load_existing_enrichments(path: Path) -> dict[str, list[str]]:
    enrichments: dict[str, list[str]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            enrichments[entry["slug"]] = entry["aliases"]
    return enrichments


def load_events_from_snapshot(snapshot: Path) -> list[dict]:
    if not snapshot.exists():
        print(f"No snapshot at {snapshot}. Run the provider build first.", file=sys.stderr)
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


def kalshi_slug(ev: dict) -> str:
    return (ev.get("event_ticker") or ev.get("slug") or "").lower()


def is_closed_market(market: dict) -> bool:
    status = (market.get("status") or "").lower()
    return bool(market.get("closed")) or status in {"closed", "settled", "expired", "finalized"}


def market_volume(market: dict) -> float:
    for key in ("volume", "volume_fp"):
        value = market.get(key)
        if value not in (None, ""):
            return float(value or 0)
    return 0.0


def market_volume_24h(market: dict) -> float:
    for key in ("volume24hr", "volume_24h_fp"):
        value = market.get(key)
        if value not in (None, ""):
            return float(value or 0)
    return 0.0


def event_slug(ev: dict, provider: str) -> str:
    if provider == "kalshi":
        return kalshi_slug(ev)
    return ev.get("slug", "")


def active_markets(ev: dict) -> list[dict]:
    return [m for m in (ev.get("markets") or []) if not is_closed_market(m)]


def event_volume(ev: dict) -> float:
    return sum(market_volume(m) for m in active_markets(ev))


def event_volume_24h(ev: dict) -> float:
    return sum(market_volume_24h(m) for m in active_markets(ev))


def build_kalshi_user_message(ev: dict) -> str:
    title = ev.get("title", "")
    category = ev.get("category", "")
    sub_title = ev.get("sub_title", "")
    markets = active_markets(ev)
    market_lines = []
    for m in markets[:12]:
        label = m.get("yes_sub_title") or m.get("subtitle") or m.get("title") or ""
        question = m.get("title") or ""
        if label and question and label != question:
            market_lines.append(f"- {label}: {question}")
        elif question:
            market_lines.append(f"- {question}")

    parts = [f"Event: {title}"]
    if sub_title:
        parts.append(f"Subtitle: {sub_title}")
    if category:
        parts.append(f"Category: {category}")
    if market_lines:
        parts.append("Markets:\n" + "\n".join(market_lines))
    return "\n".join(parts)


def user_message(ev: dict, provider: str) -> str:
    if provider == "kalshi":
        return build_kalshi_user_message(ev)
    return build_user_message(ev)


def call_llm(user_msg: str, model: str, api_key: str) -> list[str]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 1.0,
        "max_tokens": 4096,
        "response_format": SCHEMA,
    }
    # DeepSeek models enable reasoning by default; disable for speed + cost.
    if model.startswith("deepseek/"):
        body["reasoning"] = {"enabled": False}
    payload = json.dumps(body).encode()

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
    parser.add_argument("--provider", choices=sorted(PROVIDER_CONFIG), default="polymarket")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key and not args.dry_run:
        print("No OPENROUTER_API_KEY found", file=sys.stderr)
        sys.exit(1)

    cfg = PROVIDER_CONFIG[args.provider]
    enrichment_file = cfg["enrichment_file"]
    existing = load_existing_enrichments(enrichment_file)
    print(f"Existing enrichments: {len(existing)}")

    events = load_events_from_snapshot(cfg["snapshot"])
    print(f"Total events in snapshot: {len(events)}")

    to_enrich = []
    for ev in events:
        slug = event_slug(ev, args.provider)
        if not slug:
            continue
        if slug in existing:
            continue
        vol = event_volume(ev)
        vol24 = event_volume_24h(ev)
        if vol == 0 and vol24 == 0:
            continue
        to_enrich.append(ev)

    to_enrich.sort(
        key=event_volume,
        reverse=True,
    )

    if args.limit:
        to_enrich = to_enrich[:args.limit]

    print(f"Events to enrich: {len(to_enrich)}")

    if args.dry_run:
        for ev in to_enrich[:20]:
            print(f"  {event_slug(ev, args.provider)[:50]} {ev.get('title', '')[:80]}")
        if len(to_enrich) > 20:
            print(f"  ... +{len(to_enrich) - 20} more")
        return

    print(f"Model: {args.model}")
    print()

    enrichment_file.parent.mkdir(parents=True, exist_ok=True)
    succeeded = 0
    failed = 0
    consecutive_failures = 0
    t0 = time.time()

    with enrichment_file.open("a") as f:
        for i, ev in enumerate(to_enrich):
            slug = event_slug(ev, args.provider)
            title = ev.get("title", "")
            try:
                user_msg = user_message(ev, args.provider)
                aliases = call_llm(user_msg, args.model, api_key)
                entry = {"slug": slug, "aliases": aliases, "model": args.model}
                f.write(json.dumps(entry) + "\n")
                f.flush()
                succeeded += 1
                consecutive_failures = 0
                print(f"  [{i+1}/{len(to_enrich)}] {title[:50]} → {len(aliases)} aliases")
            except Exception as e:
                failed += 1
                consecutive_failures += 1
                print(f"  [{i+1}/{len(to_enrich)}] {title[:50]} → ERROR: {e}")
                if consecutive_failures >= 5:
                    print(f"\nAborting: {consecutive_failures} consecutive failures.")
                    print("Likely API key issue or model access denied. Check OPENROUTER_API_KEY.")
                    sys.exit(1)
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
