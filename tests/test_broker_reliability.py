"""Broker read-reliability regressions.

Covers two real 2026-07 production bugs found from a week of VM agent logs
cross-checked against the user's actual MT5 trade history:

1. ``get_account_info`` used to fabricate a fake all-zero ``AccountInfo``
   whenever ``mt5.account_info()`` returned ``None`` (e.g. during an Exness
   scheduled-maintenance disconnect). The daily-DD check then read that as
   a 100% drawdown and panic-closed everything, writing a kill switch that
   outlived VM/script restarts. It must now raise ``BrokerReadError``
   instead, so callers can tell "couldn't read" apart from "read zero".

2. ``get_closed_trade`` is new: when the broker closes a position on its
   own (a TP/SL order filling between two ~5s polls), the monitor
   previously had no way to know the true fill and fell back to a stale
   last-polled tick. On 2026-07-02 (ticket 2915834625, USDCAD short) this
   caused a real +$2.98 take-profit to be logged as a -$0.87 loss. This
   method reads the authoritative fill from MT5's own trade history.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agent.live.broker import BrokerReadError, MT5Broker


class _FakeMT5:
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1

    DEAL_REASON_CLIENT = 0
    DEAL_REASON_MOBILE = 1
    DEAL_REASON_WEB = 2
    DEAL_REASON_EXPERT = 3
    DEAL_REASON_SL = 4
    DEAL_REASON_TP = 5
    DEAL_REASON_SO = 6

    def __init__(self, account=None, deals=None, last_error=(0, "ok")):
        self._account = account
        self._deals = deals
        self._last_error = last_error

    def account_info(self):
        return self._account

    def last_error(self):
        return self._last_error

    def history_deals_get(self, position=None):
        if self._deals is None:
            return None
        return self._deals


def _broker_with(fake: _FakeMT5) -> MT5Broker:
    broker = MT5Broker(login=1, password="x", server="test")
    broker._mt5 = fake
    broker._connected = True
    return broker


# ---------------------------------------------------------------------------
# get_account_info
# ---------------------------------------------------------------------------


def test_account_info_raises_instead_of_fabricating_zero():
    fake = _FakeMT5(account=None, last_error=(10004, "no connection"))
    broker = _broker_with(fake)
    with pytest.raises(BrokerReadError, match="no connection"):
        asyncio.run(broker.get_account_info())


def test_account_info_returns_real_values_when_available():
    fake = _FakeMT5(account=SimpleNamespace(
        balance=1000.0, equity=987.65, margin=10.0, margin_free=977.65,
        leverage=100, currency="USD", server="Exness-MT5Trial", login=12345,
    ))
    broker = _broker_with(fake)
    info = asyncio.run(broker.get_account_info())
    assert info.balance == 1000.0
    assert info.equity == 987.65
    assert info.login == 12345


# ---------------------------------------------------------------------------
# get_closed_trade
# ---------------------------------------------------------------------------


def test_get_closed_trade_none_when_no_history():
    fake = _FakeMT5(deals=None)
    broker = _broker_with(fake)
    result = asyncio.run(broker.get_closed_trade(2915834625, "USDCAD"))
    assert result is None


def test_get_closed_trade_none_when_no_out_deals():
    fake = _FakeMT5(deals=[
        SimpleNamespace(entry=_FakeMT5.DEAL_ENTRY_IN, price=1.42069,
                        volume=0.04, profit=0.0, swap=0.0, commission=0.0,
                        reason=_FakeMT5.DEAL_REASON_CLIENT, time=1_751_440_975),
    ])
    broker = _broker_with(fake)
    result = asyncio.run(broker.get_closed_trade(2915834625, "USDCAD"))
    assert result is None


def test_get_closed_trade_reproduces_real_usdcad_take_profit():
    """Ticket 2915834625, 2026-07-02: agent's USDCAD short. Broker history
    (the user's actual MT5 trade log) says Close=1.41963 == the TP level,
    Reason=Take Profit, P/L=+2.98 — NOT the -$0.87 loss the stale-tick
    fallback would have produced."""
    fake = _FakeMT5(deals=[
        SimpleNamespace(entry=_FakeMT5.DEAL_ENTRY_IN, price=1.42069,
                        volume=0.04, profit=0.0, swap=0.0, commission=0.0,
                        reason=_FakeMT5.DEAL_REASON_CLIENT, time=1_751_440_975),
        SimpleNamespace(entry=_FakeMT5.DEAL_ENTRY_OUT, price=1.41963,
                        volume=0.04, profit=2.98, swap=0.0, commission=0.0,
                        reason=_FakeMT5.DEAL_REASON_TP, time=1_751_445_006),
    ])
    broker = _broker_with(fake)
    result = asyncio.run(broker.get_closed_trade(2915834625, "USDCAD"))
    assert result is not None
    assert result.exit_price == pytest.approx(1.41963)
    assert result.profit == pytest.approx(2.98)
    assert result.reason == "tp"


def test_get_closed_trade_aggregates_partial_close_deals():
    """Two partial-close OUT deals must be volume-weighted for price and
    summed for profit, not just the last one taken in isolation."""
    fake = _FakeMT5(deals=[
        SimpleNamespace(entry=_FakeMT5.DEAL_ENTRY_IN, price=1.10000,
                        volume=0.10, profit=0.0, swap=0.0, commission=0.0,
                        reason=_FakeMT5.DEAL_REASON_CLIENT, time=1_000),
        SimpleNamespace(entry=_FakeMT5.DEAL_ENTRY_OUT, price=1.10500,
                        volume=0.05, profit=25.0, swap=0.0, commission=-1.0,
                        reason=_FakeMT5.DEAL_REASON_TP, time=1_100),
        SimpleNamespace(entry=_FakeMT5.DEAL_ENTRY_OUT, price=1.10700,
                        volume=0.05, profit=35.0, swap=-0.5, commission=-1.0,
                        reason=_FakeMT5.DEAL_REASON_TP, time=1_200),
    ])
    broker = _broker_with(fake)
    result = asyncio.run(broker.get_closed_trade(555, "EURUSD"))
    assert result is not None
    assert result.exit_price == pytest.approx((1.10500 * 0.05 + 1.10700 * 0.05) / 0.10)
    assert result.profit == pytest.approx(25.0 - 1.0 + 35.0 - 0.5 - 1.0)


@pytest.mark.parametrize("reason_attr,expected", [
    ("DEAL_REASON_SL", "sl"),
    ("DEAL_REASON_TP", "tp"),
    ("DEAL_REASON_SO", "stop_out"),
    ("DEAL_REASON_CLIENT", "manual"),
    ("DEAL_REASON_MOBILE", "manual"),
    ("DEAL_REASON_WEB", "manual"),
    ("DEAL_REASON_EXPERT", "expert"),
])
def test_get_closed_trade_maps_all_reason_codes(reason_attr, expected):
    fake = _FakeMT5(deals=[
        SimpleNamespace(entry=_FakeMT5.DEAL_ENTRY_OUT, price=1.0, volume=0.01,
                        profit=1.0, swap=0.0, commission=0.0,
                        reason=getattr(_FakeMT5, reason_attr), time=1_000),
    ])
    broker = _broker_with(fake)
    result = asyncio.run(broker.get_closed_trade(1, "EURUSD"))
    assert result.reason == expected


def test_get_closed_trade_swallows_broker_errors():
    """A broker exception (e.g. terminal disconnected mid-query) must not
    propagate — the monitor falls back to its own estimate instead."""
    class _Broken(_FakeMT5):
        def history_deals_get(self, position=None):
            raise RuntimeError("terminal not responding")

    broker = _broker_with(_Broken())
    result = asyncio.run(broker.get_closed_trade(1, "EURUSD"))
    assert result is None
