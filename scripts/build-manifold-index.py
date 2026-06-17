"""Build the search index from Manifold's public market API."""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from importlib import import_module
from pathlib import Path
from typing import Any

build_index_mod = import_module("build-index")
build_index = build_index_mod.build_index
tokenize = build_index_mod.tokenize

BASE = "https://api.manifold.markets/v0"
PUBLIC = Path(__file__).parent.parent / "public"
OUT = PUBLIC / "search-data-manifold.json"
SNAPSHOT = Path(__file__).parent.parent / "data" / "manifold_markets_open.jsonl"
DETAIL_SNAPSHOT = Path(__file__).parent.parent / "data" / "manifold_market_details.jsonl"

USER_AGENT = "polymarket-search-indexer/0.1 (andrewburkard@gmail.com)"
API_PAGE_SIZE = 1000
DEFAULT_MAX_PAGES = 5
DETAIL_RETRIES = 4
DETAIL_MIN_INTERVAL = 0.13


def _request_json(path: str, params: dict[str, Any] | None = None) -> Any:
    qs = urllib.parse.urlencode(params or {})
    url = f"{BASE}{path}"
    if qs:
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def fetch_all_markets(
    *,
    page_size: int = API_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
    sort: str = "last-bet-time",
) -> list[dict]:
    markets: list[dict] = []
    seen_ids: set[str] = set()
    before = ""

    for page_num in range(1, max_pages + 1):
        params: dict[str, Any] = {"limit": page_size, "sort": sort}
        if before:
            params["before"] = before

        try:
            page = _request_json("/markets", params)
        except Exception as e:
            print(f"  ERROR before={before or '<first>'}: {e}", file=sys.stderr)
            if not markets:
                raise
            print(f"  Stopping early with {len(markets)} markets", file=sys.stderr)
            break

        if not isinstance(page, list) or not page:
            break

        new_items = []
        for market in page:
            market_id = str(market.get("id") or "")
            if not market_id or market_id in seen_ids:
                continue
            seen_ids.add(market_id)
            new_items.append(market)

        markets.extend(new_items)
        before = str(page[-1].get("id") or "")
        print(f"  fetched page={page_num} got={len(page)} new={len(new_items)} total={len(markets)}")

        if len(page) < page_size or not before or not new_items:
            break
        time.sleep(0.1)

    return markets


def load_local_markets(path: str) -> list[dict]:
    markets = []
    with open(path) as f:
        for line in f:
            if line.strip():
                markets.append(json.loads(line))
    return markets


def load_detail_snapshot(path: Path = DETAIL_SNAPSHOT) -> dict[str, dict]:
    details: dict[str, dict] = {}
    if not path.exists():
        return details
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            market_id = str(item.get("id") or "")
            if market_id:
                details[market_id] = item
    return details


def save_detail_snapshot(details: dict[str, dict], path: Path = DETAIL_SNAPSHOT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for market_id in sorted(details):
            f.write(json.dumps(details[market_id], separators=(",", ":")) + "\n")


def fetch_market_detail_with_retry(market_id: str) -> dict:
    delay = 2.0
    for attempt in range(DETAIL_RETRIES + 1):
        try:
            return _request_json(f"/market/{urllib.parse.quote(market_id, safe='')}")
        except urllib.error.HTTPError as e:
            if e.code != http.client.TOO_MANY_REQUESTS or attempt >= DETAIL_RETRIES:
                raise
            retry_after = e.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"detail retries exhausted for {market_id}")


def market_activity(market: dict) -> float:
    return max(
        _float(market.get("volume")),
        _float(market.get("volume24Hours")),
        _float(market.get("totalLiquidity")),
        _float(market.get("uniqueBettorCount")) * 25,
    )


def should_keep_market(
    market: dict,
    *,
    now_ms: int | None = None,
    min_volume: float = 100,
    min_bettors: int = 5,
) -> bool:
    now_ms = now_ms or int(time.time() * 1000)
    if market.get("isResolved"):
        return False
    close_time = _int(market.get("closeTime"))
    if close_time and close_time <= now_ms:
        return False
    return (
        _float(market.get("volume")) >= min_volume
        or _float(market.get("volume24Hours")) > 0
        or _int(market.get("uniqueBettorCount")) >= min_bettors
    )


def fetch_detail_map(
    markets: list[dict],
    *,
    existing_details: dict[str, dict] | None = None,
    max_details: int = 300,
    min_interval: float = DETAIL_MIN_INTERVAL,
) -> dict[str, dict]:
    details: dict[str, dict] = dict(existing_details or {})
    candidates = [
        market
        for market in markets
        if market.get("outcomeType") == "MULTIPLE_CHOICE"
    ]
    candidates.sort(key=market_activity, reverse=True)
    candidates = candidates[:max_details]
    missing = [
        str(market.get("id"))
        for market in candidates
        if market.get("id") and market.get("id") not in details
    ]

    if not missing:
        print(f"  Detail cache covers selected {len(candidates)} multiple-choice markets")
        return details

    print(f"  Fetching details for {len(missing)} missing multiple-choice markets ({len(details)} cached)")
    last_request = 0.0
    failures = 0
    for i, market_id in enumerate(missing, start=1):
        wait_for = min_interval - (time.monotonic() - last_request)
        if wait_for > 0:
            time.sleep(wait_for)
        last_request = time.monotonic()

        try:
            details[market_id] = fetch_market_detail_with_retry(market_id)
        except Exception as e:
            failures += 1
            if failures <= 5:
                print(f"  detail skipped for {market_id}: {e}", file=sys.stderr)
        if i % 50 == 0 or i == len(missing):
            print(f"  fetched details {i}/{len(missing)} missing ({len(details)} cached)")

    if failures:
        print(f"  Details unavailable for {failures}/{len(missing)} markets", file=sys.stderr)
    return details


def _float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _ms_date(value: Any) -> str:
    ms = _int(value)
    if not ms:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def _probability(value: Any) -> float:
    return round(min(max(_float(value), 0), 1), 4)


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


def manifold_topic_metadata(market: dict, detail: dict | None = None) -> tuple[list[str], list[str]]:
    detail = detail or {}
    text = " ".join([
        str(market.get("question") or ""),
        str(market.get("sportsLeague") or ""),
        " ".join(str(s) for s in detail.get("groupSlugs") or []),
    ]).lower()
    tokens = set(tokenize(text))

    tags: list[str] = []
    aliases: list[str] = []
    league = str(market.get("sportsLeague") or "").strip()
    if league:
        tags.append("Sports")
        tags.append(league)
        aliases.append(league)

    keyword_map = [
        (["bitcoin", "btc", "crypto", "ethereum", "solana", "xrp"], ["Crypto"], ["bitcoin", "btc", "crypto"]),
        (["nba", "basketball"], ["Sports", "NBA", "Basketball"], ["nba", "basketball"]),
        (["nfl", "football"], ["Sports", "NFL", "Football"], ["nfl", "football"]),
        (["world", "cup", "fifa", "soccer"], ["Sports", "Soccer", "World Cup"], ["world cup", "fifa", "soccer"]),
        (["election", "president", "presidential", "trump", "biden", "democrat", "republican", "senate", "house"], ["Politics", "Elections"], ["election", "president"]),
        (["fed", "fomc", "inflation", "cpi", "gdp", "recession", "rate", "rates"], ["Economics"], ["fed", "fomc", "inflation", "cpi"]),
        (["ai", "artificial", "intelligence", "agi", "openai"], ["Technology", "AI"], ["ai", "artificial intelligence", "agi"]),
    ]
    for needles, needle_tags, needle_aliases in keyword_map:
        if any(needle in tokens for needle in needles):
            tags.extend(needle_tags)
            aliases.extend(needle_aliases)
    if "nba" in tokens and any(word in tokens for word in ("champion", "championship", "championships", "finals")):
        aliases.extend(["nba champion", "nba championship", "nba finals"])

    return _unique(tags), _unique(aliases)


def _answer_probability(answer: dict) -> float:
    for key in ("probability", "p"):
        if answer.get(key) is not None:
            return _probability(answer.get(key))
    return 0.0


def normalize_market(
    market: dict,
    detail: dict | None = None,
    *,
    now_ms: int | None = None,
    min_volume: float = 100,
    min_bettors: int = 5,
) -> dict | None:
    if not should_keep_market(
        market,
        now_ms=now_ms,
        min_volume=min_volume,
        min_bettors=min_bettors,
    ):
        return None

    detail = detail or {}
    outcome_type = market.get("outcomeType") or ""
    title = market.get("question") or market.get("id") or ""
    slug = market.get("slug") or market.get("id") or ""
    token = market.get("token") or detail.get("token") or "MANA"
    markets = []

    if outcome_type == "MULTIPLE_CHOICE" and detail.get("answers"):
        for answer in detail.get("answers") or []:
            label = answer.get("text") or answer.get("name") or answer.get("id") or ""
            probability = _answer_probability(answer)
            markets.append({
                "id": answer.get("id") or f"{market.get('id')}:{label}",
                "question": title,
                "slug": str(answer.get("id") or label).lower(),
                "closed": False,
                "volume": str(_float(answer.get("volume"))),
                "volume24hr": "0",
                "endDate": _ms_date(market.get("closeTime")),
                "groupItemTitle": label,
                "outcomePrices": json.dumps([probability]),
            })

    if not markets:
        probability = _probability(market.get("probability", market.get("p")))
        markets.append({
            "id": market.get("id") or slug,
            "question": title,
            "slug": slug,
            "closed": False,
            "volume": str(_float(market.get("volume"))),
            "volume24hr": str(_float(market.get("volume24Hours"))),
            "endDate": _ms_date(market.get("closeTime")),
            "groupItemTitle": "",
            "outcomePrices": json.dumps([probability, round(1 - probability, 4)]),
        })

    tags, aliases = manifold_topic_metadata(market, detail)
    context_aliases = _unique([
        market.get("creatorName") or "",
        market.get("creatorUsername") or "",
        market.get("sportsLeague") or "",
        " ".join(str(s) for s in detail.get("groupSlugs") or []),
        detail.get("textDescription") or "",
        *aliases,
    ])

    return {
        "id": market.get("id") or slug,
        "title": title,
        "slug": slug,
        "endDate": _ms_date(market.get("closeTime")),
        "image": "",
        "tags": [{"label": tag} for tag in tags],
        "markets": markets,
        "negRisk": outcome_type == "MULTIPLE_CHOICE",
        "enableNegRisk": outcome_type == "MULTIPLE_CHOICE",
        "eventMetadata": {
            "context_description": " ".join(context_aliases),
        },
        "source": "manifold",
        "url": market.get("url") or f"https://manifold.markets/{slug}",
        "token": token,
        "volume": _float(market.get("volume")),
        "volume24hr": _float(market.get("volume24Hours")),
    }


def normalize_markets(
    markets: list[dict],
    details_by_id: dict[str, dict] | None = None,
    *,
    now_ms: int | None = None,
    min_volume: float = 100,
    min_bettors: int = 5,
) -> list[dict]:
    details_by_id = details_by_id or {}
    normalized = []
    for market in markets:
        item = normalize_market(
            market,
            details_by_id.get(str(market.get("id") or "")),
            now_ms=now_ms,
            min_volume=min_volume,
            min_bettors=min_bettors,
        )
        if item:
            normalized.append(item)
    return normalized


def attach_manifold_fields(data: dict, normalized_markets: list[dict]) -> dict:
    by_slug = {market["slug"]: market for market in normalized_markets}
    for doc in data.get("docs") or []:
        market = by_slug.get(doc.get("s"))
        doc["p"] = "manifold"
        if not market:
            continue
        if market.get("url"):
            doc["u"] = market["url"]
        if market.get("token"):
            doc["tk"] = market["token"]
        doc["v"] = round(float(market.get("volume24hr") or 0))
        doc["vt"] = round(float(market.get("volume") or 0))
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", help="Read Manifold markets from a local JSONL snapshot")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--page-size", type=int, default=API_PAGE_SIZE)
    parser.add_argument("--max-details", type=int, default=300)
    parser.add_argument("--min-volume", type=float, default=100)
    parser.add_argument("--min-bettors", type=int, default=5)
    parser.add_argument("--detail-cache-only", action="store_true")
    parser.add_argument("--skip-details", action="store_true")
    args = parser.parse_args()

    print("Building Manifold search index...")
    if args.local:
        print(f"  Loading from local file: {args.local}")
        markets = load_local_markets(args.local)
    else:
        print("  Fetching from Manifold API...")
        markets = fetch_all_markets(page_size=args.page_size, max_pages=args.max_pages)
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        with SNAPSHOT.open("w") as f:
            for market in markets:
                f.write(json.dumps(market, separators=(",", ":")) + "\n")
        print(f"  Saved snapshot: {SNAPSHOT}")

    print(f"  Total Manifold markets: {len(markets)}")
    active_markets = [
        market
        for market in markets
        if should_keep_market(
            market,
            min_volume=args.min_volume,
            min_bettors=args.min_bettors,
        )
    ]
    print(f"  Active/activity-filtered markets: {len(active_markets)}")

    details_by_id: dict[str, dict] = {}
    if args.skip_details:
        print("  Skipping Manifold multiple-choice details")
    elif args.detail_cache_only:
        if DETAIL_SNAPSHOT.exists():
            details_by_id = load_detail_snapshot()
            print(f"  Cached details: {len(details_by_id)}")
        else:
            print(f"  Detail cache not found: {DETAIL_SNAPSHOT}", file=sys.stderr)
    else:
        details_by_id = load_detail_snapshot()
        if details_by_id:
            print(f"  Cached details: {len(details_by_id)}")
        details_by_id = fetch_detail_map(
            active_markets,
            existing_details=details_by_id,
            max_details=args.max_details,
        )
        save_detail_snapshot(details_by_id)
        print(f"  Saved details snapshot: {DETAIL_SNAPSHOT}")

    normalized = normalize_markets(
        active_markets,
        details_by_id=details_by_id,
        min_volume=args.min_volume,
        min_bettors=args.min_bettors,
    )
    print(f"  Normalized markets: {len(normalized)}")

    data = build_index(normalized)
    attach_manifold_fields(data, normalized)
    print(f"  Indexed: {data['n']} markets, {len(data['idf'])} unique terms")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, separators=(",", ":"))
    OUT.write_text(raw)

    size_mb = len(raw) / 1024 / 1024
    print(f"  Written: {OUT} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
