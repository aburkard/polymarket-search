import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  tokenize,
  levenshtein,
  outcomeMatchScore,
  prepareIndex,
  docsMatchingTags,
  rankOutcomesForDisplay,
  parseFilterParam,
  rankOutcomesForQuery,
  search,
  searchMany,
  serializeFilterParam,
  topByVolumeMany,
  topTagsForDocs,
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
  const dl = [];
  const n = docs.length;

  docs.forEach((doc, i) => {
    const mkText = (doc.mk || []).map((m) => m.q).join(" ");
    const text = `${doc.q} ${mkText} ${doc.tg}`;
    const terms = tokenize(text);
    dl.push(terms.length);
    const tf = {};
    for (const t of terms) tf[t] = (tf[t] || 0) + 1;
    for (const [t, count] of Object.entries(tf)) {
      if (!idx[t]) idx[t] = [];
      idx[t].push([i, count]);
      df[t] = (df[t] || 0) + 1;
    }
  });

  const avgDl = dl.reduce((a, b) => a + b, 0) / n;
  const idf = {};
  for (const [term, freq] of Object.entries(df)) {
    idf[term] = Math.log((n - freq + 0.5) / (freq + 0.5) + 1);
  }

  return prepareIndex({ v: 3, n, avgDl, dl, idx, idf, docs });
}

// ── Tokenization ────────────────────────────────────────────────────────

describe("tokenize", () => {
  it("lowercases and splits on non-alnum", () => {
    assert.deepEqual(tokenize("Hello World"), ["hello", "world"]);
  });

  it("strips $, %, and commas from numbers", () => {
    assert.deepEqual(tokenize("$80,000"), ["80000", "80k"]);
    assert.deepEqual(tokenize("3.3%"), ["3.3"]);
    assert.deepEqual(tokenize("$150k"), ["150k", "150000"]);
  });

  it("normalizes k/m suffixes and whole-number variants", () => {
    assert.deepEqual(tokenize("5k 5000 2m"), [
      "5k",
      "5000",
      "5000",
      "5k",
      "2m",
      "2000000",
    ]);
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
      "100000",
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

  it("does not prefix-match two-letter terms into unrelated words", () => {
    const data = prepareIndex({
      v: 3,
      n: 1,
      avgDl: 2,
      dl: [2],
      idx: { airline: [[0, 1]], default: [[0, 1]] },
      idf: { airline: 1, default: 1 },
      docs: [{ q: "Airline Default", s: "airline-default", v: 100, vt: 100, mk: [] }],
    });

    assert.equal(search("ai", data).length, 0);
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

  it("common term 'will' returns results (low IDF, volume matters less)", () => {
    const results = search("will", data);
    assert.ok(results.length > 0);
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

// ── Search: multiple indexes ────────────────────────────────────────────

describe("search: multiple indexes", () => {
  const active = makeIndex();
  const archived = makeIndex();
  archived.docs = archived.docs.map((doc) => ({
    ...doc,
    q: doc.s === "btc-prices" ? "Archived Bitcoin $100k Market" : doc.q,
    ar: 1,
  }));

  it("merges active and archived results when requested", () => {
    const results = searchMany("archived bitcoin", [
      { data: active },
      { data: archived, archived: true, scoreMultiplier: 0.92 },
    ]);
    assert.ok(results.length > 0);
    assert.ok(results.some((r) => r.ar === 1));
  });

  it("can rank top results across active and archived indexes by volume", () => {
    const results = topByVolumeMany([
      { data: active },
      { data: archived, archived: true, volumeMultiplier: 0.75 },
    ], 5);
    assert.equal(results.length, 5);
    assert.ok(results.some((r) => r.ar === 1));
  });
});

// ── Facet filters ───────────────────────────────────────────────────────

describe("facet filters", () => {
  const data = makeIndex();

  it("serializes and parses unique URL filters", () => {
    const value = serializeFilterParam(["Sports", "Soccer", "Sports", ""]);
    assert.equal(value, "Sports,Soccer");
    assert.deepEqual(parseFilterParam(value), ["Sports", "Soccer"]);
  });

  it("filters docs by selected tags", () => {
    const docs = docsMatchingTags(data.docs, ["Sports", "Soccer"]);
    assert.deepEqual(docs.map((d) => d.s), ["wc-2026"]);
  });

  it("suggests tags from the current query result pool", () => {
    const queryDocs = search("world cup", data, 20);
    const tags = topTagsForDocs(queryDocs, {
      activeFilters: [],
      includeUniversal: true,
      limit: 4,
    });
    assert.ok(tags.includes("Sports"));
    assert.ok(tags.includes("Soccer"));
    assert.ok(tags.includes("FIFA"));
    assert.ok(!tags.includes("Politics"));
  });

  it("omits active and hidden tags from suggestions", () => {
    const queryDocs = search("world cup", data, 20);
    const tags = topTagsForDocs(queryDocs, {
      activeFilters: ["Sports"],
      hiddenTags: ["FIFA"],
      includeUniversal: true,
      limit: 4,
    });
    assert.ok(!tags.includes("Sports"));
    assert.ok(!tags.includes("FIFA"));
    assert.ok(tags.includes("Soccer"));
  });

  it("can weight query filter suggestions by result score", () => {
    const tags = topTagsForDocs([
      { tg: ["Politics"], _score: 1 },
      { tg: ["Politics"], _score: 1 },
      { tg: ["Sports", "Soccer"], _score: 10 },
    ], { includeUniversal: true, limit: 2, weightByScore: true });
    assert.deepEqual(tags, ["Soccer", "Sports"]);
  });
});

// ── Outcome ranking ─────────────────────────────────────────────────────

describe("outcome ranking", () => {
  it("bubbles a numeric query match to the top", () => {
    const outcomes = [
      { l: "↑ 3,500", q: "Will Ethereum reach $3,500 by December 31, 2026?" },
      { l: "↑ 4,000", q: "Will Ethereum reach $4,000 by December 31, 2026?" },
      { l: "↑ 5,000", q: "Will Ethereum reach $5,000 by December 31, 2026?" },
    ];
    const ranked = rankOutcomesForQuery(outcomes, "ethereum 5000");
    assert.equal(ranked[0].l, "↑ 5,000");
    assert.ok(outcomeMatchScore(ranked[0], "ethereum 5000") > 0);
  });

  it("keeps original order when the query does not match outcomes", () => {
    const outcomes = [{ l: "Alice" }, { l: "Bob" }, { l: "Carol" }];
    assert.deepEqual(rankOutcomesForQuery(outcomes, "bitcoin"), outcomes);
  });

  it("sorts non-temporal display outcomes by probability", () => {
    const doc = {
      q: "Republican Presidential Nominee 2028",
      mk: [
        { l: "Donald Trump", op: [0.02], v: 100 },
        { l: "J.D. Vance", op: [0.34], v: 100 },
        { l: "Marco Rubio", op: [0.24], v: 100 },
      ],
    };

    const ranked = rankOutcomesForDisplay(doc, "gop president");
    assert.deepEqual(ranked.map((o) => o.l), [
      "J.D. Vance",
      "Marco Rubio",
      "Donald Trump",
    ]);
  });

  it("keeps query-matched outcomes first even when probability is lower", () => {
    const doc = {
      q: "Republican Presidential Nominee 2028",
      mk: [
        { l: "Donald Trump", op: [0.02], v: 100 },
        { l: "J.D. Vance", op: [0.34], v: 100 },
        { l: "Marco Rubio", op: [0.24], v: 100 },
      ],
    };

    const ranked = rankOutcomesForDisplay(doc, "trump president");
    assert.equal(ranked[0].l, "Donald Trump");
  });

  it("preserves temporal threshold outcome order", () => {
    const doc = {
      q: "Bitcoin above ___ on June 17?",
      mk: [
        { l: "56,000", op: [0.94], v: 100 },
        { l: "60,000", op: [0.72], v: 100 },
        { l: "58,000", op: [0.84], v: 100 },
      ],
    };

    const ranked = rankOutcomesForDisplay(doc, "bitcoin");
    assert.deepEqual(ranked.map((o) => o.l), ["56,000", "60,000", "58,000"]);
  });
});
