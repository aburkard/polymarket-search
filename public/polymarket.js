const round4 = (value) => Math.round(value * 10000) / 10000;

function validPrice(value) {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const price = Number(value);
  return Number.isFinite(price) && price >= 0 && price <= 1 ? price : null;
}

export function polymarketDisplayPrices(market) {
  let raw = market.outcomePrices || [];
  try {
    raw = typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch (_) {
    raw = [];
  }
  if (!Array.isArray(raw)) raw = [];
  let price = validPrice(raw[0]);
  // Settled outcomes must not be replaced by pre-resolution quotes.
  if (!market.closed) {
    const bid = validPrice(market.bestBid);
    const ask = validPrice(market.bestAsk);
    const last = validPrice(market.lastTradePrice);
    if (bid != null && ask != null && bid <= ask) {
      if (Math.round((ask - bid) * 1e10) / 1e10 <= 0.10) {
        price = (bid + ask) / 2;
      } else if (last != null) {
        price = last;
      }
    } else if (price == null) {
      price = last;
    }
  }
  if (price == null) return [];
  const p = round4(price);
  return raw.length === 1 ? [p] : [p, round4(1 - p)];
}

export function updatePolymarketOutcomes(result, event) {
  const markets = (event.markets || []).filter((market) => !market.closed);
  for (const outcome of result.mk || []) {
    // Empty group labels are common in binary markets; never match on those.
    const match = markets.find((market) => market.question === outcome.q &&
      (market.groupItemTitle || "") === (outcome.l || "")) ||
      markets.find((market) => outcome.l && market.groupItemTitle === outcome.l);
    if (!match) continue;
    outcome.op = polymarketDisplayPrices(match);
    for (const [field, key] of [["bid", "bestBid"], ["ask", "bestAsk"], ["last", "lastTradePrice"]]) {
      const value = validPrice(match[key]);
      if (value == null) delete outcome[field];
      else outcome[field] = round4(value);
    }
    if (outcome.bid != null && outcome.ask != null && outcome.ask - outcome.bid >= 0.10) {
      outcome.thin = 1;
    } else {
      delete outcome.thin;
    }
  }
}
