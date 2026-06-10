export const DEFAULT_CONFIG = {
  bm25K1: 1.2,
  bm25B: 0.3,
  ctxWeight: 0.5,
  prefixDiscount: 0.6,
  fuzzyMinLen: 4,
  fuzzyMaxDistFrac: 0.25,
  fuzzyDiscount: 0.3,
  volWeight24h: 0.2,
  volWeightTotal: 0.4,
  coverageExp: 2,
  yearBoostMatch: 3,
  yearBoostMiss: 0.05,
};

export function tokenize(text) {
  const base = text
    .toLowerCase()
    .replace(/[$%,]/g, "")
    .replace(/[^a-z0-9.]/g, " ")
    .split(/\s+/)
    .map((t) => t.replace(/^\.+|\.+$/g, ""))
    .filter((t) => t.length >= 2);
  return expandNumericTokens(base);
}

export function outcomeMatchScore(outcome, query) {
  const queryTerms = tokenize(query);
  if (!queryTerms.length) return 0;

  const outcomeTerms = new Set(tokenize(`${outcome?.l || ""} ${outcome?.q || ""}`));
  let score = 0;
  for (const term of queryTerms) {
    if (!outcomeTerms.has(term)) continue;
    score += /^\d/.test(term) ? 5 : 2;
  }
  return score;
}

export function rankOutcomesForQuery(outcomes, query) {
  if (!query?.trim()) return outcomes;
  return outcomes
    .map((outcome, index) => ({
      outcome,
      index,
      score: outcomeMatchScore(outcome, query),
    }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map(({ outcome }) => outcome);
}

function expandNumericTokens(tokens) {
  const expanded = [];
  for (const token of tokens) {
    expanded.push(token);
    const kMatch = token.match(/^(\d+(?:\.\d+)?)k$/);
    if (kMatch) {
      const value = Number(kMatch[1]) * 1000;
      if (Number.isInteger(value)) expanded.push(String(value));
      continue;
    }
    const mMatch = token.match(/^(\d+(?:\.\d+)?)m$/);
    if (mMatch) {
      const value = Number(mMatch[1]) * 1000000;
      if (Number.isInteger(value)) expanded.push(String(value));
      continue;
    }
    if (/^\d{4,}$/.test(token) && token.endsWith("000")) {
      const value = Number(token);
      if (value % 1000000 === 0) expanded.push(`${value / 1000000}m`);
      if (value % 1000 === 0) expanded.push(`${value / 1000}k`);
    }
  }
  return expanded;
}

export function levenshtein(a, b) {
  const m = a.length,
    n = b.length;
  const dp = Array.from({ length: m + 1 }, (_, i) => {
    const row = new Array(n + 1);
    row[0] = i;
    return row;
  });
  for (let j = 1; j <= n; j++) dp[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] =
        a[i - 1] === b[j - 1]
          ? dp[i - 1][j - 1]
          : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
    }
  }
  return dp[m][n];
}

const SYNONYMS = {
  btc: ["bitcoin"],
  bitcoin: ["btc"],
  eth: ["ethereum", "ether"],
  ethereum: ["eth"],
  sol: ["solana"],
  solana: ["sol"],
  xrp: ["ripple"],
  ripple: ["xrp"],
  doge: ["dogecoin"],
  dogecoin: ["doge"],
  cpi: ["inflation", "consumer price index"],
  gdp: ["economic growth", "gross domestic product"],
  fomc: ["fed", "federal reserve"],
  potus: ["president", "trump"],
  scotus: ["supreme court"],
  aoc: ["ocasio-cortez", "ocasio"],
  epl: ["premier league"],
  ufc: ["mma"],
  mma: ["ufc"],
  wemby: ["wembanyama"],
  sga: ["gilgeous-alexander", "gilgeous"],
  ai: ["artificial intelligence"],
  ipo: ["going public", "public offering"],
  nato: ["north atlantic treaty"],
  jcpoa: ["iran nuclear deal"],
  ecb: ["european central bank"],
  boj: ["bank japan"],
  rba: ["reserve bank australia"],
  mn: ["minnesota"],
  ca: ["california"],
  tx: ["texas"],
  fl: ["florida"],
  ny: ["new york"],
  ga: ["georgia"],
  pa: ["pennsylvania"],
  az: ["arizona"],
  mi: ["michigan"],
  wi: ["wisconsin"],
  nc: ["north carolina"],
  oh: ["ohio"],
  va: ["virginia"],
  nv: ["nevada"],
  il: ["illinois"],
  ma: ["massachusetts"],
  wa: ["washington"],
  co: ["colorado"],
  md: ["maryland"],
  sc: ["south carolina"],
  rates: ["interest rate", "fed"],
  housing: ["mortgage", "rent", "real estate"],
  mortgage: ["housing"],
};

function expandQuery(terms) {
  const expanded = [];
  const termOrigin = new Map();
  for (const t of terms) {
    expanded.push(t);
    termOrigin.set(t, t);
    const syns = SYNONYMS[t];
    if (syns) {
      for (const syn of syns) {
        for (const st of tokenize(syn)) {
          if (!termOrigin.has(st)) {
            expanded.push(st);
            termOrigin.set(st, t);
          }
        }
      }
    }
  }
  return { expanded, termOrigin };
}

function unpackPostings(packed) {
  if (typeof packed === "string") {
    const result = [];
    let prev = 0;
    for (const part of packed.split(",")) {
      if (!part) continue;
      const colon = part.indexOf(":");
      if (colon === -1) {
        prev += parseInt(part, 10);
        result.push([prev, 1]);
      } else {
        prev += parseInt(part.slice(0, colon), 10);
        result.push([prev, parseInt(part.slice(colon + 1), 10)]);
      }
    }
    return result;
  }
  return packed;
}

export function prepareIndex(data) {
  for (const tier of ["idx", "ctx"]) {
    if (!data[tier]) continue;
    for (const term of Object.keys(data[tier])) {
      data[tier][term] = unpackPostings(data[tier][term]);
    }
  }
  data._vocab = Object.keys(data.idx);
  data._ctxVocab = data.ctx ? Object.keys(data.ctx) : [];
  return data;
}

export function search(query, data, limit = 20, config = DEFAULT_CONFIG) {
  const rawTerms = tokenize(query);
  if (!rawTerms.length) return [];
  const { expanded: terms, termOrigin } = expandQuery(rawTerms);
  const nTerms = rawTerms.length;

  const C = config;
  const vocab = data._vocab || Object.keys(data.idx);
  const ctxVocab = data._ctxVocab || [];
  const ctxIdx = data.ctx || {};
  const avgDl = data.avgDl || 1;
  const dl = data.dl || [];

  const scores = new Map();
  const termHits = new Map();

  for (const term of terms) {
    const baseMatches = findMatches(term, data.idx, data.idf, vocab, dl, avgDl, C);
    const ctxMatches = data.ctx
      ? findMatches(term, ctxIdx, data.idf, ctxVocab, dl, avgDl, C)
      : new Map();

    const merged = new Map(baseMatches);
    for (const [docIdx, score] of ctxMatches) {
      const discounted = score * C.ctxWeight;
      merged.set(docIdx, Math.max(merged.get(docIdx) || 0, discounted));
    }

    for (const [docIdx, score] of merged) {
      scores.set(docIdx, (scores.get(docIdx) || 0) + score);
      if (!termHits.has(docIdx)) termHits.set(docIdx, new Set());
      termHits.get(docIdx).add(termOrigin.get(term) || term);
    }
  }

  const queryYears = rawTerms.filter((t) => /^20\d{2}$/.test(t));

  const results = [];
  for (const [docIdx, textScore] of scores) {
    const doc = data.docs[docIdx];
    const volBoost =
      Math.log1p(doc.v) * C.volWeight24h +
      Math.log1p(doc.vt) * C.volWeightTotal;
    const coverage = termHits.get(docIdx).size / nTerms;
    const coveragePenalty = Math.pow(coverage, C.coverageExp);

    let yearBoost = 1;
    if (queryYears.length && doc.ed) {
      const docYear = doc.ed.slice(0, 4);
      yearBoost = queryYears.includes(docYear)
        ? C.yearBoostMatch
        : C.yearBoostMiss;
    }

    results.push({
      ...doc,
      _idx: docIdx,
      _score: textScore * coveragePenalty * (1 + volBoost) * yearBoost,
    });
  }

  results.sort((a, b) => b._score - a._score);


  const districtMatch = query.match(/\b([a-z]{2})[- ]?(\d{1,2})\b/i);
  if (districtMatch) {
    const prefix = `${districtMatch[1]}-${districtMatch[2].padStart(2, "0")}`.toUpperCase();
    results.sort((a, b) => {
      const aMatch = a.q.toUpperCase().startsWith(prefix) ? 1 : 0;
      const bMatch = b.q.toUpperCase().startsWith(prefix) ? 1 : 0;
      return bMatch - aMatch || b._score - a._score;
    });
  }

  const stateKeyword = query.match(/\b([a-z]{2})\s+(senate|governor|house)\b/i);
  if (stateKeyword) {
    const stAbbr = stateKeyword[1].toUpperCase();
    const stName = SYNONYMS[stateKeyword[1].toLowerCase()]?.[0] || "";
    const kw = stateKeyword[2].toLowerCase();
    results.sort((a, b) => {
      const ql = (s) => s.q.toLowerCase();
      const aHas = (ql(a).includes(kw) && (ql(a).includes(stName) || a.q.includes(stAbbr))) ? 1 : 0;
      const bHas = (ql(b).includes(kw) && (ql(b).includes(stName) || b.q.includes(stAbbr))) ? 1 : 0;
      return bHas - aHas || b._score - a._score;
    });
  }

  return results.slice(0, limit);
}

export function searchMany(query, sources, limit = 20, config = DEFAULT_CONFIG) {
  const merged = [];
  for (const source of sources) {
    if (!source?.data) continue;
    const multiplier = source.scoreMultiplier ?? 1;
    const results = search(query, source.data, limit, config);
    for (const result of results) {
      merged.push({
        ...result,
        ar: source.archived ? 1 : result.ar,
        _score: result._score * multiplier,
      });
    }
  }
  merged.sort((a, b) => b._score - a._score);
  return merged.slice(0, limit);
}

export function topByVolumeMany(sources, limit = 20) {
  const merged = [];
  for (const source of sources) {
    if (!source?.data) continue;
    const multiplier = source.volumeMultiplier ?? 1;
    for (const doc of source.data.docs || []) {
      merged.push({
        ...doc,
        ar: source.archived ? 1 : doc.ar,
        _volumeScore: (doc.vt || doc.v || 0) * multiplier,
      });
    }
  }
  merged.sort((a, b) => b._volumeScore - a._volumeScore);
  return merged.slice(0, limit);
}

export function docTags(doc) {
  const tags = doc?.tg || [];
  if (Array.isArray(tags)) return tags.filter(Boolean);
  if (typeof tags === "string") return tags.split(/\s+/).filter(Boolean);
  return [];
}

export function parseFilterParam(value) {
  if (!value) return [];
  const seen = new Set();
  const filters = [];
  for (const raw of value.split(",")) {
    const tag = raw.trim();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    filters.push(tag);
  }
  return filters;
}

export function serializeFilterParam(filters) {
  return [...new Set(filters.map((tag) => tag.trim()).filter(Boolean))].join(",");
}

export function docsMatchingTags(docs, filters) {
  if (!filters.length) return docs;
  return docs.filter((doc) => {
    const tags = docTags(doc);
    return filters.every((filter) => tags.includes(filter));
  });
}

export function topTagsForDocs(
  docs,
  {
    activeFilters = [],
    hiddenTags = [],
    includeUniversal = false,
    limit = 8,
    weightByScore = false,
  } = {},
) {
  const counts = {};
  const docCounts = {};
  const hidden = new Set(hiddenTags);
  const active = new Set(activeFilters);
  for (const doc of docs) {
    const weight = weightByScore && Number.isFinite(doc._score)
      ? Math.max(doc._score, 0)
      : 1;
    for (const tag of docTags(doc)) {
      if (hidden.has(tag) || active.has(tag)) continue;
      counts[tag] = (counts[tag] || 0) + weight;
      docCounts[tag] = (docCounts[tag] || 0) + 1;
    }
  }
  return Object.entries(counts)
    .filter(([tag]) => includeUniversal || docCounts[tag] < docs.length)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([tag]) => tag);
}

function bm25Score(tf, idf, docLen, avgDl, K1, B) {
  const norm = 1 - B + B * (docLen / avgDl);
  return idf * ((tf * (K1 + 1)) / (tf + K1 * norm));
}

function findMatches(term, idx, idf, vocab, dl, avgDl, C) {
  const seen = new Map();
  const K1 = C.bm25K1;
  const B = C.bm25B;

  function add(docIdx, score) {
    seen.set(docIdx, Math.max(seen.get(docIdx) || 0, score));
  }

  const termIdf = idf[term] || 0;

  if (idx[term]) {
    for (const posting of idx[term]) {
      const [docIdx, tf] = posting;
      const docLen = dl[docIdx] || avgDl;
      add(docIdx, bm25Score(tf, termIdf, docLen, avgDl, K1, B));
    }
  }

  for (const vt of vocab) {
    if (vt === term) continue;
    if (vt.startsWith(term)) {
      const vtIdf = idf[vt] || 0;
      for (const posting of idx[vt]) {
        const [docIdx, tf] = posting;
        const docLen = dl[docIdx] || avgDl;
        add(docIdx, bm25Score(tf, vtIdf, docLen, avgDl, K1, B) * C.prefixDiscount);
      }
    }
  }

  if (term.length >= C.fuzzyMinLen) {
    const maxDist = Math.ceil(term.length * C.fuzzyMaxDistFrac);
    const fuzzyCandidates = [];
    for (const vt of vocab) {
      if (vt === term || vt.startsWith(term)) continue;
      if (Math.abs(vt.length - term.length) > maxDist) continue;
      if (vt.slice(0, 2) !== term.slice(0, 2)) continue;
      const dist = levenshtein(term, vt);
      if (dist <= maxDist) fuzzyCandidates.push({ vt, dist });
    }
    const bestDist = Math.min(...fuzzyCandidates.map((c) => c.dist), 99);
    const bestCandidates = fuzzyCandidates.filter((c) => c.dist === bestDist);
    const mostCommon = bestCandidates.reduce(
      (best, c) => ((idf[c.vt] || 99) < (idf[best.vt] || 99) ? c : best),
      bestCandidates[0] || { vt: "" },
    );
    const idfCap = idf[mostCommon.vt] || 1;

    for (const { vt, dist } of fuzzyCandidates) {
      const vtIdf = Math.min(idf[vt] || 0, idfCap * 1.5);
      const fuzzyMult = (1 - dist / term.length) * C.fuzzyDiscount;
      for (const posting of idx[vt]) {
        const [docIdx, tf] = posting;
        const docLen = dl[docIdx] || avgDl;
        add(docIdx, bm25Score(tf, vtIdf, docLen, avgDl, K1, B) * fuzzyMult);
      }
    }
  }

  return seen;
}
