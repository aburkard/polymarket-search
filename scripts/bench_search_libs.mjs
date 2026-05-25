/**
 * Benchmark MiniSearch vs FlexSearch vs a hand-rolled trigram index
 * using our actual Polymarket snapshot.
 *
 * Measures: index build time, serialized index size, per-query latency,
 * and result quality for clean / misspelled / partial / abbreviation queries.
 */

import { readFileSync } from "fs";
import { createRequire } from "module";
const require = createRequire(import.meta.url);

const MiniSearch = require("minisearch");

// FlexSearch's ESM exports are messy — use require
const { Index: FlexIndex, Document: FlexDocument } = require("flexsearch");

// ── Load data ───────────────────────────────────────────────────────────

const lines = readFileSync("data/events_active.jsonl", "utf8").trim().split("\n");
const docs = [];
for (const line of lines) {
  const ev = JSON.parse(line);
  const eventTitle = ev.title || "";
  const tags = (ev.tags || []).map(t => (typeof t === "object" ? t.label : t) || "").join(" ");
  const ctx = ev.eventMetadata?.context_description || "";
  for (const m of ev.markets || []) {
    if (m.closed) continue;
    const vol = parseFloat(m.volume || 0);
    const vol24 = parseFloat(m.volume24hr || 0);
    if (vol === 0 && vol24 === 0) continue;
    docs.push({
      id: m.id,
      question: m.question || "",
      eventTitle,
      tags,
      context: ctx.slice(0, 300),
      slug: m.slug || "",
      eventSlug: ev.slug || "",
      volume24hr: vol24,
      volume: vol,
      endDate: m.endDate || "",
    });
  }
}
console.log(`Loaded ${docs.length} searchable markets\n`);

// ── Queries ──────────────────────────────────────────────────────────────

const QUERIES = [
  { q: "trump 2028", cat: "clean" },
  { q: "bitcoin price", cat: "clean" },
  { q: "fed rate cut", cat: "clean" },
  { q: "world cup winner", cat: "clean" },
  { q: "iran ceasefire", cat: "clean" },
  { q: "nba finals", cat: "clean" },
  { q: "trmup", cat: "misspelling" },
  { q: "bitconi", cat: "misspelling" },
  { q: "ceaseifre", cat: "misspelling" },
  { q: "etherium", cat: "misspelling" },
  { q: "wrold cup", cat: "misspelling" },
  { q: "intrest rates", cat: "misspelling" },
  { q: "tru", cat: "partial" },
  { q: "bitcoi", cat: "partial" },
  { q: "world cu", cat: "partial" },
  { q: "fed ra", cat: "partial" },
  { q: "btc", cat: "abbreviation" },
  { q: "eth", cat: "abbreviation" },
  { q: "fomc", cat: "abbreviation" },
  { q: "cpi", cat: "abbreviation" },
  { q: "will bitcoin hit 100k", cat: "natural" },
  { q: "who will be president", cat: "natural" },
  { q: "interest rates", cat: "conceptual" },
  { q: "crypto crash", cat: "conceptual" },
  { q: "election odds", cat: "conceptual" },
];

// ── 1. MiniSearch ────────────────────────────────────────────────────────

function benchMiniSearch() {
  console.log("=".repeat(78));
  console.log("  MiniSearch");
  console.log("=".repeat(78));

  const t0 = performance.now();
  const ms = new MiniSearch({
    fields: ["question", "eventTitle", "tags", "context"],
    storeFields: ["question", "eventTitle", "volume24hr", "volume", "endDate", "slug"],
    searchOptions: {
      boost: { question: 5, eventTitle: 3, tags: 2, context: 1 },
      fuzzy: 0.2,
      prefix: true,
    },
  });
  ms.addAll(docs);
  const buildMs = performance.now() - t0;

  const serialized = JSON.stringify(ms);
  const serializedSize = Buffer.byteLength(serialized);

  console.log(`  Build: ${buildMs.toFixed(0)}ms`);
  console.log(`  Index size: ${(serializedSize / 1024 / 1024).toFixed(2)} MB`);
  console.log();

  const timings = [];
  for (const { q, cat } of QUERIES) {
    const st = performance.now();
    const results = ms.search(q, {
      boost: { question: 5, eventTitle: 3, tags: 2, context: 1 },
      fuzzy: 0.2,
      prefix: true,
    });
    const elapsed = performance.now() - st;
    timings.push(elapsed);

    const top3 = results.slice(0, 3).map(r => {
      const rr = r;
      return `$${(rr.volume24hr || 0).toFixed(0).padStart(10)} | ${(rr.question || "").slice(0, 60)}`;
    });
    console.log(`  [${cat.padEnd(12)}] "${q}"`);
    if (top3.length === 0) {
      console.log(`    (no results)`);
    }
    for (const t of top3) console.log(`    ${t}`);
  }
  const avgMs = timings.reduce((a, b) => a + b, 0) / timings.length;
  const maxMs = Math.max(...timings);
  console.log(`\n  Avg query: ${avgMs.toFixed(2)}ms, Max: ${maxMs.toFixed(2)}ms\n`);

  // Test deserialization speed
  const dt0 = performance.now();
  const ms2 = MiniSearch.loadJSON(serialized, {
    fields: ["question", "eventTitle", "tags", "context"],
    storeFields: ["question", "eventTitle", "volume24hr", "volume", "endDate", "slug"],
  });
  const deserMs = performance.now() - dt0;
  console.log(`  Deserialize: ${deserMs.toFixed(0)}ms`);

  // Verify deserialized search works
  const check = ms2.search("trump 2028", { fuzzy: 0.2, prefix: true });
  console.log(`  Deserialized search check: ${check.length} results`);
  console.log();
}

// ── 2. FlexSearch ────────────────────────────────────────────────────────

function benchFlexSearch() {
  console.log("=".repeat(78));
  console.log("  FlexSearch (Document mode)");
  console.log("=".repeat(78));

  const t0 = performance.now();
  const index = new FlexDocument({
    tokenize: "forward",
    document: {
      id: "id",
      index: [
        { field: "question", tokenize: "forward" },
        { field: "eventTitle", tokenize: "forward" },
        { field: "tags", tokenize: "forward" },
      ],
      store: ["question", "eventTitle", "volume24hr", "volume", "endDate", "slug"],
    },
  });
  for (const doc of docs) {
    index.add(doc);
  }
  const buildMs = performance.now() - t0;
  console.log(`  Build: ${buildMs.toFixed(0)}ms`);

  // FlexSearch export is async and complex — skip size measurement
  console.log(`  Index size: (export API is async/complex, skipping)`);
  console.log();

  const timings = [];
  for (const { q, cat } of QUERIES) {
    const st = performance.now();
    const rawResults = index.search(q, { limit: 10, suggest: true });
    const elapsed = performance.now() - st;
    timings.push(elapsed);

    // FlexSearch returns results per field — merge and dedupe
    const seen = new Set();
    const merged = [];
    for (const fieldResult of rawResults) {
      for (const item of fieldResult.result || []) {
        const id = typeof item === "object" ? item.id : item;
        if (!seen.has(id)) {
          seen.add(id);
          // Try to get stored doc
          const doc = typeof item === "object" ? item.doc : null;
          merged.push(doc || { id });
        }
      }
    }

    console.log(`  [${cat.padEnd(12)}] "${q}"`);
    if (merged.length === 0) {
      console.log(`    (no results)`);
    }
    for (const r of merged.slice(0, 3)) {
      if (r.question) {
        console.log(`    $${(r.volume24hr || 0).toFixed(0).padStart(10)} | ${(r.question || "").slice(0, 60)}`);
      } else {
        console.log(`    id=${r.id} (no stored fields returned)`);
      }
    }
  }
  const avgMs = timings.reduce((a, b) => a + b, 0) / timings.length;
  const maxMs = Math.max(...timings);
  console.log(`\n  Avg query: ${avgMs.toFixed(2)}ms, Max: ${maxMs.toFixed(2)}ms\n`);
}

// ── 3. Hand-rolled trigram index ─────────────────────────────────────────

function trigrams(s) {
  const lower = s.toLowerCase().replace(/[^\w\s]/g, "");
  const grams = new Set();
  const words = lower.split(/\s+/);
  for (const w of words) {
    if (w.length < 3) {
      grams.add(w);
    }
    for (let i = 0; i <= w.length - 3; i++) {
      grams.add(w.slice(i, i + 3));
    }
  }
  return grams;
}

function benchTrigram() {
  console.log("=".repeat(78));
  console.log("  Hand-rolled Trigram Index");
  console.log("=".repeat(78));

  const t0 = performance.now();

  // Build inverted index: trigram → Set<docIndex>
  const invertedIndex = new Map();
  const docStore = [];

  for (let i = 0; i < docs.length; i++) {
    const d = docs[i];
    const text = `${d.question} ${d.eventTitle} ${d.tags}`;
    const grams = trigrams(text);
    docStore.push({
      question: d.question,
      eventTitle: d.eventTitle,
      volume24hr: d.volume24hr,
      volume: d.volume,
      endDate: d.endDate,
      slug: d.slug,
    });
    for (const g of grams) {
      if (!invertedIndex.has(g)) invertedIndex.set(g, new Set());
      invertedIndex.get(g).add(i);
    }
  }
  const buildMs = performance.now() - t0;

  // Estimate size: count entries
  let totalEntries = 0;
  for (const s of invertedIndex.values()) totalEntries += s.size;
  const estSizeMB = (totalEntries * 4 + invertedIndex.size * 20) / 1024 / 1024;

  console.log(`  Build: ${buildMs.toFixed(0)}ms`);
  console.log(`  Trigrams: ${invertedIndex.size}, total postings: ${totalEntries}`);
  console.log(`  Est. index size: ~${estSizeMB.toFixed(1)} MB`);
  console.log();

  function search(query, limit = 10) {
    const qGrams = trigrams(query);
    if (qGrams.size === 0) return [];

    // Score = fraction of query trigrams matched
    const scores = new Map();
    for (const g of qGrams) {
      const posting = invertedIndex.get(g);
      if (!posting) continue;
      for (const docIdx of posting) {
        scores.set(docIdx, (scores.get(docIdx) || 0) + 1);
      }
    }

    const results = [];
    for (const [idx, matchCount] of scores) {
      const trigramScore = matchCount / qGrams.size;
      if (trigramScore < 0.3) continue; // at least 30% trigram overlap
      const d = docStore[idx];
      const volBoost = Math.log1p(d.volume24hr) + 0.3 * Math.log1p(d.volume);
      const finalScore = trigramScore * (1 + volBoost);
      results.push({ ...d, score: finalScore });
    }
    results.sort((a, b) => b.score - a.score);
    return results.slice(0, limit);
  }

  const timings = [];
  for (const { q, cat } of QUERIES) {
    const st = performance.now();
    const results = search(q);
    const elapsed = performance.now() - st;
    timings.push(elapsed);

    console.log(`  [${cat.padEnd(12)}] "${q}"`);
    if (results.length === 0) {
      console.log(`    (no results)`);
    }
    for (const r of results.slice(0, 3)) {
      console.log(`    $${(r.volume24hr || 0).toFixed(0).padStart(10)} | ${(r.question || "").slice(0, 60)}`);
    }
  }
  const avgMs = timings.reduce((a, b) => a + b, 0) / timings.length;
  const maxMs = Math.max(...timings);
  console.log(`\n  Avg query: ${avgMs.toFixed(2)}ms, Max: ${maxMs.toFixed(2)}ms\n`);
}

// ── Run all ──────────────────────────────────────────────────────────────

benchMiniSearch();
benchFlexSearch();
benchTrigram();
