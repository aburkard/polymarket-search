import {
  docsMatchingTags,
  outcomeMatchScore,
  parseFilterParam,
  prepareIndex,
  isTemporalOutcomeGroup,
  rankOutcomesForDisplay,
  searchMany,
  serializeFilterParam,
  topByVolumeMany,
  topTagsForDocs,
} from "./search.js?v=6";

const PROVIDERS = {
  polymarket: {
    label: "Polymarket",
    script: "search-data.js",
    globalName: "__SD__",
    supportsArchived: true,
    archivedScript: "search-data-archived.js",
    archivedGlobalName: "__SDA__",
  },
  kalshi: {
    label: "Kalshi",
    script: "search-data-kalshi.js",
    globalName: "__SDK__",
    supportsArchived: true,
    archivedScript: "search-data-kalshi-archived.js",
    archivedGlobalName: "__SDKA__",
  },
  manifold: {
    label: "Manifold",
    script: "search-data-manifold.js",
    globalName: "__SDM__",
    supportsArchived: false,
  },
};
const KALSHI_LIVE_EVENTS_URL = "https://polymarket-search-api.wkr0.workers.dev/kalshi/events";
const KALSHI_LIVE_CONCURRENCY = 2;
const KALSHI_LIVE_DELAY_MS = 350;

const providerState = Object.fromEntries(
  Object.keys(PROVIDERS).map((name) => [
    name,
    { data: null, archivedData: null, archivedLoadPromise: null, loadPromise: null },
  ]),
);

let provider = "polymarket";
let data = null;
let archivedData = null;
let archivedLoadPromise = null;
let includeArchived = false;
let debounceTimer = null;
let selectedIdx = -1;
let activeFilters = [];
let currentQuery = "";
let resultRenderToken = 0;

const HIDDEN_TAGS = new Set([
  "Hide From New", "Recurring", "Up or Down", "Games", "5M", "15M",
  "1H", "Rewards", "New", "Earn 4%", "Rewards 20, 4.5, 50",
  "Rewards Automation 50 4.5 50", "Crypto Prices",
]);

const input = document.getElementById("search-input");
const resultsEl = document.getElementById("results");
const statusEl = document.getElementById("status");
const archiveToggle = document.getElementById("archive-toggle");
const archiveToggleLabel = archiveToggle.closest(".archive-toggle");
const providerToggle = document.querySelector(".provider-toggle");
const FILTER_PARAM = "tags";
const PROVIDER_PARAM = "provider";

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

function activeProviderConfig() {
  return PROVIDERS[provider] || PROVIDERS.polymarket;
}

function syncProviderState() {
  const state = providerState[provider];
  data = state.data;
  archivedData = state.archivedData;
  archivedLoadPromise = state.archivedLoadPromise;
}

function normalizeProvider(value) {
  return PROVIDERS[value] ? value : "polymarket";
}

function setProviderUi() {
  const cfg = activeProviderConfig();
  providerToggle.querySelectorAll(".provider-option").forEach((button) => {
    const active = button.dataset.provider === provider;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  archiveToggleLabel.classList.toggle("is-hidden", !cfg.supportsArchived);
  archiveToggleLabel.setAttribute("aria-hidden", cfg.supportsArchived ? "false" : "true");
  archiveToggle.disabled = !cfg.supportsArchived;
  if (!cfg.supportsArchived) {
    archiveToggle.checked = false;
  }
}

async function loadProviderData(name) {
  const cfg = PROVIDERS[name];
  const state = providerState[name];
  if (state.data) return state.data;
  if (!state.loadPromise) {
    state.loadPromise = loadScriptOnce(cfg.script, cfg.globalName)
      .then((raw) => {
        expandImages(raw);
        state.data = prepareIndex(raw);
        return state.data;
      })
      .catch((err) => {
        state.loadPromise = null;
        throw err;
      });
  }
  return state.loadPromise;
}

function updateStatus(message = "") {
  if (!data) {
    statusEl.textContent = message || "Loading...";
    statusEl.classList.remove("is-stale");
    return;
  }
  if (message) {
    statusEl.textContent = message;
    statusEl.classList.remove("is-stale");
    return;
  }
  if (activeProviderConfig().supportsArchived && includeArchived && !archivedData) {
    statusEl.textContent = "Loading archived...";
    statusEl.classList.remove("is-stale");
    return;
  }
  const total = data.n + (
    activeProviderConfig().supportsArchived && includeArchived && archivedData
      ? archivedData.n
      : 0
  );
  statusEl.classList.remove("is-stale");
  statusEl.textContent = `${total.toLocaleString()} events`;
}

function indexMeta(indexData) {
  return {
    updatedAt: indexData.ts || null,
    events: indexData.n || 0,
  };
}

function loadScriptOnce(src, globalName) {
  if (self[globalName]) return Promise.resolve(self[globalName]);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => {
      if (self[globalName]) {
        resolve(self[globalName]);
      } else {
        reject(new Error(`Missing ${globalName}`));
      }
    };
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

async function loadArchivedData() {
  const providerName = provider;
  const cfg = activeProviderConfig();
  const state = providerState[providerName];
  if (!cfg.supportsArchived) return null;
  if (state.archivedData) return state.archivedData;
  if (!state.archivedLoadPromise) {
    updateStatus();
    state.archivedLoadPromise = loadScriptOnce(cfg.archivedScript, cfg.archivedGlobalName)
      .then((raw) => {
        expandImages(raw);
        state.archivedData = prepareIndex(raw);
        if (provider === providerName) {
          archivedData = state.archivedData;
          archivedLoadPromise = state.archivedLoadPromise;
          updateStatus();
        }
        return state.archivedData;
      })
      .catch((err) => {
        state.archivedLoadPromise = null;
        if (provider === providerName) {
          archivedLoadPromise = null;
          includeArchived = false;
          archiveToggle.checked = false;
          const url = new URL(window.location);
          url.searchParams.delete("archived");
          history.replaceState(null, "", url);
          updateStatus("Archived index unavailable");
        }
        throw err;
      });
  }
  archivedLoadPromise = state.archivedLoadPromise;
  return state.archivedLoadPromise;
}

function getSources() {
  const sources = [{ data, archived: false }];
  if (activeProviderConfig().supportsArchived && includeArchived && archivedData) {
    sources.push({
      data: archivedData,
      archived: true,
      scoreMultiplier: 0.92,
      volumeMultiplier: 0.75,
    });
  }
  return sources;
}

async function onDataReady() {
  const params = new URLSearchParams(window.location.search);
  provider = normalizeProvider(params.get(PROVIDER_PARAM) || "polymarket");
  setProviderUi();
  updateStatus(`Loading ${activeProviderConfig().label}...`);
  try {
    await loadProviderData(provider);
  } catch {
    statusEl.textContent = `Failed to load ${activeProviderConfig().label}`;
    return;
  }
  syncProviderState();

  const urlQuery = params.get("q");
  activeFilters = parseFilterParam(params.get(FILTER_PARAM));
  includeArchived = activeProviderConfig().supportsArchived && params.get("archived") === "1";
  archiveToggle.checked = includeArchived;
  setProviderUi();

  if (params.get("format") === "json") {
    if (includeArchived) {
      try { await loadArchivedData(); } catch {}
    }
    const limit = Math.min(parseInt(params.get("limit") || "20", 10), 100);
    let results;
    if (urlQuery) {
      results = searchMany(urlQuery, getSources(), Math.max(limit * 4, 50));
      if (activeFilters.length) results = docsMatchingTags(results, activeFilters);
    } else if (activeFilters.length) {
      results = docsMatchingTags(getAllDocs(), activeFilters)
        .sort((a, b) => (b.vt || b.v || 0) - (a.vt || a.v || 0));
    } else {
      results = topByVolumeMany(getSources(), limit);
    }
    results = results.slice(0, limit);
    document.documentElement.innerHTML = `<pre id="json">${JSON.stringify(
      {
        query: urlQuery || null,
        provider,
        archived: includeArchived,
        filters: activeFilters,
        count: results.length,
        meta: {
          indexes: {
            active: indexMeta(data),
            archived: archivedData ? indexMeta(archivedData) : null,
          },
        },
        results,
      },
      null,
      2,
    )}</pre>`;
    return;
  }

  updateStatus();
  input.disabled = false;
  if (urlQuery) {
    input.value = urlQuery;
    currentQuery = urlQuery;
    input.closest(".search-wrap").classList.add("has-value");
  }
  renderFilters();
  if (includeArchived) {
    try { await loadArchivedData(); } catch {}
    renderFilters();
  }
  if (urlQuery) {
    await updateResults();
  } else if (activeFilters.length) {
    await updateResults();
  } else {
    input.focus();
    showTrending();
  }
}

function init() {
  statusEl.textContent = "Loading...";
  onDataReady();
}

// ── Keyboard ────────────────────────────────────────────────────────

document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement !== input) {
    e.preventDefault();
    input.focus();
    input.select();
  }
  if (e.key === "Escape") {
    if (input.value) {
      input.value = "";
      handleInput();
    } else {
      input.blur();
    }
  }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (document.activeElement !== input && selectedIdx < 0) return;
    const cards = resultsEl.querySelectorAll(".result");
    if (!cards.length) return;
    e.preventDefault();
    cards[selectedIdx]?.removeAttribute("aria-selected");
    if (e.key === "ArrowDown") {
      selectedIdx = Math.min(selectedIdx + 1, cards.length - 1);
    } else {
      selectedIdx = Math.max(selectedIdx - 1, -1);
    }
    if (selectedIdx === -1) {
      input.focus();
    } else {
      cards[selectedIdx]?.setAttribute("aria-selected", "true");
      cards[selectedIdx]?.scrollIntoView({ block: "nearest" });
      cards[selectedIdx]?.focus();
    }
  }
  if (e.key === "Enter" && selectedIdx >= 0) {
    const card = resultsEl.querySelectorAll(".result")[selectedIdx];
    if (card) window.open(card.href, "_blank");
  }
});

// ── Search handling ────────────────────────────────────────────────

function handleInput() {
  clearTimeout(debounceTimer);
  selectedIdx = -1;
  debounceTimer = setTimeout(() => {
    const query = input.value.trim();
    currentQuery = query;
    const url = new URL(window.location);
    if (query) {
      url.searchParams.set("q", query);
    } else {
      url.searchParams.delete("q");
    }
    history.replaceState(null, "", url);

    renderFilters();
    updateResults();
    window.scrollTo({ top: 0 });
  }, 80);
}

const filtersEl = document.getElementById("filters");

function displayTag(tag) {
  return tag.replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

function getAllDocs() {
  return getSources().flatMap((source) =>
    (source.data.docs || []).map((doc) => ({
      ...doc,
      ar: source.archived ? 1 : doc.ar,
    })),
  );
}

function getFilteredDocs() {
  if (!data || !activeFilters.length) return null;
  return docsMatchingTags(getAllDocs(), activeFilters);
}

function getQueryDocs(query) {
  if (!query) return null;
  return searchMany(query, getSources(), 80);
}

function getFilterPool() {
  const queryDocs = getQueryDocs(input.value.trim());
  const docs = queryDocs || getAllDocs();
  return docsMatchingTags(docs, activeFilters);
}

function renderFilters() {
  if (!data) { filtersEl.innerHTML = ""; return; }
  const pool = getFilterPool();
  const tags = topTagsForDocs(pool, {
    activeFilters,
    hiddenTags: HIDDEN_TAGS,
    includeUniversal: Boolean(input.value.trim()),
    weightByScore: Boolean(input.value.trim()),
  });

  const activePills = activeFilters
    .map((f) => `<button class="filter-pill active" data-tag="${esc(f)}">${esc(displayTag(f))} ✕</button>`)
    .join("");
  const tagPills = tags
    .map((t) => `<button class="filter-pill" data-tag="${esc(t)}">${esc(displayTag(t))}</button>`)
    .join("");

  filtersEl.innerHTML = activePills + tagPills;
}

filtersEl.addEventListener("click", (e) => {
  const pill = e.target.closest(".filter-pill");
  if (!pill) return;
  const tag = pill.dataset.tag;
  if (activeFilters.includes(tag)) {
    activeFilters = activeFilters.filter((f) => f !== tag);
  } else {
    activeFilters.push(tag);
  }
  syncFilterUrl();
  renderFilters();
  updateResults();
});

function syncFilterUrl() {
  const url = new URL(window.location);
  const value = serializeFilterParam(activeFilters);
  if (value) {
    url.searchParams.set(FILTER_PARAM, value);
  } else {
    url.searchParams.delete(FILTER_PARAM);
  }
  history.replaceState(null, "", url);
}

function syncProviderUrl() {
  const url = new URL(window.location);
  if (provider === "polymarket") {
    url.searchParams.delete(PROVIDER_PARAM);
  } else {
    url.searchParams.set(PROVIDER_PARAM, provider);
    url.searchParams.delete("archived");
  }
  history.replaceState(null, "", url);
}

async function updateResults() {
  const renderToken = ++resultRenderToken;
  const query = input.value.trim();
  currentQuery = query;
  if (!data) return;
  if (includeArchived && !archivedData) {
    try {
      await loadArchivedData();
      if (renderToken !== resultRenderToken) return;
      renderFilters();
    } catch {
      return;
    }
  }

  if (!query && !activeFilters.length) {
    showTrending(renderToken);
    return;
  }

  let results;
  if (query) {
    results = searchMany(query, getSources(), 50);
  } else {
    results = [...(getFilteredDocs() || data.docs)]
      .sort((a, b) => b.vt - a.vt);
  }

  if (activeFilters.length) {
    results = docsMatchingTags(results, activeFilters);
  }

  results = results.slice(0, 12);
  if (renderToken !== resultRenderToken) return;
  lastRendered = results;
  if (results.length) {
    resultsEl.innerHTML = results.map((r) => renderCard(r)).join("");
    refreshLivePrices(results);
  } else {
    resultsEl.innerHTML = '<div class="no-results">No markets found</div>';
  }
}

function showTrending(renderToken = ++resultRenderToken) {
  if (!data) return;
  if (renderToken !== resultRenderToken) return;
  currentQuery = "";
  const trending = topByVolumeMany(getSources(), 10);
  lastRendered = trending;
  resultsEl.innerHTML =
    '<div class="section-label">Trending</div>' +
    trending.map((r) => renderCard(r)).join("");
  refreshLivePrices(trending);
}

let lastRendered = [];

function renderResults(results) {
  if (!results.length) {
    resultsEl.innerHTML = '<div class="no-results">No markets found</div>';
    lastRendered = [];
    return;
  }
  lastRendered = results;
  resultsEl.innerHTML = results.map((r) => renderCard(r)).join("");
  refreshLivePrices(results);
}

// ── Card rendering ──────────────────────────────────────────────────

function renderCard(r) {
  const url = resultUrl(r);
  if (r.tm) return renderSportCard(r, url);

  const img = resultImageHtml(r);

  const outcomes = rankOutcomesForDisplay(r, currentQuery).slice(0, 5);
  let rowsHtml = "";

  if (outcomes.length === 1) {
    const p = outcomes[0].op?.[0];
    const pct = p != null ? Math.round(p * 100) : null;
    if (pct != null) {
      const yesLeads = pct >= 50;
      const thin = outcomes[0].thin ? " is-thin" : "";
      rowsHtml = `
        <div class="outcome-row ${yesLeads ? "" : "is-dim"}${thin}">
          <span class="outcome-label">Yes</span>
          <span class="outcome-pct">${pct}%${priceTipHtml(outcomes[0])}</span>
        </div>
        <div class="outcome-row ${yesLeads ? "is-dim is-no" : "is-no"}${thin}">
          <span class="outcome-label">No</span>
          <span class="outcome-pct">${100 - pct}%</span>
        </div>`;
    }
  } else if (outcomes.length > 1) {
    const visible = outcomes.filter((o) => {
      const p = o.op?.[0];
      return p != null && Math.round(p * 100) >= 1;
    });
    const show = (visible.length ? visible : outcomes.slice(0, 2)).slice(0, 3);
    const isTemporal = isTemporalOutcomeGroup(r, show);
    rowsHtml = show
      .map((o, i) => {
        const p = o.op?.[0];
        const pct = p != null ? Math.round(p * 100) + "%" : "–";
        const label = o.l || shortenQuestion(o.q, r.q);
        const oImg = o.im ? `<img src="${o.im}" alt="" class="outcome-icon" loading="lazy">` : "";
        const thin = o.thin ? " is-thin" : "";
        const isQueryMatch = currentQuery && outcomeMatchScore(o, currentQuery) > 0;
        const cls = [
          isTemporal ? "is-temporal" : (i > 0 ? "is-dim" : ""),
          isQueryMatch ? "is-query-match" : "",
        ].filter(Boolean).join(" ");
        return `
        <div class="outcome-row${cls ? ` ${cls}` : ""}${thin}">
          ${oImg}<span class="outcome-label">${esc(label)}</span>
          <span class="outcome-pct">${pct}${priceTipHtml(o)}</span>
        </div>`;
      })
      .join("");
    const remaining = r.mc - Math.min((r.mk || []).length, 3);
    if (remaining > 0) {
      rowsHtml += `<div class="outcome-more">+${remaining} more</div>`;
    }
  }

  const meta = buildMeta(r);

  return `
  <a href="${url}" target="_blank" rel="noopener" class="result" role="listitem" tabindex="0">
    <div class="result-header">
      ${img}
      <div class="result-question">${esc(r.q)}</div>
    </div>
    ${rowsHtml ? `<div class="outcome-rows">${rowsHtml}</div>` : ""}
    <div class="result-meta">${meta}</div>
  </a>`;
}

function resultUrl(r) {
  if (r.u) return r.u;
  if (r.p === "kalshi") return `https://kalshi.com/markets/${r.s}`;
  if (r.p === "manifold") return `https://manifold.markets/${r.s}`;
  return `https://polymarket.com/event/${r.s}`;
}

function resultImageHtml(r) {
  if (r.im) {
    return `<img src="${r.im}" alt="" class="result-img" loading="lazy">`;
  }
  if (r.p === "kalshi") {
    return `<div class="result-img provider-avatar kalshi-avatar" aria-hidden="true">${esc(categoryInitials(r))}</div>`;
  }
  if (r.p === "manifold") {
    return `<div class="result-img provider-avatar manifold-avatar" aria-hidden="true">${esc(categoryInitials(r) || "M")}</div>`;
  }
  return '<div class="result-img placeholder"></div>';
}

function categoryInitials(r) {
  const label = (r.tg || []).find(Boolean) || "K";
  const words = String(label).split(/\s+/).filter(Boolean);
  if (!words.length) return "K";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
}

function renderSportCard(r, url) {
  const away = r.tm[0] || {};
  const home = r.tm[1] || {};

  const moneyline = (r.mk || []).find((m) => {
    const q = (m.q || m.l || "").toLowerCase();
    return (
      !q.includes("spread") &&
      !q.includes("o/u") &&
      !q.includes(":") &&
      !q.includes("odd/even") &&
      !q.includes("team to")
    );
  });
  const awayPct = moneyline?.op?.[0] != null ? Math.round(moneyline.op[0] * 100) : null;
  const homePct = moneyline?.op?.[1] != null ? Math.round(moneyline.op[1] * 100) : null;

  const spreadMkt = (r.mk || []).find((m) => (m.l || "").toLowerCase().startsWith("spread"));
  const totalMkt = (r.mk || []).find((m) => (m.l || "").toLowerCase().startsWith("o/u") && !(m.l || "").toLowerCase().startsWith("1h"));

  let awaySpread = "", homeSpread = "";
  if (spreadMkt?.l) {
    const num = spreadMkt.l.match(/-?\d+\.?\d*/)?.[0] || "";
    const favInQ = (spreadMkt.q || "").toLowerCase();
    const awayInFav = favInQ.includes(away.n?.toLowerCase?.() || "___");
    if (awayInFav) {
      awaySpread = num ? `-${Math.abs(num)}` : "";
      homeSpread = num ? `+${Math.abs(num)}` : "";
    } else {
      homeSpread = num ? `-${Math.abs(num)}` : "";
      awaySpread = num ? `+${Math.abs(num)}` : "";
    }
  }

  let totalNum = "";
  let overPct = "", underPct = "";
  if (totalMkt?.l) {
    totalNum = totalMkt.l.match(/\d+\.?\d*/)?.[0] || "";
    overPct = totalMkt.op?.[0] != null ? Math.round(totalMkt.op[0] * 100) + "%" : "";
    underPct = totalMkt.op?.[1] != null ? Math.round(totalMkt.op[1] * 100) + "%" : "";
  }

  const hasML = awayPct != null || homePct != null;
  const hasSpread = !!awaySpread;
  const hasTotal = !!totalNum;
  const colCount = [hasML, hasSpread, hasTotal].filter(Boolean).length;

  const liveHtml = r.live
    ? `<span class="live-badge">Live ${esc(r.per || "")}</span><span class="score">${esc(r.sc || "")}</span>`
    : "";

  const meta = [];
  if (liveHtml) meta.push(liveHtml);
  meta.push(`<span>${formatVol(r.vt || r.v)} vol</span>`);
  if (r.gd || r.ed) meta.push(`<span>${r.gd || r.ed}</span>`);

  const colW = colCount === 0 ? "1fr" : `1fr repeat(${colCount}, 56px)`;
  const headers = [
    hasML ? '<span class="sport-col-label">ML</span>' : "",
    hasSpread ? '<span class="sport-col-label">Spread</span>' : "",
    hasTotal ? '<span class="sport-col-label">Total</span>' : "",
  ].join("");

  return `
  <a href="${url}" target="_blank" rel="noopener" class="result result-sport" role="listitem" tabindex="0">
    ${colCount > 0 ? `<div class="sport-header" style="grid-template-columns:${colW}"><span></span>${headers}</div>` : ""}
    <div class="sport-grid" style="grid-template-columns:${colW}">
      <div class="sport-team-info">
        ${away.l ? `<img src="${away.l}" alt="" class="team-logo">` : ""}
        <span class="team-name">${esc(away.n)}</span>
        <span class="team-record">${esc(away.r)}</span>
      </div>
      ${hasML ? `<span class="sport-cell is-ml${awayPct != null && homePct != null && awayPct >= homePct ? " is-fav" : ""}">${awayPct != null ? `${awayPct}%` : ""}</span>` : ""}
      ${hasSpread ? `<span class="sport-cell">${esc(awaySpread)}</span>` : ""}
      ${hasTotal ? `<span class="sport-cell">O ${esc(totalNum)}</span>` : ""}

      <div class="sport-team-info">
        ${home.l ? `<img src="${home.l}" alt="" class="team-logo">` : ""}
        <span class="team-name">${esc(home.n)}</span>
        <span class="team-record">${esc(home.r)}</span>
      </div>
      ${hasML ? `<span class="sport-cell is-ml${homePct != null && awayPct != null && homePct > awayPct ? " is-fav" : ""}">${homePct != null ? `${homePct}%` : ""}</span>` : ""}
      ${hasSpread ? `<span class="sport-cell">${esc(homeSpread)}</span>` : ""}
      ${hasTotal ? `<span class="sport-cell">U ${esc(totalNum)}</span>` : ""}
    </div>
    <div class="result-meta">${meta.join('<span class="meta-sep"></span>')}</div>
  </a>`;
}

// ── Helpers ──────────────────────────────────────────────────────────

let refreshAbort = null;

function updateThinState(outcome) {
  if (outcome.bid == null || outcome.ask == null) {
    delete outcome.thin;
    return;
  }

  if (outcome.ask - outcome.bid >= 0.10) {
    outcome.thin = 1;
  } else {
    delete outcome.thin;
  }
}

function round4(value) {
  return Math.round(value * 10000) / 10000;
}

function num(value, fallback = 0) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizedLabel(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function centsPrice(value) {
  const n = num(value, NaN);
  if (!Number.isFinite(n)) return null;
  return n > 1 ? n / 100 : n;
}

function kalshiBestPrice(market) {
  const bid = centsPrice(market.yes_bid_dollars);
  const ask = centsPrice(market.yes_ask_dollars);
  const last = centsPrice(market.last_price_dollars) || 0;

  if (bid == null && ask == null) return last;
  const safeBid = bid ?? 0;
  const safeAsk = ask ?? 1;
  const mid = round4((safeBid + safeAsk) / 2);
  const spread = safeAsk - safeBid;
  const volume = num(market.volume_fp);

  if (spread < 0.05) return mid;
  if (volume >= 1000 && last > 0) return Math.max(safeBid, last);
  if (safeBid > 0) return safeBid;
  return last || 0;
}

function activeKalshiMarkets(markets) {
  const inactive = new Set(["closed", "settled", "expired", "finalized"]);
  return (markets || []).filter((market) => !inactive.has(String(market.status || "").toLowerCase()));
}

function findKalshiMarket(outcome, markets) {
  if (outcome.id) {
    const byId = markets.find((market) => market.ticker === outcome.id);
    if (byId) return byId;
  }

  const outcomeLabels = [
    outcome.l,
    outcome.q,
  ].map(normalizedLabel).filter(Boolean);
  if (!outcomeLabels.length && markets.length === 1) return markets[0];

  return markets.find((market) => {
    const labels = [
      market.yes_sub_title,
      market.subtitle,
      market.title,
    ].map(normalizedLabel).filter(Boolean);
    return labels.some((label) => outcomeLabels.includes(label));
  });
}

function updateKalshiOutcome(outcome, market, normFactor = 1) {
  const best = kalshiBestPrice(market);
  const p = normFactor > 0 ? best / normFactor : best;
  outcome.op = [round4(Math.min(Math.max(p, 0), 1))];
  if ((outcome.op[0] ?? 0) <= 1) outcome.op[1] = round4(1 - outcome.op[0]);

  const bid = centsPrice(market.yes_bid_dollars);
  const ask = centsPrice(market.yes_ask_dollars);
  const last = centsPrice(market.last_price_dollars);
  if (bid != null) outcome.bid = round4(bid);
  if (ask != null) outcome.ask = round4(ask);
  if (last != null) outcome.last = round4(last);
  updateThinState(outcome);
}

function delay(ms, signal) {
  if (signal.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timeout);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

async function runLimited(items, concurrency, signal, task) {
  let next = 0;
  const workerCount = Math.min(concurrency, items.length);
  const workers = Array.from({ length: workerCount }, async (_, workerIndex) => {
    if (workerIndex > 0) await delay(workerIndex * 150, signal);
    while (!signal.aborted && next < items.length) {
      const item = items[next++];
      await task(item);
      if (!signal.aborted && next < items.length) await delay(KALSHI_LIVE_DELAY_MS, signal);
    }
  });
  await Promise.allSettled(workers);
}

async function refreshKalshiLivePrices(results, ctrl) {
  const targets = results.filter((r) => !r.ar && r.p === "kalshi" && r.s);
  if (!targets.length) return;

  await runLimited(targets, KALSHI_LIVE_CONCURRENCY, ctrl.signal, async (r) => {
    const url = `${KALSHI_LIVE_EVENTS_URL}/${encodeURIComponent(r.s.toUpperCase())}`;
    const resp = await fetch(url, { signal: ctrl.signal });
    if (!resp.ok || ctrl.signal.aborted) return;
    const payload = await resp.json();
    const event = payload.event || payload;
    const markets = activeKalshiMarkets(event.markets || payload.markets || []);
    if (!markets.length) return;

    const isExclusive = Boolean(event.mutually_exclusive);
    const bestPrices = markets.map(kalshiBestPrice);
    const meaningful = bestPrices.filter((p) => p > 0.005);
    const normFactor = isExclusive && meaningful.length > 1
      ? meaningful.reduce((sum, p) => sum + p, 0)
      : 1;

    for (const outcome of r.mk || []) {
      const match = findKalshiMarket(outcome, markets);
      if (match) updateKalshiOutcome(outcome, match, normFactor);
    }

    r.v = Math.round(markets.reduce((sum, market) => sum + num(market.volume_24h_fp), 0));
    r.vt = Math.round(markets.reduce((sum, market) => sum + num(market.volume_fp), 0));
    r.mc = markets.length;
  });
}

function msDate(ms) {
  const value = Number(ms);
  if (!Number.isFinite(value) || value <= 0) return "";
  return new Date(value).toISOString().slice(0, 10);
}

function manifoldAnswerProbability(answer) {
  return round4(Math.min(Math.max(num(answer.probability ?? answer.p), 0), 1));
}

function manifoldAnswerOutcome(answer) {
  const p = manifoldAnswerProbability(answer);
  const outcome = {
    id: String(answer.id || answer.text || ""),
    l: String(answer.text || answer.name || answer.id || ""),
    op: [p],
    v: Math.round(num(answer.volume)),
  };
  if (answer.imageUrl || answer.avatarUrl) outcome.im = answer.imageUrl || answer.avatarUrl;
  return outcome;
}

async function refreshManifoldLivePrices(results, ctrl) {
  const targets = results.filter((r) => !r.ar && r.p === "manifold" && r.s);
  if (!targets.length) return;

  await Promise.allSettled(targets.map(async (r) => {
    const url = `https://api.manifold.markets/v0/slug/${encodeURIComponent(r.s)}`;
    const resp = await fetch(url, { signal: ctrl.signal });
    if (!resp.ok || ctrl.signal.aborted) return;
    const market = await resp.json();
    if (market.isResolved) return;

    const answers = Array.isArray(market.answers) ? market.answers : [];
    if (answers.length) {
      const liveOutcomes = answers
        .map(manifoldAnswerOutcome)
        .filter((outcome) => outcome.l)
        .sort((a, b) => (b.op?.[0] || 0) - (a.op?.[0] || 0) || (b.v || 0) - (a.v || 0));

      if (liveOutcomes.length) {
        r.mk = liveOutcomes.slice(0, 12);
        r.mc = answers.length;
      }
    } else {
      const p = round4(Math.min(Math.max(num(market.probability ?? market.p), 0), 1));
      const outcome = (r.mk || [])[0];
      if (outcome && Number.isFinite(p)) {
        outcome.op = [p, round4(1 - p)];
      }
    }

    r.v = Math.round(num(market.volume24Hours));
    r.vt = Math.round(num(market.volume));
    r.tk = market.token || r.tk;
    const closeDate = msDate(market.closeTime);
    if (closeDate) r.ed = closeDate;
  }));
}

async function refreshPolymarketLivePrices(results, ctrl) {
  const slugs = results
    .filter((r) => !r.ar && !r.p)
    .map((r) => r.s)
    .filter(Boolean);
  if (!slugs.length) return;

  const url = "https://gamma-api.polymarket.com/events?" +
    slugs.map((s) => `slug=${encodeURIComponent(s)}`).join("&");
  const resp = await fetch(url, { signal: ctrl.signal });
  if (!resp.ok || ctrl.signal.aborted) return;
  const events = await resp.json();

  const bySlug = {};
  for (const ev of events) bySlug[ev.slug] = ev;

  for (const r of results) {
    const live = bySlug[r.s];
    if (!live) continue;

    if (live.live) r.live = true;
    if (live.score) r.sc = live.score;
    if (live.period) r.per = live.period;

    const liveMarkets = (live.markets || []).filter((m) => !m.closed);
    for (const mk of r.mk || []) {
      const match = liveMarkets.find(
        (m) => m.groupItemTitle === mk.l || m.question === mk.q,
      );
      if (!match) continue;
      const op = typeof match.outcomePrices === "string"
        ? JSON.parse(match.outcomePrices)
        : match.outcomePrices;
      if (op?.[0] != null) mk.op = [parseFloat(op[0])];
      if (op?.[1] != null) mk.op[1] = parseFloat(op[1]);
      if (match.bestBid != null) mk.bid = parseFloat(match.bestBid);
      if (match.bestAsk != null) mk.ask = parseFloat(match.bestAsk);
      if (match.lastTradePrice != null) mk.last = parseFloat(match.lastTradePrice);
      updateThinState(mk);
    }
  }
}

async function refreshLivePrices(results) {
  if (refreshAbort) refreshAbort.abort();
  const ctrl = new AbortController();
  refreshAbort = ctrl;

  try {
    await Promise.allSettled([
      refreshPolymarketLivePrices(results, ctrl),
      refreshKalshiLivePrices(results, ctrl),
      refreshManifoldLivePrices(results, ctrl),
    ]);

    if (!ctrl.signal.aborted && results === lastRendered) {
      resultsEl.innerHTML = results.map((r) => renderCard(r)).join("");
    }
  } catch (e) {
    if (e.name !== "AbortError") console.warn("Live refresh failed:", e);
  }
}

function priceTipHtml(o) {
  const parts = [];
  if (o.bid != null) parts.push(`Bid ${Math.round(o.bid * 100)}¢`);
  if (o.ask != null) parts.push(`Ask ${Math.round(o.ask * 100)}¢`);
  if (o.last != null) parts.push(`Last ${Math.round(o.last * 100)}¢`);
  if (!parts.length) return "";
  return `<span class="price-tip">${parts.join(" · ")}</span>`;
}

function buildMeta(r) {
  const parts = [];
  if (r.ar) parts.push('<span class="archive-badge">Archived</span>');
  parts.push(`<span>${formatVol(r.vt || r.v, r)} vol</span>`);
  if (r.ed) parts.push(`<span>${r.ed}</span>`);
  return parts.join('<span class="meta-sep"></span>');
}

function shortenQuestion(marketQ, eventTitle) {
  let label = marketQ.replace(/^Will\s+/i, "").replace(/\?$/, "");
  const titleWords = eventTitle.toLowerCase().split(/\s+/);
  for (const w of titleWords) {
    if (w.length > 3) {
      label = label
        .replace(
          new RegExp(
            w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
            "gi",
          ),
          "",
        )
        .trim();
    }
  }
  label = label.replace(/\s{2,}/g, " ").replace(/^[\s,]+|[\s,]+$/g, "");
  if (label.length > 35) label = label.slice(0, 32) + "…";
  return label || marketQ.slice(0, 35);
}

function formatVol(v, result = null) {
  const isManifold = result?.p === "manifold";
  const prefix = isManifold ? "" : "$";
  const suffix = isManifold && result?.tk ? ` ${result.tk}` : "";
  if (v >= 1_000_000) return `${prefix}${(v / 1_000_000).toFixed(1)}M${suffix}`;
  if (v >= 1_000) return `${prefix}${(v / 1_000).toFixed(0)}K${suffix}`;
  if (v > 0) return `${prefix}${v}${suffix}`;
  return `${prefix}0${suffix}`;
}

function esc(s) {
  const el = document.createElement("span");
  el.textContent = s;
  return el.innerHTML;
}

// ── Theme toggle ────────────────────────────────────────────────────

function getSystemTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function getEffectiveTheme() {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr) return attr;
  return getSystemTheme();
}

document.getElementById("theme-toggle").addEventListener("click", () => {
  const current = getEffectiveTheme();
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem(
    "theme-pref",
    JSON.stringify({ theme: next, systemWhenSet: getSystemTheme() }),
  );
});

providerToggle.addEventListener("click", async (e) => {
  const button = e.target.closest(".provider-option");
  if (!button) return;
  const nextProvider = normalizeProvider(button.dataset.provider);
  if (nextProvider === provider) return;

  provider = nextProvider;
  includeArchived = false;
  archiveToggle.checked = false;
  activeFilters = [];
  syncProviderState();
  setProviderUi();
  syncFilterUrl();
  syncProviderUrl();
  selectedIdx = -1;
  resultRenderToken++;
  resultsEl.innerHTML = "";
  updateStatus(`Loading ${activeProviderConfig().label}...`);

  try {
    await loadProviderData(provider);
  } catch {
    updateStatus(`Failed to load ${activeProviderConfig().label}`);
    return;
  }

  syncProviderState();
  setProviderUi();
  updateStatus();
  renderFilters();
  updateResults();
});

archiveToggle.addEventListener("change", async () => {
  if (!activeProviderConfig().supportsArchived) return;
  includeArchived = archiveToggle.checked;
  const url = new URL(window.location);
  if (includeArchived) {
    url.searchParams.set("archived", "1");
  } else {
    url.searchParams.delete("archived");
  }
  history.replaceState(null, "", url);
  updateStatus();
  if (includeArchived) {
    try {
      await loadArchivedData();
    } catch {
      return;
    }
  }
  renderFilters();
  updateResults();
});

window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => {
    const stored = localStorage.getItem("theme-pref");
    if (stored) {
      try {
        const p = JSON.parse(stored);
        if (getSystemTheme() !== p.systemWhenSet) {
          localStorage.removeItem("theme-pref");
          document.documentElement.removeAttribute("data-theme");
        }
      } catch {
        localStorage.removeItem("theme-pref");
        document.documentElement.removeAttribute("data-theme");
      }
    }
  });

document.getElementById("site-title").addEventListener("click", () => {
  input.value = "";
  activeFilters = [];
  currentQuery = "";
  syncFilterUrl();
  handleInput();
  input.focus();
});

let tipTimer = null;

function closeTips() {
  clearTimeout(tipTimer);
  document.querySelectorAll(".tip-open").forEach((el) => el.classList.remove("tip-open"));
}

function openTip(pct) {
  closeTips();
  pct.classList.add("tip-open");
  tipTimer = setTimeout(closeTips, 2500);
}

resultsEl.addEventListener("mouseenter", (e) => {
  const pct = e.target.closest(".outcome-pct");
  if (pct?.querySelector(".price-tip")) openTip(pct);
}, true);

resultsEl.addEventListener("mouseleave", (e) => {
  const pct = e.target.closest(".outcome-pct");
  if (pct) { closeTips(); }
}, true);

let tipClickBlock = false;

resultsEl.addEventListener("pointerdown", (e) => {
  const pct = e.target.closest(".outcome-pct");
  if (pct?.querySelector(".price-tip")) {
    e.stopImmediatePropagation();
    tipClickBlock = true;
    if (pct.classList.contains("tip-open")) {
      closeTips();
    } else {
      openTip(pct);
    }
  }
});

resultsEl.addEventListener("click", (e) => {
  if (tipClickBlock) {
    e.preventDefault();
    e.stopImmediatePropagation();
    tipClickBlock = false;
  }
}, true);

document.addEventListener("pointerdown", (e) => {
  if (!e.target.closest(".outcome-pct")) closeTips();
});

document.getElementById("clear-btn").addEventListener("click", () => {
  input.value = "";
  input.closest(".search-wrap").classList.remove("has-value");
  handleInput();
  input.focus();
});

input.addEventListener("input", () => {
  input.closest(".search-wrap").classList.toggle("has-value", input.value.length > 0);
  handleInput();
});

init();
