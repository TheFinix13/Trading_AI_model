"""Structured trade-lifecycle log tags."""
from __future__ import annotations

import logging

from agent.live.trade_events import (
    classify_exit_tag,
    log_adopted_breach,
    log_ladder,
    log_ladder_unknown,
    log_order_rejected,
    log_position_adopted,
    log_position_restored,
    log_signal_detected,
    log_soft_stop_armed,
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


def test_trade_opened_includes_pip_distances_and_tp_rr(caplog):
    """50p soft stop, 100p catastrophe, 75p TP — TP must report 1.5R."""
    log = logging.getLogger("test.trade.distances")
    with caplog.at_level(logging.INFO, logger="test.trade.distances"):
        log_trade_opened(
            log, symbol="EURUSD", timeframe="H4", alpha="zone_h4_all",
            direction="long", ticket=42, entry=1.15151, lots=0.05,
            soft_sl=1.14651, catastrophe_sl=1.14151, tp=1.15901,
            risk_pct=0.01,
        )
    msg = caplog.records[0].message
    assert "soft_sl=1.14651 (50p)" in msg
    assert "catastrophe_sl=1.14151 (100p)" in msg
    assert "tp_mech=1.15901 (1.5R, +75p)" in msg
    assert "risk=1.00%" in msg


def test_trade_opened_short_direction_pip_distances(caplog):
    """Short side — pip distances must still come out positive."""
    log = logging.getLogger("test.trade.short")
    with caplog.at_level(logging.INFO, logger="test.trade.short"):
        log_trade_opened(
            log, symbol="USDCAD", timeframe="H4", alpha="zone_h4_all",
            direction="short", ticket=77, entry=1.39715, lots=0.03,
            soft_sl=1.39915, catastrophe_sl=1.40215, tp=1.39415,
            risk_pct=0.005,
        )
    msg = caplog.records[0].message
    assert msg.startswith("[TRADE OPENED]")
    assert "SHORT" in msg
    assert "soft_sl=1.39915 (20p)" in msg
    assert "catastrophe_sl=1.40215 (50p)" in msg
    assert "tp_mech=1.39415 (1.5R, +30p)" in msg


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
    assert classify_exit_tag("sl", -20.0) == "CATASTROPHE SL"
    assert classify_exit_tag("stop_out", -50.0) == "MARGIN STOP-OUT"
    assert classify_exit_tag("expert", 3.0) == "EA/EXPERT CLOSE"
    # "manual" is the honest fallback for an unresolved close cause — it
    # must NOT read as a stop-loss just because pnl happens to be negative
    # (that mislabeled a real +$2.98 take-profit as "CATASTROPHE SL" on
    # 2026-07-02; see agent/live/monitor.py::_handle_close).
    assert classify_exit_tag("manual", 0.0) == "CLOSED (cause unconfirmed)"
    assert classify_exit_tag("manual", -3.0) == "CLOSED (cause unconfirmed)"
    assert classify_exit_tag("unknown", 2.0) == "CLOSED (cause unconfirmed)"


def test_signal_detected_before_order(caplog):
    log = logging.getLogger("test.trade")
    with caplog.at_level(logging.INFO, logger="test.trade"):
        log_signal_detected(
            log, symbol="GBPUSD", timeframe="H4", alpha="zone_h4_all",
            direction="long", entry=1.34, soft_sl=1.33, tp=1.35, conviction=0.8,
        )
    assert caplog.records[0].message.startswith("[SIGNAL]")


def test_signal_log_line_includes_htf_meta(caplog):
    """When the alpha attached HTF gate metadata, the [SIGNAL] line must
    surface it so an operator can grep ``htf_bias=`` without opening the
    JSON vault."""
    log = logging.getLogger("test.trade.htf")
    with caplog.at_level(logging.INFO, logger="test.trade.htf"):
        log_signal_detected(
            log, symbol="USDCAD", timeframe="H4", alpha="zone_h4_all",
            direction="short", entry=1.39824, soft_sl=1.40223, tp=1.39225,
            conviction=0.65,
            meta={"htf_bias": "up", "htf_align": "D1",
                  "htf_align_mode": "against",
                  "htf_lookback": 10, "htf_min_move_pips": 60.0},
        )
    msg = caplog.records[0].message
    assert msg.startswith("[SIGNAL]")
    assert "htf_bias=up" in msg
    assert "htf=D1(against)" in msg


def test_signal_log_line_omits_meta_suffix_when_empty(caplog):
    """An alpha without an HTF gate (meta={}/None) keeps the legacy line
    shape — no trailing whitespace, no orphan ``htf_=?`` fragments."""
    log = logging.getLogger("test.trade.no_htf")
    with caplog.at_level(logging.INFO, logger="test.trade.no_htf"):
        log_signal_detected(
            log, symbol="EURUSD", timeframe="H4", alpha="zone_h4_all",
            direction="long", entry=1.10, soft_sl=1.0950, tp=1.1100,
            conviction=0.65, meta=None,
        )
        log_signal_detected(
            log, symbol="EURUSD", timeframe="H4", alpha="zone_h4_all",
            direction="long", entry=1.10, soft_sl=1.0950, tp=1.1100,
            conviction=0.65, meta={},
        )
    for rec in caplog.records:
        assert rec.message.startswith("[SIGNAL]")
        assert "htf" not in rec.message
        assert not rec.message.endswith(" ")


def test_log_ladder_renders_each_rung_with_pips_and_r(caplog):
    log = logging.getLogger("test.ladder.full")
    rungs = [
        {"source": "swing", "price": 1.16000, "r_multiple": 2.0,
         "detail": "swing high"},
        {"source": "zone_edge", "price": 1.16500, "r_multiple": 3.0},
        {"source": "fib_ext", "price": 1.17500, "r_multiple": 5.0},
    ]
    with caplog.at_level(logging.INFO, logger="test.ladder.full"):
        log_ladder(log, symbol="EURUSD", ticket=42, rungs=rungs, entry=1.15000)
    msg = caplog.records[0].message
    assert msg.startswith("[LADDER]")
    assert "EURUSD" in msg
    assert "ticket=42" in msg
    assert "n=3" in msg
    assert "swing=1.16000(100p,2.0R)" in msg
    assert "zone_edge=1.16500(150p,3.0R)" in msg
    assert "fib_ext=1.17500(250p,5.0R)" in msg


def test_log_ladder_uses_journaled_distance_pips_when_present(caplog):
    """Close-phase rungs carry ``distance_pips`` from score_rungs — reuse them."""
    log = logging.getLogger("test.ladder.scored")
    rungs = [
        {"source": "swing", "price": 1.16000, "r_multiple": 2.0,
         "distance_pips": 100.0, "reached": True},
    ]
    with caplog.at_level(logging.INFO, logger="test.ladder.scored"):
        log_ladder(log, symbol="EURUSD", ticket=7, rungs=rungs, entry=None)
    assert "swing=1.16000(100p,2.0R)" in caplog.records[0].message


def test_log_ladder_zero_rungs_is_explicit(caplog):
    log = logging.getLogger("test.ladder.empty")
    with caplog.at_level(logging.INFO, logger="test.ladder.empty"):
        log_ladder(log, symbol="EURUSD", ticket=8, rungs=[], entry=1.15)
    msg = caplog.records[0].message
    assert "[LADDER]" in msg
    assert "ticket=8" in msg
    assert "n=0" in msg
    assert "no structural rungs" in msg


def test_log_ladder_skips_malformed_rungs(caplog):
    """Bad rung dicts must be silently dropped — never raise."""
    log = logging.getLogger("test.ladder.malformed")
    rungs = [
        {"source": "swing", "price": 1.16000, "r_multiple": 2.0},
        {"source": "broken"},                  # missing price/r
        "not even a dict",
        {"source": "zone_edge", "price": "oops", "r_multiple": 3.0},
    ]
    with caplog.at_level(logging.INFO, logger="test.ladder.malformed"):
        log_ladder(log, symbol="EURUSD", ticket=9, rungs=rungs, entry=1.15)
    msg = caplog.records[0].message
    assert "n=1" in msg
    assert "swing=1.16000" in msg
    assert "broken" not in msg
    assert "oops" not in msg


def test_log_ladder_unknown_for_adopted(caplog):
    log = logging.getLogger("test.ladder.unknown")
    with caplog.at_level(logging.INFO, logger="test.ladder.unknown"):
        log_ladder_unknown(log, symbol="USDCAD", ticket=2842973741)
    msg = caplog.records[0].message
    assert msg.startswith("[LADDER]")
    assert "ticket=2842973741" in msg
    assert "status=unknown" in msg
    assert "(adopted)" in msg


def test_position_adopted_includes_soft_sl_unknown(caplog):
    """Adopted tickets pre-date entry_ctx — the soft SL must read 'unknown'."""
    log = logging.getLogger("test.adopted")
    with caplog.at_level(logging.INFO, logger="test.adopted"):
        log_position_adopted(
            log, symbol="USDCAD", ticket=2842973741, direction="short",
            lots=0.01, entry=1.39715, broker_sl=1.40215, tp=1.39415,
            profit=-4.74,
        )
    msg = caplog.records[0].message
    assert msg.startswith("[POSITION ADOPTED]")
    assert "USDCAD" in msg
    assert "ticket=2842973741" in msg
    assert "SHORT" in msg
    assert "entry=1.39715" in msg
    assert "broker_sl=1.40215 (50p)" in msg
    assert "tp=1.39415 (30p)" in msg
    assert "soft_sl=unknown (adopted)" in msg
    assert "profit=-4.74" in msg
    assert "(opened before this process started)" in msg


def test_position_adopted_handles_missing_sl_and_tp(caplog):
    log = logging.getLogger("test.adopted.bare")
    with caplog.at_level(logging.INFO, logger="test.adopted.bare"):
        log_position_adopted(
            log, symbol="EURUSD", ticket=1, direction="long",
            lots=0.10, entry=1.15151, broker_sl=0.0, tp=0.0, profit=0.0,
        )
    msg = caplog.records[0].message
    assert "broker_sl=none" in msg
    assert "tp=none" in msg
    assert "soft_sl=unknown (adopted)" in msg


def test_position_restored_known_soft_stop(caplog):
    log = logging.getLogger("test.restored.known")
    with caplog.at_level(logging.INFO, logger="test.restored.known"):
        log_position_restored(
            log, symbol="GBPUSD", ticket=2843893443, direction="long",
            entry=1.33980, soft_sl=1.33480, broker_sl=1.32980,
            tp=1.34730, be_applied=False,
        )
    msg = caplog.records[0].message
    assert msg.startswith("[POSITION RESTORED]")
    assert "ticket=2843893443" in msg
    assert "LONG" in msg
    assert "soft_sl=1.33480 (50p)" in msg
    assert "broker_sl=1.32980 (100p)" in msg
    assert "tp_mech=1.34730 (1.5R, +75p)" in msg
    assert "be_applied=False" in msg


def test_position_adopted_with_inferred_soft_sl(caplog):
    """Inferred soft SL must read ``(Np, inferred)`` — different from the
    ``unknown (adopted)`` fallback so an operator can tell them apart at a
    glance in the daily log."""
    log = logging.getLogger("test.adopted.inferred")
    with caplog.at_level(logging.INFO, logger="test.adopted.inferred"):
        log_position_adopted(
            log, symbol="USDCAD", ticket=2842973741, direction="short",
            lots=0.01, entry=1.39715, broker_sl=1.40215, tp=1.39415,
            profit=-4.74, soft_sl=1.39915,
        )
    msg = caplog.records[0].message
    assert "[POSITION ADOPTED]" in msg
    assert "soft_sl=1.39915 (20p, inferred)" in msg
    assert "broker_sl=1.40215 (50p)" in msg


def test_soft_stop_armed_log_line(caplog):
    log = logging.getLogger("test.softarm")
    with caplog.at_level(logging.INFO, logger="test.softarm"):
        log_soft_stop_armed(log, symbol="USDCAD", ticket=1,
                            soft_sl=1.39915, source="inferred")
    msg = caplog.records[0].message
    assert msg.startswith("[SOFT SL ARMED]")
    assert "ticket=1" in msg
    assert "soft_sl=1.39915" in msg
    assert "source=inferred" in msg


def test_adopted_breach_warning(caplog):
    log = logging.getLogger("test.breach")
    with caplog.at_level(logging.WARNING, logger="test.breach"):
        log_adopted_breach(log, symbol="USDCAD", ticket=1,
                           current_price=1.39936, soft_sl=1.39915)
    msg = caplog.records[0].message
    assert msg.startswith("[ADOPTED — SOFT SL ALREADY BREACHED]")
    assert "price=1.39936" in msg
    assert "soft_sl=1.39915" in msg


def test_classify_exit_tag_inferred_overshoot():
    """The new soft-SL inferred overshoot cause must classify as SOFT SL."""
    assert classify_exit_tag("soft_sl_inferred_overshoot", -3.0) == "SOFT SL"


def test_position_restored_with_unknown_soft_sl(caplog):
    """A restored ticket whose ctx never carried a soft_stop must say so."""
    log = logging.getLogger("test.restored.unknown")
    with caplog.at_level(logging.INFO, logger="test.restored.unknown"):
        log_position_restored(
            log, symbol="USDCAD", ticket=1, direction="short",
            entry=1.39715, soft_sl=None, broker_sl=1.40215, tp=1.39415,
            be_applied=False,
        )
    msg = caplog.records[0].message
    assert "soft_sl=unknown" in msg
    assert "broker_sl=1.40215" in msg
    assert "tp_mech=1.39415" in msg
