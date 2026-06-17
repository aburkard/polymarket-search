"""Tests for the Manifold index builder."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

manifold_mod = import_module("build-manifold-index")
normalize_market = manifold_mod.normalize_market
normalize_markets = manifold_mod.normalize_markets
attach_manifold_fields = manifold_mod.attach_manifold_fields
manifold_topic_metadata = manifold_mod.manifold_topic_metadata
should_keep_market = manifold_mod.should_keep_market
build_index = manifold_mod.build_index


SAMPLE_BINARY = {
    "id": "btc1",
    "question": "Will Bitcoin reach $100,000 in 2026?",
    "slug": "will-bitcoin-reach-100000-in-2026",
    "url": "https://manifold.markets/test/will-bitcoin-reach-100000-in-2026",
    "closeTime": 1_800_000_000_000,
    "outcomeType": "BINARY",
    "probability": 0.42,
    "volume": 1234.5,
    "volume24Hours": 12.3,
    "totalLiquidity": 500,
    "uniqueBettorCount": 20,
    "isResolved": False,
    "creatorName": "Test Creator",
    "creatorUsername": "test",
    "token": "MANA",
}


SAMPLE_MULTI = {
    "id": "wc1",
    "question": "Who will win the 2026 FIFA World Cup?",
    "slug": "who-will-win-the-2026-fifa-world-cup",
    "url": "https://manifold.markets/test/who-will-win-the-2026-fifa-world-cup",
    "closeTime": 1_800_000_000_000,
    "outcomeType": "MULTIPLE_CHOICE",
    "volume": 5000,
    "volume24Hours": 250,
    "totalLiquidity": 1000,
    "uniqueBettorCount": 40,
    "isResolved": False,
    "sportsLeague": "FIFA World Cup",
    "token": "MANA",
}


SAMPLE_MULTI_DETAIL = {
    "id": "wc1",
    "textDescription": "National teams competing in the World Cup.",
    "groupSlugs": ["sports", "world-cup"],
    "answers": [
        {"id": "fr", "text": "France", "probability": 0.18, "volume": 1000},
        {"id": "br", "text": "Brazil", "probability": 0.16, "volume": 900},
        {"id": "es", "text": "Spain", "probability": 0.15, "volume": 800},
    ],
}


class TestNormalizeManifoldMarket(unittest.TestCase):
    def test_filters_resolved_and_inactive_markets(self):
        self.assertFalse(should_keep_market({**SAMPLE_BINARY, "isResolved": True}))
        self.assertFalse(should_keep_market({**SAMPLE_BINARY, "volume": 0, "volume24Hours": 0, "uniqueBettorCount": 0}))

    def test_normalizes_binary_market_for_shared_index_builder(self):
        market = normalize_market(SAMPLE_BINARY, now_ms=1_700_000_000_000)

        self.assertIsNotNone(market)
        assert market is not None
        self.assertEqual(market["title"], SAMPLE_BINARY["question"])
        self.assertEqual(market["slug"], SAMPLE_BINARY["slug"])
        self.assertEqual(market["source"], "manifold")
        self.assertEqual(market["token"], "MANA")
        self.assertIn({"label": "Crypto"}, market["tags"])
        self.assertEqual(market["markets"][0]["outcomePrices"], "[0.42, 0.58]")

    def test_normalizes_multiple_choice_answers_from_detail_payload(self):
        market = normalize_market(
            SAMPLE_MULTI,
            SAMPLE_MULTI_DETAIL,
            now_ms=1_700_000_000_000,
        )

        self.assertIsNotNone(market)
        assert market is not None
        self.assertEqual(len(market["markets"]), 3)
        self.assertEqual(market["markets"][0]["groupItemTitle"], "France")
        self.assertEqual(market["markets"][0]["outcomePrices"], "[0.18]")
        self.assertIn({"label": "Sports"}, market["tags"])
        self.assertIn({"label": "World Cup"}, market["tags"])

    def test_topic_hints_do_not_match_substrings(self):
        tags, _ = manifold_topic_metadata({
            **SAMPLE_MULTI,
            "question": "Will Spain win the FIFA World Cup?",
        })

        self.assertIn("World Cup", tags)
        self.assertNotIn("AI", tags)
        self.assertNotIn("Technology", tags)


class TestBuildManifoldIndex(unittest.TestCase):
    def test_builds_searchable_manifold_docs(self):
        markets = normalize_markets(
            [SAMPLE_BINARY, SAMPLE_MULTI],
            details_by_id={"wc1": SAMPLE_MULTI_DETAIL},
            now_ms=1_700_000_000_000,
        )
        data = build_index(markets)
        attach_manifold_fields(data, markets)

        self.assertEqual(data["n"], 2)
        docs_by_slug = {doc["s"]: doc for doc in data["docs"]}
        btc = docs_by_slug[SAMPLE_BINARY["slug"]]
        self.assertEqual(btc["p"], "manifold")
        self.assertEqual(btc["u"], SAMPLE_BINARY["url"])
        self.assertEqual(btc["tk"], "MANA")
        self.assertEqual(btc["vt"], 1234)
        self.assertIn("bitcoin", data["idx"])
        self.assertIn("world", data["idx"])


if __name__ == "__main__":
    unittest.main()
