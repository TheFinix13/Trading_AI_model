"""Tests for the Phase-A evaluation protocol (docs/10): bootstrap CIs.

The embargo / walk-forward `_slice_bars` helper was burned with `walkforward.py`
in the v2 reset (the rebuild target is `scripts/evaluate.py` over the v2 alpha
registry); this test module covers the surviving bootstrap + scorecard plumbing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.backtest.metrics import (
    MetricCI,
    _expectancy,
    _profit_factor,
    _win_rate,
    bootstrap_ci,
    make_scorecard,
)
from agent.types import Bar, Direction, Setup, Timeframe, Trade


def _bar(i: int, price: float = 1.10) -> Bar:
    return Bar(
        time=datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i),
        open=price, high=price + 0.001, low=price - 0.001, close=price,
        volume=1000.0, timeframe=Timeframe.H1,
    )


def _trade(pnl: float, i: int = 0) -> Trade:
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
    setup = Setup(
        direction=Direction.LONG, timeframe=Timeframe.H1,
        detected_at=t0, detected_bar_index=i,
        entry=1.10, stop=1.09, take_profit=1.12,
    )
    return Trade(
        setup=setup, direction=Direction.LONG, entry_time=t0,
        entry_price=1.10, stop_price=1.09, tp_price=1.12, lot_size=0.1,
        exit_time=t0 + timedelta(hours=2),
        exit_price=1.11 if pnl > 0 else 1.095,
        exit_reason="tp" if pnl > 0 else "sl",
        pnl=pnl, pnl_pips=pnl,
    )


class TestBootstrapCI:
    def test_ci_brackets_point_estimate(self):
        pnls = [1.0, -0.5, 2.0, -1.0, 0.5, 1.5, -0.8, 0.3]
        ci = bootstrap_ci(pnls, _expectancy, n_resamples=500)
        assert ci.lo <= ci.value <= ci.hi

    def test_strong_positive_edge_excludes_zero(self):
        # A clean, consistent winner — the interval should sit above zero.
        pnls = [1.0] * 40 + [-0.2] * 5
        ci = bootstrap_ci(pnls, _expectancy, n_resamples=800)
        assert ci.excludes_zero and ci.value > 0

    def test_noisy_breakeven_straddles_zero(self):
        # Symmetric coin-flip P&L — must NOT look like an edge.
        pnls = [1.0, -1.0] * 20
        ci = bootstrap_ci(pnls, _expectancy, n_resamples=800)
        assert not ci.excludes_zero

    def test_tiny_sample_is_degenerate(self):
        ci = bootstrap_ci([1.0], _expectancy)
        assert ci.lo == ci.hi == ci.value

    def test_profit_factor_handles_no_losses(self):
        # All winners → PF is inf; bootstrap must not crash and value is finite-ish.
        pnls = [1.0, 2.0, 0.5]
        ci = bootstrap_ci(pnls, _profit_factor, n_resamples=100)
        assert isinstance(ci, MetricCI)

    def test_win_rate_metric(self):
        pnls = [1.0, 1.0, 1.0, -1.0]  # 75%
        ci = bootstrap_ci(pnls, _win_rate, n_resamples=200)
        assert 0.0 <= ci.lo <= ci.value <= ci.hi <= 1.0
        assert abs(ci.value - 0.75) < 1e-9


class TestScorecard:
    def test_scorecard_flags_edge_vs_noise(self):
        winners = [_trade(1.0, i) for i in range(40)] + [_trade(-0.2, i + 40) for i in range(5)]
        card = make_scorecard("edge", winners, 10000.0, n_resamples=500)
        assert "EDGE" in str(card)

        coinflip = [_trade(1.0 if i % 2 else -1.0, i) for i in range(40)]
        card2 = make_scorecard("noise", coinflip, 10000.0, n_resamples=500)
        assert "noise" in str(card2)


