"""Mandatory SL/TP enforcement — naked orders must be impossible."""
import asyncio

from agent.live.broker import BrokerConnection, PaperBroker
from agent.types import Direction


def test_validate_rejects_missing_sltp():
    ok, reason = BrokerConnection.validate_sltp(Direction.LONG, 0.0, 0.0)
    assert not ok
    ok, reason = BrokerConnection.validate_sltp(Direction.LONG, None, None)
    assert not ok


def test_validate_rejects_inverted_sltp():
    # Long needs SL below TP.
    ok, _ = BrokerConnection.validate_sltp(Direction.LONG, 1.20, 1.10)
    assert not ok
    # Short needs SL above TP.
    ok, _ = BrokerConnection.validate_sltp(Direction.SHORT, 1.10, 1.20)
    assert not ok


def test_validate_accepts_proper_bracket():
    ok, _ = BrokerConnection.validate_sltp(Direction.LONG, 1.10, 1.20, ref_price=1.15)
    assert ok
    ok, _ = BrokerConnection.validate_sltp(Direction.SHORT, 1.20, 1.10, ref_price=1.15)
    assert ok


def test_validate_rejects_when_price_not_bracketed():
    # Long SL/TP both below current price (price not inside the bracket).
    ok, _ = BrokerConnection.validate_sltp(Direction.LONG, 1.05, 1.08, ref_price=1.15)
    assert not ok


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_paper_broker_refuses_naked_order():
    broker = PaperBroker(initial_balance=1000.0)
    _run(broker.connect())
    # Seed a price so the broker has a bid/ask.
    broker._last_prices["EURUSD"] = (1.1500, 1.1502)
    # Naked order (no SL/TP) must be refused.
    res = _run(broker.place_order("EURUSD", Direction.LONG, 0.10, stop=0.0, tp=0.0))
    assert not res.success
    assert "SL/TP guard" in res.message
    # A properly bracketed order goes through.
    res2 = _run(broker.place_order("EURUSD", Direction.LONG, 0.10, stop=1.1450, tp=1.1600))
    assert res2.success
