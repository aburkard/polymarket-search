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
  } catch (e) {
    statusEl.textContent = `Failed to load: ${e.message}`;
  }
}

function handleInput() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    const query = input.value.trim();
    if (!query || !data) {
      resultsEl.innerHTML = "";
      return;
    }
    const results = search(query, data, 20);
    renderResults(results);
  }, 100);
}

function renderResults(results) {
  if (!results.length) {
    resultsEl.innerHTML = '<div class="no-results">No markets found</div>';
    return;
  }

  resultsEl.innerHTML = results
    .map((r) => {
      const vol = formatVolume(r.v);
      const endDate = r.ed || "";
      const url = `https://polymarket.com/event/${r.s}`;
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
            const label = shortenQuestion(o.q, r.q);
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
    })
    .join("");
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
