"""Baseline search experiment: SQLite FTS5 vs Polymarket /public-search.

Builds a local FTS5 index from the snapshot, runs a diverse battery of
realistic queries, and compares top-5 results side by side.

The index combines:
  - market.question (high weight)
  - event.title
  - event tags
  - event.eventMetadata.context_description (LLM summary)
  - market.description (resolution criteria — lower weight)

Ranking: FTS5 bm25() × log1p(volume24hr) × recency_boost(endDate).
Filters: skip closed markets, skip markets with zero all-time volume.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
DB_PATH = DATA / "search_experiment.db"
SNAPSHOT = DATA / "events_active.jsonl"

NOW = datetime.now(timezone.utc)

# ── Realistic query battery ──────────────────────────────────────────────

QUERIES = [
    # Clean, specific
    ("trump 2028", "clean"),
    ("bitcoin price", "clean"),
    ("fed rate cut", "clean"),
    ("world cup winner", "clean"),
    ("iran ceasefire", "clean"),
    ("drake album", "clean"),
    ("gta 6 release", "clean"),
    ("inflation 2026", "clean"),
    ("nba finals", "clean"),
    ("ethereum price", "clean"),
    ("ukraine russia peace", "clean"),
    ("recession 2026", "clean"),

    # Misspellings
    ("trmup", "misspelling"),
    ("bitconi price", "misspelling"),
    ("ceaseifre iran", "misspelling"),
    ("etherium", "misspelling"),
    ("wrold cup", "misspelling"),
    ("intrest rates", "misspelling"),

    # Partial / typing in progress
    ("tru", "partial"),
    ("bitcoi", "partial"),
    ("world cu", "partial"),
    ("fed ra", "partial"),
    ("iran cea", "partial"),
    ("elec", "partial"),

    # Conceptual / indirect
    ("interest rates", "conceptual"),
    ("crypto crash", "conceptual"),
    ("election odds", "conceptual"),
    ("gas prices", "conceptual"),
    ("who will win president", "conceptual"),
    ("stock market crash", "conceptual"),
    ("housing market", "conceptual"),

    # Natural-language questions
    ("will bitcoin hit 100k", "natural"),
    ("will trump win 2028", "natural"),
    ("when will the war end", "natural"),
    ("next fed meeting", "natural"),
    ("will there be a recession", "natural"),

    # Abbreviations / jargon
    ("btc", "abbreviation"),
    ("eth", "abbreviation"),
    ("sol", "abbreviation"),
    ("xrp", "abbreviation"),
    ("fomc", "abbreviation"),
    ("cpi", "abbreviation"),
    ("gdp", "abbreviation"),
    ("nfl draft", "abbreviation"),
]


# ── Build FTS5 index ─────────────────────────────────────────────────────

def build_index():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    c.execute("""
        CREATE TABLE markets (
            market_id TEXT PRIMARY KEY,
            event_id TEXT,
            question TEXT,
            event_title TEXT,
            tags TEXT,
            context_desc TEXT,
            description TEXT,
            slug TEXT,
            event_slug TEXT,
            volume REAL,
            volume24hr REAL,
            liquidity REAL,
            end_date TEXT,
            closed INTEGER,
            image TEXT,
            outcomes TEXT,
            outcome_prices TEXT
        )
    """)

    c.execute("""
        CREATE VIRTUAL TABLE markets_fts USING fts5(
            question,
            event_title,
            tags,
            context_desc,
            description,
            content='markets',
            content_rowid='rowid',
            tokenize='porter unicode61'
        )
    """)

    n_events = 0
    n_markets = 0
    n_skipped_closed = 0
    n_skipped_zero_vol = 0

    with SNAPSHOT.open() as f:
        for line in f:
            ev = json.loads(line)
            n_events += 1
            event_id = str(ev.get("id", ""))
            event_title = ev.get("title", "")
            event_slug = ev.get("slug", "")
            tag_labels = " ".join(
                t.get("label", "") if isinstance(t, dict) else str(t)
                for t in (ev.get("tags") or [])
            )
            meta = ev.get("eventMetadata") or {}
            ctx = meta.get("context_description", "")

            for m in (ev.get("markets") or []):
                mid = str(m.get("id", ""))
                closed = m.get("closed", False)
                vol = float(m.get("volume") or 0)
                vol24 = float(m.get("volume24hr") or 0)

                if closed:
                    n_skipped_closed += 1
                    continue
                if vol == 0 and vol24 == 0:
                    n_skipped_zero_vol += 1
                    continue

                n_markets += 1
                c.execute(
                    "INSERT INTO markets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        mid,
                        event_id,
                        m.get("question", ""),
                        event_title,
                        tag_labels,
                        ctx,
                        m.get("description", ""),
                        m.get("slug", ""),
                        event_slug,
                        vol,
                        vol24,
                        float(m.get("liquidity") or 0),
                        m.get("endDate") or m.get("endDateIso") or "",
                        1 if closed else 0,
                        m.get("image", ""),
                        m.get("outcomes", ""),
                        m.get("outcomePrices", ""),
                    ),
                )

    c.execute("""
        INSERT INTO markets_fts(rowid, question, event_title, tags, context_desc, description)
        SELECT rowid, question, event_title, tags, context_desc, description FROM markets
    """)

    conn.commit()
    print(f"Indexed: {n_events:,} events → {n_markets:,} markets")
    print(f"Skipped: {n_skipped_closed:,} closed, {n_skipped_zero_vol:,} zero-volume")
    return conn


# ── Our search ───────────────────────────────────────────────────────────

def search_fts(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict]:
    c = conn.cursor()

    # Sanitize: remove FTS5 operators from user input
    clean_q = re.sub(r'[^\w\s]', ' ', query).strip()
    if not clean_q:
        return []

    # Build FTS query: try exact phrase first, then individual terms, then prefix
    terms = clean_q.split()

    results = []
    for fts_query in _build_query_variants(terms):
        try:
            c.execute("""
                SELECT
                    m.market_id,
                    m.question,
                    m.event_title,
                    m.slug,
                    m.event_slug,
                    m.volume24hr,
                    m.volume,
                    m.liquidity,
                    m.end_date,
                    m.closed,
                    m.tags,
                    bm25(markets_fts, 10.0, 5.0, 3.0, 3.0, 1.0) as text_score
                FROM markets_fts
                JOIN markets m ON m.rowid = markets_fts.rowid
                WHERE markets_fts MATCH ?
                ORDER BY text_score
                LIMIT 50
            """, (fts_query,))
            rows = c.fetchall()
        except sqlite3.OperationalError:
            continue

        if rows:
            results = rows
            break

    if not results:
        return []

    # Re-rank with volume + recency boost
    scored = []
    for row in results:
        (mid, question, ev_title, slug, ev_slug,
         vol24, vol, liq, end_date, closed, tags, text_score) = row

        # text_score from bm25() is negative (lower = better)
        text_s = -text_score

        # Volume boost: log1p so zero-volume still ranks, high-volume gets a boost
        vol_boost = math.log1p(vol24) + 0.3 * math.log1p(vol)

        # Recency: prefer markets ending sooner (still active)
        recency = 1.0
        if end_date:
            try:
                ed = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                days_out = (ed - NOW).total_seconds() / 86400
                if days_out < 0:
                    recency = 0.3  # past end date
                elif days_out < 7:
                    recency = 2.0
                elif days_out < 30:
                    recency = 1.5
                elif days_out < 90:
                    recency = 1.2
            except Exception:
                pass

        # Liquidity signal
        liq_boost = math.log1p(liq) * 0.2

        final_score = text_s * (1 + vol_boost + liq_boost) * recency
        scored.append({
            "market_id": mid,
            "question": question,
            "event_title": ev_title,
            "slug": slug,
            "event_slug": ev_slug,
            "volume24hr": vol24,
            "volume": vol,
            "end_date": end_date,
            "tags": tags[:80],
            "text_score": round(text_s, 4),
            "final_score": round(final_score, 4),
        })

    scored.sort(key=lambda x: -x["final_score"])
    return scored[:limit]


def _build_query_variants(terms: list[str]) -> list[str]:
    """Generate FTS5 query variants from most specific to most lenient."""
    variants = []

    # 1. All terms together (implicit AND in FTS5)
    if len(terms) > 1:
        variants.append(" ".join(terms))

    # 2. Prefix match on last term (for typing-in-progress)
    if terms:
        prefix_terms = terms[:-1] + [terms[-1] + "*"]
        variants.append(" ".join(prefix_terms))

    # 3. Single term (if multi-word returned nothing)
    if len(terms) == 1:
        variants.append(terms[0])
        variants.append(terms[0] + "*")

    # 4. OR across terms (looser)
    if len(terms) > 1:
        variants.append(" OR ".join(terms))

    return variants


# ── Polymarket /public-search ────────────────────────────────────────────

def search_polymarket(query: str, limit: int = 5) -> list[dict]:
    qs = urllib.parse.urlencode({"q": query, "limit": limit})
    url = f"https://gamma-api.polymarket.com/public-search?{qs}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "polymarket-search-research/0.1 (andrewburkard@gmail.com)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"error": str(e)}]

    results = []
    for ev in (data.get("events") or [])[:limit]:
        markets = ev.get("markets") or []
        top_market = markets[0] if markets else {}
        results.append({
            "event_title": ev.get("title", ""),
            "question": top_market.get("question", ev.get("title", "")),
            "slug": top_market.get("slug", ""),
            "volume24hr": float(top_market.get("volume24hr") or 0),
            "volume": float(top_market.get("volume") or ev.get("volume") or 0),
            "end_date": ev.get("endDate", ""),
            "closed": ev.get("closed"),
        })
    return results


# ── Run the experiment ───────────────────────────────────────────────────

def fmt_result(r: dict, i: int) -> str:
    vol24 = r.get("volume24hr", 0)
    vol_str = f"${vol24:>10,.0f}" if vol24 else "$         0"
    closed = r.get("closed", False)
    end = (r.get("end_date") or "")[:10]
    q = (r.get("question") or r.get("event_title", ""))[:75]
    score = r.get("final_score", "")
    score_str = f" score={score}" if score else ""
    closed_str = " CLOSED" if closed else ""
    return f"  {i+1}. {vol_str} 24h | {end} | {q}{closed_str}{score_str}"


def run_experiment():
    print("Building FTS5 index from snapshot...")
    conn = build_index()
    print()

    categories: dict[str, list] = {}
    for query, cat in QUERIES:
        categories.setdefault(cat, []).append(query)

    total_ours_better = 0
    total_pm_better = 0
    total_tie = 0
    total_ours_has_results = 0
    total_pm_has_results = 0

    for cat, queries in categories.items():
        print()
        print("=" * 78)
        print(f"  Category: {cat.upper()}")
        print("=" * 78)

        for query in queries:
            our_results = search_fts(conn, query, limit=5)
            pm_results = search_polymarket(query, limit=5)
            time.sleep(0.1)  # be polite to PM API

            print(f'\n  Query: "{query}"')
            print(f"  ── Ours (FTS5 + volume + recency) ──")
            if our_results:
                total_ours_has_results += 1
                for i, r in enumerate(our_results):
                    print(fmt_result(r, i))
            else:
                print("  (no results)")

            print(f"  ── Polymarket /public-search ──")
            if pm_results and "error" not in pm_results[0]:
                total_pm_has_results += 1
                for i, r in enumerate(pm_results):
                    print(fmt_result(r, i))
            else:
                print(f"  (no results / error)")

            # Simple quality heuristic: does our #1 have higher 24h volume
            # than their #1? (Active, high-volume = more relevant for a live market)
            our_top_vol = our_results[0]["volume24hr"] if our_results else 0
            pm_top_vol = pm_results[0].get("volume24hr", 0) if pm_results and "error" not in pm_results[0] else 0
            pm_top_closed = pm_results[0].get("closed", False) if pm_results and "error" not in pm_results[0] else False

            if our_results and (not pm_results or "error" in pm_results[0]):
                total_ours_better += 1
            elif pm_top_closed and our_results and not our_results[0].get("closed"):
                total_ours_better += 1
            elif our_top_vol > pm_top_vol * 1.5:
                total_ours_better += 1
            elif pm_top_vol > our_top_vol * 1.5:
                total_pm_better += 1
            else:
                total_tie += 1

    print()
    print("=" * 78)
    print("  SUMMARY")
    print("=" * 78)
    print(f"  Total queries: {len(QUERIES)}")
    print(f"  Ours had results: {total_ours_has_results}")
    print(f"  PM had results: {total_pm_has_results}")
    print(f"  Ours clearly better: {total_ours_better}")
    print(f"  PM clearly better: {total_pm_better}")
    print(f"  Roughly tied: {total_tie}")
    print()

    conn.close()


if __name__ == "__main__":
    run_experiment()
