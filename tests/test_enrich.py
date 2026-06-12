"""Tests for enrichment provider helpers."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

enrich = import_module("enrich")


class TestKalshiEnrichmentHelpers(unittest.TestCase):
    def test_uses_event_ticker_as_kalshi_slug(self):
        event = {"event_ticker": "KXBTC-26JUN"}
        self.assertEqual(enrich.event_slug(event, "kalshi"), "kxbtc-26jun")

    def test_reads_kalshi_volume_fields(self):
        market = {"volume_fp": "123.45", "volume_24h_fp": "6.78"}
        self.assertEqual(enrich.market_volume(market), 123.45)
        self.assertEqual(enrich.market_volume_24h(market), 6.78)

    def test_builds_kalshi_prompt_from_category_and_market_labels(self):
        event = {
            "event_ticker": "KXMLBGAME-26JUN101840MINDET",
            "series_ticker": "KXMLBGAME",
            "title": "2026 Men's World Cup Winner",
            "category": "Sports",
            "sub_title": "Winner",
            "markets": [
                {
                    "status": "active",
                    "yes_sub_title": "Spain",
                    "title": "Will Spain win the 2026 World Cup?",
                }
            ],
        }

        msg = enrich.user_message(event, "kalshi")
        self.assertIn("Event: 2026 Men's World Cup Winner", msg)
        self.assertIn("Event ticker: KXMLBGAME-26JUN101840MINDET", msg)
        self.assertIn("Series ticker: KXMLBGAME", msg)
        self.assertIn("Category: Sports", msg)
        self.assertIn("Spain: Will Spain win the 2026 World Cup?", msg)

    def test_active_markets_excludes_settled_kalshi_markets(self):
        event = {
            "markets": [
                {"status": "active", "title": "Active"},
                {"status": "settled", "title": "Settled"},
            ],
        }
        self.assertEqual([m["title"] for m in enrich.active_markets(event)], ["Active"])

    def test_enrichment_candidates_skip_existing_and_baseline(self):
        events = [
            {
                "event_ticker": "KXOLD",
                "markets": [{"status": "active", "volume_fp": "10"}],
            },
            {
                "event_ticker": "KXENRICHED",
                "markets": [{"status": "active", "volume_fp": "20"}],
            },
            {
                "event_ticker": "KXNEW",
                "markets": [{"status": "active", "volume_fp": "30"}],
            },
            {
                "event_ticker": "KXNOVOL",
                "markets": [{"status": "active", "volume_fp": "0", "volume_24h_fp": "0"}],
            },
        ]

        candidates = enrich.enrichment_candidates(
            events,
            "kalshi",
            {"kxenriched": ["already done"]},
            baseline_slugs={"kxold"},
        )

        self.assertEqual([enrich.event_slug(ev, "kalshi") for ev in candidates], ["kxnew"])

    def test_event_slugs_collects_provider_slugs(self):
        events = [
            {"event_ticker": "KXBTC-26JUN"},
            {"event_ticker": "KXNBA-26"},
            {"title": "missing ticker"},
        ]
        self.assertEqual(
            enrich.event_slugs(events, "kalshi"),
            {"kxbtc-26jun", "kxnba-26"},
        )


if __name__ == "__main__":
    unittest.main()
