"""Equivalence + perf tests for the cursor-based BOS detector.

Same shape as ``test_liquidity_sweep_speedup.py``: a verbatim copy of the v2
inner loop lives here as the reference, and the production detector must
match its output bit-for-bit on real EURUSD bars.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.detectors.bos import _enrich_bos_quality, detect_bos
from agent.detectors.swings import detect_swings
from agent.types import Bar, BreakOfStructure, Direction, Timeframe


def _detect_bos_reference(
    bars: list[Bar], swing_lookback: int = 5,
) -> list[BreakOfStructure]:
    """Verbatim v2 inner loop, untouched. Kept here so the production
    implementation can evolve without weakening the equivalence guarantee."""
    swings = detect_swings(bars, lookback=swing_lookback)
    if not swings:
        return []
    breaks: list[BreakOfStructure] = []
    last_broken_high: float | None = None
    last_broken_low: float | None = None
    for i, bar in enumerate(bars):
        prior_highs = [s for s in swings if s.is_high and s.bar_index < i - swing_lookback]
        prior_lows = [s for s in swings if not s.is_high and s.bar_index < i - swing_lookback]
        if prior_highs:
            ref = prior_highs[-1]
            if bar.close > ref.price and (last_broken_high is None or ref.price > last_broken_high):
                bos = BreakOfStructure(
                    direction=Direction.LONG, broken_swing_price=ref.price,
                    broken_at=bar.time, broken_bar_index=i,
                )
                _enrich_bos_quality(bos, bar, ref.price, ref.bar_index, i, bars)
                breaks.append(bos)
                last_broken_high = ref.price
        if prior_lows:
            ref = prior_lows[-1]
            if bar.close < ref.price and (last_broken_low is None or ref.price < last_broken_low):
                bos = BreakOfStructure(
                    direction=Direction.SHORT, broken_swing_price=ref.price,
                    broken_at=bar.time, broken_bar_index=i,
                )
                _enrich_bos_quality(bos, bar, ref.price, ref.bar_index, i, bars)
                breaks.append(bos)
                last_broken_low = ref.price
    return breaks


def _load_bars(tf: Timeframe, n_months: int = 6) -> list[Bar]:
    cfg = load_config()
    loader = BarLoader(cache_root=cfg.data_dir)
    end = datetime.fromisoformat(cfg.eval.dev_end).replace(tzinfo=timezone.utc)
    start = end - timedelta(days=30 * n_months)
    df = loader.get(cfg.symbol, tf, start, end, refresh=False)
    return df_to_bars(df, tf)


@pytest.mark.parametrize("tf", [Timeframe.H4, Timeframe.H1])
def test_bos_detector_matches_reference_on_real_data(tf: Timeframe):
    bars = _load_bars(tf, n_months=6)
    fast = detect_bos(bars, swing_lookback=5)
    ref = _detect_bos_reference(bars, swing_lookback=5)

    assert len(fast) == len(ref), (
        f"BOS count mismatch on {tf}: fast={len(fast)} ref={len(ref)}"
    )
    # All fields must match (quality + legacy). Compare as dicts; dataclasses
    # are equal iff every field matches.
    for f, r in zip(fast, ref):
        assert asdict(f) == asdict(r), (
            f"BOS field drift on {tf} at broken_bar_index={f.broken_bar_index}:\n"
            f"  fast={asdict(f)}\n  ref ={asdict(r)}"
        )


def test_bos_detector_perf_floor_h1():
    bars = _load_bars(Timeframe.H1, n_months=6)
    t0 = time.perf_counter()
    _ = detect_bos(bars, swing_lookback=5)
    dt = time.perf_counter() - t0
    # Old impl took ~15s on this slice; new should be <2s.
    assert dt < 5.0, f"BOS detector regressed to {dt:.2f}s on 6mo H1"
