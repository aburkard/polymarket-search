import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  tokenize,
  levenshtein,
  prepareIndex,
  search,
} from "../public/search.js";

// ── Test fixtures ───────────────────────────────────────────────────────

function makeIndex() {
  const docs = [
    { q: "Bitcoin Prices", s: "btc-prices", ed: "2026-06-30", v: 5000000, vt: 12000000, mc: 2, mk: [{q: "Will Bitcoin hit $150k?", op: [0.01, 0.99], v: 3000000}, {q: "Will Bitcoin reach $80k?", op: [0.18, 0.82], v: 2000000}], tg: "Crypto Bitcoin" },
    { q: "Trump 2028 Election", s: "trump-2028", ed: "2028-11-07", v: 500000, vt: 2000000, mc: 1, mk: [{q: "Will Trump win 2028?", op: [0.35, 0.65], v: 500000}], tg: "Politics Elections" },
    { q: "Fed Rate Decision", s: "fed-rate", ed: "2026-06-17", v: 200000, vt: 1000000, mc: 1, mk: [{q: "Fed rate cut by June?", op: [0.80, 0.20], v: 200000}], tg: "Finance Fed fomc" },
    { q: "Iran Ceasefire", s: "iran-cf", ed: "2026-05-01", v: 10000000, vt: 20000000, mc: 1, mk: [{q: "Will Iran ceasefire hold?", op: [0.54, 0.46], v: 10000000}], tg: "Geopolitics Iran" },
    { q: "NBA Finals MVP", s: "nba-mvp", ed: "2026-06-15", v: 100, vt: 500, mc: 1, mk: [{q: "NBA Finals MVP?", op: [0.10, 0.90], v: 100}], tg: "Sports NBA" },
    { q: "Ethereum Prices", s: "eth-prices", ed: "2026-12-31", v: 300000, vt: 800000, mc: 1, mk: [{q: "Will Ethereum reach $5000?", op: [0.05, 0.95], v: 300000}], tg: "Crypto Ethereum" },
    { q: "World Cup 2026", s: "wc-2026", ed: "2026-07-19", v: 4000000, vt: 15000000, mc: 1, mk: [{q: "World Cup winner 2026?", op: [0.08, 0.92], v: 4000000}], tg: "Sports Soccer FIFA" },
    { q: "US Election 2028", s: "election-2028", ed: "2028-11-07", v: 1000, vt: 5000, mc: 1, mk: [{q: "US election 2028 odds", op: [0.50, 0.50], v: 1000}], tg: "Politics Elections" },
  ];

  const idx = {};
  const df = {};
  const n = docs.length;

  docs.forEach((doc, i) => {
    const mkText = (doc.mk || []).map((m) => m.q).join(" ");
    const text = `${doc.q} ${mkText} ${doc.tg}`;
    const terms = tokenize(text);
    const unique = [...new Set(terms)];
    for (const t of unique) {
      if (!idx[t]) idx[t] = [];
      idx[t].push(i);
      df[t] = (df[t] || 0) + 1;
    }
  });

  const idf = {};
  for (const [term, freq] of Object.entries(df)) {
    idf[term] = Math.log(n / freq);
  }

  return prepareIndex({ v: 1, n, idx, idf, docs });
}

// ── Tokenization ────────────────────────────────────────────────────────

describe("tokenize", () => {
  it("lowercases and splits on non-alnum", () => {
    assert.deepEqual(tokenize("Hello World"), ["hello", "world"]);
  });

  it("strips $, %, and commas from numbers", () => {
    assert.deepEqual(tokenize("$80,000"), ["80000"]);
    assert.deepEqual(tokenize("3.3%"), ["3.3"]);
    assert.deepEqual(tokenize("$150k"), ["150k"]);
  });

  it("filters tokens shorter than 2 chars", () => {
    assert.deepEqual(tokenize("I am a test"), ["am", "test"]);
  });

  it("handles empty and whitespace input", () => {
    assert.deepEqual(tokenize(""), []);
    assert.deepEqual(tokenize("   "), []);
  });

  it("handles special characters", () => {
    assert.deepEqual(tokenize("trump's plan!"), ["trump", "plan"]);
  });

  it("preserves numbers and mixed alphanumeric", () => {
    assert.deepEqual(tokenize("Bitcoin 100k 2026"), [
      "bitcoin",
      "100k",
      "2026",
    ]);
  });
});

// ── Levenshtein ─────────────────────────────────────────────────────────

describe("levenshtein", () => {
  it("returns 0 for identical strings", () => {
    assert.equal(levenshtein("abc", "abc"), 0);
  });

  it("handles insertions", () => {
    assert.equal(levenshtein("abc", "abcd"), 1);
  });

  it("handles deletions", () => {
    assert.equal(levenshtein("abcd", "abc"), 1);
  });

  it("handles substitutions", () => {
    assert.equal(levenshtein("abc", "axc"), 1);
  });

  it("handles transpositions as 2 ops", () => {
    assert.equal(levenshtein("ab", "ba"), 2);
  });

  it("trmup → trump = 2", () => {
    assert.equal(levenshtein("trmup", "trump"), 2);
  });

  it("bitconi → bitcoin = 2", () => {
    assert.equal(levenshtein("bitconi", "bitcoin"), 2);
  });

  it("ceaseifre → ceasefire = 2", () => {
    assert.equal(levenshtein("ceaseifre", "ceasefire"), 2);
  });

  it("etherium → ethereum = 1", () => {
    assert.equal(levenshtein("etherium", "ethereum"), 1);
  });

  it("election → elections = 1 (stemming proxy)", () => {
    assert.equal(levenshtein("election", "elections"), 1);
  });
});

// ── Search: exact match ─────────────────────────────────────────────────

describe("search: exact match", () => {
  const data = makeIndex();

  it("finds bitcoin markets for 'bitcoin'", () => {
    const results = search("bitcoin", data);
    assert.ok(results.length > 0);
    assert.ok(results[0].q.toLowerCase().includes("bitcoin"));
  });

  it("finds trump markets for 'trump'", () => {
    const results = search("trump", data);
    assert.ok(results.length > 0);
    assert.ok(results.some((r) => r.q.toLowerCase().includes("trump")));
  });

  it("returns empty for non-existent term", () => {
    const results = search("zzzznotaword", data);
    assert.equal(results.length, 0);
  });
});

// ── Search: prefix match ────────────────────────────────────────────────

describe("search: prefix match", () => {
  const data = makeIndex();

  it("'bit' prefix-matches bitcoin markets", () => {
    const results = search("bit", data);
    assert.ok(results.length > 0);
    assert.ok(results.some((r) => r.q.toLowerCase().includes("bitcoin")));
  });

  it("'tru' prefix-matches trump markets", () => {
    const results = search("tru", data);
    assert.ok(results.length > 0);
    assert.ok(results.some((r) => r.q.toLowerCase().includes("trump")));
  });

  it("'fed ra' matches fed rate markets", () => {
    const results = search("fed ra", data);
    assert.ok(results.length > 0);
    assert.ok(results.some((r) => r.q.toLowerCase().includes("fed")));
  });
});

// ── Search: fuzzy match ─────────────────────────────────────────────────

describe("search: fuzzy match", () => {
  const data = makeIndex();

  it("'trmup' fuzzy-matches trump (distance 2)", () => {
    const results = search("trmup", data);
    assert.ok(results.length > 0);
    assert.ok(results.some((r) => r.q.toLowerCase().includes("trump")));
  });

  it("'etherium' fuzzy-matches ethereum (distance 1)", () => {
    const results = search("etherium", data);
    assert.ok(results.length > 0);
    assert.ok(results.some((r) => r.q.toLowerCase().includes("ethereum")));
  });

  it("'ceaseifre' fuzzy-matches ceasefire (distance 2)", () => {
    const results = search("ceaseifre", data);
    assert.ok(results.length > 0);
    assert.ok(results.some((r) => r.q.toLowerCase().includes("ceasefire")));
  });

  it("fuzzy skips short terms (< 4 chars)", () => {
    const results = search("xzy", data);
    assert.equal(results.length, 0);
  });
});

// ── Search: volume boosting ─────────────────────────────────────────────

describe("search: volume boost", () => {
  const data = makeIndex();

  it("high-volume market ranks above low-volume for same match", () => {
    const results = search("crypto", data);
    assert.ok(results.length >= 2);
    assert.ok(results[0].v >= results[1].v);
  });

  it("iran ceasefire (10M vol) ranks high for 'ceasefire'", () => {
    const results = search("ceasefire", data);
    assert.ok(results.length > 0);
    assert.ok(results[0].q.toLowerCase().includes("iran"));
  });
});

// ── Search: IDF weighting ───────────────────────────────────────────────

describe("search: IDF weighting", () => {
  const data = makeIndex();

  it("rare term 'fomc' retrieves specific event", () => {
    const results = search("fomc", data);
    assert.ok(results.length > 0);
    assert.ok(results.some((r) => r.q.toLowerCase().includes("fed")));
  });

  it("common term 'will' alone returns results biased by volume", () => {
    const results = search("will", data);
    assert.ok(results.length > 0);
    assert.ok(results[0].v >= results[1].v);
  });
});

// ── Search: multi-term queries ──────────────────────────────────────────

describe("search: multi-term queries", () => {
  const data = makeIndex();

  it("'bitcoin crypto' ranks bitcoin event highest", () => {
    const results = search("bitcoin crypto", data);
    assert.ok(results.length > 0);
    assert.equal(results[0].s, "btc-prices");
  });

  it("'world cup 2026' finds world cup market", () => {
    const results = search("world cup 2026", data);
    assert.ok(results.length > 0);
    assert.ok(results.some((r) => r.s === "wc-2026"));
  });

  it("doc matching more query terms ranks higher", () => {
    const results = search("election 2028 politics", data);
    assert.ok(results.length >= 2);
    const top = results[0];
    assert.ok(
      top.tg.toLowerCase().includes("politics") ||
        top.q.toLowerCase().includes("election"),
    );
  });
});

// ── Search: edge cases ──────────────────────────────────────────────────

describe("search: edge cases", () => {
  const data = makeIndex();

  it("empty query returns empty", () => {
    assert.deepEqual(search("", data), []);
  });

  it("single char query returns empty (filtered by tokenizer)", () => {
    assert.deepEqual(search("a", data), []);
  });

  it("special chars only returns empty", () => {
    assert.deepEqual(search("!@#$", data), []);
  });

  it("respects limit parameter", () => {
    const results = search("will", data, 2);
    assert.ok(results.length <= 2);
  });

  it("results have expected fields", () => {
    const results = search("bitcoin", data);
    const r = results[0];
    assert.ok("q" in r);
    assert.ok("s" in r);
    assert.ok("v" in r);
    assert.ok("mk" in r);
    assert.ok("_score" in r);
  });
});
