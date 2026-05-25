/**
 * Measure realistic gzipped index sizes for MiniSearch and trigram approaches.
 * Also test MiniSearch with boostDocument for proper volume ranking.
 */

import { readFileSync, writeFileSync } from "fs";
import { gzipSync } from "zlib";
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const MiniSearch = require("minisearch");

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
      liquidity: parseFloat(m.liquidity || 0),
      endDate: m.endDate || "",
      image: m.image || "",
      outcomePrices: m.outcomePrices || "",
    });
  }
}

// ── MiniSearch: full (with context) ──
const msFull = new MiniSearch({
  fields: ["question", "eventTitle", "tags", "context"],
  storeFields: ["question", "eventTitle", "volume24hr", "volume", "endDate", "slug", "eventSlug", "image", "outcomePrices"],
  searchOptions: {
    boost: { question: 5, eventTitle: 3, tags: 2, context: 1 },
    fuzzy: 0.2,
    prefix: true,
  },
});
msFull.addAll(docs);
const fullJson = JSON.stringify(msFull);
const fullGz = gzipSync(fullJson);
console.log(`MiniSearch (4 fields + context):`);
console.log(`  Raw: ${(fullJson.length / 1024 / 1024).toFixed(2)} MB`);
console.log(`  Gzip: ${(fullGz.length / 1024 / 1024).toFixed(2)} MB`);

// ── MiniSearch: lean (no context) ──
const msLean = new MiniSearch({
  fields: ["question", "eventTitle", "tags"],
  storeFields: ["question", "eventTitle", "volume24hr", "volume", "endDate", "slug", "eventSlug", "image", "outcomePrices"],
  searchOptions: {
    boost: { question: 5, eventTitle: 3, tags: 2 },
    fuzzy: 0.2,
    prefix: true,
  },
});
msLean.addAll(docs);
const leanJson = JSON.stringify(msLean);
const leanGz = gzipSync(leanJson);
console.log(`\nMiniSearch (3 fields, no context):`);
console.log(`  Raw: ${(leanJson.length / 1024 / 1024).toFixed(2)} MB`);
console.log(`  Gzip: ${(leanGz.length / 1024 / 1024).toFixed(2)} MB`);

// ── MiniSearch: minimal stored fields ──
const msMin = new MiniSearch({
  fields: ["question", "eventTitle", "tags"],
  storeFields: ["question", "slug", "eventSlug", "volume24hr"],
  searchOptions: {
    boost: { question: 5, eventTitle: 3, tags: 2 },
    fuzzy: 0.2,
    prefix: true,
  },
});
msMin.addAll(docs);
const minJson = JSON.stringify(msMin);
const minGz = gzipSync(minJson);
console.log(`\nMiniSearch (3 fields, minimal store):`);
console.log(`  Raw: ${(minJson.length / 1024 / 1024).toFixed(2)} MB`);
console.log(`  Gzip: ${(minGz.length / 1024 / 1024).toFixed(2)} MB`);

// ── Separate data file approach: index + side-loaded doc store ──
const docStore = docs.map(d => ({
  id: d.id,
  q: d.question,
  s: d.slug,
  es: d.eventSlug,
  et: d.eventTitle,
  v: Math.round(d.volume24hr),
  vt: Math.round(d.volume),
  ed: d.endDate.slice(0, 10),
  im: d.image,
  op: d.outcomePrices,
}));
const docStoreJson = JSON.stringify(docStore);
const docStoreGz = gzipSync(docStoreJson);
console.log(`\nSeparate doc store (all display fields, short keys):`);
console.log(`  Raw: ${(docStoreJson.length / 1024 / 1024).toFixed(2)} MB`);
console.log(`  Gzip: ${(docStoreGz.length / 1024 / 1024).toFixed(2)} MB`);

// ── MiniSearch: NO stored fields (use separate doc store) ──
const msNoStore = new MiniSearch({
  fields: ["question", "eventTitle", "tags"],
  storeFields: [],
});
msNoStore.addAll(docs);
const nsJson = JSON.stringify(msNoStore);
const nsGz = gzipSync(nsJson);
console.log(`\nMiniSearch (index only, no stored fields):`);
console.log(`  Raw: ${(nsJson.length / 1024 / 1024).toFixed(2)} MB`);
console.log(`  Gzip: ${(nsGz.length / 1024 / 1024).toFixed(2)} MB`);
console.log(`  Combined with doc store: ${((nsGz.length + docStoreGz.length) / 1024 / 1024).toFixed(2)} MB gzip`);

// ── Test boostDocument for volume-aware ranking ──
console.log("\n" + "=".repeat(78));
console.log("  MiniSearch with boostDocument (volume-aware ranking)");
console.log("=".repeat(78));

const volMap = new Map();
for (const d of docs) {
  volMap.set(d.id, { v24: d.volume24hr, v: d.volume });
}

const testQueries = [
  "trump 2028", "bitcoin price", "fed rate cut", "world cup winner",
  "iran ceasefire", "nba finals", "trmup", "bitconi", "ceaseifre",
  "tru", "bitcoi", "btc", "fomc", "interest rates",
];

for (const q of testQueries) {
  const results = msLean.search(q, {
    boost: { question: 5, eventTitle: 3, tags: 2 },
    fuzzy: 0.25,
    prefix: true,
    boostDocument: (id) => {
      const v = volMap.get(id);
      if (!v) return 1;
      return 1 + Math.log1p(v.v24) * 0.5;
    },
  });
  console.log(`\n  "${q}"`);
  for (const r of results.slice(0, 3)) {
    const vol = r.volume24hr || 0;
    console.log(`    $${vol.toFixed(0).padStart(10)} | ${(r.question || r.eventTitle || "").slice(0, 65)}`);
  }
  if (results.length === 0) console.log("    (no results)");
}

// ── Test higher fuzzy for misspellings ──
console.log("\n" + "=".repeat(78));
console.log("  MiniSearch fuzzy=0.3 on misspellings");
console.log("=".repeat(78));

const misspellings = ["trmup", "bitconi", "ceaseifre", "etherium", "wrold cup"];
for (const q of misspellings) {
  for (const fz of [0.2, 0.25, 0.3, 0.35, 0.4]) {
    const results = msLean.search(q, { fuzzy: fz, prefix: true });
    const n = results.length;
    const top = n > 0 ? results[0].question?.slice(0, 50) : "(none)";
    console.log(`  fuzzy=${fz} "${q}" → ${n} results | ${top}`);
  }
  console.log();
}
