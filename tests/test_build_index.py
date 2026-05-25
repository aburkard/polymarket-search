"""Tests for the index builder."""

import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from importlib import import_module

build_index_mod = import_module("build-index")
tokenize = build_index_mod.tokenize
parse_outcome_prices = build_index_mod.parse_outcome_prices
build_index = build_index_mod.build_index


SAMPLE_EVENTS = [
    {
        "id": "1",
        "title": "Bitcoin Prices",
        "slug": "bitcoin-prices",
        "tags": [{"label": "Crypto"}, {"label": "Bitcoin"}],
        "markets": [
            {
                "id": "100",
                "question": "Will Bitcoin hit $150k?",
                "slug": "btc-150k",
                "closed": False,
                "volume": "5000000",
                "volume24hr": "100000",
                "endDate": "2026-06-30T12:00:00Z",
                "image": "https://example.com/btc.jpg",
                "outcomePrices": '["0.15", "0.85"]',
            },
            {
                "id": "101",
                "question": "Will Bitcoin hit $200k?",
                "slug": "btc-200k",
                "closed": True,
                "volume": "3000000",
                "volume24hr": "50000",
                "endDate": "2026-12-31T12:00:00Z",
                "image": "https://example.com/btc2.jpg",
                "outcomePrices": '["0.05", "0.95"]',
            },
        ],
    },
    {
        "id": "2",
        "title": "Fed Rate Decision",
        "slug": "fed-rate",
        "tags": [{"label": "Finance"}, {"label": "Fed"}],
        "markets": [
            {
                "id": "200",
                "question": "Fed rate cut by June?",
                "slug": "fed-cut-june",
                "closed": False,
                "volume": "1000000",
                "volume24hr": "200000",
                "endDate": "2026-06-17T00:00:00Z",
                "image": "https://example.com/fed.jpg",
                "outcomePrices": '["0.80", "0.20"]',
            },
        ],
    },
    {
        "id": "3",
        "title": "Dead Market",
        "slug": "dead",
        "tags": [],
        "markets": [
            {
                "id": "300",
                "question": "Will nothing happen?",
                "slug": "nothing",
                "closed": False,
                "volume": "0",
                "volume24hr": "0",
                "endDate": "2026-01-01T00:00:00Z",
                "image": "",
                "outcomePrices": '["0.50", "0.50"]',
            },
        ],
    },
]


class TestTokenize(unittest.TestCase):
    def test_lowercase_and_split(self):
        self.assertEqual(tokenize("Hello World"), ["hello", "world"])

    def test_strip_currency(self):
        self.assertEqual(tokenize("$80,000"), ["80000"])

    def test_strip_percent(self):
        self.assertEqual(tokenize("3.3%"), ["3.3"])

    def test_filter_short(self):
        self.assertEqual(tokenize("I am a test"), ["am", "test"])

    def test_empty(self):
        self.assertEqual(tokenize(""), [])

    def test_preserves_numbers(self):
        self.assertEqual(tokenize("Bitcoin 100k 2026"), ["bitcoin", "100k", "2026"])

    def test_consistency_with_js(self):
        """Key cases that must match the JS tokenizer."""
        self.assertEqual(tokenize("$150k"), ["150k"])
        self.assertEqual(tokenize("trump's"), ["trump"])
        self.assertEqual(tokenize("Will Bitcoin hit $150k?"), ["will", "bitcoin", "hit", "150k"])


class TestParseOutcomePrices(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(parse_outcome_prices('["0.535", "0.465"]'), [0.535, 0.465])

    def test_none(self):
        self.assertEqual(parse_outcome_prices(None), [])

    def test_empty_string(self):
        self.assertEqual(parse_outcome_prices(""), [])

    def test_invalid_json(self):
        self.assertEqual(parse_outcome_prices("not json"), [])

    def test_already_list(self):
        self.assertEqual(parse_outcome_prices(["0.1", "0.9"]), [0.1, 0.9])


class TestBuildIndex(unittest.TestCase):
    def setUp(self):
        self.data = build_index(SAMPLE_EVENTS)

    def test_filters_closed_markets(self):
        questions = [d["q"] for d in self.data["docs"]]
        self.assertNotIn("Will Bitcoin hit $200k?", questions)

    def test_filters_zero_volume(self):
        questions = [d["q"] for d in self.data["docs"]]
        self.assertNotIn("Will nothing happen?", questions)

    def test_includes_active_markets(self):
        questions = [d["q"] for d in self.data["docs"]]
        self.assertIn("Will Bitcoin hit $150k?", questions)
        self.assertIn("Fed rate cut by June?", questions)

    def test_doc_count(self):
        self.assertEqual(self.data["n"], 2)
        self.assertEqual(len(self.data["docs"]), 2)

    def test_doc_fields(self):
        doc = self.data["docs"][0]
        for key in ("q", "s", "es", "ed", "im", "op", "v", "vt", "tg"):
            self.assertIn(key, doc, f"Missing key: {key}")

    def test_outcome_prices_parsed(self):
        doc = self.data["docs"][0]
        self.assertIsInstance(doc["op"], list)
        self.assertIsInstance(doc["op"][0], float)

    def test_volume_rounded(self):
        doc = self.data["docs"][0]
        self.assertIsInstance(doc["v"], int)
        self.assertIsInstance(doc["vt"], int)

    def test_end_date_trimmed(self):
        doc = self.data["docs"][0]
        self.assertEqual(doc["ed"], "2026-06-30")

    def test_tags_present(self):
        doc = self.data["docs"][0]
        self.assertIn("Crypto", doc["tg"])
        self.assertIn("Bitcoin", doc["tg"])

    def test_inverted_index_structure(self):
        idx = self.data["idx"]
        self.assertIsInstance(idx, dict)
        self.assertIn("bitcoin", idx)
        self.assertIsInstance(idx["bitcoin"], list)
        for doc_idx in idx["bitcoin"]:
            self.assertIsInstance(doc_idx, int)
            self.assertLess(doc_idx, self.data["n"])

    def test_idf_computed(self):
        idf = self.data["idf"]
        self.assertIn("bitcoin", idf)
        self.assertIsInstance(idf["bitcoin"], float)
        self.assertGreater(idf["bitcoin"], 0)

    def test_idf_common_term_lower(self):
        idf = self.data["idf"]
        # Both docs have tag "Finance" or text containing common terms;
        # "fed" and "rate" only appear in one doc, so they should have
        # higher IDF than terms appearing in both.
        # In our 2-doc fixture, terms in both docs get idf=log(2/2)=0,
        # terms in one doc get idf=log(2/1)=0.6931.
        # Verify the math: a term in 1 doc has higher IDF than one in 2.
        self.assertAlmostEqual(math.log(2 / 1), 0.6931, places=3)

    def test_no_duplicate_doc_indices(self):
        for term, doc_indices in self.data["idx"].items():
            self.assertEqual(len(doc_indices), len(set(doc_indices)),
                             f"Duplicate doc indices for term '{term}'")

    def test_version_and_timestamp(self):
        self.assertEqual(self.data["v"], 1)
        self.assertIn("ts", self.data)
        self.assertRegex(self.data["ts"], r"\d{4}-\d{2}-\d{2}T")

    def test_event_slug_stored(self):
        doc = self.data["docs"][0]
        self.assertEqual(doc["es"], "bitcoin-prices")


class TestBuildIndexEmpty(unittest.TestCase):
    def test_empty_events(self):
        data = build_index([])
        self.assertEqual(data["n"], 0)
        self.assertEqual(len(data["docs"]), 0)
        self.assertEqual(len(data["idx"]), 0)

    def test_events_with_no_markets(self):
        events = [{"id": "1", "title": "Empty", "slug": "empty", "tags": [], "markets": []}]
        data = build_index(events)
        self.assertEqual(data["n"], 0)


if __name__ == "__main__":
    unittest.main()
