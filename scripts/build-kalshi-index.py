"""Build the search index from Kalshi's public market data API."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from importlib import import_module
from pathlib import Path
from typing import Any

build_index_mod = import_module("build-index")
build_index = build_index_mod.build_index

BASE = "https://external-api.kalshi.com/trade-api/v2"
PUBLIC = Path(__file__).parent.parent / "public"
OUT = PUBLIC / "search-data-kalshi.json"
SNAPSHOT = Path(__file__).parent.parent / "data" / "kalshi_events_open.jsonl"
ENRICHMENT_FILE = Path(__file__).parent.parent / "data" / "kalshi_enrichments.jsonl"

USER_AGENT = "polymarket-search-indexer/0.1 (andrewburkard@gmail.com)"
API_PAGE_SIZE = 200


def _request_json(path: str, params: dict[str, Any]) -> dict:
    qs = urllib.parse.urlencode(params)
    url = f"{BASE}{path}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def fetch_all_events(
    *,
    status: str = "open",
    page_size: int = API_PAGE_SIZE,
    max_pages: int = 0,
) -> list[dict]:
    events: list[dict] = []
    cursor = ""
    pages = 0

    while True:
        params: dict[str, Any] = {
            "limit": page_size,
            "status": status,
            "with_nested_markets": "true",
        }
        if cursor:
            params["cursor"] = cursor

        try:
            page = _request_json("/events", params)
        except Exception as e:
            print(f"  ERROR at cursor={cursor or '<first>'}: {e}", file=sys.stderr)
            if not events:
                raise
            print(f"  Stopping early with {len(events)} events", file=sys.stderr)
            break

        got = page.get("events") or []
        if not got:
            break

        events.extend(got)
        cursor = page.get("cursor") or ""
        pages += 1
        print(f"  fetched page={pages} got={len(got)} total={len(events)}")

        if not cursor:
            break
        if max_pages and pages >= max_pages:
            print(f"  Reached max pages ({max_pages})")
            break

        # Kalshi responses are public-cacheable. Be polite during full builds.
        time.sleep(0.05)

    return events


def load_local_events(path: str) -> list[dict]:
    events = []
    with open(path) as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
    return events


def _float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _yes_probability(market: dict) -> float:
    bid = _float(market.get("yes_bid_dollars"), -1)
    ask = _float(market.get("yes_ask_dollars"), -1)
    last = _float(market.get("last_price_dollars"), 0)

    if bid >= 0 and ask >= 0:
        return round((bid + ask) / 2, 4)
    if last > 0:
        return round(last, 4)
    if bid >= 0:
        return round(bid, 4)
    if ask >= 0:
        return round(ask, 4)
    return 0.0


def _event_url(event: dict) -> str:
    slug = (event.get("series_ticker") or event.get("event_ticker") or "").lower()
    if not slug:
        return "https://kalshi.com/markets"
    return f"https://kalshi.com/markets/{slug}"


def _event_end_date(markets: list[dict], event: dict) -> str:
    dates = [
        m.get("close_time") or m.get("expected_expiration_time") or m.get("expiration_time")
        for m in markets
        if m.get("close_time") or m.get("expected_expiration_time") or m.get("expiration_time")
    ]
    if dates:
        return sorted(dates)[0]
    return event.get("strike_date") or ""


def _market_label(event: dict, market: dict, market_count: int) -> str:
    label = (
        market.get("yes_sub_title")
        or market.get("subtitle")
        or market.get("title")
        or ""
    )
    title = event.get("title") or ""
    if market_count == 1 and label == title:
        return ""
    return label


def normalize_event(event: dict) -> dict | None:
    markets = []
    for market in event.get("markets") or []:
        status = (market.get("status") or "").lower()
        closed = status in {"closed", "settled", "expired", "finalized"}
        volume = _float(market.get("volume_fp"))
        volume24 = _float(market.get("volume_24h_fp"))
        probability = _yes_probability(market)

        markets.append({
            "id": market.get("ticker") or "",
            "question": market.get("title") or event.get("title") or "",
            "slug": (market.get("ticker") or "").lower(),
            "closed": closed,
            "volume": str(volume),
            "volume24hr": str(volume24),
            "endDate": (
                market.get("close_time")
                or market.get("expected_expiration_time")
                or market.get("expiration_time")
                or ""
            ),
            "groupItemTitle": _market_label(event, market, len(event.get("markets") or [])),
            "outcomePrices": json.dumps([probability, round(1 - probability, 4)]),
            "bestBid": market.get("yes_bid_dollars"),
            "bestAsk": market.get("yes_ask_dollars"),
            "lastTradePrice": market.get("last_price_dollars"),
            "image": "",
        })

    if not markets:
        return None

    category = event.get("category") or ""
    tags = [{"label": category}] if category else []
    event_ticker = event.get("event_ticker") or ""

    return {
        "id": event_ticker,
        "title": event.get("title") or event_ticker,
        "slug": event_ticker.lower(),
        "endDate": _event_end_date(event.get("markets") or [], event),
        "image": "",
        "tags": tags,
        "markets": markets,
        "negRisk": bool(event.get("mutually_exclusive")),
        "enableNegRisk": bool(event.get("mutually_exclusive")),
        "source": "kalshi",
        "url": _event_url(event),
    }


def normalize_events(events: list[dict]) -> list[dict]:
    normalized = []
    for event in events:
        item = normalize_event(event)
        if item:
            normalized.append(item)
    return normalized


def attach_kalshi_fields(data: dict, normalized_events: list[dict]) -> dict:
    by_slug = {event["slug"]: event for event in normalized_events}
    for doc in data.get("docs") or []:
        event = by_slug.get(doc.get("s"))
        doc["p"] = "kalshi"
        if event and event.get("url"):
            doc["u"] = event["url"]
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", help="Read Kalshi events from a local JSONL snapshot")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Maximum pages to fetch from Kalshi API (0 means no cap)",
    )
    parser.add_argument(
        "--status",
        default="open",
        choices=["unopened", "open", "closed", "settled"],
        help="Kalshi event status to fetch",
    )
    args = parser.parse_args()

    print("Building Kalshi search index...")
    if args.local:
        print(f"  Loading from local file: {args.local}")
        events = load_local_events(args.local)
    else:
        print("  Fetching from Kalshi API...")
        events = fetch_all_events(status=args.status, max_pages=args.max_pages)
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        with SNAPSHOT.open("w") as f:
            for event in events:
                f.write(json.dumps(event, separators=(",", ":")) + "\n")
        print(f"  Saved snapshot: {SNAPSHOT}")

    print(f"  Total Kalshi events: {len(events)}")
    normalized = normalize_events(events)
    print(f"  Normalized events: {len(normalized)}")

    data = build_index(normalized, enrichments_path=ENRICHMENT_FILE)
    attach_kalshi_fields(data, normalized)
    print(f"  Indexed: {data['n']} events, {len(data['idf'])} unique terms")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, separators=(",", ":"))
    OUT.write_text(raw)

    size_mb = len(raw) / 1024 / 1024
    print(f"  Written: {OUT} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
