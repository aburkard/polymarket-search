import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { polymarketDisplayPrices, updatePolymarketOutcomes } from "../public/polymarket.js";

const cases = JSON.parse(readFileSync(new URL("./fixtures/polymarket-prices.json", import.meta.url)));

describe("Polymarket display prices (shared with index builder)", () => {
  for (const { name, market, expected } of cases) {
    it(name, () => assert.deepEqual(polymarketDisplayPrices(market), expected));
  }
});

describe("Polymarket live refresh", () => {
  it("keeps source probabilities in exclusive groups with omitted and tiny outcomes", () => {
    const result = { mk: [{ q: "Anna?", l: "Anna", op: [0.3553, 0.6447] }] };
    updatePolymarketOutcomes(result, {
      negRisk: true, enableNegRisk: true,
      markets: [
        { question: "Anna?", groupItemTitle: "Anna", bestBid: 0.2, bestAsk: 0.22 },
        { question: "Scott?", outcomePrices: [0.1575, 0.8425] },
        { question: "Other?", outcomePrices: [0.004, 0.996] },
      ],
    });
    assert.deepEqual(result.mk[0].op, [0.21, 0.79]);
  });

  it("matches binary questions instead of empty labels and clears stale quotes", () => {
    const result = { mk: [{ q: "Second?", l: "", op: [0.2, 0.8], bid: 0.1, ask: 0.9, last: 0.5, thin: 1 }] };
    updatePolymarketOutcomes(result, { markets: [
      { question: "First?", groupItemTitle: "", outcomePrices: [0.7, 0.3] },
      { question: "Second?", groupItemTitle: "", outcomePrices: [0.4, 0.6] },
    ] });
    assert.deepEqual(result.mk[0], { q: "Second?", l: "", op: [0.4, 0.6] });
  });

  it("retains bid/ask/last and thin indicator without changing last to bid", () => {
    const result = { mk: [{ q: "Will it happen?" }] };
    updatePolymarketOutcomes(result, { markets: [
      { question: "Will it happen?", bestBid: 0.4, bestAsk: 0.6, lastTradePrice: 0.3 },
    ] });
    assert.deepEqual(result.mk[0], { q: "Will it happen?", op: [0.3, 0.7], bid: 0.4, ask: 0.6, last: 0.3, thin: 1 });
  });
});
