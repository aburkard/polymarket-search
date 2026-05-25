"""Pull a full snapshot of active Polymarket events into ./data/.

Saves:
  data/events_active.jsonl   - one event per line
  data/snapshot_meta.json    - fetch stats

Also pulls all closed events with non-trivial volume into a separate file
so we can sanity-check what the search competition looks like for a query
like "bitcoin 100k" where many strong-volume historical markets exist.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://gamma-api.polymarket.com"
DATA = Path(__file__).parent.parent / "data"
DATA.mkdir(exist_ok=True)


def fetch_page(active: str, closed: str, offset: int, limit: int = 500) -> list[dict]:
    qs = urllib.parse.urlencode(
        {"active": active, "closed": closed, "limit": limit, "offset": offset}
    )
    url = f"{BASE}/events?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "polymarket-search-research/0.1 (andrewburkard@gmail.com)"
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def pull_all(active: str, closed: str, label: str, max_pages: int = 200) -> tuple[int, int, float]:
    out_path = DATA / f"events_{label}.jsonl"
    seen_ids: set[str] = set()
    pages = 0
    t0 = time.time()
    total_bytes = 0
    with out_path.open("w") as f:
        offset = 0
        while pages < max_pages:
            page_t0 = time.time()
            page = fetch_page(active, closed, offset)
            page_dt = time.time() - page_t0
            if not page:
                print(f"  [{label}] empty page at offset={offset}, stopping")
                break
            written = 0
            for ev in page:
                eid = str(ev.get("id"))
                if eid in seen_ids:
                    continue
                seen_ids.add(eid)
                line = json.dumps(ev, separators=(",", ":"))
                f.write(line)
                f.write("\n")
                total_bytes += len(line) + 1
                written += 1
            print(
                f"  [{label}] page={pages} offset={offset} got={len(page)} "
                f"new={written} cum={len(seen_ids)} {page_dt:.2f}s"
            )
            if len(page) < 500:
                break
            offset += 500
            pages += 1
    dt = time.time() - t0
    print(f"  [{label}] done: {len(seen_ids)} events, {total_bytes:,} bytes, {dt:.1f}s")
    return len(seen_ids), total_bytes, dt


def main() -> None:
    print("=" * 78)
    print("Pulling all ACTIVE+OPEN events")
    print("=" * 78)
    active_n, active_b, active_t = pull_all("true", "false", "active")

    print()
    print("=" * 78)
    print("Pulling first 5 pages of CLOSED events (sample, not full archive)")
    print("=" * 78)
    # Closed archive is huge; sample for query baseline analysis only.
    out_path = DATA / "events_closed_sample.jsonl"
    seen: set[str] = set()
    total_bytes = 0
    t0 = time.time()
    with out_path.open("w") as f:
        for offset in range(0, 5 * 500, 500):
            page = fetch_page("false", "true", offset)
            if not page:
                break
            for ev in page:
                eid = str(ev.get("id"))
                if eid in seen:
                    continue
                seen.add(eid)
                line = json.dumps(ev, separators=(",", ":"))
                f.write(line)
                f.write("\n")
                total_bytes += len(line) + 1
            print(f"  closed page offset={offset} got={len(page)} cum={len(seen)}")
            if len(page) < 500:
                break
    closed_t = time.time() - t0
    print(f"  closed sample: {len(seen)} events, {total_bytes:,} bytes, {closed_t:.1f}s")

    meta = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "active_open": {
            "events": active_n,
            "bytes": active_b,
            "seconds": round(active_t, 2),
        },
        "closed_sample": {
            "events": len(seen),
            "bytes": total_bytes,
            "seconds": round(closed_t, 2),
        },
    }
    (DATA / "snapshot_meta.json").write_text(json.dumps(meta, indent=2))
    print()
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
