"""Verify the BE-stop migration converts spike-outs to breakeven exits and
does not create lookahead within a bar."""
from datetime import datetime, timedelta

from agent.backtest.engine import Backtester
from agent.config import load_config
from agent.types import Bar, Direction, Setup, Timeframe, Trade


def _bars_long_spikes_then_reverses() -> list[Bar]:
    """Build a bar series:
      bar0: entry signal at close=1.10000
      bar1: huge favorable bar (high=1.10300 = +30 pips, +3R on a 10-pip stop)
      bar2: full reversal that wicks down through the original stop
    With BE migration enabled, bar1's MFE (+3R) should ratchet stop to entry,
    so bar2's down-wick exits at breakeven, not -1R."""
    base = datetime(2024, 1, 1, 10, 0, tzinfo=None)
    out = []
    out.append(Bar(time=base, open=1.0995, high=1.1001, low=1.0994, close=1.1000,
                   volume=100, timeframe=Timeframe.H1))
    out.append(Bar(time=base + timedelta(hours=1),
                   open=1.1000, high=1.1030, low=1.0998, close=1.1025,
                   volume=100, timeframe=Timeframe.H1))
    out.append(Bar(time=base + timedelta(hours=2),
                   open=1.1025, high=1.1026, low=1.0985, close=1.0987,
                   volume=100, timeframe=Timeframe.H1))
    return out


def _make_open_trade(bars):
    setup = Setup(
        direction=Direction.LONG, timeframe=Timeframe.H1,
        detected_at=bars[0].time, detected_bar_index=0,
        entry=1.10000,
        stop=1.09900,        # 10 pip stop
        take_profit=1.10500, # 50 pip target (5R)
    )
    trade = Trade(
        setup=setup, direction=Direction.LONG,
        entry_time=bars[0].time, entry_price=1.10000,
        stop_price=1.09900, tp_price=1.10500,
        lot_size=0.01,
    )
    return trade


def test_be_migration_converts_spike_out_to_breakeven():
    cfg = load_config()
    cfg.backtest.move_be_at_r = 1.0
    cfg.backtest.be_lock_r = 0.0

    bt = Backtester(cfg)
    bars = _bars_long_spikes_then_reverses()
    trade = _make_open_trade(bars)

    # Manually replay the loop's logic (bar1 then bar2 — bar0 is the entry bar).
    # bar1: trade survives, MFE crosses 1R (+3R actually), stop migrates to entry.
    bt._check_exit(trade, bars[1])
    assert trade.exit_reason is None
    bt._update_excursions(trade, bars[1], migrate=True)
    assert trade.stop_price == 1.10000  # snapped to entry

    # bar2: now the original stop (1.099) is no longer in play; new stop (1.100) gets
    # hit by bar2's open=1.1025 -> low=1.0985. Trade exits at 1.100 (breakeven, not -10 pips).
    exited = bt._check_exit(trade, bars[2])
    assert exited
    assert trade.exit_price == 1.10000
    assert abs(trade.pnl_pips) < 0.01  # essentially zero P&L (commission ignored at this layer)


def test_be_migration_disabled_keeps_original_stop():
    cfg = load_config()
    cfg.backtest.move_be_at_r = 0.0  # disable

    bt = Backtester(cfg)
    bars = _bars_long_spikes_then_reverses()
    trade = _make_open_trade(bars)

    bt._check_exit(trade, bars[1])
    bt._update_excursions(trade, bars[1], migrate=True)
    assert trade.stop_price == 1.09900  # unchanged

    bt._check_exit(trade, bars[2])
    assert trade.exit_reason == "sl"
    assert trade.pnl_pips < 0
