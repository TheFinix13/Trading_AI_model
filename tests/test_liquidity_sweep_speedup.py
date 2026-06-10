"""Equivalence + perf tests for the bisect-based liquidity-sweep detector.

The detector was rewritten from an O(N × S) per-bar swing scan to an O(log N)
bisect-based one. These tests:

  1. Prove output-equivalence on real EURUSD H4/H1 data vs a *reference*
     implementation that mirrors the v2 (pre-speedup) loop. If anything in
     either the original semantics or the new implementation drifts, this
     test fires loudly.
  2. Smoke-time the new detector to guard against silent regressions to
     O(N²).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.detectors.daily_levels import compute_daily_levels
from agent.detectors.liquidity_sweep import (
    LiquiditySweep,
    _equal_levels,
    detect_liquidity_sweeps,
)
from agent.detectors.swings import detect_swings
from agent.types import Bar, Direction, Timeframe


def _detect_sweeps_reference(
    bars: list[Bar],
    *,
    swing_lookback: int = 5,
    pierce_buffer_pips: float = 1.0,
    use_daily_levels: bool = True,
) -> list[LiquiditySweep]:
    """Verbatim copy of the v2 (pre-speedup) inner loop. Kept in this test
    module so we have a stable reference to diff against — the real detector
    can keep evolving without invalidating the equivalence guarantee."""
    if len(bars) < swing_lookback * 2 + 2:
        return []
    swings = detect_swings(bars, lookback=swing_lookback)
    daily_levels = compute_daily_levels(bars) if use_daily_levels else [None] * len(bars)
    equal_clusters = _equal_levels(swings)
    pip = 0.0001
    buf = pierce_buffer_pips * pip
    out: list[LiquiditySweep] = []

    for i in range(len(bars)):
        bar = bars[i]
        upper_targets: list[tuple[str, float]] = []
        lower_targets: list[tuple[str, float]] = []

        dl = daily_levels[i] if use_daily_levels else None
        if dl is not None:
            ref = max(bar.open, bar.close)
            for lbl, price in dl.levels_dict().items():
                (upper_targets if price >= ref else lower_targets).append((lbl, price))

        for s in swings:
            if s.bar_index >= i - swing_lookback:
                continue
            if s.is_high and s.price >= max(bar.open, bar.close):
                upper_targets.append(("swing_high", s.price))
            elif (not s.is_high) and s.price <= min(bar.open, bar.close):
                lower_targets.append(("swing_low", s.price))

        for lbl, price, end_idx in equal_clusters:
            if end_idx >= i:
                continue
            if lbl == "equal_highs" and price >= max(bar.open, bar.close):
                upper_targets.append((lbl, price))
            elif lbl == "equal_lows" and price <= min(bar.open, bar.close):
                lower_targets.append((lbl, price))

        # buyside
        pierced = [t for t in upper_targets if bar.high > t[1] + buf]
        up = min(pierced, key=lambda t: t[1]) if pierced else None
        if up is not None and bar.close < up[1]:
            out.append(LiquiditySweep(
                side="buyside", direction=Direction.SHORT,
                swept_label=up[0], swept_price=up[1],
                sweep_bar_index=i, sweep_time=bar.time,
                sweep_high=bar.high, sweep_low=bar.low, sweep_close=bar.close,
                confirm_bar_index=-1, confirm_pips=0.0, rr_estimate=None,
            ))
        # sellside
        pierced = [t for t in lower_targets if bar.low < t[1] - buf]
        dn = max(pierced, key=lambda t: t[1]) if pierced else None
        if dn is not None and bar.close > dn[1]:
            out.append(LiquiditySweep(
                side="sellside", direction=Direction.LONG,
                swept_label=dn[0], swept_price=dn[1],
                sweep_bar_index=i, sweep_time=bar.time,
                sweep_high=bar.high, sweep_low=bar.low, sweep_close=bar.close,
                confirm_bar_index=-1, confirm_pips=0.0, rr_estimate=None,
            ))
    return out


def _load_bars(tf: Timeframe, n_months: int = 6) -> list[Bar]:
    """Pull a slice of EURUSD bars from the cache. ``n_months`` keeps the
    test cheap while still exercising hundreds of swings."""
    cfg = load_config()
    loader = BarLoader(cache_root=cfg.data_dir)
    end = datetime.fromisoformat(cfg.eval.dev_end).replace(tzinfo=timezone.utc)
    # Walk back n_months by 30-day chunks.
    from datetime import timedelta
    start = end - timedelta(days=30 * n_months)
    df = loader.get(cfg.symbol, tf, start, end, refresh=False)
    return df_to_bars(df, tf)


def _sweep_signature(s: LiquiditySweep) -> tuple:
    """Field tuple used for set-equality. ``rr_estimate`` is excluded because
    causal-mode never populates it (always None) — and including it would
    invite NaN-comparison flakiness if anyone ever turns on confirmation."""
    return (
        s.side, s.direction, s.swept_label, round(s.swept_price, 8),
        s.sweep_bar_index, s.sweep_time,
        round(s.sweep_high, 8), round(s.sweep_low, 8), round(s.sweep_close, 8),
    )


@pytest.mark.parametrize("tf", [Timeframe.H4, Timeframe.H1])
def test_sweep_detector_matches_reference_on_real_data(tf: Timeframe):
    """The bisect detector must produce the same set of sweep events as the
    verbatim v2 reference on real cached EURUSD bars. Set-equality, not
    list-equality: ordering inside the output is the same (chronological by
    bar) but we use a set to fail with a useful diff."""
    bars = _load_bars(tf, n_months=6)
    fast = detect_liquidity_sweeps(bars, swing_lookback=5, pierce_buffer_pips=1.0)
    ref = _detect_sweeps_reference(bars, swing_lookback=5, pierce_buffer_pips=1.0)

    fast_sigs = {_sweep_signature(s) for s in fast}
    ref_sigs = {_sweep_signature(s) for s in ref}

    missing = ref_sigs - fast_sigs
    extra = fast_sigs - ref_sigs
    assert not missing and not extra, (
        f"Sweep detector drift on {tf}:\n"
        f"  missing from fast: {len(missing)} (first: {sorted(missing)[:3]})\n"
        f"  extra in fast:     {len(extra)} (first: {sorted(extra)[:3]})"
    )
    # Same length implies same multiset given the bar_index is in the
    # signature.
    assert len(fast) == len(ref)


def test_sweep_detector_perf_floor_h1():
    """Hard regression guard: H1 detector should finish in well under 30s
    even on a 6-month slice. The old implementation took ~30s for 1 year."""
    bars = _load_bars(Timeframe.H1, n_months=6)
    t0 = time.perf_counter()
    _ = detect_liquidity_sweeps(bars, swing_lookback=5, pierce_buffer_pips=1.0)
    dt = time.perf_counter() - t0
    # Generous ceiling so the test isn't flaky on slow CI. Locally this
    # finishes in <1s; the v2 version on the same slice was ~15s.
    assert dt < 10.0, f"sweep detector regressed to {dt:.2f}s on 6mo H1"
