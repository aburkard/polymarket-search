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
  return data;
}

export function search(query, data, limit = 20) {
  const terms = tokenize(query);
  if (!terms.length) return [];

  const vocab = data._vocab || Object.keys(data.idx);
  const scores = new Map();

  for (const term of terms) {
    const matches = findMatches(term, data.idx, data.idf, vocab);
    for (const [docIdx, score] of matches) {
      scores.set(docIdx, (scores.get(docIdx) || 0) + score);
    }
  }

  const results = [];
  for (const [docIdx, textScore] of scores) {
    const doc = data.docs[docIdx];
    const volBoost = Math.log1p(doc.v) * 0.5;
    results.push({
      ...doc,
      _idx: docIdx,
      _score: textScore * (1 + volBoost),
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
      const dist = levenshtein(term, vt);
      if (dist <= maxDist) {
        const s = (idf[vt] || 1) * (1 - dist / term.length) * 0.6;
        for (const docIdx of idx[vt]) add(docIdx, s);
      }
    }
  }

  return seen;
}
