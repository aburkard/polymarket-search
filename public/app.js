import { prepareIndex, search } from "./search.js";

let data = null;
let debounceTimer = null;
let selectedIdx = -1;

const input = document.getElementById("search-input");
const resultsEl = document.getElementById("results");
const statusEl = document.getElementById("status");

async function init() {
  statusEl.textContent = "Loading markets…";
  try {
    const resp = await fetch("search-data.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = prepareIndex(await resp.json());
    statusEl.textContent = `${data.n.toLocaleString()} events loaded`;
    input.disabled = false;
    const urlQuery = new URLSearchParams(window.location.search).get("q");
    if (urlQuery) {
      input.value = urlQuery;
      const results = search(urlQuery, data, 12);
      renderResults(results);
    } else {
      input.focus();
      showTrending();
    }
  } catch (e) {
    statusEl.textContent = `Failed to load: ${e.message}`;
  }
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
    const url = new URL(window.location);
    if (query) {
      url.searchParams.set("q", query);
    } else {
      url.searchParams.delete("q");
    }
    history.replaceState(null, "", url);

    if (!query || !data) {
      showTrending();
      return;
    }
    const results = search(query, data, 12);
    renderResults(results);
    window.scrollTo({ top: 0 });
  }, 80);
}

function showTrending() {
  if (!data) return;
  const trending = [...data.docs]
    .sort((a, b) => b.v - a.v)
    .slice(0, 10);
  resultsEl.innerHTML =
    '<div class="section-label">Trending</div>' +
    trending.map((r) => renderCard(r)).join("");
}

function renderResults(results) {
  if (!results.length) {
    resultsEl.innerHTML = '<div class="no-results">No markets found</div>';
    return;
  }
  resultsEl.innerHTML = results.map((r) => renderCard(r)).join("");
}

// ── Card rendering ──────────────────────────────────────────────────

function renderCard(r) {
  const url = `https://polymarket.com/event/${r.s}`;
  if (r.tm) return renderSportCard(r, url);

  const img = r.im
    ? `<img src="${r.im}" alt="" class="result-img" loading="lazy">`
    : '<div class="result-img placeholder"></div>';

  const outcomes = (r.mk || []).slice(0, 5);
  let rowsHtml = "";

  if (outcomes.length === 1) {
    const p = outcomes[0].op?.[0];
    const pct = p != null ? Math.round(p * 100) : null;
    if (pct != null) {
      const yesLeads = pct >= 50;
      rowsHtml = `
        <div class="outcome-row ${yesLeads ? "" : "is-dim"}">
          <span class="outcome-label">Yes</span>
          <span class="outcome-pct">${pct}%</span>
        </div>
        <div class="outcome-row ${yesLeads ? "is-dim is-no" : "is-no"}">
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
    rowsHtml = show
      .map((o, i) => {
        const p = o.op?.[0];
        const pct = p != null ? Math.round(p * 100) + "%" : "–";
        const label = o.l || shortenQuestion(o.q, r.q);
        return `
        <div class="outcome-row${i > 0 ? " is-dim" : ""}">
          <span class="outcome-label">${esc(label)}</span>
          <span class="outcome-pct">${pct}</span>
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

function renderSportCard(r, url) {
  const away = r.tm[0] || {};
  const home = r.tm[1] || {};

  const moneyline = (r.mk || []).find((m) => {
    const q = m.q.toLowerCase();
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

  const spread = (r.mk || []).find((m) => (m.l || "").toLowerCase().startsWith("spread"));
  const total = (r.mk || []).find((m) => (m.l || "").toLowerCase().startsWith("o/u") && !(m.l || "").toLowerCase().startsWith("1h"));

  const propsLine = [spread?.l, total?.l].filter(Boolean).join("  ·  ");

  const liveHtml = r.live
    ? `<span class="live-badge">Live ${esc(r.per || "")}</span><span class="score">${esc(r.sc || "")}</span>`
    : "";

  const meta = [];
  if (liveHtml) meta.push(liveHtml);
  meta.push(`<span>${formatVol(r.v)} vol</span>`);
  if (r.gd || r.ed) meta.push(`<span>${r.gd || r.ed}</span>`);

  return `
  <a href="${url}" target="_blank" rel="noopener" class="result result-sport" role="listitem" tabindex="0">
    <div class="sport-matchup">
      <div class="sport-team">
        ${away.l ? `<img src="${away.l}" alt="" class="team-logo">` : ""}
        <span class="team-name">${esc(away.n)}</span>
        <span class="team-record">${esc(away.r)}</span>
        ${awayPct != null ? `<span class="team-odds">${awayPct}%</span>` : ""}
      </div>
      <div class="sport-team">
        ${home.l ? `<img src="${home.l}" alt="" class="team-logo">` : ""}
        <span class="team-name">${esc(home.n)}</span>
        <span class="team-record">${esc(home.r)}</span>
        ${homePct != null ? `<span class="team-odds">${homePct}%</span>` : ""}
      </div>
    </div>
    ${propsLine ? `<div class="sport-props">${esc(propsLine)}</div>` : ""}
    <div class="result-meta">${meta.join('<span class="meta-sep"></span>')}</div>
  </a>`;
}

// ── Helpers ──────────────────────────────────────────────────────────

function buildMeta(r) {
  const parts = [];
  parts.push(`<span>${formatVol(r.v)} vol</span>`);
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

function formatVol(v) {
  if (v >= 1_000_000) return "$" + (v / 1_000_000).toFixed(1) + "M";
  if (v >= 1_000) return "$" + (v / 1_000).toFixed(0) + "K";
  if (v > 0) return "$" + v;
  return "$0";
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

input.addEventListener("input", handleInput);
init();
