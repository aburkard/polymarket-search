/**
 * Search evaluation framework.
 *
 * Runs a battery of queries against the search index with configurable
 * params, computes metrics (MRR, Hits@1/3/5), and prints detailed results
 * for manual analysis.
 *
 * Usage:
 *   node scripts/eval.mjs
 *   node scripts/eval.mjs --provider=kalshi
 *   node scripts/eval.mjs --sweep   # sweep params
 */

import { existsSync, readFileSync } from "fs";
import { prepareIndex, search, DEFAULT_CONFIG } from "../public/search.js";

function loadIndex(path) {
  return prepareIndex(JSON.parse(readFileSync(path, "utf8")));
}

// ── Eval set: [query, regex pattern that should match, notes] ──────────

const POLYMARKET_EVALS = [
  // ── Clean, specific queries ──────────────────────────────────────────
  ["bitcoin price", /bitcoin/i, "clean:crypto"],
  ["ethereum price", /ethereum/i, "clean:crypto"],
  ["solana price", /solana/i, "clean:crypto"],
  ["fed rate cut", /fed.*rate|fed.*decision/i, "clean:finance"],
  ["interest rates", /fed.*decision|fed.*rate|interest.*rate/i, "clean:finance"],
  ["world cup winner", /fifa.*world.*cup|world.*cup/i, "clean:sports"],
  ["nba finals", /nba.*champion|nba.*final/i, "clean:sports"],
  ["stanley cup", /stanley.*cup|nhl/i, "clean:sports"],
  ["champions league", /champions.*league|uefa/i, "clean:sports"],
  ["premier league", /premier.*league/i, "clean:sports"],
  ["democratic presidential nominee", /democratic.*nomin/i, "clean:politics"],
  ["republican presidential nominee", /republican.*nomin/i, "clean:politics"],
  ["trump tariffs", /trump.*tariff/i, "clean:politics"],
  ["iran ceasefire", /iran.*ceasefire|ceasefire.*iran/i, "clean:geopolitics"],
  ["ukraine russia peace", /ukraine|russia/i, "clean:geopolitics"],
  ["china taiwan", /china.*taiwan|taiwan/i, "clean:geopolitics"],
  ["spacex starship", /spacex.*starship|starship/i, "clean:science"],
  ["ai safety bill", /ai.*safety/i, "clean:science"],
  ["taylor swift", /taylor.*swift/i, "clean:culture"],
  ["gta 6", /gta/i, "clean:culture"],
  ["james bond", /james.*bond|bond.*actor/i, "clean:culture"],
  ["minnesota senate", /minnesota.*(senate|democratic.*senate|republican.*senate)/i, "clean:politics"],
  ["ca-38", /CA-38/i, "clean:politics"],
  ["openai ipo", /openai.*ipo/i, "clean:finance"],
  ["kraken ipo", /kraken/i, "clean:crypto"],

  // ── Multi-word specific ──────────────────────────────────────────────
  ["will bitcoin hit 100k", /bitcoin/i, "multiword:crypto"],
  ["trump out as president", /trump.*out.*president|trump.*leave/i, "multiword:politics"],
  ["who will win world cup", /world.*cup|fifa/i, "multiword:sports"],
  ["next james bond actor", /james.*bond|bond/i, "multiword:culture"],
  ["spacex launch this week", /spacex/i, "multiword:science"],
  ["fed meeting this month", /fed.*decision|fed.*meeting|fomc/i, "multiword:finance"],

  // ── Abbreviations / jargon ───────────────────────────────────────────
  ["btc", /bitcoin|btc/i, "abbrev:crypto"],
  ["eth", /ethereum|eth/i, "abbrev:crypto"],
  ["sol", /solana|sol/i, "abbrev:crypto"],
  ["xrp", /xrp|ripple/i, "abbrev:crypto"],
  ["fomc", /fed.*decision|fed.*rate|fomc/i, "abbrev:finance"],
  ["cpi", /inflation|cpi|consumer.*price/i, "abbrev:finance"],
  ["gdp", /gdp|growth/i, "abbrev:finance"],
  ["aoc", /ocasio|ny-14|democratic.*nomin/i, "abbrev:politics"],
  ["potus", /president|trump|white.*house/i, "abbrev:politics"],
  ["scotus", /scotus|supreme.*court/i, "abbrev:politics"],
  ["epl", /premier.*league/i, "abbrev:sports"],
  ["nfl", /nfl|football.*champion/i, "abbrev:sports"],
  ["ufc", /ufc|mma/i, "abbrev:sports"],
  ["ipo", /ipo/i, "abbrev:finance"],

  // ── Nicknames / alternate names ──────────────────────────────────────
  ["musk", /musk|elon/i, "nickname"],
  ["wemby", /wemb/i, "nickname"],
  ["sga", /gilgeous|thunder|okc/i, "nickname:sports"],
  ["macron", /macron|france.*president/i, "nickname:politics"],
  ["starmer", /starmer/i, "nickname:politics"],

  // ── Misspellings ─────────────────────────────────────────────────────
  ["etherium", /ethereum/i, "misspell"],
  ["trmup", /trump/i, "misspell"],
  ["ceaseifre", /ceasefire/i, "misspell"],
  ["bitconi", /bitcoin/i, "misspell"],
  ["ukrane", /ukraine/i, "misspell"],
  ["chamions league", /champions.*league/i, "misspell"],

  // ── Partial / typing in progress ─────────────────────────────────────
  ["fed ra", /fed.*rate|fed.*decision/i, "partial"],
  ["world cu", /world.*cup|fifa/i, "partial"],
  ["bitcoi", /bitcoin/i, "partial"],
  ["trum", /trump/i, "partial"],
  ["ethe", /ethereum/i, "partial"],
  ["spacex star", /spacex.*starship|starship/i, "partial"],
  ["taylor sw", /taylor.*swift/i, "partial"],
  ["champions lea", /champions.*league/i, "partial"],

  // ── Conceptual / indirect ────────────────────────────────────────────
  ["trump die", /trump.*out.*president|trump.*leave|assassination/i, "conceptual"],
  ["crypto crash", /bitcoin|crypto/i, "conceptual"],
  ["stock market crash", /equit|stock|s.p|market.*crash/i, "conceptual"],
  ["gas prices", /natural.*gas|oil|energy|gas/i, "conceptual"],
  ["housing market", /hous|real.*estate|mortgage/i, "conceptual"],
  ["will rates go up", /fed.*rate|interest.*rate|fed.*decision/i, "conceptual"],
  ["robot future", /robot|humanoid|optimus/i, "conceptual"],
  ["nuclear war", /nuclear|ww3|world.*war/i, "conceptual"],
  ["recession", /recession|gdp|economy/i, "conceptual"],

  // ── Year-specific ────────────────────────────────────────────────────
  ["2026", /2026/i, "year"],
  ["2028 election", /2028.*election|election.*2028|president.*2028/i, "year"],

  // ── Sports-specific patterns ─────────────────────────────────────────
  ["spurs thunder", /thunder.*spurs|spurs.*thunder|okc.*sas/i, "sports:game"],
  ["lakers celtics", /laker|celtic/i, "sports:game"],
  ["france brazil world cup", /france|brazil/i, "sports:matchup"],
  ["nba mvp", /nba.*mvp|mvp/i, "sports:award"],
  ["nfl draft", /draft|nfl/i, "sports:event"],
  ["ballon dor", /ballon|golden.*ball/i, "sports:award"],

  // ── Niche / long tail ────────────────────────────────────────────────
  ["covid variant", /covid|variant/i, "niche:science"],
  ["tiktok ban", /tiktok/i, "niche:tech"],
  ["nato", /nato/i, "niche:geopolitics"],
  ["harvey weinstein", /weinstein/i, "niche:culture"],
  ["cs2 map pool", /cache|map.*pool|counter.*strike/i, "niche:esports"],
  ["aaron rodgers retire", /rodgers|retire/i, "niche:sports"],
  ["pump.fun airdrop", /pump/i, "niche:crypto"],

  // ── Edge cases: punctuation & special chars ──────────────────────────
  ["trump's tariffs", /trump.*tariff/i, "edge:punctuation"],
  ["s&p 500", /s.p|equit|stock/i, "edge:punctuation"],
  ["u.s. iran", /iran/i, "edge:punctuation"],
  ["$80,000 bitcoin", /bitcoin/i, "edge:punctuation"],
  ["50%+ chance", /./i, "edge:punctuation"],

  // ── Edge cases: single character / very short ────────────────────────
  ["a", null, "edge:tooShort (expect empty)"],
  ["", null, "edge:empty (expect empty)"],
  ["ai", /ai|artificial/i, "edge:short"],
  ["uk", /uk|united.*kingdom|brit/i, "edge:short"],

  // ── Edge cases: very long queries ────────────────────────────────────
  ["will the federal reserve cut interest rates at the next fomc meeting", /fed.*rate|fed.*decision|fomc/i, "edge:longQuery"],
  ["who is going to win the 2026 fifa world cup in north america", /fifa.*world.*cup|world.*cup/i, "edge:longQuery"],

  // ── Edge cases: all caps / mixed case ────────────────────────────────
  ["BITCOIN", /bitcoin/i, "edge:caps"],
  ["TRUMP 2028", /trump.*2028|2028.*trump|republican.*nomin|president/i, "edge:caps"],
  ["Bitcoin Price", /bitcoin/i, "edge:mixedCase"],

  // ── Edge cases: numbers and prices ───────────────────────────────────
  ["bitcoin 80000", /bitcoin/i, "edge:numbers"],
  ["100k", /bitcoin|100k/i, "edge:numbers"],
  ["btc 100k 2026", /bitcoin/i, "edge:numbers"],
  ["ethereum 5000", /ethereum/i, "edge:numbers"],
  ["3.5%", /inflation|rate|fed/i, "edge:numbers"],

  // ── Edge cases: repeated/duplicate terms ─────────────────────────────
  ["trump trump", /trump/i, "edge:repeated"],
  ["bitcoin bitcoin price", /bitcoin/i, "edge:repeated"],

  // ── Edge cases: stop-word-heavy ──────────────────────────────────────
  ["will the", /./i, "edge:stopWords"],
  ["what is the", /./i, "edge:stopWords"],
  ["is there a", /./i, "edge:stopWords"],

  // ── Edge cases: unicode / accents ────────────────────────────────────
  ["macron président", /macron/i, "edge:unicode"],
  ["são paulo", /brazil|paulo/i, "edge:unicode"],

  // ── Edge cases: query IS the exact event title ───────────────────────
  ["2026 NBA Champion", /nba.*champion/i, "edge:exactTitle"],
  ["Fed decision in April?", /fed.*decision.*april/i, "edge:exactTitle"],
];

const KALSHI_EVALS = [
  ["nba champion", /pro basketball champion|basketball.*champion/i, "kalshi:sports"],
  ["pro basketball champion", /pro basketball champion|basketball.*champion/i, "kalshi:sports"],
  ["world cup winner", /world.*soccer.*cup.*winner|world.*cup.*winner/i, "kalshi:sports"],
  ["world cup", /world.*soccer.*cup|golden boot/i, "kalshi:sports"],
  ["democratic presidential nominee", /democratic.*presidential.*nominee/i, "kalshi:politics"],
  ["republican presidential nominee", /republican.*presidential.*nominee/i, "kalshi:politics"],
  ["gop nominee", /republican.*nominee/i, "kalshi:politics"],
  ["bitcoin", /bitcoin|btc/i, "kalshi:crypto"],
  ["btc", /bitcoin|btc/i, "kalshi:crypto"],
  ["fed rate cut", /rate cuts|fed decision/i, "kalshi:finance"],
  ["inflation cpi", /inflation|cpi/i, "kalshi:finance"],
  ["stanley cup", /stanley.*cup/i, "kalshi:sports"],
  ["nfl champion", /pro football champion|championship winner/i, "kalshi:sports"],
  ["tariffs", /tariff/i, "kalshi:politics"],
  ["agi", /agi|artificial intelligence|math ai/i, "kalshi:tech"],
];

const PROVIDERS = {
  polymarket: {
    path: "public/search-data.json",
    evals: POLYMARKET_EVALS,
  },
  kalshi: {
    path: "public/search-data-kalshi.json",
    evals: KALSHI_EVALS,
  },
};

// ── Scoring ─────────────────────────────────────────────────────────────

function evalQuery(query, pattern, data, config, topK = 10) {
  const results = search(query, data, topK, config);
  if (pattern === null) {
    return results.length === 0
      ? { rank: 1, hit: true, top: "(empty — correct)" }
      : { rank: 0, hit: false, top: results[0]?.q };
  }
  for (let i = 0; i < results.length; i++) {
    if (pattern.test(results[i].q)) {
      return { rank: i + 1, hit: true, top: results[0]?.q };
    }
  }
  return { rank: 0, hit: false, top: results[0]?.q || "(none)" };
}

function runEval(provider, evals, data, config, label = "", verbose = false) {
  let totalRR = 0;
  let hits1 = 0,
    hits3 = 0,
    hits5 = 0;

  if (verbose) {
    console.log(`\n${"=".repeat(70)}\n  ${provider}: ${label || "Eval"}\n${"=".repeat(70)}`);
  }

  for (const [query, pattern, notes] of evals) {
    const { rank, hit, top } = evalQuery(query, pattern, data, config);
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

  const n = evals.length;
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

function selectedProviders() {
  const providerArg = process.argv.find((arg) => arg.startsWith("--provider="));
  const provider = providerArg?.split("=")[1];
  if (!provider || provider === "all") return Object.keys(PROVIDERS);
  if (!PROVIDERS[provider]) {
    throw new Error(`Unknown provider "${provider}". Use one of: ${Object.keys(PROVIDERS).join(", ")}, all`);
  }
  return [provider];
}

function loadSelectedProviders() {
  return selectedProviders().flatMap((provider) => {
    const suite = PROVIDERS[provider];
    if (!existsSync(suite.path)) {
      console.warn(`Skipping ${provider}: missing ${suite.path}`);
      return [];
    }
    return [{ provider, ...suite, data: loadIndex(suite.path) }];
  });
}

function runEvalSuite(providerSuites, config, label = "", verbose = false) {
  let total = 0;
  let weightedMRR = 0;
  let hits1n = 0;
  let hits3n = 0;
  let hits5n = 0;

  for (const suite of providerSuites) {
    const metrics = runEval(
      suite.provider,
      suite.evals,
      suite.data,
      config,
      label,
      verbose,
    );
    const n = suite.evals.length;
    total += n;
    weightedMRR += metrics.mrr * n;
    hits1n += metrics.hits1n;
    hits3n += metrics.hits3n;
    hits5n += metrics.hits5n;
  }

  return {
    mrr: total ? weightedMRR / total : 0,
    hits1: total ? hits1n / total : 0,
    hits3: total ? hits3n / total : 0,
    hits5: total ? hits5n / total : 0,
    hits1n,
    hits3n,
    hits5n,
    total,
  };
}

// ── Param sweep ─────────────────────────────────────────────────────────

function sweep(providerSuites) {
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
      const metrics = runEvalSuite(providerSuites, config);
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
      `  ${param.padEnd(20)} best=${String(best.val).padEnd(6)} MRR=${best.mrr.toFixed(3)} H@1=${best.hits1n}/${best.total} ${improved ? `← change from ${current}` : "(current is best)"}`,
    );
  }
}

// ── Main ────────────────────────────────────────────────────────────────

const doSweep = process.argv.includes("--sweep");
const providerSuites = loadSelectedProviders();

if (doSweep) {
  runEvalSuite(providerSuites, DEFAULT_CONFIG, "Current defaults", true);
  console.log();
  sweep(providerSuites);
} else {
  runEvalSuite(providerSuites, DEFAULT_CONFIG, "Current defaults", true);
}
