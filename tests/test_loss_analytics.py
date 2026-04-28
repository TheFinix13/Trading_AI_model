"""Unit tests for loss analytics. Synthesizes Trades with known MAE/MFE shapes
and asserts categorization is correct."""
from datetime import datetime

from agent.analysis.losses import (
    LOSS_NEVER_WORKED,
    LOSS_REVERSAL,
    LOSS_SPIKE_OUT,
    LOSS_STOPPED_ON_RETRACE,
    analyze,
    format_report,
)
from agent.types import Direction, Setup, Timeframe, Trade


def _trade(*, mae=0.0, mfe=0.0, bars=5, exit_reason="sl",
           pnl_pips=-30.0, stop_pips=30.0, direction=Direction.LONG):
    setup = Setup(
        direction=direction,
        timeframe=Timeframe.H1,
        detected_at=datetime(2024, 1, 1, 10, 0),
        detected_bar_index=100,
        entry=1.10000,
        stop=1.10000 - stop_pips * 0.0001 if direction == Direction.LONG else 1.10000 + stop_pips * 0.0001,
        take_profit=1.10000 + 2 * stop_pips * 0.0001 if direction == Direction.LONG else 1.10000 - 2 * stop_pips * 0.0001,
    )
    return Trade(
        setup=setup,
        direction=direction,
        entry_time=datetime(2024, 1, 1, 10, 0),
        entry_price=setup.entry,
        stop_price=setup.stop,
        tp_price=setup.take_profit,
        lot_size=0.01,
        exit_time=datetime(2024, 1, 1, 11, 0),
        exit_price=setup.stop,
        exit_reason=exit_reason,
        pnl=pnl_pips * 0.01 * 10.0,
        pnl_pips=pnl_pips,
        commission=0.07,
        mae_pips=mae,
        mfe_pips=mfe,
        bars_held=bars,
    )


def test_never_worked_category():
    # 30 pip stop, MFE 1 pip, MAE 30 pips, held 20 bars: never worked.
    t = _trade(mae=30.0, mfe=1.0, bars=20)
    r = analyze([t])
    assert r.by_category[LOSS_NEVER_WORKED] == 1


def test_reversal_category():
    # 30 pip stop, MFE 20 pips (~0.66R), MAE 30: got into profit, then reversed.
    t = _trade(mae=30.0, mfe=20.0, bars=15)
    r = analyze([t])
    assert r.by_category[LOSS_REVERSAL] == 1


def test_spike_out_category():
    # MAE 30 (1R hit), MFE 25 (0.83R favorable on the same bar): classic spike-out.
    t = _trade(mae=30.0, mfe=25.0, bars=3)
    r = analyze([t])
    assert r.by_category[LOSS_SPIKE_OUT] == 1


def test_stopped_on_retrace_category():
    # 30 pip stop, MFE 4 pips (<0.2R), MAE 30, held 5 bars: chop killed us.
    t = _trade(mae=30.0, mfe=4.0, bars=5)
    r = analyze([t])
    assert r.by_category[LOSS_STOPPED_ON_RETRACE] == 1


def test_aggregates():
    trades = [
        _trade(mae=30.0, mfe=1.0, bars=20, pnl_pips=-30.0),
        _trade(mae=30.0, mfe=20.0, bars=15, pnl_pips=-30.0),
        _trade(mae=5.0, mfe=45.0, bars=10, exit_reason="tp", pnl_pips=45.0),
        _trade(mae=10.0, mfe=50.0, bars=8, exit_reason="tp", pnl_pips=45.0),
    ]
    r = analyze(trades, n_worst=10)
    assert r.n_trades == 4
    assert r.n_winners == 2
    assert r.n_losers == 2
    assert 0.49 < r.win_rate < 0.51
    s = format_report(r)
    assert "LOSS DIAGNOSTICS" in s
    assert "By hour" in s
