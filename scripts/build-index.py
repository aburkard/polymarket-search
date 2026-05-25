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
            "limit": 100,
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

        if len(page) < 100:
            break
        offset += 100

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


def _outcome_tier(m: dict, event_title: str) -> int:
    git = (m.get("groupItemTitle") or "").strip()
    q = m.get("question", "")
    if not git or git == event_title or q == event_title:
        return 0  # moneyline
    gl = git.lower()
    if gl.startswith("spread") and "1h" not in gl:
        return 1
    if gl.startswith("o/u") and "1h" not in gl:
        return 2
    if gl.startswith("1h"):
        return 3
    if gl.startswith("team to"):
        return 4
    if ":" in gl:
        return 6  # player props
    return 5


def _closeness_to_even(m: dict) -> float:
    prices = parse_outcome_prices(m.get("outcomePrices"))
    if not prices:
        return 1.0
    return abs(prices[0] - 0.5)


def pick_sports_outcomes(markets: list[dict], event_title: str) -> list[dict]:
    by_tier: dict[int, list[dict]] = {}
    for m in markets:
        tier = _outcome_tier(m, event_title)
        if tier >= 6:
            continue
        by_tier.setdefault(tier, []).append(m)

    picked: list[dict] = []
    for tier in sorted(by_tier):
        candidates = by_tier[tier]
        if tier in (1, 2, 3):
            best = min(candidates, key=_closeness_to_even)
            picked.append(best)
        else:
            candidates.sort(key=lambda m: -float(m.get("volume24hr") or 0))
            picked.append(candidates[0])
        if len(picked) >= 4:
            break
    return picked


STOP_WORDS = {
    "the", "be", "to", "of", "and", "in", "that", "have", "it", "for",
    "not", "on", "with", "he", "as", "you", "do", "at", "this", "but",
    "his", "by", "from", "they", "we", "say", "her", "she", "or", "an",
    "will", "my", "one", "all", "would", "there", "their", "what", "so",
    "up", "out", "if", "about", "who", "get", "which", "go", "me", "when",
    "make", "can", "like", "time", "no", "just", "him", "know", "take",
    "people", "into", "year", "your", "good", "some", "could", "them",
    "see", "other", "than", "then", "now", "look", "only", "come", "its",
    "over", "think", "also", "back", "after", "use", "two", "how", "our",
    "work", "first", "well", "way", "even", "new", "want", "because",
    "any", "these", "give", "day", "most", "us", "has", "been", "had",
    "are", "was", "were", "did", "does", "is", "am", "may", "might",
    "more", "between", "since", "while", "during", "before", "under",
    "through", "against", "both", "each", "few", "those", "own", "same",
    "where", "such", "should", "still", "last", "much", "another",
    "following", "recent", "among", "ahead", "per", "amid", "including",
    "current", "within", "across", "leading", "driven", "expected",
    "according", "based", "around", "however", "despite", "whether",
    "likely", "remains", "continued", "significant", "announced",
    "trader", "traders", "consensus", "probability", "implied",
    "market", "markets", "trading", "volume", "confidence", "pricing",
    "momentum", "sentiment", "activity", "positions", "bets",
}


def load_enrichments() -> dict[str, list[str]]:
    path = Path(__file__).parent.parent / "data" / "enrichments.jsonl"
    enrichments: dict[str, list[str]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            enrichments[entry["slug"]] = entry["aliases"]
    return enrichments


def build_index(events: list[dict]) -> dict:
    docs = []
    idx: dict[str, list] = {}
    ctx: dict[str, list] = {}
    df: dict[str, int] = {}
    doc_lens: list[int] = []
    enrichments = load_enrichments()
    n_enriched = 0

    for ev in events:
        event_title = ev.get("title", "")
        event_slug = ev.get("slug", "")
        tag_labels = " ".join(
            t.get("label", "") if isinstance(t, dict) else str(t)
            for t in (ev.get("tags") or [])
        )

        active_markets = []
        for m in ev.get("markets") or []:
            if m.get("closed"):
                continue
            vol = float(m.get("volume") or 0)
            vol24 = float(m.get("volume24hr") or 0)
            if vol == 0 and vol24 == 0:
                continue
            active_markets.append(m)

        if not active_markets:
            continue

        doc_idx = len(docs)

        market_questions = " ".join(m.get("question", "") for m in active_markets)
        base_text = f"{event_title} {market_questions} {tag_labels}"
        base_tokens = tokenize(base_text)
        base_terms = set(base_tokens)

        base_tf: dict[str, int] = {}
        for t in base_tokens:
            base_tf[t] = base_tf.get(t, 0) + 1
        doc_lens.append(len(base_tokens))

        context_raw = (ev.get("eventMetadata") or {}).get("context_description", "")
        context_tokens = tokenize(context_raw)
        context_terms = set(context_tokens) - base_terms - STOP_WORDS

        ctx_tf: dict[str, int] = {}
        for t in context_tokens:
            if t in context_terms:
                ctx_tf[t] = ctx_tf.get(t, 0) + 1

        llm_aliases = enrichments.get(event_slug, [])
        if llm_aliases:
            n_enriched += 1
        for alias in llm_aliases:
            for t in tokenize(alias):
                if t not in base_terms:
                    context_terms.add(t)
                    ctx_tf[t] = ctx_tf.get(t, 0) + 1

        for t in base_terms:
            if t not in idx:
                idx[t] = []
            idx[t].append([doc_idx, base_tf[t]])
            df[t] = df.get(t, 0) + 1

        for t in context_terms:
            if t not in ctx:
                ctx[t] = []
            ctx[t].append([doc_idx, ctx_tf.get(t, 1)])
            df[t] = df.get(t, 0) + 1

        total_vol24 = sum(float(m.get("volume24hr") or 0) for m in active_markets)
        total_vol = sum(float(m.get("volume") or 0) for m in active_markets)

        is_sports = bool(ev.get("sport") or ev.get("teams"))

        is_temporal = (
            ("by" in event_title.lower() and ("...?" in event_title or "___" in event_title))
            and len(active_markets) >= 2
            and any(m.get("groupItemThreshold") is not None for m in active_markets)
        )

        if is_sports:
            top_markets = pick_sports_outcomes(active_markets, event_title)
        elif is_temporal:
            top_markets = sorted(
                active_markets,
                key=lambda m: float(m.get("groupItemThreshold") or 999),
            )[:5]
        else:
            top_markets = sorted(
                active_markets,
                key=lambda m: (parse_outcome_prices(m.get("outcomePrices")) or [0])[0],
                reverse=True,
            )[:5]

        outcomes = []
        for m in top_markets:
            o = {
                "q": m.get("question", ""),
                "l": m.get("groupItemTitle", ""),
                "op": parse_outcome_prices(m.get("outcomePrices")),
                "v": round(float(m.get("volume24hr") or 0)),
            }
            mimg = m.get("image") or m.get("icon") or ""
            if mimg and mimg != ev.get("image", ""):
                o["im"] = mimg
            outcomes.append(o)

        doc = {
            "q": event_title,
            "s": event_slug,
            "ed": (ev.get("endDate") or "")[:10],
            "im": ev.get("image", ""),
            "v": round(total_vol24),
            "vt": round(total_vol),
            "tg": tag_labels[:100],
            "mc": len(active_markets),
            "mk": outcomes,
        }

        if is_sports:
            teams = ev.get("teams") or []
            if teams:
                doc["tm"] = [
                    {"n": t.get("name", ""), "l": t.get("logo", ""), "r": t.get("record", "")}
                    for t in teams[:2]
                ]
            doc["gd"] = ev.get("eventDate") or ""
            if ev.get("live"):
                doc["live"] = True
                doc["sc"] = ev.get("score", "")
                doc["per"] = ev.get("period", "")

        docs.append(doc)

    n = len(docs)
    avg_dl = sum(doc_lens) / n if n else 0

    idf = {}
    for term, freq in df.items():
        idf[term] = round(math.log((n - freq + 0.5) / (freq + 0.5) + 1), 4)

    result = {
        "v": 3,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n": n,
        "avgDl": round(avg_dl, 2),
        "dl": doc_lens,
        "idf": idf,
        "idx": idx,
        "ctx": ctx,
        "docs": docs,
    }
    result["_n_enriched"] = n_enriched
    return result


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
        snapshot_path = Path(__file__).parent.parent / "data" / "events_active.jsonl"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with snapshot_path.open("w") as f:
            for ev in events:
                f.write(json.dumps(ev, separators=(",", ":")) + "\n")
        print(f"  Saved snapshot: {snapshot_path}")

    print(f"  Total events: {len(events)}")

    data = build_index(events)
    print(f"  Indexed: {data['n']} events, {len(data['idf'])} unique terms, {data.get('_n_enriched', 0)} enriched")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, separators=(",", ":"))
    OUT.write_text(raw)

    size_mb = len(raw) / 1024 / 1024
    print(f"  Written: {OUT} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
