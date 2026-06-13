"""Structured, grep-friendly trade-lifecycle log lines for daily log files.

Every significant event gets a bracket tag prefix so operators can filter
with e.g. `grep '\\[TRADE OPENED\\]' GBPUSD_2026-06-12.log`.
"""
from __future__ import annotations

import logging


def log_signal_detected(
    log: logging.Logger,
    *,
    symbol: str,
    timeframe: str,
    alpha: str,
    direction: str,
    entry: float,
    soft_sl: float,
    tp: float,
    conviction: float,
) -> None:
    log.info(
        "[SIGNAL] %s %s %s %s entry=%.5f soft_sl=%.5f tp=%.5f conviction=%.2f",
        symbol, timeframe, alpha, direction.upper(), entry, soft_sl, tp, conviction,
    )


def log_order_rejected(
    log: logging.Logger,
    *,
    symbol: str,
    timeframe: str,
    alpha: str,
    message: str,
) -> None:
    log.warning("[ORDER REJECTED] %s %s %s — %s", symbol, timeframe, alpha, message)


def log_trade_opened(
    log: logging.Logger,
    *,
    symbol: str,
    timeframe: str,
    alpha: str,
    direction: str,
    ticket: int,
    entry: float,
    lots: float,
    soft_sl: float,
    catastrophe_sl: float,
    tp: float,
    risk_pct: float,
) -> None:
    log.info(
        "[TRADE OPENED] %s %s %s %s ticket=%d entry=%.5f lots=%.2f "
        "soft_sl=%.5f cat_sl=%.5f tp=%.5f risk=%.2f%%",
        symbol, timeframe, alpha, direction.upper(), ticket,
        entry, lots, soft_sl, catastrophe_sl, tp, risk_pct * 100,
    )


def log_near_miss(
    log: logging.Logger,
    *,
    symbol: str,
    timeframe: str,
    alpha: str,
    reason: str,
    detail: str = "",
) -> None:
    msg = f"[NEAR MISS] {symbol} {timeframe} {alpha} reason={reason}"
    if detail:
        msg = f"{msg} — {detail}"
    log.info(msg)


def log_trade_closed(
    log: logging.Logger,
    *,
    symbol: str,
    ticket: int,
    alpha: str,
    direction: str,
    exit_tag: str,
    exit_reason: str,
    pnl: float,
    pnl_pips: float,
    r_multiple: float,
    exit_price: float,
) -> None:
    log.info(
        "[%s] %s ticket=%d %s %s exit=%.5f pnl=%+.2f (%+.0fp, %+.2fR) cause=%s",
        exit_tag, symbol, ticket, alpha, direction.upper(),
        exit_price, pnl, pnl_pips, r_multiple, exit_reason,
    )


def log_soft_stop_fired(
    log: logging.Logger,
    *,
    symbol: str,
    ticket: int,
    detail: str,
) -> None:
    log.warning("[SOFT SL] %s ticket=%d — %s", symbol, ticket, detail)


def log_breakeven_moved(
    log: logging.Logger,
    *,
    symbol: str,
    ticket: int,
    old_sl: float,
    new_sl: float,
    r_multiple: float,
) -> None:
    log.info(
        "[BREAKEVEN] %s ticket=%d sl %.5f -> %.5f (at %.1fR)",
        symbol, ticket, old_sl, new_sl, r_multiple,
    )


def log_partial_scaleout(
    log: logging.Logger,
    *,
    symbol: str,
    ticket: int,
    closed_lots: float,
    total_lots: float,
    r_multiple: float,
) -> None:
    log.info(
        "[PARTIAL TP] %s ticket=%d closed %.2f of %.2f lots at %.2fR",
        symbol, ticket, closed_lots, total_lots, r_multiple,
    )


def classify_exit_tag(exit_reason: str, pnl: float) -> str:
    """Map internal exit_reason to a log tag."""
    if exit_reason in ("soft_sl_close", "soft_sl_panic"):
        return "SOFT SL"
    if exit_reason == "tp":
        return "TP HIT"
    if exit_reason == "catastrophe_sl":
        return "CATASTROPHE SL"
    if exit_reason == "sl":
        return "CATASTROPHE SL"
    if pnl > 0:
        return "TRADE CLOSED"
    if pnl < 0:
        return "TRADE CLOSED"
    return "TRADE CLOSED"
