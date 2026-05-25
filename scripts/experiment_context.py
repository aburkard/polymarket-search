"""Experiment with different strategies for indexing context_description.

Tests multiple approaches on the same set of problem queries and
compares which produces the best search results.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from importlib import import_module

build_mod = import_module("build-index")
tokenize = build_mod.tokenize
parse_outcome_prices = build_mod.parse_outcome_prices
_outcome_tier = build_mod._outcome_tier
pick_sports_outcomes = build_mod.pick_sports_outcomes

DATA = Path(__file__).parent.parent / "data" / "events_active.jsonl"

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

TEST_QUERIES = [
    ("ca-38", "CA-38 House Election"),
    ("ossoff", "Georgia Senate"),
    ("trump die", "Trump out as President"),
    ("minnesota senate", "Minnesota.*Senate"),
    ("musk", "Musk"),
    ("wemby", "Wemb"),
    ("aoc", "Ocasio|NY-14|Democratic.*Nominee"),
    ("bitcoin price", "Bitcoin"),
    ("fomc", "Fed.*decision|Fed.*rate"),
    ("spurs thunder", "Thunder|Spurs"),
    ("democratic presidential nominee", "Democratic.*Nominee"),
    ("etherium", "Ethereum"),
    ("2026", "2026"),
]


def load_events():
    events = []
    with DATA.open() as f:
        for line in f:
            events.append(json.loads(line))
    return events


def build_with_strategy(events, strategy_fn):
    """Build an index using a given context extraction strategy."""
    docs = []
    idx = {}
    df = {}

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
        base_terms = set(tokenize(base_text))

        context = (ev.get("eventMetadata") or {}).get("context_description", "")
        context_terms = strategy_fn(context, base_terms)

        terms = base_terms | context_terms

        for t in terms:
            if t not in idx:
                idx[t] = []
            idx[t].append(doc_idx)
            df[t] = df.get(t, 0) + 1

        total_vol24 = sum(float(m.get("volume24hr") or 0) for m in active_markets)
        total_vol = sum(float(m.get("volume") or 0) for m in active_markets)

        docs.append({
            "q": event_title,
            "s": event_slug,
            "ed": (ev.get("endDate") or "")[:10],
            "v": round(total_vol24),
            "vt": round(total_vol),
        })

    n = len(docs)
    idf = {}
    for term, freq in df.items():
        idf[term] = round(math.log(n / freq), 4)

    return {"n": n, "idx": idx, "idf": idf, "docs": docs}


def build_two_tier(events):
    """Build a two-tier index: base terms at full weight, context at 0.3x."""
    docs = []
    idx = {}
    ctx = {}
    df = {}

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
        base_terms = set(tokenize(base_text))

        context_raw = (ev.get("eventMetadata") or {}).get("context_description", "")
        context_terms = set(tokenize(context_raw)) - base_terms - STOP_WORDS

        for t in base_terms:
            if t not in idx:
                idx[t] = []
            idx[t].append(doc_idx)
            df[t] = df.get(t, 0) + 1

        for t in context_terms:
            if t not in ctx:
                ctx[t] = []
            ctx[t].append(doc_idx)
            df[t] = df.get(t, 0) + 1

        total_vol24 = sum(float(m.get("volume24hr") or 0) for m in active_markets)
        total_vol = sum(float(m.get("volume") or 0) for m in active_markets)

        docs.append({
            "q": event_title,
            "s": event_slug,
            "ed": (ev.get("endDate") or "")[:10],
            "v": round(total_vol24),
            "vt": round(total_vol),
        })

    n = len(docs)
    idf = {}
    for term, freq in df.items():
        idf[term] = round(math.log(n / freq), 4)

    return {"n": n, "idx": idx, "ctx": ctx, "idf": idf, "docs": docs}


# ── Search (local reimplementation for testing) ─────────────────────────

def levenshtein(a, b):
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = (
                dp[i - 1][j - 1]
                if a[i - 1] == b[j - 1]
                else 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
            )
    return dp[m][n]


def find_matches(term, idx, idf, vocab, weight=1.0):
    seen = {}

    def add(doc_idx, score):
        seen[doc_idx] = max(seen.get(doc_idx, 0), score)

    if term in idx:
        s = (idf.get(term, 1)) * 2 * weight
        for di in idx[term]:
            add(di, s)

    for vt in vocab:
        if vt == term:
            continue
        if vt.startswith(term):
            s = (idf.get(vt, 1)) * 0.8 * weight
            for di in idx[vt]:
                add(di, s)

    if len(term) >= 4:
        max_dist = math.ceil(len(term) * 0.25)
        for vt in vocab:
            if vt == term or vt.startswith(term):
                continue
            if abs(len(vt) - len(term)) > max_dist:
                continue
            if vt[:2] != term[:2]:
                continue
            dist = levenshtein(term, vt)
            if dist <= max_dist:
                s = (idf.get(vt, 1)) * (1 - dist / len(term)) * 0.6 * weight
                for di in idx[vt]:
                    add(di, s)

    return seen


def search_index(query, data, limit=5):
    terms = tokenize(query)
    if not terms:
        return []

    has_ctx = "ctx" in data
    base_vocab = list(data["idx"].keys())
    ctx_vocab = list(data.get("ctx", {}).keys()) if has_ctx else []

    scores = {}
    term_hits = {}

    for term in terms:
        matches = find_matches(term, data["idx"], data["idf"], base_vocab, weight=1.0)
        if has_ctx:
            ctx_matches = find_matches(term, data["ctx"], data["idf"], ctx_vocab, weight=0.3)
            for di, s in ctx_matches.items():
                matches[di] = max(matches.get(di, 0), s)

        for di, s in matches.items():
            scores[di] = scores.get(di, 0) + s
            if di not in term_hits:
                term_hits[di] = set()
            term_hits[di].add(term)

    n_terms = len(terms)
    query_years = [t for t in terms if re.match(r"^20\d{2}$", t)]

    results = []
    for di, text_score in scores.items():
        doc = data["docs"][di]
        vol_boost = math.log1p(doc["v"]) * 0.4 + math.log1p(doc["vt"]) * 0.2
        coverage = len(term_hits[di]) / n_terms
        penalty = coverage ** 3

        year_boost = 1
        if query_years and doc.get("ed"):
            doc_year = doc["ed"][:4]
            year_boost = 2 if doc_year in query_years else 0.3

        results.append({
            "q": doc["q"],
            "score": text_score * penalty * (1 + vol_boost) * year_boost,
            "v": doc["v"],
        })

    results.sort(key=lambda x: -x["score"])
    return results[:limit]


# ── Context extraction strategies ────────────────────────────────────────

def strategy_none(context, base_terms):
    """No context indexing."""
    return set()


def strategy_all(context, base_terms):
    """Index all context terms not in base."""
    return set(tokenize(context)) - base_terms


def strategy_all_minus_stops(context, base_terms):
    """Index all context terms not in base, minus stop words."""
    return set(tokenize(context)) - base_terms - STOP_WORDS


def strategy_proper_nouns(context, base_terms):
    """Only capitalized words (not sentence-start)."""
    names = set()
    sentences = re.split(r"[.!?]\s+", context)
    for sent in sentences:
        words = sent.split()
        for i, word in enumerate(words):
            if i == 0:
                continue
            clean = re.sub(r"[^a-zA-Z]", "", word)
            if clean and clean[0].isupper() and len(clean) >= 2:
                names.add(clean.lower())
    return names - base_terms


def strategy_proper_nouns_alpha_only(context, base_terms):
    """Capitalized words, pure alpha only (no digits)."""
    names = set()
    sentences = re.split(r"[.!?]\s+", context)
    for sent in sentences:
        words = sent.split()
        for i, word in enumerate(words):
            if i == 0:
                continue
            clean = re.sub(r"[^a-zA-Z]", "", word)
            if clean and clean[0].isupper() and len(clean) >= 3 and clean.isalpha():
                names.add(clean.lower())
    return names - base_terms


def strategy_stops_and_min4(context, base_terms):
    """All terms minus stops, minimum 4 chars."""
    return {t for t in set(tokenize(context)) - base_terms - STOP_WORDS if len(t) >= 4}


# ── Run experiment ───────────────────────────────────────────────────────

def score_results(results, want_pattern):
    """Score how well the results match what we want."""
    for i, r in enumerate(results):
        if re.search(want_pattern, r["q"], re.IGNORECASE):
            return (len(results) - i, i + 1)  # (score, rank)
    return (0, 0)


def main():
    print("Loading events...")
    events = load_events()
    print(f"Loaded {len(events)} events\n")

    strategies = {
        "none":              strategy_none,
        "all":               strategy_all,
        "all-stops":         strategy_all_minus_stops,
        "proper-nouns":      strategy_proper_nouns,
        "proper-alpha":      strategy_proper_nouns_alpha_only,
        "stops+min4":        strategy_stops_and_min4,
        "two-tier":          None,  # special case
    }

    all_scores = {}

    for name, fn in strategies.items():
        print(f"{'=' * 70}")
        print(f"  Strategy: {name}")
        print(f"{'=' * 70}")

        if name == "two-tier":
            data = build_two_tier(events)
            n_terms = len(data["idx"]) + len(data["ctx"])
        else:
            data = build_with_strategy(events, fn)
            n_terms = len(data["idx"])

        print(f"  {data['n']} events, {n_terms} terms\n")

        total_score = 0
        for query, want in TEST_QUERIES:
            results = search_index(query, data)
            sc, rank = score_results(results, want)
            total_score += sc
            top = results[0]["q"][:45] if results else "(none)"
            mark = f"#{rank}" if rank else "MISS"
            print(f"  {mark:5s} \"{query:35s}\" → {top}")

        all_scores[name] = total_score
        print(f"\n  Total score: {total_score}\n")

    print(f"\n{'=' * 70}")
    print("  FINAL RANKING")
    print(f"{'=' * 70}")
    for name, score in sorted(all_scores.items(), key=lambda x: -x[1]):
        print(f"  {score:4d}  {name}")


if __name__ == "__main__":
    main()
