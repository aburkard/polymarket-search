import { readFileSync } from "fs";
import { prepareIndex, search } from "../public/search.js";

const raw = readFileSync("public/search-data.json", "utf8");
const data = prepareIndex(JSON.parse(raw));
console.log(`Loaded ${data.n} markets, ${data._vocab.length} terms\n`);

const queries = [
  "bitcoin price",
  "trump 2028",
  "fed rate cut",
  "world cup winner",
  "iran ceasefire",
  "nba finals",
  "trmup",
  "bitconi",
  "ceaseifre",
  "etherium",
  "tru",
  "bitcoi",
  "fed ra",
  "btc",
  "fomc",
  "interest rates",
  "will bitcoin hit 100k",
  "election odds",
  "crypto crash",
];

for (const q of queries) {
  const t0 = performance.now();
  const results = search(q, data, 3);
  const ms = (performance.now() - t0).toFixed(1);

  console.log(`"${q}" (${ms}ms)`);
  if (!results.length) {
    console.log("  (no results)\n");
    continue;
  }
  for (const r of results) {
    const vol = r.v >= 1e6 ? `$${(r.v / 1e6).toFixed(1)}M` : `$${(r.v / 1e3).toFixed(0)}K`;
    const prices = (r.op || []).map((p) => (p * 100).toFixed(0) + "¢").join("/");
    console.log(`  ${vol.padStart(8)} | ${prices.padEnd(10)} | ${r.q.slice(0, 70)}`);
  }
  console.log();
}
