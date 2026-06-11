"""Tests for the Kalshi index builder."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

kalshi_mod = import_module("build-kalshi-index")
normalize_event = kalshi_mod.normalize_event
normalize_events = kalshi_mod.normalize_events
attach_kalshi_fields = kalshi_mod.attach_kalshi_fields
kalshi_topic_metadata = kalshi_mod.kalshi_topic_metadata
build_index = kalshi_mod.build_index


SAMPLE_KALSHI_EVENT = {
    "event_ticker": "KXBTC-26JUN",
    "series_ticker": "KXBTC",
    "title": "Bitcoin above $100,000 on Jun 30?",
    "category": "Crypto",
    "mutually_exclusive": False,
    "markets": [
        {
            "ticker": "KXBTC-26JUN-T100000",
            "event_ticker": "KXBTC-26JUN",
            "title": "Will Bitcoin be above $100,000 on Jun 30?",
            "yes_sub_title": "Above $100,000",
            "status": "active",
            "yes_bid_dollars": "0.4100",
            "yes_ask_dollars": "0.4300",
            "last_price_dollars": "0.4200",
            "volume_fp": "12345.67",
            "volume_24h_fp": "234.56",
            "close_time": "2026-06-30T16:00:00Z",
        },
    ],
}


EXCLUSIVE_KALSHI_EVENT = {
    "event_ticker": "KXWINNER-26",
    "series_ticker": "KXWINNER",
    "title": "Who will win?",
    "category": "Politics",
    "mutually_exclusive": True,
    "markets": [
        {
            "ticker": "KXWINNER-26-A",
            "title": "Will Alice win?",
            "yes_sub_title": "Alice",
            "status": "active",
            "yes_bid_dollars": "0.3900",
            "yes_ask_dollars": "0.4100",
            "last_price_dollars": "0.4000",
            "volume_fp": "10000",
            "volume_24h_fp": "100",
            "close_time": "2026-11-03T05:00:00Z",
        },
        {
            "ticker": "KXWINNER-26-B",
            "title": "Will Bob win?",
            "yes_sub_title": "Bob",
            "status": "active",
            "yes_bid_dollars": "0.2900",
            "yes_ask_dollars": "0.3100",
            "last_price_dollars": "0.3000",
            "volume_fp": "10000",
            "volume_24h_fp": "100",
            "close_time": "2026-11-03T05:00:00Z",
        },
    ],
}


class TestNormalizeKalshiEvent(unittest.TestCase):
    def test_normalizes_event_shape_for_shared_index_builder(self):
        event = normalize_event(SAMPLE_KALSHI_EVENT)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["title"], "Bitcoin above $100,000 on Jun 30?")
        self.assertEqual(event["slug"], "kxbtc-26jun")
        self.assertEqual(event["tags"], [{"label": "Crypto"}, {"label": "Bitcoin"}])
        self.assertEqual(event["url"], "https://kalshi.com/markets/kxbtc")
        self.assertEqual(event["endDate"], "2026-06-30T16:00:00Z")

    def test_normalizes_market_prices_and_volume(self):
        event = normalize_event(SAMPLE_KALSHI_EVENT)
        assert event is not None
        market = event["markets"][0]

        self.assertEqual(market["groupItemTitle"], "Above $100,000")
        self.assertEqual(market["volume"], "12345.67")
        self.assertEqual(market["volume24hr"], "234.56")
        self.assertEqual(market["outcomePrices"], "[0.42, 0.58]")
        self.assertEqual(market["bestBid"], "0.4100")
        self.assertEqual(market["bestAsk"], "0.4300")
        self.assertEqual(market["lastTradePrice"], "0.4200")

    def test_marks_settled_markets_closed(self):
        raw = {
            **SAMPLE_KALSHI_EVENT,
            "markets": [{**SAMPLE_KALSHI_EVENT["markets"][0], "status": "settled"}],
        }
        event = normalize_event(raw)
        assert event is not None
        self.assertTrue(event["markets"][0]["closed"])


class TestBuildKalshiIndex(unittest.TestCase):
    def test_builds_searchable_kalshi_docs(self):
        events = normalize_events([SAMPLE_KALSHI_EVENT])
        data = build_index(events)
        attach_kalshi_fields(data, events)

        self.assertEqual(data["n"], 1)
        doc = data["docs"][0]
        self.assertEqual(doc["p"], "kalshi")
        self.assertEqual(doc["u"], "https://kalshi.com/markets/kxbtc")
        self.assertEqual(doc["ed"], "2026-06-30")
        self.assertIn("Crypto", doc["tg"])
        self.assertIn("Bitcoin", doc["tg"])
        self.assertIn("bitcoin", data["idx"])
        self.assertIn("100000", data["idx"])

    def test_adds_topic_metadata_from_kalshi_ticker(self):
        event = {
            "event_ticker": "KXMLBGAME-26JUN101840MINDET",
            "series_ticker": "KXMLBGAME",
        }

        tags, aliases = kalshi_topic_metadata(event)

        self.assertIn("MLB", tags)
        self.assertIn("Baseball", tags)
        self.assertIn("mlb", aliases)
        self.assertIn("baseball", aliases)

    def test_mutually_exclusive_prices_are_normalized_by_shared_builder(self):
        events = normalize_events([EXCLUSIVE_KALSHI_EVENT])
        data = build_index(events)
        doc = data["docs"][0]

        self.assertEqual(doc["mc"], 2)
        total = sum(m["op"][0] for m in doc["mk"])
        self.assertAlmostEqual(total, 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
