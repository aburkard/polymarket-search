import { prepareIndex, search } from "./search.js";

let data = null;
let debounceTimer = null;

const input = document.getElementById("search-input");
const resultsEl = document.getElementById("results");
const statusEl = document.getElementById("status");

async function init() {
  statusEl.textContent = "Loading markets…";
  try {
    const resp = await fetch("search-data.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = prepareIndex(await resp.json());
    statusEl.textContent = `${data.n.toLocaleString()} markets loaded`;
    input.disabled = false;
    input.focus();
    showTrending();
  } catch (e) {
    statusEl.textContent = `Failed to load: ${e.message}`;
  }
}

function handleInput() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    const query = input.value.trim();
    if (!query || !data) {
      showTrending();
      return;
    }
    const results = search(query, data, 20);
    renderResults(results);
  }, 100);
}

function showTrending() {
  if (!data) return;
  const trending = [...data.docs]
    .sort((a, b) => b.v - a.v)
    .slice(0, 10);
  resultsEl.innerHTML =
    '<div class="trending-label">Trending</div>' +
    trending
      .map((r) => renderResultCard(r))
      .join("");
}

function renderResults(results) {
  if (!results.length) {
    resultsEl.innerHTML = '<div class="no-results">No markets found</div>';
    return;
  }

  resultsEl.innerHTML = results.map((r) => renderResultCard(r)).join("");
}

function renderResultCard(r) {
  const vol = formatVolume(r.v);
  const endDate = r.ed || "";
  const url = `https://polymarket.com/event/${r.s}`;

  if (r.tm) return renderSportsResult(r, url, vol);

  const img = r.im
    ? `<img src="${r.im}" alt="" class="result-img" loading="lazy">`
    : '<div class="result-img placeholder"></div>';

  const outcomes = (r.mk || []).slice(0, 4);
  let outcomesHtml;

  if (outcomes.length === 1) {
    const prices = outcomes[0].op || [];
    const yes = prices[0] != null ? (prices[0] * 100).toFixed(0) : "–";
    const no = prices[1] != null ? (prices[1] * 100).toFixed(0) : "–";
    outcomesHtml = `
      <span class="price yes">${yes}¢ Yes</span>
      <span class="price no">${no}¢ No</span>`;
  } else {
    outcomesHtml = outcomes
      .map((o) => {
        const p = o.op?.[0];
        const pct = p != null ? (p * 100).toFixed(0) + "¢" : "–";
        const label = o.l || shortenQuestion(o.q, r.q);
        return `<span class="outcome">${escapeHtml(label)} <b>${pct}</b></span>`;
      })
      .join("");
  }

  const marketCount = r.mc > outcomes.length
    ? `<span class="more-markets">+${r.mc - outcomes.length} more</span>`
    : "";

  return `
  <a href="${url}" target="_blank" rel="noopener" class="result">
    ${img}
    <div class="result-body">
      <div class="result-question">${escapeHtml(r.q)}</div>
      <div class="result-outcomes">${outcomesHtml}</div>
      <div class="result-meta">
        <span class="vol">$${vol} vol</span>
        ${endDate ? `<span class="end-date">${endDate}</span>` : ""}
        ${marketCount}
      </div>
    </div>
  </a>`;
}

function renderSportsResult(r, url, vol) {
  const away = r.tm[0] || {};
  const home = r.tm[1] || {};

  const moneyline = (r.mk || []).find((m) => {
    const q = m.q.toLowerCase();
    return !q.includes("spread") && !q.includes("o/u") && !q.includes(":") && !q.includes("odd/even") && !q.includes("team to");
  });
  const awayOdds = moneyline?.op?.[0];
  const homeOdds = moneyline?.op?.[1];

  const props = (r.mk || [])
    .filter((m) => m !== moneyline)
    .map((m) => {
      const p = m.op?.[0];
      const pct = p != null ? (p * 100).toFixed(0) + "¢" : "–";
      const label = m.l || m.q.replace(r.q + ": ", "").replace(r.q.split(" vs. ").reverse().join(" vs. ") + ": ", "");
      return `<span class="outcome">${escapeHtml(label)} <b>${pct}</b></span>`;
    });

  const liveHtml = r.live
    ? `<span class="live-badge">LIVE ${escapeHtml(r.per || "")}</span><span class="score">${escapeHtml(r.sc || "")}</span>`
    : "";

  const dateStr = r.gd || r.ed || "";

  return `
    <a href="${url}" target="_blank" rel="noopener" class="result result-sport">
      <div class="sport-matchup">
        <div class="sport-team">
          ${away.l ? `<img src="${away.l}" alt="" class="team-logo">` : ""}
          <span class="team-name">${escapeHtml(away.n)}</span>
          <span class="team-record">${escapeHtml(away.r)}</span>
          ${awayOdds != null ? `<span class="team-odds">${(awayOdds * 100).toFixed(0)}¢</span>` : ""}
        </div>
        <div class="sport-team">
          ${home.l ? `<img src="${home.l}" alt="" class="team-logo">` : ""}
          <span class="team-name">${escapeHtml(home.n)}</span>
          <span class="team-record">${escapeHtml(home.r)}</span>
          ${homeOdds != null ? `<span class="team-odds">${(homeOdds * 100).toFixed(0)}¢</span>` : ""}
        </div>
      </div>
      ${props.length ? `<div class="result-outcomes">${props.join("")}</div>` : ""}
      <div class="result-meta">
        ${liveHtml}
        <span class="vol">$${vol} vol</span>
        ${dateStr ? `<span class="end-date">${dateStr}</span>` : ""}
        ${r.mc > (r.mk || []).length ? `<span class="more-markets">+${r.mc - (r.mk || []).length} more props</span>` : ""}
      </div>
    </a>`;
}

function shortenQuestion(marketQ, eventTitle) {
  let label = marketQ
    .replace(/^Will\s+/i, "")
    .replace(/\?$/, "");
  const titleWords = eventTitle.toLowerCase().split(/\s+/);
  for (const w of titleWords) {
    if (w.length > 3) {
      label = label.replace(new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), "").trim();
    }
  }
  label = label.replace(/\s{2,}/g, " ").replace(/^[\s,]+|[\s,]+$/g, "");
  if (label.length > 40) label = label.slice(0, 37) + "…";
  return label || marketQ.slice(0, 40);
}

function formatVolume(v) {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + "M";
  if (v >= 1_000) return (v / 1_000).toFixed(0) + "K";
  return String(v);
}

function escapeHtml(s) {
  const el = document.createElement("span");
  el.textContent = s;
  return el.innerHTML;
}

input.addEventListener("input", handleInput);
init();
