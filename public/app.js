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
      const prices = r.op || [];
      const yesPrice = prices[0] != null ? (prices[0] * 100).toFixed(0) : "–";
      const noPrice = prices[1] != null ? (prices[1] * 100).toFixed(0) : "–";
      const vol = formatVolume(r.v);
      const endDate = r.ed || "";
      const url = `https://polymarket.com/event/${r.es}`;
      const img = r.im
        ? `<img src="${r.im}" alt="" class="result-img" loading="lazy">`
        : '<div class="result-img placeholder"></div>';

      return `
      <a href="${url}" target="_blank" rel="noopener" class="result">
        ${img}
        <div class="result-body">
          <div class="result-question">${escapeHtml(r.q)}</div>
          <div class="result-meta">
            <span class="price yes">${yesPrice}¢ Yes</span>
            <span class="price no">${noPrice}¢ No</span>
            <span class="vol">$${vol}</span>
            ${endDate ? `<span class="end-date">${endDate}</span>` : ""}
          </div>
        </div>
      </a>`;
    })
    .join("");
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
