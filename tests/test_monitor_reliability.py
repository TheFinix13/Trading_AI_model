"""PositionMonitor reliability regressions found from a week of VM agent
logs cross-checked against the user's actual MT5 trade history
(2026-06-30 -> 2026-07-06):

1. A broker-side close (TP/SL order filling between two poll cycles) must
   prefer the authoritative broker history lookup over the last-polled
   tick estimate — reproduces the real USDCAD ticket 2915834625 case where
   a +$2.98 take-profit was logged as a -$0.87 loss tagged CATASTROPHE SL.
2. Daily-DD halt must not fire on an implausible balance/equity reading
   (the root cause of the multi-day "stuck kill switch" after an Exness
   maintenance window: a fabricated $0 account read as a 100% drawdown).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.config import load_config
from agent.live.broker import ClosedTrade, OrderResult, Position
from agent.live.config import LiveConfig
from agent.live.monitor import PositionMonitor
from agent.live.soft_stop import SoftStopConfig
from agent.types import Direction


def _utc(seconds_offset: int = 0) -> datetime:
    return datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)


def _make_monitor(symbol: str = "USDCAD") -> PositionMonitor:
    broker = MagicMock()
    cfg = load_config()
    live = LiveConfig(symbol=symbol)
    notifier = MagicMock()
    notifier.notify_text = MagicMock()
    return PositionMonitor(
        broker=broker, config=cfg, live_config=live, notifier=notifier,
        soft_stop_cfg=SoftStopConfig(enabled=False),
    )


# ---------------------------------------------------------------------------
# Real bug reproduction: 2026-07-02 USDCAD ticket 2915834625
# ---------------------------------------------------------------------------


def test_broker_closed_tp_is_not_logged_as_a_loss(caplog):
    """The agent's own position monitor never issued the close (the broker's
    TP order filled on its own) so close_result is empty and the only
    signal available before this fix was the last-polled tick — which
    still showed a small floating loss moments before the fill. The
    broker's own trade history (get_closed_trade) is ground truth and must
    win."""
    mon = _make_monitor("USDCAD")
    fake_pos = Position(
        ticket=2915834625, symbol="USDCAD", direction=Direction.SHORT,
        volume=0.04, open_price=1.42069, open_time=_utc(),
        stop_loss=1.42557, take_profit=1.41963,
        profit=-0.87, current_price=1.42100,
    )
    mon.broker.get_open_positions = AsyncMock(return_value=[fake_pos])
    mon.broker.get_account_info = AsyncMock(return_value=MagicMock(
        balance=1000.0, equity=999.13,
    ))
    mon.broker.get_latest_bars = AsyncMock(return_value=[])
    asyncio.run(mon._check_positions())

    # Next cycle: broker's own TP order has filled and the position is gone.
    # The excursion snapshot from the LAST poll still shows the stale,
    # losing state (this is exactly what happened in production).
    mon.broker.get_open_positions = AsyncMock(return_value=[])
    mon.broker.get_closed_trade = AsyncMock(return_value=ClosedTrade(
        exit_price=1.41963, profit=2.98, reason="tp",
    ))
    closes: list[tuple[int, dict]] = []
    mon.trade_closed_cb = lambda t, i: closes.append((t, i))

    with caplog.at_level(logging.INFO, logger="agent.live.monitor"):
        asyncio.run(mon._check_positions())

    assert closes, "trade_closed callback never fired"
    ticket, info = closes[0]
    assert ticket == 2915834625
    assert info["exit_reason"] == "tp"
    assert info["pnl"] == pytest.approx(2.98)
    assert info["pnl"] > 0, "a real take-profit must never resolve to a loss"
    assert "[TP HIT]" in caplog.text
    assert "CATASTROPHE" not in caplog.text
    mon.broker.get_closed_trade.assert_awaited_once_with(2915834625, "USDCAD")


def test_broker_closed_sl_is_confirmed_not_guessed(caplog):
    """A genuine broker-side SL fill, confirmed via history, must still tag
    as CATASTROPHE SL — the fix removes the pnl-sign GUESS, not real
    confirmed stop-loss reporting."""
    mon = _make_monitor("USDCAD")
    fake_pos = Position(
        ticket=999, symbol="USDCAD", direction=Direction.SHORT,
        volume=0.04, open_price=1.42069, open_time=_utc(),
        stop_loss=1.42557, take_profit=1.41963,
        profit=-5.0, current_price=1.42300,
    )
    mon.broker.get_open_positions = AsyncMock(return_value=[fake_pos])
    mon.broker.get_account_info = AsyncMock(return_value=MagicMock(
        balance=1000.0, equity=995.0,
    ))
    mon.broker.get_latest_bars = AsyncMock(return_value=[])
    asyncio.run(mon._check_positions())

    mon.broker.get_open_positions = AsyncMock(return_value=[])
    mon.broker.get_closed_trade = AsyncMock(return_value=ClosedTrade(
        exit_price=1.42557, profit=-19.5, reason="sl",
    ))
    closes: list[tuple[int, dict]] = []
    mon.trade_closed_cb = lambda t, i: closes.append((t, i))

    with caplog.at_level(logging.INFO, logger="agent.live.monitor"):
        asyncio.run(mon._check_positions())

    info = closes[0][1]
    assert info["exit_reason"] == "sl"
    assert info["pnl"] == pytest.approx(-19.5)
    assert "[CATASTROPHE SL]" in caplog.text


def test_unresolved_close_falls_back_honestly_not_as_stop_loss(caplog):
    """No close_result, no broker history (e.g. paper broker / mocked
    broker without support), and price doesn't match any known level:
    must land on the honest "manual" reason, NEVER a pnl-sign guess of
    "sl" just because the estimate happens to be negative."""
    mon = _make_monitor("EURUSD")
    fake_pos = Position(
        ticket=42, symbol="EURUSD", direction=Direction.LONG,
        volume=0.01, open_price=1.10000, open_time=_utc(),
        stop_loss=1.09500, take_profit=1.10800,
        profit=-1.0, current_price=1.09900,
    )
    mon.broker.get_open_positions = AsyncMock(return_value=[fake_pos])
    mon.broker.get_account_info = AsyncMock(return_value=MagicMock(
        balance=1000.0, equity=999.0,
    ))
    mon.broker.get_latest_bars = AsyncMock(return_value=[])
    asyncio.run(mon._check_positions())

    # Position vanishes; broker mock has no get_closed_trade configured, so
    # the defensive fallback in _handle_close must kick in (not crash).
    mon.broker.get_open_positions = AsyncMock(return_value=[])
    # Simulate a broker whose get_closed_trade isn't a real coroutine (e.g.
    # an un-mocked plain MagicMock attribute) — awaiting it must be caught
    # defensively rather than crashing the monitor cycle.
    mon.broker.get_closed_trade = MagicMock(return_value=None)
    closes: list[tuple[int, dict]] = []
    mon.trade_closed_cb = lambda t, i: closes.append((t, i))

    with caplog.at_level(logging.INFO, logger="agent.live.monitor"):
        asyncio.run(mon._check_positions())

    info = closes[0][1]
    # Price (1.09900) is not within 3 pips of stop (1.09500) or tp (1.10800),
    # so the old code's pnl-sign guess would have said "sl" (pnl < 0). The
    # fix must NOT do that.
    assert info["exit_reason"] == "manual"
    assert "CLOSED (cause unconfirmed)" in caplog.text
    assert "CATASTROPHE" not in caplog.text


# ---------------------------------------------------------------------------
# Daily-DD sanity floor
# ---------------------------------------------------------------------------


def test_daily_dd_skips_on_zero_balance_reading():
    mon = _make_monitor("EURUSD")
    mon._current_day = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    mon._day_start_balance = 1000.0
    mon._emergency_close_all = AsyncMock()
    asyncio.run(mon._check_daily_dd(balance=0.0, equity=0.0, positions=[]))
    mon._emergency_close_all.assert_not_called()


def test_daily_dd_skips_on_implausible_drawdown():
    """Even if balance/equity individually look plausible-ish, a >60% swing
    in one poll cycle is not a real market move given position-sizing caps
    — treat it as a bad reading, not a real halt trigger."""
    mon = _make_monitor("EURUSD")
    mon._current_day = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    mon._day_start_balance = 1000.0
    mon._emergency_close_all = AsyncMock()
    asyncio.run(mon._check_daily_dd(balance=1000.0, equity=350.0, positions=[]))
    mon._emergency_close_all.assert_not_called()


def test_daily_dd_still_halts_on_a_real_drawdown():
    """Sanity floor must not defang the real halt: a plausible 5% loss on a
    healthy account still triggers the configured 3% limit."""
    mon = _make_monitor("EURUSD")
    mon._current_day = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    mon._day_start_balance = 1000.0
    mon._emergency_close_all = AsyncMock()
    asyncio.run(mon._check_daily_dd(balance=1000.0, equity=950.0, positions=[]))
    mon._emergency_close_all.assert_awaited_once()
