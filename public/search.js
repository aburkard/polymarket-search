export function tokenize(text) {
  return text
    .toLowerCase()
    .replace(/[$%,]/g, "")
    .replace(/[^a-z0-9.]/g, " ")
    .split(/\s+/)
    .map((t) => t.replace(/^\.+|\.+$/g, ""))
    .filter((t) => t.length >= 2);
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

export function prepareIndex(data) {
  data._vocab = Object.keys(data.idx);
  data._ctxVocab = data.ctx ? Object.keys(data.ctx) : [];
  return data;
}

export function search(query, data, limit = 20) {
  const terms = tokenize(query);
  if (!terms.length) return [];

  const vocab = data._vocab || Object.keys(data.idx);
  const scores = new Map();
  const termHits = new Map();

  const ctxVocab = data._ctxVocab || [];
  const ctxIdx = data.ctx || {};

  for (const term of terms) {
    const baseMatches = findMatches(term, data.idx, data.idf, vocab);
    const ctxMatches = data.ctx
      ? findMatches(term, ctxIdx, data.idf, ctxVocab)
      : new Map();

    const merged = new Map(baseMatches);
    for (const [docIdx, score] of ctxMatches) {
      const discounted = score * 0.3;
      merged.set(docIdx, Math.max(merged.get(docIdx) || 0, discounted));
    }

    for (const [docIdx, score] of merged) {
      scores.set(docIdx, (scores.get(docIdx) || 0) + score);
      if (!termHits.has(docIdx)) termHits.set(docIdx, new Set());
      termHits.get(docIdx).add(term);
    }
  }

  const nTerms = terms.length;
  const queryYears = terms.filter((t) => /^20\d{2}$/.test(t));

  const results = [];
  for (const [docIdx, textScore] of scores) {
    const doc = data.docs[docIdx];
    const volBoost = Math.log1p(doc.v) * 0.4 + Math.log1p(doc.vt) * 0.2;
    const coverage = termHits.get(docIdx).size / nTerms;
    const coveragePenalty = coverage * coverage * coverage;

    let yearBoost = 1;
    if (queryYears.length && doc.ed) {
      const docYear = doc.ed.slice(0, 4);
      yearBoost = queryYears.includes(docYear) ? 2 : 0.3;
    }

    results.push({
      ...doc,
      _idx: docIdx,
      _score: textScore * coveragePenalty * (1 + volBoost) * yearBoost,
    });
  }

  results.sort((a, b) => b._score - a._score);
  return results.slice(0, limit);
}

function findMatches(term, idx, idf, vocab) {
  const seen = new Map();

  function add(docIdx, score) {
    seen.set(docIdx, Math.max(seen.get(docIdx) || 0, score));
  }

  if (idx[term]) {
    const s = (idf[term] || 1) * 2;
    for (const docIdx of idx[term]) add(docIdx, s);
  }

  for (const vt of vocab) {
    if (vt === term) continue;
    if (vt.startsWith(term)) {
      const s = (idf[vt] || 1) * 0.8;
      for (const docIdx of idx[vt]) add(docIdx, s);
    }
  }

  if (term.length >= 4) {
    const maxDist = Math.ceil(term.length * 0.25);
    for (const vt of vocab) {
      if (vt === term || vt.startsWith(term)) continue;
      if (Math.abs(vt.length - term.length) > maxDist) continue;
      if (vt.slice(0, 2) !== term.slice(0, 2)) continue;
      const dist = levenshtein(term, vt);
      if (dist <= maxDist) {
        const s = (idf[vt] || 1) * (1 - dist / term.length) * 0.6;
        for (const docIdx of idx[vt]) add(docIdx, s);
      }
    }
  }

  return seen;
}
