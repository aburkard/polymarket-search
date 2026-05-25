"""Analyze the active-events snapshot.

Answers:
  - How many markets total (events flatten to markets)?
  - Field coverage: which fields are populated, on what fraction of rows?
  - Distribution of volume / liquidity / endDate / commentCount
  - Tag taxonomy size
  - Description length distribution (matters for search index)
  - Presence and quality of eventMetadata.context_description
  - How many active-open events have closed=true on all child markets
    (i.e. zombies — the search index should probably skip these)
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
SRC = DATA / "events_active.jsonl"


def load_events():
    with SRC.open() as f:
        for line in f:
            yield json.loads(line)


def quantiles(values, qs=(0.5, 0.9, 0.95, 0.99)):
    if not values:
        return {q: None for q in qs}
    s = sorted(values)
    n = len(s)
    return {q: s[min(int(q * n), n - 1)] for q in qs}


def main():
    events = list(load_events())
    n_events = len(events)
    print(f"Total active+open events: {n_events:,}")

    # --- field coverage at event level ---
    event_field_counts: Counter[str] = Counter()
    for ev in events:
        for k in ev:
            event_field_counts[k] += 1
    print("\nEvent field coverage (top 40):")
    for k, c in event_field_counts.most_common(40):
        pct = 100 * c / n_events
        print(f"  {pct:5.1f}%  {k}")

    # --- markets ---
    all_markets = []
    markets_per_event = []
    for ev in events:
        ms = ev.get("markets") or []
        markets_per_event.append(len(ms))
        all_markets.extend(ms)
    n_markets = len(all_markets)
    print(f"\nTotal markets across all events: {n_markets:,}")
    print(f"  markets/event: median={statistics.median(markets_per_event):.1f} "
          f"mean={statistics.mean(markets_per_event):.2f} "
          f"max={max(markets_per_event)}")

    # --- closed-but-active zombies ---
    zombie_events = 0
    fully_open_events = 0
    partially_open = 0
    closed_market_count = 0
    for ev in events:
        ms = ev.get("markets") or []
        if not ms:
            continue
        closed = [m for m in ms if m.get("closed")]
        if len(closed) == len(ms):
            zombie_events += 1
        elif not closed:
            fully_open_events += 1
        else:
            partially_open += 1
        closed_market_count += len(closed)
    print(f"\nEvents where ALL child markets closed (zombies): {zombie_events:,}")
    print(f"Events where ALL markets open: {fully_open_events:,}")
    print(f"Events with some open / some closed: {partially_open:,}")
    print(f"Closed markets (despite parent active): {closed_market_count:,} / {n_markets:,}")

    # --- volume distribution ---
    vols24 = [float(m.get("volume24hr") or 0) for m in all_markets]
    vol_total = [float(m.get("volume") or 0) for m in all_markets]
    liq = [float(m.get("liquidity") or 0) for m in all_markets]
    print("\n24h volume per market:")
    print(f"  mean={statistics.mean(vols24):,.0f} median={statistics.median(vols24):,.0f}")
    qs = quantiles(vols24, (0.5, 0.9, 0.95, 0.99, 0.999))
    print(f"  quantiles: {qs}")
    print(f"  zero-volume markets (vol24=0): {sum(1 for v in vols24 if v == 0):,} "
          f"({100*sum(1 for v in vols24 if v==0)/len(vols24):.1f}%)")

    print("\nAll-time volume per market:")
    qs = quantiles(vol_total, (0.5, 0.9, 0.95, 0.99))
    print(f"  quantiles: {qs}")

    print("\nLiquidity per market:")
    qs = quantiles(liq, (0.5, 0.9, 0.95, 0.99))
    print(f"  quantiles: {qs}")

    # --- description length ---
    desc_lens = [len(m.get("description") or "") for m in all_markets]
    print("\nMarket description length (chars):")
    print(f"  mean={statistics.mean(desc_lens):.0f} median={statistics.median(desc_lens):.0f}")
    print(f"  empty: {sum(1 for d in desc_lens if d==0):,} "
          f"({100*sum(1 for d in desc_lens if d==0)/len(desc_lens):.1f}%)")
    print(f"  quantiles: {quantiles(desc_lens, (0.5, 0.9, 0.99))}")

    qlens = [len(m.get("question") or "") for m in all_markets]
    print(f"\nMarket question length (chars): "
          f"mean={statistics.mean(qlens):.0f} median={statistics.median(qlens):.0f} "
          f"max={max(qlens)}")

    # --- event-level context_description (LLM summary?) ---
    ctx_present = 0
    ctx_lens = []
    ctx_sample = None
    for ev in events:
        meta = ev.get("eventMetadata") or {}
        ctx = meta.get("context_description")
        if ctx:
            ctx_present += 1
            ctx_lens.append(len(ctx))
            if ctx_sample is None:
                ctx_sample = (ev.get("title"), ctx[:300])
    print(f"\nEvents with eventMetadata.context_description: "
          f"{ctx_present:,} / {n_events:,} ({100*ctx_present/n_events:.1f}%)")
    if ctx_lens:
        print(f"  context_description length: mean={statistics.mean(ctx_lens):.0f} "
              f"median={statistics.median(ctx_lens):.0f}")
    if ctx_sample:
        print(f"  sample for '{ctx_sample[0]}':")
        print(f"    {ctx_sample[1]!r}")

    # --- tag coverage ---
    # Tags may be on event or market level — let's check both
    event_with_tags = sum(1 for ev in events if ev.get("tags"))
    print(f"\nEvents with .tags field set: {event_with_tags:,}")
    sample_tags = []
    tag_label_counter: Counter[str] = Counter()
    for ev in events:
        for t in (ev.get("tags") or []):
            label = t.get("label") if isinstance(t, dict) else str(t)
            if label:
                tag_label_counter[label] += 1
    print(f"Unique tag labels seen on events: {len(tag_label_counter):,}")
    print(f"Top 30 tags:")
    for label, c in tag_label_counter.most_common(30):
        print(f"  {c:6d}  {label}")

    # --- end-date distribution ---
    now = datetime.now(timezone.utc)
    days_to_end = []
    none_end = 0
    far_future = 0
    expired_open = 0
    for m in all_markets:
        ed = m.get("endDate") or m.get("endDateIso")
        if not ed:
            none_end += 1
            continue
        try:
            d = datetime.fromisoformat(ed.replace("Z", "+00:00"))
            delta_days = (d - now).total_seconds() / 86400
            days_to_end.append(delta_days)
            if delta_days < 0 and not m.get("closed"):
                expired_open += 1
            if delta_days > 365 * 5:
                far_future += 1
        except Exception:
            none_end += 1
    print(f"\nEnd-date sanity:")
    print(f"  markets with no parseable endDate: {none_end:,}")
    print(f"  markets where endDate is past but closed=false: {expired_open:,}")
    print(f"  markets ending >5y in future: {far_future:,}")
    if days_to_end:
        print(f"  days-to-end quantiles: {quantiles(days_to_end, (0.1, 0.5, 0.9, 0.99))}")

    # --- volume sums by tag (rough domain split) ---
    tag_vol: dict[str, float] = defaultdict(float)
    for ev in events:
        v = sum(float(m.get("volume24hr") or 0) for m in (ev.get("markets") or []))
        for t in (ev.get("tags") or []):
            label = t.get("label") if isinstance(t, dict) else str(t)
            if label:
                tag_vol[label] += v
    print("\nTop tags by 24h volume:")
    for label, v in sorted(tag_vol.items(), key=lambda x: -x[1])[:20]:
        print(f"  ${v:>14,.0f}  {label}")

    # --- 24h-volume-weighted top markets (where the action is) ---
    print("\nTop 15 markets by 24h volume (the 'live' set):")
    top = sorted(
        all_markets, key=lambda m: float(m.get("volume24hr") or 0), reverse=True
    )[:15]
    for m in top:
        v24 = float(m.get("volume24hr") or 0)
        q = m.get("question", "")[:80]
        closed = m.get("closed")
        print(f"  ${v24:>12,.0f}  closed={str(closed)[:5]:5s}  {q}")


if __name__ == "__main__":
    main()
