import { prepareIndex, search } from "../../public/search.js";

const INDEX_URL = "https://aburkard.github.io/polymarket-search/search-data.json";
const CACHE_TTL_MS = 5 * 60 * 1000;

let cached = null;
let cachedAt = 0;
let inflight = null;

function expandImages(data) {
  const pfx = data.imgPfx || "";
  for (const doc of data.docs) {
    if (doc.im && !doc.im.startsWith("http")) doc.im = pfx + doc.im;
    for (const mk of doc.mk || []) {
      if (mk.im && !mk.im.startsWith("http")) mk.im = pfx + mk.im;
    }
    for (const tm of doc.tm || []) {
      if (tm.l && !tm.l.startsWith("http")) tm.l = pfx + tm.l;
    }
  }
}

async function loadIndex() {
  const now = Date.now();
  if (cached && now - cachedAt < CACHE_TTL_MS) return cached;
  if (inflight) return inflight;

  inflight = (async () => {
    const resp = await fetch(INDEX_URL, { cf: { cacheTtl: 300 } });
    if (!resp.ok) throw new Error(`Failed to fetch index: HTTP ${resp.status}`);
    const raw = await resp.json();
    expandImages(raw);
    cached = prepareIndex(raw);
    cachedAt = Date.now();
    inflight = null;
    return cached;
  })();

  try {
    return await inflight;
  } catch (e) {
    inflight = null;
    throw e;
  }
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=60",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
    },
  });
}

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    if (request.method !== "GET") {
      return jsonResponse({ error: "Method not allowed" }, 405);
    }

    const url = new URL(request.url);
    const query = url.searchParams.get("q") || "";
    const limit = Math.min(
      Math.max(parseInt(url.searchParams.get("limit") || "20", 10), 1),
      100,
    );

    // No query params at all: return API info
    if (!query && !url.searchParams.has("limit") && !url.searchParams.has("trending")) {
      return jsonResponse({
        name: "polymarket-search",
        description: "JSON search API for Polymarket prediction markets",
        usage: {
          search: `${url.origin}/?q=YOUR_QUERY`,
          trending: `${url.origin}/?trending=1&limit=20`,
        },
        parameters: {
          q: "search query string. Supports typos, abbreviations, nicknames.",
          limit: "number of results (default 20, max 100)",
          trending: "set to any value to fetch top events by volume (when q is empty)",
        },
        docs: "https://aburkard.github.io/polymarket-search/llms.txt",
        source: "https://github.com/aburkard/polymarket-search",
      });
    }

    try {
      const data = await loadIndex();
      const results = query
        ? search(query, data, limit)
        : [...data.docs].sort((a, b) => b.vt - a.vt).slice(0, limit);

      return jsonResponse({
        query: query || null,
        count: results.length,
        results,
      });
    } catch (e) {
      return jsonResponse({ error: e.message }, 500);
    }
  },
};
