"""Tests for the index builder."""

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from importlib import import_module

build_index_mod = import_module("build-index")
tokenize = build_index_mod.tokenize
parse_outcome_prices = build_index_mod.parse_outcome_prices
build_index = build_index_mod.build_index
fetch_events_for_mode = build_index_mod.fetch_events_for_mode


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
                "groupItemTitle": "$100,000",
                "groupItemThreshold": "100000",
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

EXCLUSIVE_EVENT = {
    "id": "10",
    "title": "Who will win?",
    "slug": "who-will-win",
    "negRisk": True,
    "enableNegRisk": True,
    "tags": [{"label": "Politics"}],
    "markets": [
        {"id": "1001", "question": "Will Alice win?", "slug": "alice", "closed": False,
         "volume": "500000", "volume24hr": "10000", "groupItemTitle": "Alice",
         "outcomePrices": '["0.40", "0.60"]', "bestBid": "0.38", "bestAsk": "0.42", "lastTradePrice": "0.40",
         "endDate": "2026-12-31T00:00:00Z", "image": ""},
        {"id": "1002", "question": "Will Bob win?", "slug": "bob", "closed": False,
         "volume": "500000", "volume24hr": "10000", "groupItemTitle": "Bob",
         "outcomePrices": '["0.30", "0.70"]', "bestBid": "0.28", "bestAsk": "0.32", "lastTradePrice": "0.30",
         "endDate": "2026-12-31T00:00:00Z", "image": ""},
        {"id": "1003", "question": "Will Carol win?", "slug": "carol", "closed": False,
         "volume": "500000", "volume24hr": "10000", "groupItemTitle": "Carol",
         "outcomePrices": '["0.20", "0.80"]', "bestBid": "0.18", "bestAsk": "0.22", "lastTradePrice": "0.20",
         "endDate": "2026-12-31T00:00:00Z", "image": ""},
    ],
}

INDEPENDENT_EVENT = {
    "id": "11",
    "title": "What will happen?",
    "slug": "what-will-happen",
    "negRisk": False,
    "enableNegRisk": False,
    "tags": [{"label": "Culture"}],
    "markets": [
        {"id": "1101", "question": "Will X happen?", "slug": "x", "closed": False,
         "volume": "100000", "volume24hr": "5000", "groupItemTitle": "X",
         "outcomePrices": '["0.60", "0.40"]',
         "endDate": "2026-12-31T00:00:00Z", "image": ""},
        {"id": "1102", "question": "Will Y happen?", "slug": "y", "closed": False,
         "volume": "100000", "volume24hr": "5000", "groupItemTitle": "Y",
         "outcomePrices": '["0.70", "0.30"]',
         "endDate": "2026-12-31T00:00:00Z", "image": ""},
    ],
}

EXCLUSIVE_WITH_DEAD = {
    "id": "12",
    "title": "Big race",
    "slug": "big-race",
    "negRisk": True,
    "enableNegRisk": True,
    "tags": [],
    "markets": [
        {"id": "1201", "question": "Will Fav win?", "slug": "fav", "closed": False,
         "volume": "100000", "volume24hr": "1000", "groupItemTitle": "Fav",
         "outcomePrices": '["0.60", "0.40"]',
         "endDate": "2026-12-31T00:00:00Z", "image": ""},
        {"id": "1202", "question": "Will Underdog win?", "slug": "underdog", "closed": False,
         "volume": "100000", "volume24hr": "1000", "groupItemTitle": "Underdog",
         "outcomePrices": '["0.30", "0.70"]',
         "endDate": "2026-12-31T00:00:00Z", "image": ""},
        {"id": "1203", "question": "Will Nobody win?", "slug": "nobody", "closed": False,
         "volume": "5", "volume24hr": "0", "groupItemTitle": "Nobody",
         "outcomePrices": '["0.50", "0.50"]', "bestBid": "0", "bestAsk": "1", "lastTradePrice": "0",
         "endDate": "2026-12-31T00:00:00Z", "image": ""},
    ],
}


SPORT_DRAW_EVENT = {
    "id": "20",
    "title": "United States vs. Australia",
    "slug": "fifwc-usa-aus-2026-06-19",
    "negRisk": True,
    "enableNegRisk": True,
    "sport": {"sport": "fifwc"},
    "eventDate": "2026-06-19",
    "tags": [{"label": "Sports"}, {"label": "Soccer"}],
    "teams": [
        {"name": "United States", "logo": "us.png", "record": "0-0", "abbreviation": "usa"},
        {"name": "Australia", "logo": "au.png", "record": "0-0", "abbreviation": "aus"},
    ],
    "markets": [
        {"id": "2001", "question": "Will United States vs. Australia end in a draw?", "slug": "draw",
         "closed": False, "volume": "258", "volume24hr": "0", "groupItemTitle": "Draw (United States vs. Australia)",
         "outcomePrices": '["0.245", "0.755"]', "bestBid": "0.24", "bestAsk": "0.25", "lastTradePrice": "0.25",
         "endDate": "2026-06-19T00:00:00Z", "image": ""},
        {"id": "2002", "question": "Will Australia win on 2026-06-19?", "slug": "aus",
         "closed": False, "volume": "148", "volume24hr": "0", "groupItemTitle": "Australia",
         "outcomePrices": '["0.20", "0.80"]', "bestBid": "0.19", "bestAsk": "0.21", "lastTradePrice": "0.21",
         "endDate": "2026-06-19T00:00:00Z", "image": ""},
        {"id": "2003", "question": "Will United States win on 2026-06-19?", "slug": "usa",
         "closed": False, "volume": "441", "volume24hr": "103", "groupItemTitle": "United States",
         "outcomePrices": '["0.565", "0.435"]', "bestBid": "0.55", "bestAsk": "0.58", "lastTradePrice": "0.58",
         "endDate": "2026-06-19T00:00:00Z", "image": ""},
    ],
}


SPORT_NEXT_TEAM_EVENT = {
    "id": "21",
    "title": "NBA: LeBron James Next Team",
    "slug": "lebron-james-next-team",
    "negRisk": True,
    "enableNegRisk": True,
    "sport": {"sport": "nba"},
    "tags": [{"label": "Sports"}, {"label": "NBA"}],
    "teams": [
        {"name": "Cleveland Cavaliers", "abbreviation": "cle"},
        {"name": "Golden State Warriors", "abbreviation": "gsw"},
    ],
    "markets": [
        {"id": "2101", "question": "Will LeBron James play for the Cleveland Cavaliers next?",
         "slug": "cle", "closed": False, "volume": "100000", "volume24hr": "1000",
         "groupItemTitle": "Cleveland Cavaliers", "groupItemThreshold": "0",
         "outcomePrices": '["0.42", "0.58"]',
         "endDate": "2026-10-31T00:00:00Z", "image": ""},
        {"id": "2102", "question": "Will LeBron James play for the Golden State Warriors next?",
         "slug": "gsw", "closed": False, "volume": "100000", "volume24hr": "1000",
         "groupItemTitle": "Golden State Warriors", "groupItemThreshold": "1",
         "outcomePrices": '["0.19", "0.81"]',
         "endDate": "2026-10-31T00:00:00Z", "image": ""},
        {"id": "2103", "question": "Will LeBron James play for the Denver Nuggets next?",
         "slug": "den", "closed": False, "volume": "100000", "volume24hr": "5000",
         "groupItemTitle": "Denver Nuggets", "groupItemThreshold": "2",
         "outcomePrices": '["0.03", "0.97"]',
         "endDate": "2026-10-31T00:00:00Z", "image": ""},
        {"id": "2104", "question": "Will LeBron James play for the Philadelphia 76ers next?",
         "slug": "phi", "closed": False, "volume": "100000", "volume24hr": "1000",
         "groupItemTitle": "Philadelphia 76ers", "groupItemThreshold": "3",
         "outcomePrices": '["0.11", "0.89"]',
         "endDate": "2026-10-31T00:00:00Z", "image": ""},
    ],
}


SPORT_SINGLE_MONEYLINE_EVENT = {
    "id": "22",
    "title": "Knicks vs. Cavaliers",
    "slug": "nba-nyk-cle-2026-05-25",
    "sport": {"sport": "nba"},
    "teams": [
        {"name": "Knicks", "abbreviation": "nyk"},
        {"name": "Cavaliers", "abbreviation": "cle"},
    ],
    "markets": [
        {"id": "2201", "question": "Will the Knicks beat the Cavaliers?",
         "slug": "nyk-cle", "closed": False, "volume": "100000", "volume24hr": "1000",
         "groupItemTitle": "Knicks vs. Cavaliers", "groupItemThreshold": "0",
         "outcomePrices": '["0.53", "0.47"]',
         "endDate": "2026-05-25T00:00:00Z", "image": ""},
        {"id": "2202", "question": "Will Knicks vs. Cavaliers clear the spread?",
         "slug": "spread", "closed": False, "volume": "100000", "volume24hr": "1000",
         "groupItemTitle": "Spread -1.5", "groupItemThreshold": "1",
         "outcomePrices": '["0.51", "0.49"]',
         "endDate": "2026-05-25T00:00:00Z", "image": ""},
        {"id": "2203", "question": "Will Knicks vs. Cavaliers go over 218.5?",
         "slug": "total", "closed": False, "volume": "100000", "volume24hr": "1000",
         "groupItemTitle": "O/U 218.5", "groupItemThreshold": "2",
         "outcomePrices": '["0.49", "0.51"]',
         "endDate": "2026-05-25T00:00:00Z", "image": ""},
    ],
}


THRESHOLD_EVENT = {
    "id": "13",
    "title": "What price will Ethereum hit in 2026?",
    "slug": "ethereum-thresholds",
    "tags": [{"label": "Crypto"}, {"label": "Ethereum"}],
    "markets": [
        {
            "id": f"130{i}",
            "question": f"Will Ethereum reach ${i * 1000:,} by December 31, 2026?",
            "slug": f"eth-{i}k",
            "closed": False,
            "volume": "1000",
            "volume24hr": "100",
            "groupItemTitle": f"Up {i * 1000:,}",
            "groupItemThreshold": str(i),
            "outcomePrices": json.dumps([round((14 - i) / 100, 4), round(1 - ((14 - i) / 100), 4)]),
            "endDate": "2026-12-31T00:00:00Z",
            "image": "",
        }
        for i in range(1, 14)
    ],
}


class TestTokenize(unittest.TestCase):
    def test_lowercase_and_split(self):
        self.assertEqual(tokenize("Hello World"), ["hello", "world"])

    def test_strip_currency(self):
        self.assertEqual(tokenize("$80,000"), ["80000", "80k"])

    def test_strip_percent(self):
        self.assertEqual(tokenize("3.3%"), ["3.3"])

    def test_filter_short(self):
        self.assertEqual(tokenize("I am a test"), ["am", "test"])

    def test_empty(self):
        self.assertEqual(tokenize(""), [])

    def test_preserves_numbers(self):
        self.assertEqual(tokenize("Bitcoin 100k 2026"), ["bitcoin", "100k", "100000", "2026"])

    def test_normalizes_suffix_numbers(self):
        self.assertEqual(tokenize("5k 5000 2m"), ["5k", "5000", "5000", "5k", "2m", "2000000"])

    def test_consistency_with_js(self):
        """Key cases that must match the JS tokenizer."""
        self.assertEqual(tokenize("$150k"), ["150k", "150000"])
        self.assertEqual(tokenize("trump's"), ["trump"])
        self.assertEqual(tokenize("Will Bitcoin hit $150k?"), ["will", "bitcoin", "hit", "150k", "150000"])


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


class TestFetchEventsForMode(unittest.TestCase):
    def test_active_fetch_uses_gamma_page_size(self):
        with patch.object(build_index_mod, "fetch_all_events", return_value=[]) as fetch_all_events:
            fetch_events_for_mode(archived=False, max_pages=3)

        fetch_all_events.assert_called_once_with(
            active="true",
            closed="false",
            page_size=100,
            max_pages=3,
        )

    def test_archived_fetch_uses_gamma_page_size(self):
        with patch.object(build_index_mod, "fetch_all_events", return_value=[]) as fetch_all_events:
            fetch_events_for_mode(archived=True, max_pages=3)

        fetch_all_events.assert_called_once_with(
            active="false",
            closed="true",
            page_size=100,
            max_pages=3,
        )


class TestBuildIndex(unittest.TestCase):
    def setUp(self):
        self.data = build_index(SAMPLE_EVENTS)

    def test_skips_events_with_only_closed_markets(self):
        titles = [d["q"] for d in self.data["docs"]]
        self.assertNotIn("Dead Market", titles)

    def test_skips_events_with_only_zero_volume(self):
        self.assertEqual(self.data["n"], 2)

    def test_indexes_at_event_level(self):
        titles = [d["q"] for d in self.data["docs"]]
        self.assertIn("Bitcoin Prices", titles)
        self.assertIn("Fed Rate Decision", titles)

    def test_doc_count(self):
        self.assertEqual(self.data["n"], 2)
        self.assertEqual(len(self.data["docs"]), 2)

    def test_doc_fields(self):
        doc = self.data["docs"][0]
        for key in ("q", "s", "ed", "im", "v", "vt", "tg", "mc", "mk"):
            self.assertIn(key, doc, f"Missing key: {key}")

    def test_doc_uses_event_slug(self):
        doc = self.data["docs"][0]
        self.assertEqual(doc["s"], "bitcoin-prices")

    def test_markets_array_has_outcomes(self):
        doc = self.data["docs"][0]
        self.assertIsInstance(doc["mk"], list)
        self.assertGreater(len(doc["mk"]), 0)
        mk = doc["mk"][0]
        self.assertIn("q", mk)
        self.assertIn("op", mk)
        self.assertIsInstance(mk["op"], list)
        self.assertIsInstance(mk["op"][0], float)

    def test_closed_markets_excluded_from_outcomes(self):
        doc = next(d for d in self.data["docs"] if d["q"] == "Bitcoin Prices")
        market_qs = [m["q"] for m in doc["mk"]]
        self.assertIn("Will Bitcoin hit $150k?", market_qs)
        self.assertNotIn("Will Bitcoin hit $200k?", market_qs)

    def test_market_count(self):
        doc = next(d for d in self.data["docs"] if d["q"] == "Bitcoin Prices")
        self.assertEqual(doc["mc"], 1)

    def test_volume_aggregated(self):
        doc = next(d for d in self.data["docs"] if d["q"] == "Bitcoin Prices")
        self.assertEqual(doc["v"], 100000)
        self.assertEqual(doc["vt"], 5000000)

    def test_volume_rounded(self):
        doc = self.data["docs"][0]
        self.assertIsInstance(doc["v"], int)
        self.assertIsInstance(doc["vt"], int)

    def test_tags_present(self):
        doc = next(d for d in self.data["docs"] if d["q"] == "Bitcoin Prices")
        self.assertIn("Crypto", doc["tg"])
        self.assertIn("Bitcoin", doc["tg"])

    def test_child_market_questions_indexed(self):
        idx = self.data["idx"]
        self.assertIn("150k", idx)

    def test_child_market_labels_and_thresholds_indexed(self):
        idx = self.data["idx"]
        self.assertIn("100000", idx)
        self.assertIn("100k", idx)

    def test_stores_enough_child_markets_for_query_relevant_display(self):
        data = build_index([THRESHOLD_EVENT])
        doc = data["docs"][0]
        labels = [m["l"] for m in doc["mk"]]
        self.assertEqual(len(doc["mk"]), 12)
        self.assertIn("Up 5,000", labels)
        self.assertNotIn("Up 13,000", labels)

    def test_archived_index_includes_closed_markets(self):
        data = build_index(
            SAMPLE_EVENTS,
            include_closed_markets=True,
            archived=True,
        )
        doc = next(d for d in data["docs"] if d["q"] == "Bitcoin Prices")
        market_qs = [m["q"] for m in doc["mk"]]
        self.assertEqual(doc["ar"], 1)
        self.assertEqual(doc["mc"], 2)
        self.assertIn("Will Bitcoin hit $200k?", market_qs)

    def test_inverted_index_structure(self):
        idx = self.data["idx"]
        self.assertIsInstance(idx, dict)
        self.assertIn("bitcoin", idx)
        self.assertIsInstance(idx["bitcoin"], list)
        for posting in idx["bitcoin"]:
            self.assertIsInstance(posting, list)
            self.assertEqual(len(posting), 2)
            doc_idx, tf = posting
            self.assertIsInstance(doc_idx, int)
            self.assertLess(doc_idx, self.data["n"])
            self.assertGreater(tf, 0)

    def test_doc_lengths_stored(self):
        self.assertIn("dl", self.data)
        self.assertIn("avgDl", self.data)
        self.assertEqual(len(self.data["dl"]), self.data["n"])
        self.assertGreater(self.data["avgDl"], 0)

    def test_idf_computed(self):
        idf = self.data["idf"]
        self.assertIn("bitcoin", idf)
        self.assertIsInstance(idf["bitcoin"], float)
        self.assertGreater(idf["bitcoin"], 0)

    def test_no_duplicate_doc_indices(self):
        for term, postings in self.data["idx"].items():
            doc_ids = [p[0] for p in postings]
            self.assertEqual(len(doc_ids), len(set(doc_ids)),
                             f"Duplicate doc indices for term '{term}'")

    def test_version_and_timestamp(self):
        self.assertEqual(self.data["v"], 3)
        self.assertIn("ts", self.data)
        self.assertRegex(self.data["ts"], r"\d{4}-\d{2}-\d{2}T")

    def test_custom_enrichments_path_adds_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "enrichments.jsonl"
            path.write_text(json.dumps({
                "slug": "fed-rate",
                "aliases": ["central bank"],
            }) + "\n")
            data = build_index(SAMPLE_EVENTS, enrichments_path=path)

        self.assertIn("central", data["ctx"])
        self.assertIn("bank", data["ctx"])
        self.assertEqual(data["_n_enriched"], 1)


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


class TestNormalization(unittest.TestCase):
    def test_exclusive_event_prices_normalized(self):
        """Mutually exclusive event: prices should be normalized to sum ~100%."""
        data = build_index([EXCLUSIVE_EVENT])
        doc = data["docs"][0]
        prices = [m["op"][0] for m in doc["mk"]]
        total = sum(prices)
        self.assertAlmostEqual(total, 1.0, places=1,
            msg=f"Normalized prices should sum to ~1.0, got {total}")

    def test_exclusive_event_relative_order(self):
        """Normalization should preserve relative ordering."""
        data = build_index([EXCLUSIVE_EVENT])
        doc = data["docs"][0]
        prices = [m["op"][0] for m in doc["mk"]]
        self.assertEqual(prices, sorted(prices, reverse=True),
            msg="Prices should still be in descending order")

    def test_exclusive_event_alice_is_highest(self):
        """Alice (0.40 raw) should be highest after normalization."""
        data = build_index([EXCLUSIVE_EVENT])
        doc = data["docs"][0]
        self.assertEqual(doc["mk"][0]["l"], "Alice")
        self.assertGreater(doc["mk"][0]["op"][0], 0.4,
            msg="Alice should be >40% after normalization (raw sum was 0.9)")

    def test_independent_event_not_normalized(self):
        """Non-mutually-exclusive event: prices should NOT be normalized."""
        data = build_index([INDEPENDENT_EVENT])
        doc = data["docs"][0]
        prices = [m["op"][0] for m in doc["mk"]]
        self.assertAlmostEqual(prices[0], 0.70, places=2,
            msg="Y should stay at ~70% (not normalized)")
        self.assertAlmostEqual(prices[1], 0.60, places=2,
            msg="X should stay at ~60% (not normalized)")

    def test_exclusive_with_dead_markets_excluded(self):
        """Dead markets (low vol, ~50%) should not inflate normalization."""
        data = build_index([EXCLUSIVE_WITH_DEAD])
        doc = data["docs"][0]
        fav = next(m for m in doc["mk"] if m["l"] == "Fav")
        # Raw: 0.60, sum of meaningful: 0.60+0.30=0.90, normalized: 0.60/0.90=0.667
        # If dead market included: sum=1.40, normalized: 0.60/1.40=0.43 (wrong)
        self.assertGreater(fav["op"][0], 0.6,
            msg="Fav should be >60% (dead market excluded from norm)")

    def test_bid_ask_last_stored(self):
        """Bid, ask, and last trade price should be stored when available."""
        data = build_index([EXCLUSIVE_EVENT])
        doc = data["docs"][0]
        alice = doc["mk"][0]
        self.assertIn("bid", alice)
        self.assertIn("ask", alice)
        self.assertIn("last", alice)
        self.assertAlmostEqual(alice["bid"], 0.38, places=2)
        self.assertAlmostEqual(alice["ask"], 0.42, places=2)
        self.assertAlmostEqual(alice["last"], 0.40, places=2)

    def test_no_bid_ask_when_absent(self):
        """Markets without bid/ask data should not have those fields."""
        data = build_index([INDEPENDENT_EVENT])
        doc = data["docs"][0]
        m = doc["mk"][0]
        self.assertNotIn("bid", m)
        self.assertNotIn("last", m)

    def test_sports_moneyline_uses_each_team_yes_market(self):
        """Draw-capable sports cards should not label a binary No price as the other team."""
        data = build_index([SPORT_DRAW_EVENT])
        doc = data["docs"][0]
        by_label = {m["l"]: m for m in doc["mk"]}

        self.assertEqual([m["l"] for m in doc["mk"][:3]], [
            "United States",
            "Australia",
            "Draw (United States vs. Australia)",
        ])
        self.assertAlmostEqual(by_label["United States"]["op"][0], 0.5594, places=4)
        self.assertAlmostEqual(by_label["Australia"]["op"][0], 0.1980, places=4)
        self.assertNotAlmostEqual(by_label["Australia"]["op"][0], 0.4406, places=3)

    def test_sports_future_uses_probability_order(self):
        """Sports futures/props should not treat option indexes as ordered thresholds."""
        data = build_index([SPORT_NEXT_TEAM_EVENT])
        doc = data["docs"][0]

        self.assertEqual([m["l"] for m in doc["mk"][:3]], [
            "Cleveland Cavaliers",
            "Golden State Warriors",
            "Philadelphia 76ers",
        ])
        self.assertLess(
            [m["l"] for m in doc["mk"]].index("Philadelphia 76ers"),
            [m["l"] for m in doc["mk"]].index("Denver Nuggets"),
        )

    def test_sports_matchup_keeps_representative_markets(self):
        """Two-team matchup cards should keep the sports-specific summary rows."""
        data = build_index([SPORT_SINGLE_MONEYLINE_EVENT])
        doc = data["docs"][0]

        self.assertEqual([m["l"] for m in doc["mk"][:2]], [
            "Spread -1.5",
            "O/U 218.5",
        ])


if __name__ == "__main__":
    unittest.main()
