from datetime import datetime

from agent.backtest.metrics import compute_metrics
from agent.types import Direction, Setup, Timeframe, Trade


def t(pnl):
    s = Setup(
        direction=Direction.LONG,
        timeframe=Timeframe.H1,
        detected_at=datetime(2024, 1, 1),
        detected_bar_index=0,
        entry=1.1, stop=1.09, take_profit=1.12,
    )
    tr = Trade(
        setup=s, direction=Direction.LONG,
        entry_time=datetime(2024, 1, 1), entry_price=1.1,
        stop_price=1.09, tp_price=1.12, lot_size=0.01,
        exit_time=datetime(2024, 1, 2), exit_price=1.12 if pnl > 0 else 1.09,
        exit_reason="tp" if pnl > 0 else "sl",
    )
    tr.pnl = pnl
    tr.pnl_pips = pnl * 10
    return tr


def test_metrics_basic():
    trades = [t(2), t(2), t(-1), t(2), t(-1)]
    m = compute_metrics(trades, initial_balance=100.0)
    assert m.n_trades == 5
    assert m.n_wins == 3
    assert m.win_rate == 0.6
    assert m.profit_factor == 6 / 2
    assert m.expectancy == (3 * 2 + 2 * -1) / 5


def test_empty():
    m = compute_metrics([], initial_balance=100.0)
    assert m.n_trades == 0
    assert m.final_balance == 100.0
