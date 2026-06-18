import { prepareIndex, searchMany, topByVolumeMany } from "../../public/search.js";

const INDEX_URL = "https://aburkard.github.io/polymarket-search/search-data.json";
const ARCHIVED_INDEX_URL = "https://aburkard.github.io/polymarket-search/search-data-archived.json";
const KALSHI_INDEX_URL = "https://aburkard.github.io/polymarket-search/search-data-kalshi.json";
const KALSHI_ARCHIVED_INDEX_URL = "https://aburkard.github.io/polymarket-search/search-data-kalshi-archived.json";
const KALSHI_API_BASE = "https://external-api.kalshi.com/trade-api/v2";
const CACHE_TTL_MS = 5 * 60 * 1000;
const KALSHI_LIVE_MAX_ATTEMPTS = 3;
const KALSHI_RETRY_STATUSES = new Set([429, 500, 502, 503, 504]);

const caches = new Map();
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

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

function normalizeProvider(value) {
  return value === "kalshi" ? "kalshi" : "polymarket";
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=60",
      ...CORS_HEADERS,
    },
  });
}

function parseKalshiEventTicker(pathname) {
  const match = pathname.match(/^\/kalshi\/events\/([A-Za-z0-9_-]{3,100})$/);
  return match ? match[1].toUpperCase() : "";
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function retryAfterMs(value) {
  if (!value) return 0;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;
  const dateMs = Date.parse(value);
  return Number.isFinite(dateMs) ? Math.max(dateMs - Date.now(), 0) : 0;
}

function kalshiRetryDelay(resp, attempt) {
  const retryAfter = retryAfterMs(resp.headers.get("Retry-After"));
  if (retryAfter > 0) return Math.min(retryAfter, 5000);
  return Math.min(3000, 600 * 2 ** attempt) + Math.floor(Math.random() * 250);
}

async function fetchKalshiEvent(upstream) {
  let resp = null;
  for (let attempt = 0; attempt < KALSHI_LIVE_MAX_ATTEMPTS; attempt += 1) {
    resp = await fetch(upstream, {
      headers: {
        "User-Agent": "market-search-live/0.1 (andrewburkard@gmail.com)",
      },
      cf: {
        cacheEverything: true,
        cacheTtl: 10,
      },
    });

    const shouldRetry =
      KALSHI_RETRY_STATUSES.has(resp.status) && attempt < KALSHI_LIVE_MAX_ATTEMPTS - 1;
    if (!shouldRetry) return resp;

    try {
      await resp.body?.cancel();
    } catch (_) {
      // Ignore cancellation errors; the response is being discarded before retry.
    }
    await sleep(kalshiRetryDelay(resp, attempt));
  }
  return resp;
}

async function kalshiEventResponse(ticker) {
  if (!ticker) {
    return jsonResponse({ error: "Missing Kalshi event ticker" }, 400);
  }

  const upstream = `${KALSHI_API_BASE}/markets?event_ticker=${encodeURIComponent(ticker)}&limit=100`;
  const resp = await fetchKalshiEvent(upstream);

  const headers = new Headers({
    "Content-Type": resp.headers.get("Content-Type") || "application/json; charset=utf-8",
    "Cache-Control": "public, max-age=10, stale-while-revalidate=60",
    ...CORS_HEADERS,
  });
  const retryAfter = resp.headers.get("Retry-After");
  if (retryAfter) headers.set("Retry-After", retryAfter);

  return new Response(resp.body, {
    status: resp.status,
    statusText: resp.statusText,
    headers,
  });
}

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          ...CORS_HEADERS,
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    if (request.method !== "GET") {
      return jsonResponse({ error: "Method not allowed" }, 405);
    }

    const url = new URL(request.url);
    const kalshiTicker = parseKalshiEventTicker(url.pathname);
    if (url.pathname.startsWith("/kalshi/events/")) {
      return kalshiEventResponse(kalshiTicker);
    }

    const query = url.searchParams.get("q") || "";
    const limit = Math.min(
      Math.max(parseInt(url.searchParams.get("limit") || "20", 10), 1),
      100,
    );

    // No query params at all: return API info
    if (!query && !url.searchParams.has("limit") && !url.searchParams.has("trending")) {
      return jsonResponse({
        name: "market-search",
        description: "JSON search API for Polymarket and Kalshi prediction markets",
        usage: {
          search: `${url.origin}/?q=YOUR_QUERY`,
          kalshiSearch: `${url.origin}/?q=YOUR_QUERY&provider=kalshi`,
          trending: `${url.origin}/?trending=1&limit=20`,
          archivedSearch: `${url.origin}/?q=YOUR_QUERY&archived=1`,
          kalshiArchivedSearch: `${url.origin}/?q=YOUR_QUERY&provider=kalshi&archived=1`,
          kalshiLiveEvent: `${url.origin}/kalshi/events/KXBTC-26JUN`,
        },
        parameters: {
          q: "search query string. Supports typos, abbreviations, nicknames.",
          provider: "market source. Use kalshi for Kalshi; defaults to polymarket.",
          limit: "number of results (default 20, max 100)",
          trending: "set to any value to fetch top events by volume (when q is empty)",
          archived: "set to 1/true/yes to include archived markets for supported providers",
        },
        responseMeta: {
          indexes: "active and archived index build timestamps/event counts when data is returned; Worker results use bundled index prices",
        },
        docs: "https://aburkard.github.io/polymarket-search/llms.txt",
        source: "https://github.com/aburkard/polymarket-search",
      });
    }

    try {
      const provider = normalizeProvider(url.searchParams.get("provider"));
      const includeArchived =
        parseBoolParam(url, "archived") || parseBoolParam(url, "include_archived");
      const data = await loadIndex(provider === "kalshi" ? KALSHI_INDEX_URL : INDEX_URL);
      const archivedData = includeArchived
        ? await loadIndex(provider === "kalshi" ? KALSHI_ARCHIVED_INDEX_URL : ARCHIVED_INDEX_URL)
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
        provider,
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
