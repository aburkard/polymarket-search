import { prepareIndex, searchMany, topByVolumeMany } from "../../public/search.js";

const INDEX_URL = "https://aburkard.github.io/polymarket-search/search-data.json";
const ARCHIVED_INDEX_URL = "https://aburkard.github.io/polymarket-search/search-data-archived.json";
const CACHE_TTL_MS = 5 * 60 * 1000;

const caches = new Map();

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

async function loadIndex(indexUrl) {
  const state = caches.get(indexUrl) || { cached: null, cachedAt: 0, inflight: null };
  const now = Date.now();
  if (state.cached && now - state.cachedAt < CACHE_TTL_MS) return state.cached;
  if (state.inflight) return state.inflight;

  state.inflight = (async () => {
    const resp = await fetch(indexUrl, { cf: { cacheTtl: 300 } });
    if (!resp.ok) throw new Error(`Failed to fetch index: HTTP ${resp.status}`);
    const raw = await resp.json();
    expandImages(raw);
    state.cached = prepareIndex(raw);
    state.cachedAt = Date.now();
    state.inflight = null;
    caches.set(indexUrl, state);
    return state.cached;
  })();
  caches.set(indexUrl, state);

  try {
    return await state.inflight;
  } catch (e) {
    state.inflight = null;
    caches.set(indexUrl, state);
    throw e;
  }
}

function parseBoolParam(url, name) {
  const value = url.searchParams.get(name);
  return value === "1" || value === "true" || value === "yes";
}

function indexMeta(data) {
  return {
    updatedAt: data.ts || null,
    events: data.n || 0,
  };
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
          archivedSearch: `${url.origin}/?q=YOUR_QUERY&archived=1`,
        },
        parameters: {
          q: "search query string. Supports typos, abbreviations, nicknames.",
          limit: "number of results (default 20, max 100)",
          trending: "set to any value to fetch top events by volume (when q is empty)",
          archived: "set to 1/true/yes to include resolved archived markets",
        },
        responseMeta: {
          indexes: "active and archived index timestamps/event counts when data is returned",
        },
        docs: "https://aburkard.github.io/polymarket-search/llms.txt",
        source: "https://github.com/aburkard/polymarket-search",
      });
    }

    try {
      const includeArchived =
        parseBoolParam(url, "archived") || parseBoolParam(url, "include_archived");
      const data = await loadIndex(INDEX_URL);
      const archivedData = includeArchived
        ? await loadIndex(ARCHIVED_INDEX_URL)
        : null;
      const sources = [{ data, archived: false }];
      if (archivedData) {
        sources.push({
          data: archivedData,
          archived: true,
          scoreMultiplier: 0.92,
          volumeMultiplier: 0.75,
        });
      }
      const results = query
        ? searchMany(query, sources, limit)
        : topByVolumeMany(sources, limit);

      return jsonResponse({
        query: query || null,
        archived: includeArchived,
        count: results.length,
        meta: {
          indexes: {
            active: indexMeta(data),
            archived: archivedData ? indexMeta(archivedData) : null,
          },
        },
        results,
      });
    } catch (e) {
      return jsonResponse({ error: e.message }, 500);
    }
  },
};
