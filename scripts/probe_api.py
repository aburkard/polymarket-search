"""Quick probes of the Polymarket Gamma API.

Goal: figure out pagination behavior, filters, response shapes, ordering,
and whether updatedAt-based incremental sync is feasible. Print findings;
do not save much state.
"""

from __future__ import annotations

import json
import time
from typing import Any

import urllib.request
import urllib.parse

BASE = "https://gamma-api.polymarket.com"


def get(path: str, **params: Any) -> Any:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE}{path}?{qs}" if qs else f"{BASE}{path}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "polymarket-search-research/0.1 (andrewburkard@gmail.com)"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        elapsed = time.time() - t0
        return json.loads(body), elapsed, len(body), resp.status


def banner(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def probe_events_pagination() -> None:
    banner("PROBE: /events pagination + active filter")
    # Try a small fetch first
    data, elapsed, size, status = get(
        "/events", active="true", closed="false", limit=10
    )
    print(f"  status={status} elapsed={elapsed:.2f}s bytes={size:,} type={type(data).__name__}")
    if isinstance(data, list):
        print(f"  -> array, len={len(data)}")
        if data:
            sample = data[0]
            print(f"  first event keys: {sorted(sample.keys())[:30]}")
            print(f"  first event title: {sample.get('title')}")
            print(f"  first event has 'markets'? {'markets' in sample} "
                  f"(count={len(sample.get('markets', []))})")
    elif isinstance(data, dict):
        print(f"  -> object, keys={list(data.keys())[:20]}")

    # Try a larger limit to see if it caps
    for lim in (100, 500, 1000):
        try:
            data, elapsed, size, _ = get(
                "/events", active="true", closed="false", limit=lim
            )
            n = len(data) if isinstance(data, list) else "?"
            print(f"  limit={lim} -> got {n} in {elapsed:.2f}s ({size:,} bytes)")
        except Exception as e:
            print(f"  limit={lim} -> ERROR: {e}")


def probe_offset_pagination() -> None:
    banner("PROBE: offset-based pagination of /events")
    seen_ids: set[str] = set()
    offset = 0
    page = 0
    total_size = 0
    t0 = time.time()
    while page < 5:  # cap at 5 pages for the probe
        try:
            data, elapsed, size, _ = get(
                "/events",
                active="true",
                closed="false",
                limit=500,
                offset=offset,
            )
        except Exception as e:
            print(f"  page={page} offset={offset} ERROR: {e}")
            break
        if not isinstance(data, list):
            print(f"  unexpected type {type(data).__name__}")
            break
        new_ids = [str(e.get("id")) for e in data]
        dup = sum(1 for i in new_ids if i in seen_ids)
        seen_ids.update(new_ids)
        total_size += size
        print(
            f"  page={page} offset={offset} got={len(data)} dup={dup} "
            f"elapsed={elapsed:.2f}s size={size:,} cumulative_unique={len(seen_ids)}"
        )
        if len(data) < 500:
            print(f"  reached end of stream after {len(seen_ids)} unique events")
            break
        offset += 500
        page += 1
    print(f"  total wall time: {time.time() - t0:.2f}s, total bytes: {total_size:,}")


def probe_ordering_by_updated_at() -> None:
    banner("PROBE: /events ordering by updatedAt (for incremental sync)")
    for variant in [
        ("order=updatedAt&ascending=false", "order+ascending"),
        ("order=updated_at&ascending=false", "order_underscore"),
        ("ordering=-updated_at", "ordering=-x"),
    ]:
        url = f"{BASE}/events?active=true&closed=false&limit=5&{variant[0]}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "polymarket-search-research/0.1"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            if isinstance(data, list) and data:
                ts = [e.get("updatedAt") for e in data]
                print(f"  variant={variant[1]:20s} top updatedAt values: {ts}")
            else:
                print(f"  variant={variant[1]:20s} no array response")
        except Exception as e:
            print(f"  variant={variant[1]:20s} ERROR: {e}")


def probe_markets_endpoint() -> None:
    banner("PROBE: /markets endpoint")
    data, elapsed, size, _ = get("/markets", active="true", closed="false", limit=5)
    if isinstance(data, list):
        print(f"  /markets returned array, len={len(data)}, elapsed={elapsed:.2f}s")
        if data:
            keys = sorted(data[0].keys())
            print(f"  market keys ({len(keys)}): {keys}")
    else:
        print(f"  /markets unexpected: type={type(data).__name__}")


def probe_tags() -> None:
    banner("PROBE: /tags taxonomy")
    try:
        data, elapsed, size, _ = get("/tags")
        if isinstance(data, list):
            print(f"  got {len(data)} tags in {elapsed:.2f}s")
            for t in data[:20]:
                print(f"    - {t}")
        else:
            print(f"  unexpected: {type(data).__name__}, keys={list(data)[:10] if isinstance(data, dict) else '?'}")
    except Exception as e:
        print(f"  ERROR: {e}")


def probe_public_search() -> None:
    banner("PROBE: /public-search shape")
    queries = ["trump", "bitcoin 100k", "fed rate cut", "drake album"]
    for q in queries:
        try:
            data, elapsed, size, _ = get("/public-search", q=q, limit=5)
            keys = list(data.keys()) if isinstance(data, dict) else "?"
            top_count = (
                len(data.get("events", [])) if isinstance(data, dict) else 0
            )
            print(
                f'  q="{q}" elapsed={elapsed:.2f}s keys={keys} '
                f'events_returned={top_count}'
            )
            if isinstance(data, dict):
                for ev in (data.get("events") or [])[:3]:
                    closed = ev.get("closed")
                    end = ev.get("endDate")
                    title = ev.get("title")
                    vol = ev.get("volume")
                    print(f'    - "{title}" closed={closed} end={end} vol={vol}')
        except Exception as e:
            print(f'  q="{q}" ERROR: {e}')


def probe_rate_limit() -> None:
    banner("PROBE: rate limit (light burst)")
    t0 = time.time()
    n_ok = 0
    n_err = 0
    for i in range(20):
        try:
            data, elapsed, size, status = get("/events", active="true", limit=1)
            n_ok += 1
        except Exception as e:
            n_err += 1
            print(f"  request {i}: ERROR {e}")
            break
    dt = time.time() - t0
    print(f"  20 sequential requests: ok={n_ok} err={n_err} total={dt:.2f}s "
          f"(={n_ok/dt:.1f} req/s)")


if __name__ == "__main__":
    probe_events_pagination()
    probe_offset_pagination()
    probe_ordering_by_updated_at()
    probe_markets_endpoint()
    probe_tags()
    probe_public_search()
    probe_rate_limit()
