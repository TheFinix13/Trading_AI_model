"""Regression test for the 2026-05-03 zone-detector bug.

Bugs found while running the first 3-year backtest with all v4 gates:

  1. ``detect_zones`` was pruning ``[z for z in zones if (len(bars) - 1 -
     z.created_bar_index) <= max_age_bars]`` after detection — this kept
     only zones in the LAST ``max_age_bars`` of the input series. On a
     74 000-bar M15 history with ``max_age_bars=500`` that meant zones from
     2023-2025 were silently discarded (only 28 zones in 3 years; 5-year
     historical backtest yielded only 22 trades, all in April 2026).
  2. ``median_body`` used to filter "strong" impulses was computed from the
     last 200 bars of the entire series, biasing the impulse threshold to
     recent volatility for every historical bar.

The fixes:
  * Detector returns all zones, no time-of-detection age filter.
  * Age filter happens at use time in the engine via ``at_index``.
  * ``median_body`` is now a rolling per-impulse local median.

This test pins the fix by asserting that on a synthetic dataset spanning
several "years" with constant volatility, zones are distributed across the
whole time range, not just the tail.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone

from agent.detectors.zones import detect_zones, fresh_zones
from agent.types import Bar, Timeframe


def _synthetic_bars(n_bars: int, seed: int = 42) -> list[Bar]:
    """Build a deterministic walk with periodic strong impulses every 200 bars.
    Each impulse is the same size regardless of where it sits in the series."""
    import random
    rng = random.Random(seed)
    bars: list[Bar] = []
    price = 1.10000
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for i in range(n_bars):
        # Background noise: small bodies, ATR ~5 pips
        body = rng.gauss(0, 0.00005)
        wick = abs(rng.gauss(0, 0.00003))
        # Inject a STRONG bullish impulse every 200 bars (50 pip body)
        if i % 200 == 50:
            body = +0.0050
        # Inject a STRONG bearish impulse every 200 bars at offset 150
        if i % 200 == 150:
            body = -0.0050
        open_ = price
        close = price + body
        high = max(open_, close) + wick
        low = min(open_, close) - wick
        bars.append(Bar(
            time=t0 + timedelta(minutes=15 * i),
            open=open_, high=high, low=low, close=close,
            volume=1.0, timeframe=Timeframe.M15,
        ))
        price = close
    return bars


def test_zones_detected_across_full_history():
    """The detector must emit zones throughout the input series, not just at
    the tail. Pre-fix behaviour: only zones from the last `max_age_bars`
    bars survived. Post-fix: every periodic impulse is detected."""
    bars = _synthetic_bars(5000)  # 5000 M15 bars = ~52 days
    zones = detect_zones(
        bars, min_impulse_pips=30.0, max_age_bars=500,
    )
    # We injected 50 impulses (5000 bars / 100). The "strong" gate (body
    # >= 2x local median) and dedupe filter will trim some, so we expect
    # at least 12. The pre-fix bug would have capped this at the count
    # in the last `max_age_bars` window only, which we test for with the
    # bucket-spread assertion below.
    assert len(zones) >= 12, f"expected >=12 zones, got {len(zones)}"

    # Bucket by quintiles of the series. The pre-fix bug would put 100%
    # of zones in the last quintile; post-fix they spread evenly.
    n = len(bars)
    bucket = Counter(int(5 * z.created_bar_index / n) for z in zones)
    populated = sum(1 for k in range(5) if bucket.get(k, 0) > 0)
    assert populated >= 4, (
        f"zones concentrate in too few buckets: {dict(bucket)} "
        f"(only {populated}/5 are populated — pre-fix bug)"
    )


def test_max_age_filter_applied_at_use_time():
    """`fresh_zones(max_age_bars=...)` is the correct place for age filtering.
    The detector itself returns ALL zones; callers prune by age relative to
    `at_index`."""
    bars = _synthetic_bars(3000)
    zones = detect_zones(bars, min_impulse_pips=30.0, max_age_bars=500)
    assert len(zones) >= 10
    # Querying at index 1000 with max_age=200 should drop zones from index <800
    pruned = fresh_zones(zones, at_index=1000, max_age_bars=200)
    for z in pruned:
        assert z.created_bar_index >= 800
        assert z.created_bar_index < 1000


def test_median_body_is_local_not_global():
    """If the global-median bug were still present, an impulse in a quiet
    early region of the series would be suppressed because the late part
    of the series has higher volatility (or vice-versa). With a rolling
    local median the early impulse is detected."""
    # Build a series where the FIRST half is very quiet and the SECOND half
    # has many large bars. A 50-pip bar in the early region should still
    # qualify as a zone-impulse because LOCAL median is small.
    import random
    rng = random.Random(123)
    bars: list[Bar] = []
    price = 1.10000
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for i in range(2000):
        if i < 1000:
            body = rng.gauss(0, 0.00002)  # very quiet
        else:
            body = rng.gauss(0, 0.00050)  # 25x noisier
        wick = abs(body) * 0.5
        # One strong impulse at i=500 (in the QUIET region)
        if i == 500:
            body = +0.0050
        open_ = price
        close = price + body
        bars.append(Bar(
            time=t0 + timedelta(minutes=15 * i),
            open=open_, high=max(open_, close) + wick,
            low=min(open_, close) - wick, close=close,
            volume=1.0, timeframe=Timeframe.M15,
        ))
        price = close
    zones = detect_zones(bars, min_impulse_pips=30.0, max_age_bars=10000)
    # The impulse at i=500 must be detected. With the OLD global-median
    # this was suppressed because median_body was dominated by the noisy
    # tail and 50 pips wasn't 2x of that median.
    early_zones = [z for z in zones if z.created_bar_index < 1000]
    assert len(early_zones) >= 1, (
        "early-region impulse was not detected — global-median bug regressed"
    )
