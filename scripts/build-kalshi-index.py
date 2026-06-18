"""Build the search index from Kalshi's public market data API."""

from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import sys
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from importlib import import_module
from pathlib import Path
from typing import Any

build_index_mod = import_module("build-index")
build_index = build_index_mod.build_index

BASE = "https://external-api.kalshi.com/trade-api/v2"
PUBLIC = Path(__file__).parent.parent / "public"
OUT = PUBLIC / "search-data-kalshi.json"
ARCHIVED_OUT = PUBLIC / "search-data-kalshi-archived.json"
SNAPSHOT = Path(__file__).parent.parent / "data" / "kalshi_events_open.jsonl"
ARCHIVED_SNAPSHOT = Path(__file__).parent.parent / "data" / "kalshi_events_archived.jsonl"
METADATA_SNAPSHOT = Path(__file__).parent.parent / "data" / "kalshi_event_metadata_open.jsonl"
ENRICHMENT_FILE = Path(__file__).parent.parent / "data" / "kalshi_enrichments.jsonl"

USER_AGENT = "polymarket-search-indexer/0.1 (andrewburkard@gmail.com)"
API_PAGE_SIZE = 200
METADATA_WORKERS = 1
METADATA_RETRIES = 6
METADATA_MIN_INTERVAL = 0.5

KALSHI_TOPIC_HINTS = [
    ("KXBTC", ["Crypto", "Bitcoin"], ["btc", "bitcoin", "btcusd", "xbt", "satoshi"]),
    ("KXETH", ["Crypto", "Ethereum"], ["eth", "ethereum", "ether"]),
    ("KXSOL", ["Crypto", "Solana"], ["sol", "solana"]),
    ("KXXRP", ["Crypto", "XRP"], ["xrp", "ripple"]),
    ("KXMLB", ["Sports", "MLB", "Baseball"], ["mlb", "baseball"]),
    ("KXNBA", ["Sports", "NBA", "Basketball"], ["nba", "basketball"]),
    ("KXNFL", ["Sports", "NFL", "Football"], ["nfl", "football"]),
    ("KXNHL", ["Sports", "NHL", "Hockey"], ["nhl", "hockey"]),
    ("KXUFC", ["Sports", "UFC", "MMA"], ["ufc", "mma"]),
    ("KXPGATOUR", ["Sports", "Golf", "PGA"], ["pga", "golf"]),
    ("KXF1", ["Sports", "Formula 1"], ["f1", "formula one", "formula 1"]),
    ("KXWC", ["Sports", "Soccer", "World Cup", "FIFA"], ["world cup", "fifa", "soccer", "football"]),
    ("KXNCAAF", ["Sports", "College Football"], ["college football", "ncaa football", "cfb"]),
    ("KXNCAABASEBALL", ["Sports", "College Baseball"], ["college baseball", "college world series", "cws", "omaha"]),
    ("KXMARMAD", ["Sports", "College Basketball"], ["march madness", "college basketball", "ncaa basketball"]),
    ("KXHEISMAN", ["Sports", "College Football"], ["heisman", "college football", "cfb"]),
    ("KXFED", ["Economics", "Fed"], ["fed", "fomc", "interest rates", "rate decision"]),
    ("KXRATE", ["Economics", "Fed"], ["fed", "fomc", "rate cuts", "interest rates"]),
    ("KXPRES", ["Politics", "Elections"], ["president", "presidential election"]),
    ("CONTROLH", ["Politics", "Elections"], ["house control", "midterms", "congress"]),
    ("CONTROLS", ["Politics", "Elections"], ["senate control", "midterms", "congress"]),
]


def _request_json(path: str, params: dict[str, Any] | None = None) -> dict:
    qs = urllib.parse.urlencode(params or {})
    url = f"{BASE}{path}"
    if qs:
        url = f"{url}?{qs}"
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


def fetch_archived_events(*, max_pages: int = 0) -> list[dict]:
    events_by_ticker: dict[str, dict] = {}
    for status in ("closed", "settled"):
        print(f"  Fetching status={status}...")
        for event in fetch_all_events(status=status, max_pages=max_pages):
            ticker = event.get("event_ticker")
            if ticker:
                events_by_ticker[ticker] = event
    return list(events_by_ticker.values())


def load_local_events(path: str) -> list[dict]:
    events = []
    with open(path) as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
    return events


def fetch_event_metadata(event_ticker: str) -> dict:
    ticker = urllib.parse.quote(event_ticker, safe="")
    return _request_json(f"/events/{ticker}/metadata")


def fetch_event_metadata_with_retry(
    event_ticker: str,
    *,
    rate_limit: "MetadataRateLimit | None" = None,
) -> dict:
    delay = 10.0
    for attempt in range(METADATA_RETRIES + 1):
        try:
            if rate_limit:
                rate_limit.wait()
            return fetch_event_metadata(event_ticker)
        except urllib.error.HTTPError as e:
            if e.code != http.client.TOO_MANY_REQUESTS or attempt >= METADATA_RETRIES:
                raise
            retry_after = e.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"metadata retries exhausted for {event_ticker}")


class MetadataRateLimit:
    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(min_interval, 0)
        self.lock = threading.Lock()
        self.last_request = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self.lock:
            now = time.monotonic()
            wait_for = self.min_interval - (now - self.last_request)
            if wait_for > 0:
                time.sleep(wait_for)
            self.last_request = time.monotonic()


def fetch_event_metadata_map(
    events: list[dict],
    *,
    existing_metadata: dict[str, dict] | None = None,
    max_workers: int = METADATA_WORKERS,
    min_interval: float = METADATA_MIN_INTERVAL,
) -> dict[str, dict]:
    all_tickers = sorted({
        event.get("event_ticker") or ""
        for event in events
        if event.get("event_ticker")
    })
    metadata: dict[str, dict] = dict(existing_metadata or {})
    tickers = [ticker for ticker in all_tickers if ticker not in metadata]
    failures = 0
    if not tickers:
        print(f"  Metadata cache covers all {len(all_tickers)} events")
        return metadata

    print(f"  Fetching metadata for {len(tickers)} missing events ({len(metadata)} cached)")
    rate_limit = MetadataRateLimit(min_interval)

    def fetch_one(ticker: str) -> tuple[str, dict | None, str | None]:
        try:
            return ticker, fetch_event_metadata_with_retry(ticker, rate_limit=rate_limit), None
        except Exception as e:
            return ticker, None, str(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_one, ticker) for ticker in tickers]
        for i, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            ticker, item, error = future.result()
            if item:
                metadata[ticker] = item
            else:
                failures += 1
                if failures <= 5:
                    print(f"  metadata skipped for {ticker}: {error}", file=sys.stderr)
            if i % 200 == 0 or i == len(tickers):
                print(f"  fetched metadata {i}/{len(tickers)} missing ({len(metadata)}/{len(all_tickers)} cached)")

    if failures:
        print(f"  Metadata unavailable for {failures}/{len(tickers)} events", file=sys.stderr)
    return metadata


def load_metadata_snapshot(path: Path = METADATA_SNAPSHOT) -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    if not path.exists():
        return metadata
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            ticker = entry.get("event_ticker") or ""
            item = entry.get("metadata") or {}
            if ticker and item:
                metadata[ticker] = item
    return metadata


def save_metadata_snapshot(metadata: dict[str, dict], path: Path = METADATA_SNAPSHOT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for ticker in sorted(metadata):
            entry = {"event_ticker": ticker, "metadata": metadata[ticker]}
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")


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


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def kalshi_topic_metadata(event: dict) -> tuple[list[str], list[str]]:
    ticker_text = " ".join(
        str(event.get(key) or "").upper()
        for key in ("event_ticker", "series_ticker")
    )
    title = str(event.get("title") or "").lower()
    tags: list[str] = []
    aliases: list[str] = []
    for prefix, prefix_tags, prefix_aliases in KALSHI_TOPIC_HINTS:
        if prefix in ticker_text:
            tags.extend(prefix_tags)
            aliases.extend(prefix_aliases)
    if "KXNBA" in ticker_text and "finals series winner" in title:
        aliases.extend([
            "nba champion",
            "nba championship",
            "pro basketball champion",
            "pro basketball championship",
        ])
    return _unique(tags), _unique(aliases)


def _image_url(value: Any) -> str:
    if not value:
        return ""
    url = str(value)
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://kalshi.com{url}"
    return url


def normalize_event(
    event: dict,
    metadata: dict | None = None,
    *,
    include_closed_markets: bool = False,
) -> dict | None:
    metadata = metadata or {}
    market_images = {
        detail.get("market_ticker"): _image_url(detail.get("image_url"))
        for detail in metadata.get("market_details") or []
        if detail.get("market_ticker") and detail.get("image_url")
    }

    markets = []
    for market in event.get("markets") or []:
        market_ticker = market.get("ticker") or ""
        status = (market.get("status") or "").lower()
        closed = status in {"closed", "settled", "expired", "finalized"}
        if closed and not include_closed_markets:
            continue
        volume = _float(market.get("volume_fp"))
        volume24 = _float(market.get("volume_24h_fp"))
        probability = _yes_probability(market)

        markets.append({
            "id": market_ticker,
            "liveId": market_ticker,
            "question": market.get("title") or event.get("title") or "",
            "slug": market_ticker.lower(),
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
            "image": market_images.get(market_ticker, ""),
        })

    if not markets:
        return None

    category = event.get("category") or ""
    topic_tags, topic_aliases = kalshi_topic_metadata(event)
    tag_labels = _unique(([category] if category else []) + topic_tags)
    tags = [{"label": tag} for tag in tag_labels]
    event_ticker = event.get("event_ticker") or ""
    context_aliases = _unique([
        event.get("event_ticker") or "",
        event.get("series_ticker") or "",
        event.get("sub_title") or "",
        *topic_aliases,
    ])

    return {
        "id": event_ticker,
        "title": event.get("title") or event_ticker,
        "slug": event_ticker.lower(),
        "endDate": _event_end_date(event.get("markets") or [], event),
        "image": _image_url(metadata.get("image_url") or metadata.get("featured_image_url")),
        "tags": tags,
        "markets": markets,
        "negRisk": bool(event.get("mutually_exclusive")),
        "enableNegRisk": bool(event.get("mutually_exclusive")),
        "eventMetadata": {
            "context_description": " ".join(context_aliases),
        },
        "source": "kalshi",
        "url": _event_url(event),
    }


def normalize_events(
    events: list[dict],
    metadata_by_event: dict[str, dict] | None = None,
    *,
    include_closed_markets: bool = False,
) -> list[dict]:
    metadata_by_event = metadata_by_event or {}
    normalized = []
    for event in events:
        item = normalize_event(
            event,
            metadata_by_event.get(event.get("event_ticker") or ""),
            include_closed_markets=include_closed_markets,
        )
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
    parser.add_argument(
        "--archived",
        action="store_true",
        help="Build the archived/closed Kalshi event index instead of the open index",
    )
    parser.add_argument(
        "--skip-metadata",
        action="store_true",
        help="Skip Kalshi event metadata/image fetching",
    )
    parser.add_argument(
        "--metadata-workers",
        type=int,
        default=METADATA_WORKERS,
        help="Concurrent workers for Kalshi metadata/image fetching",
    )
    parser.add_argument(
        "--metadata-min-interval",
        type=float,
        default=METADATA_MIN_INTERVAL,
        help="Minimum seconds between Kalshi metadata requests across all workers",
    )
    parser.add_argument(
        "--refresh-metadata",
        action="store_true",
        help="Refetch metadata for all events instead of using the local metadata cache",
    )
    parser.add_argument(
        "--metadata-cache-only",
        action="store_true",
        help="Use the local metadata cache but do not fetch missing metadata",
    )
    args = parser.parse_args()

    print("Building Kalshi search index...")
    if args.local:
        print(f"  Loading from local file: {args.local}")
        events = load_local_events(args.local)
    else:
        print("  Fetching from Kalshi API...")
        events = (
            fetch_archived_events(max_pages=args.max_pages)
            if args.archived
            else fetch_all_events(status=args.status, max_pages=args.max_pages)
        )
        snapshot = ARCHIVED_SNAPSHOT if args.archived else SNAPSHOT
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        with snapshot.open("w") as f:
            for event in events:
                f.write(json.dumps(event, separators=(",", ":")) + "\n")
        print(f"  Saved snapshot: {snapshot}")

    print(f"  Total Kalshi events: {len(events)}")

    metadata_by_event: dict[str, dict] = {}
    if args.skip_metadata:
        print("  Skipping Kalshi metadata")
    elif args.metadata_cache_only:
        if METADATA_SNAPSHOT.exists():
            print(f"  Loading metadata cache: {METADATA_SNAPSHOT}")
            metadata_by_event = load_metadata_snapshot()
            print(f"  Cached metadata events: {len(metadata_by_event)}")
        else:
            print(f"  Metadata cache not found: {METADATA_SNAPSHOT}", file=sys.stderr)
    else:
        if METADATA_SNAPSHOT.exists() and not args.refresh_metadata:
            print(f"  Loading metadata cache: {METADATA_SNAPSHOT}")
            metadata_by_event = load_metadata_snapshot()
            print(f"  Cached metadata events: {len(metadata_by_event)}")
        print("  Fetching Kalshi metadata...")
        metadata_by_event = fetch_event_metadata_map(
            events,
            existing_metadata=metadata_by_event,
            max_workers=args.metadata_workers,
            min_interval=args.metadata_min_interval,
        )
        save_metadata_snapshot(metadata_by_event)
        print(f"  Saved metadata snapshot: {METADATA_SNAPSHOT}")

    normalized = normalize_events(
        events,
        metadata_by_event=metadata_by_event,
        include_closed_markets=args.archived,
    )
    print(f"  Normalized events: {len(normalized)}")

    data = build_index(
        normalized,
        include_closed_markets=args.archived,
        archived=args.archived,
        enrichments_path=ENRICHMENT_FILE,
    )
    attach_kalshi_fields(data, normalized)
    print(f"  Indexed: {data['n']} events, {len(data['idf'])} unique terms")

    out = ARCHIVED_OUT if args.archived else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, separators=(",", ":"))
    out.write_text(raw)

    size_mb = len(raw) / 1024 / 1024
    print(f"  Written: {out} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
