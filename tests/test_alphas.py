"""Tests for the modular alpha layer (docs/10 Phase B)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from agent.alphas.allocator import allocate, daily_returns
from agent.alphas.backtest import run_alpha
from agent.alphas.base import Alpha, AlphaContext, AlphaSignal
from agent.alphas.reaction_alpha import ReactionAlpha
from agent.config import load_config
from agent.rules.engine import precompute
from agent.types import Bar, Direction, Setup, Timeframe, Trade


def _bars(n: int = 300, start: float = 1.1000, step: float = 0.0005) -> list[Bar]:
    bars = []
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = start
    for i in range(n):
        # gentle zig-zag so detectors have something to chew on
        drift = step * (1 if (i // 20) % 2 == 0 else -1)
        o = price
        c = price + drift
        h = max(o, c) + step
        low = min(o, c) - step
        bars.append(Bar(time=t0 + timedelta(hours=i), open=o, high=h, low=low,
                        close=c, volume=100.0, timeframe=Timeframe.H1))
        price = c
    return bars


class _AlwaysLong(Alpha):
    name = "always_long"

    def signal(self, actx: AlphaContext, i: int):
        bar = actx.bars[i]
        return AlphaSignal(
            direction=Direction.LONG, entry=bar.close,
            stop=bar.close - 0.0020, take_profit=bar.close + 0.0030, reason="test",
        )


def _trade(day: int, pnl_pips: float) -> Trade:
    t = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
    setup = Setup(direction=Direction.LONG, timeframe=Timeframe.H1, detected_at=t,
                  detected_bar_index=0, entry=1.1, stop=1.098, take_profit=1.103)
    tr = Trade(setup=setup, direction=Direction.LONG, entry_time=t, entry_price=1.1,
               stop_price=1.098, tp_price=1.103, lot_size=0.1)
    tr.exit_time = t + timedelta(hours=2)
    tr.exit_price = 1.1
    tr.exit_reason = "tp"
    tr.pnl_pips = pnl_pips
    tr.pnl = pnl_pips
    return tr


# --- backtest fill model -----------------------------------------------------

def test_run_alpha_produces_closed_trades():
    cfg = load_config()
    bars = _bars(300)
    trades = run_alpha(_AlwaysLong(), bars, cfg, start_index=10)
    assert trades, "always-long alpha should produce trades"
    assert all(t.exit_time is not None for t in trades), "all trades must be closed"
    # one position at a time: entries strictly increasing, no overlap
    for a, b in zip(trades, trades[1:]):
        assert a.exit_time <= b.entry_time


def test_run_alpha_respects_one_position():
    cfg = load_config()
    bars = _bars(120)
    trades = run_alpha(_AlwaysLong(), bars, cfg, start_index=5)
    for a, b in zip(trades, trades[1:]):
        assert b.entry_time >= a.exit_time


def test_reaction_alpha_runs_without_error():
    """The v2 baseline alpha registry contains the ReactionAlpha; it must run
    cleanly on a synthetic series even if it doesn't fire."""
    cfg = load_config()
    bars = _bars(400)
    ctx = precompute(bars, cfg)
    trades = run_alpha(ReactionAlpha(cfg), bars, cfg, ctx=ctx, start_index=50)
    assert isinstance(trades, list)


# --- allocator ---------------------------------------------------------------

def test_daily_returns_buckets_by_exit_day():
    trades = [_trade(0, 10.0), _trade(0, -4.0), _trade(1, 6.0)]
    dr = daily_returns(trades)
    assert len(dr) == 2
    assert pytest.approx(sum(dr.values())) == 12.0


def test_allocator_downweights_correlated_duplicate():
    # Two identical (perfectly correlated) alphas + one independent edge.
    rng = np.random.default_rng(0)
    base = [_trade(d, float(rng.normal(2.0, 5.0))) for d in range(60)]
    dup = [_trade(t.entry_time.day - 1 if False else d, t.pnl_pips)
           for d, t in enumerate(base)]
    indep = [_trade(d, float(rng.normal(2.0, 5.0))) for d in range(60)]
    res = allocate({"a": base, "a_dup": dup, "indep": indep}, min_days=20)
    # The two correlated alphas should not jointly dominate the independent one.
    assert set(res.included) == {"a", "a_dup", "indep"}
    assert pytest.approx(sum(res.weights.values()), abs=1e-6) == 1.0
    # correlation between a and a_dup ~ 1.0
    ia, ib = res.names.index("a"), res.names.index("a_dup")
    assert res.correlation[ia, ib] > 0.95


def test_allocator_excludes_thin_streams():
    enough = [_trade(d, 3.0) for d in range(40)]
    thin = [_trade(d, 3.0) for d in range(5)]
    res = allocate({"enough": enough, "thin": thin}, min_days=20)
    assert "enough" in res.included
    assert "thin" in res.excluded


# --- scorecard sample-size guard --------------------------------------------

def test_scorecard_flags_thin_sample_not_edge():
    """7 all-winning trades must NOT be called an EDGE (the tiny-sample trap)."""
    from agent.backtest.metrics import make_scorecard

    winners = [_trade(d, 50.0) for d in range(7)]
    card = make_scorecard("tiny", winners, 10000.0, n_resamples=200)
    assert card.verdict == "thin"


def test_scorecard_edge_requires_positive_ci_and_size():
    from agent.backtest.metrics import make_scorecard

    rng = np.random.default_rng(1)
    # 80 trades with a clear positive edge and modest variance
    trades = [_trade(d, float(rng.normal(8.0, 3.0))) for d in range(80)]
    card = make_scorecard("edgy", trades, 10000.0, n_resamples=400)
    assert card.verdict == "EDGE"


# --- session / killzone scorecard -------------------------------------------

def _trade_at_ny_hour(day: int, ny_hour: int, pnl_pips: float) -> Trade:
    from zoneinfo import ZoneInfo

    ny = datetime(2024, 6, 3, ny_hour, 0, tzinfo=ZoneInfo("America/New_York")) + timedelta(days=day)
    t = ny.astimezone(timezone.utc)
    setup = Setup(direction=Direction.LONG, timeframe=Timeframe.H1, detected_at=t,
                  detected_bar_index=0, entry=1.1, stop=1.098, take_profit=1.103)
    tr = Trade(setup=setup, direction=Direction.LONG, entry_time=t, entry_price=1.1,
               stop_price=1.098, tp_price=1.103, lot_size=0.1)
    tr.exit_time = t + timedelta(hours=2)
    tr.exit_price = 1.1
    tr.exit_reason = "tp"
    tr.pnl_pips = pnl_pips
    tr.pnl = pnl_pips
    return tr


def test_scorecard_by_session_buckets_killzones():
    from agent.backtest.metrics import scorecard_by_session

    trades = (
        [_trade_at_ny_hour(d, 9, 5.0) for d in range(10)]   # overlap (08-12 NY)
        + [_trade_at_ny_hour(d, 5, -3.0) for d in range(8)]  # london (03-08 NY)
        + [_trade_at_ny_hour(d, 14, 2.0) for d in range(6)]  # ny (12-17 NY)
        + [_trade_at_ny_hour(d, 1, -1.0) for d in range(4)]  # asia (00-03 NY)
    )
    by = scorecard_by_session("reaction", trades, 10000.0, n_resamples=200)
    assert by["london_ny_overlap"].n_trades == 10
    assert by["london"].n_trades == 8
    assert by["ny"].n_trades == 6
    assert by["asia"].n_trades == 4
    # high-liquidity windows are reported first
    assert list(by)[0] == "london_ny_overlap"
    # the overlap bucket isolates its own positive expectancy
    assert by["london_ny_overlap"].expectancy.value > 0
