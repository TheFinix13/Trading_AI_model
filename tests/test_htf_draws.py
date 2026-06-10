"""Tests for causal HTF demand/supply draw precomputation (Phase B/C)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from agent.config import load_config
from agent.context.htf_draws import precompute_htf_draws
from agent.types import Bar, Timeframe

T0 = datetime(2023, 1, 2, tzinfo=timezone.utc)


def _wave_bars(n: int) -> list[Bar]:
    """A multi-week H1 wave so D1/H4 swing highs (supply) and lows (demand) form
    on both sides of price."""
    bars: list[Bar] = []
    for i in range(n):
        mid = 1.1000 + 0.010 * math.sin(i / 30.0)
        o = mid
        c = 1.1000 + 0.010 * math.sin((i + 1) / 30.0)
        hi = max(o, c) + 0.0008
        lo = min(o, c) - 0.0008
        bars.append(Bar(time=T0 + timedelta(hours=i), open=o, high=hi, low=lo,
                        close=c, volume=100.0, timeframe=Timeframe.H1))
    return bars


def test_htf_draws_are_symmetric_and_on_the_right_side():
    cfg = load_config()
    bars = _wave_bars(60 * 24)  # 60 days of H1
    draws = precompute_htf_draws(bars, cfg)
    assert draws, "expected some HTF draws over a 60-day wave"

    has_supply = any(v[0] is not None for v in draws.values())
    has_demand = any(v[1] is not None for v in draws.values())
    assert has_supply, "no supply-above draws — upside not perceived"
    assert has_demand, "no demand-below draws — downside not perceived"

    by_time = {b.time: b for b in bars}
    for t, (supply, demand) in draws.items():
        price = by_time[t].close
        if supply is not None:
            assert supply > price  # supply draw is above price (a long's draw)
        if demand is not None:
            assert demand < price  # demand draw is below price (a short's draw)


def test_htf_draws_are_causal_no_draw_before_enough_history():
    cfg = load_config()
    bars = _wave_bars(60 * 24)
    draws = precompute_htf_draws(bars, cfg)
    # The first ~20 daily bars must close before any zone can form, so early H1
    # bars cannot carry a draw (no look-ahead into later-formed zones).
    early_times = {b.time for b in bars[: 18 * 24]}
    assert not (early_times & set(draws)), "draw present before 20 closed D1 bars"


def test_short_series_returns_empty():
    cfg = load_config()
    assert precompute_htf_draws(_wave_bars(100), cfg) == {}
