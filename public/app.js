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
    input.focus();
    showTrending();
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
    if (!query || !data) {
      showTrending();
      return;
    }
    const results = search(query, data, 20);
    renderResults(results);
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
  let outcomesHtml = "";

  if (outcomes.length === 1) {
    const p = outcomes[0].op?.[0];
    const pct = p != null ? Math.round(p * 100) : null;
    if (pct != null) {
      const yesLeads = pct >= 50;
      outcomesHtml = `
        <span class="outcome ${yesLeads ? "outcome-yes" : "outcome-dim"}">Yes <b>${pct}%</b></span>
        <span class="outcome ${yesLeads ? "outcome-dim" : "outcome-no"}">No <b>${100 - pct}%</b></span>`;
    }
  } else if (outcomes.length > 1) {
    const visible = outcomes.filter((o) => {
      const p = o.op?.[0];
      return p != null && Math.round(p * 100) >= 1;
    });
    outcomesHtml = (visible.length ? visible : outcomes.slice(0, 2))
      .map((o) => {
        const p = o.op?.[0];
        const pct = p != null ? Math.round(p * 100) + "%" : "–";
        const label = o.l || shortenQuestion(o.q, r.q);
        return `<span class="outcome">${esc(label)} <b>${pct}</b></span>`;
      })
      .join("");
  }

  const meta = buildMeta(r);

  return `
  <a href="${url}" target="_blank" rel="noopener" class="result" role="listitem" tabindex="0">
    ${img}
    <div class="result-body">
      <div class="result-question">${esc(r.q)}</div>
      ${outcomesHtml ? `<div class="result-outcomes">${outcomesHtml}</div>` : ""}
      <div class="result-meta">${meta}</div>
    </div>
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

  const props = (r.mk || [])
    .filter((m) => m !== moneyline)
    .map((m) => {
      const p = m.op?.[0];
      const pct = p != null ? Math.round(p * 100) + "%" : "–";
      const label =
        m.l ||
        m.q
          .replace(r.q + ": ", "")
          .replace(
            r.q.split(" vs. ").reverse().join(" vs. ") + ": ",
            "",
          );
      return `<span class="outcome">${esc(label)} <b>${pct}</b></span>`;
    });

  const liveHtml = r.live
    ? `<span class="live-badge">Live ${esc(r.per || "")}</span><span class="score">${esc(r.sc || "")}</span>`
    : "";

  const meta = [];
  if (liveHtml) meta.push(liveHtml);
  meta.push(`<span>${formatVol(r.v)} vol</span>`);
  if (r.gd || r.ed) meta.push(`<span>${r.gd || r.ed}</span>`);
  if (r.mc > (r.mk || []).length)
    meta.push(`<span>+${r.mc - (r.mk || []).length} more</span>`);

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
    ${props.length ? `<div class="result-outcomes">${props.join("")}</div>` : ""}
    <div class="result-meta">${meta.join('<span class="meta-sep"></span>')}</div>
  </a>`;
}

// ── Helpers ──────────────────────────────────────────────────────────

function buildMeta(r) {
  const parts = [];
  parts.push(`<span>${formatVol(r.v)} vol</span>`);
  if (r.ed) parts.push(`<span>${r.ed}</span>`);
  if (r.mc > (r.mk || []).slice(0, 5).length)
    parts.push(`<span>+${r.mc - Math.min((r.mk || []).length, 5)} more</span>`);
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

input.addEventListener("input", handleInput);
init();
