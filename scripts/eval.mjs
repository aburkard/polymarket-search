/**
 * Search evaluation framework.
 *
 * Runs a battery of queries against the search index with configurable
 * params, computes metrics (MRR, Hits@1/3/5), and prints detailed results
 * for manual analysis.
 *
 * Usage:
 *   node --input-type=module scripts/eval.mjs
 *   node --input-type=module scripts/eval.mjs --sweep   # sweep params
 */

import { readFileSync } from "fs";
import { prepareIndex, search, DEFAULT_CONFIG } from "../public/search.js";

const data = prepareIndex(
  JSON.parse(readFileSync("public/search-data.json", "utf8")),
);

// ── Eval set: [query, regex pattern that should match, notes] ──────────

const EVALS = [
  ["ca-38", /CA-38/i, "district match over TX-38"],
  ["ossoff", /georgia.*senate|ossoff/i, "GA senate race"],
  ["trump die", /trump.*out.*president|trump.*leave|assassination/i, "trump leaving office"],
  ["minnesota senate", /minnesota.*(senate|democratic.*senate|republican.*senate)/i, "MN senate"],
  ["musk", /musk|elon/i, "Elon Musk events"],
  ["wemby", /wemb/i, "Wembanyama"],
  ["aoc", /ocasio|ny-14|democratic.*nomin/i, "AOC / her district"],
  ["bitcoin price", /bitcoin/i, "bitcoin price events"],
  ["fomc", /fed.*decision|fed.*rate|fomc/i, "fed rate decisions"],
  ["democratic presidential nominee", /democratic.*nomin/i, "dem nominee 2028"],
  ["etherium", /ethereum/i, "ethereum (misspelled)"],
  ["world cup winner", /fifa.*world.*cup|world.*cup.*winner/i, "FIFA WC"],
  ["interest rates", /fed.*decision|fed.*rate|interest.*rate/i, "interest rate events"],
  ["nba finals", /nba.*champion|nba.*final/i, "NBA championship"],
  ["fed rate cut", /fed.*rate.*cut|fed.*rate|fed.*decision/i, "fed rate cut"],
  ["spurs thunder", /thunder.*spurs|spurs.*thunder|okc.*sas|sas.*okc/i, "tonight's game"],
  ["btc", /bitcoin|btc/i, "bitcoin via abbreviation"],
  ["eth", /ethereum|eth/i, "ethereum via abbreviation"],
  ["cpi", /inflation|cpi|consumer.*price/i, "inflation/CPI"],
  ["2026", /2026/i, "2026-specific events"],
  ["trmup", /trump/i, "trump (mangled spelling)"],
  ["ceaseifre", /ceasefire/i, "ceasefire (misspelled)"],
  ["bitconi", /bitcoin/i, "bitcoin (misspelled)"],
  ["fed ra", /fed.*rate|fed.*decision/i, "fed rate (partial)"],
  ["world cu", /world.*cup|fifa/i, "world cup (partial)"],
];

// ── Scoring ─────────────────────────────────────────────────────────────

function evalQuery(query, pattern, config, topK = 10) {
  const results = search(query, data, topK, config);
  for (let i = 0; i < results.length; i++) {
    if (pattern.test(results[i].q)) {
      return { rank: i + 1, hit: true, top: results[0]?.q };
    }
  }
  return { rank: 0, hit: false, top: results[0]?.q || "(none)" };
}

function runEval(config, label = "", verbose = false) {
  let totalRR = 0;
  let hits1 = 0,
    hits3 = 0,
    hits5 = 0;

  if (verbose) console.log(`\n${"=".repeat(70)}\n  ${label || "Eval"}\n${"=".repeat(70)}`);

  for (const [query, pattern, notes] of EVALS) {
    const { rank, hit, top } = evalQuery(query, pattern, config);
    const rr = rank > 0 ? 1 / rank : 0;
    totalRR += rr;
    if (rank === 1) hits1++;
    if (rank >= 1 && rank <= 3) hits3++;
    if (rank >= 1 && rank <= 5) hits5++;

    if (verbose) {
      const mark = rank === 1 ? "✓" : rank > 0 ? `#${rank}` : "✗";
      console.log(
        `  ${mark.padEnd(4)} "${query.padEnd(35)}" → ${(top || "").slice(0, 45)}`,
      );
    }
  }

  const n = EVALS.length;
  const metrics = {
    mrr: totalRR / n,
    hits1: hits1 / n,
    hits3: hits3 / n,
    hits5: hits5 / n,
    hits1n: hits1,
    hits3n: hits3,
    hits5n: hits5,
  };

  if (verbose) {
    console.log(`\n  MRR: ${metrics.mrr.toFixed(3)}  Hits@1: ${hits1}/${n} (${(metrics.hits1 * 100).toFixed(0)}%)  Hits@3: ${hits3}/${n}  Hits@5: ${hits5}/${n}`);
  }

  return metrics;
}

// ── Param sweep ─────────────────────────────────────────────────────────

function sweep() {
  console.log("Sweeping parameters...\n");

  const sweeps = {
    bm25B: [0.1, 0.2, 0.3, 0.5, 0.75],
    ctxWeight: [0.1, 0.2, 0.3, 0.5, 0.7],
    coverageExp: [2, 3, 4, 5],
    volWeight24h: [0.2, 0.4, 0.6, 0.8],
    volWeightTotal: [0.1, 0.2, 0.3, 0.5],
    prefixDiscount: [0.5, 0.6, 0.8, 1.0],
    fuzzyDiscount: [0.3, 0.4, 0.6, 0.8],
    yearBoostMatch: [1, 2, 3, 5],
    yearBoostMiss: [0.05, 0.1, 0.2, 0.5],
  };

  const results = [];

  for (const [param, values] of Object.entries(sweeps)) {
    for (const val of values) {
      const config = { ...DEFAULT_CONFIG, [param]: val };
      const metrics = runEval(config);
      results.push({ param, val, ...metrics });
    }
  }

  // Group by param and find best
  const grouped = {};
  for (const r of results) {
    if (!grouped[r.param]) grouped[r.param] = [];
    grouped[r.param].push(r);
  }

  for (const [param, runs] of Object.entries(grouped)) {
    runs.sort((a, b) => b.mrr - a.mrr);
    const best = runs[0];
    const current = DEFAULT_CONFIG[param];
    const improved = best.val !== current;
    console.log(
      `  ${param.padEnd(20)} best=${String(best.val).padEnd(6)} MRR=${best.mrr.toFixed(3)} H@1=${best.hits1n}/${EVALS.length} ${improved ? `← change from ${current}` : "(current is best)"}`,
    );
  }
}

// ── Main ────────────────────────────────────────────────────────────────

const doSweep = process.argv.includes("--sweep");

if (doSweep) {
  runEval(DEFAULT_CONFIG, "Current defaults", true);
  console.log();
  sweep();
} else {
  runEval(DEFAULT_CONFIG, "Current defaults", true);
}
