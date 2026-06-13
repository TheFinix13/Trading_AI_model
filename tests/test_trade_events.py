"""Structured trade-lifecycle log tags."""
from __future__ import annotations

import logging

from agent.live.trade_events import (
    classify_exit_tag,
    log_order_rejected,
    log_signal_detected,
    log_trade_closed,
    log_trade_opened,
)


def test_trade_opened_log_line(caplog):
    log = logging.getLogger("test.trade")
    with caplog.at_level(logging.INFO, logger="test.trade"):
        log_trade_opened(
            log, symbol="GBPUSD", timeframe="H4", alpha="zone_h4_all",
            direction="long", ticket=12345, entry=1.33900, lots=0.04,
            soft_sl=1.33400, catastrophe_sl=1.32900, tp=1.34650,
            risk_pct=0.01,
        )
    assert len(caplog.records) == 1
    msg = caplog.records[0].message
    assert msg.startswith("[TRADE OPENED]")
    assert "GBPUSD" in msg
    assert "ticket=12345" in msg
    assert "lots=0.04" in msg


def test_order_rejected_log_line(caplog):
    log = logging.getLogger("test.trade")
    with caplog.at_level(logging.WARNING, logger="test.trade"):
        log_order_rejected(log, symbol="EURUSD", timeframe="H4",
                           alpha="zone_h4_all",
                           message="retcode=10027 AutoTrading disabled")
    assert caplog.records[0].message.startswith("[ORDER REJECTED]")
    assert "10027" in caplog.records[0].message


def test_trade_closed_tp_tag(caplog):
    log = logging.getLogger("test.trade")
    with caplog.at_level(logging.INFO, logger="test.trade"):
        log_trade_closed(
            log, symbol="USDCAD", ticket=99, alpha="zone_h4_all",
            direction="short", exit_tag="TP HIT", exit_reason="tp",
            pnl=12.5, pnl_pips=18.0, r_multiple=1.5, exit_price=1.36500,
        )
    assert "[TP HIT]" in caplog.records[0].message
    assert "pnl=+12.50" in caplog.records[0].message


def test_classify_exit_tags():
    assert classify_exit_tag("soft_sl_close", -5.0) == "SOFT SL"
    assert classify_exit_tag("tp", 10.0) == "TP HIT"
    assert classify_exit_tag("catastrophe_sl", -20.0) == "CATASTROPHE SL"
    assert classify_exit_tag("manual", 0.0) == "TRADE CLOSED"


def test_signal_detected_before_order(caplog):
    log = logging.getLogger("test.trade")
    with caplog.at_level(logging.INFO, logger="test.trade"):
        log_signal_detected(
            log, symbol="GBPUSD", timeframe="H4", alpha="zone_h4_all",
            direction="long", entry=1.34, soft_sl=1.33, tp=1.35, conviction=0.8,
        )
    assert caplog.records[0].message.startswith("[SIGNAL]")
