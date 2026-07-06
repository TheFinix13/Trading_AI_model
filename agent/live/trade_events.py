"""Structured, grep-friendly trade-lifecycle log lines for daily log files.

Every significant event gets a bracket tag prefix so operators can filter
with e.g. `grep '\\[TRADE OPENED\\]' GBPUSD_2026-06-12.log`.

Layout contract: ONE line per event, ``key=value`` pairs separated by single
spaces. Per-event totals or modifiers ride inside parentheses immediately
after the price they describe (e.g. ``soft_sl=1.14661 (49p)``) so a grep on
``soft_sl=`` still pulls a clean field. The ``[LADDER]`` line mirrors what is
journaled to ``ladders/events.jsonl`` so a log tail and the JSONL stay in
lockstep.
"""
from __future__ import annotations

import logging
from typing import Sequence

PIP = 0.0001


def _pips(distance_price: float) -> float:
    """Convert a positive price distance to pips (1 pip = 0.0001)."""
    return abs(distance_price) / PIP


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
    meta: dict | None = None,
) -> None:
    """Log a freshly fired alpha signal.

    ``meta`` is the optional decision-time metadata bag the alpha attaches
    (currently the HTF gate inputs: ``htf_bias``, ``htf_align``,
    ``htf_align_mode``). When present, it is rendered as a compact suffix
    so a grep on ``[SIGNAL]`` shows why the gate let the trade through.
    """
    suffix = _format_signal_meta(meta)
    log.info(
        "[SIGNAL] %s %s %s %s entry=%.5f soft_sl=%.5f tp=%.5f conviction=%.2f%s",
        symbol, timeframe, alpha, direction.upper(),
        entry, soft_sl, tp, conviction, suffix,
    )


def _format_signal_meta(meta: dict | None) -> str:
    """Render the optional HTF/decision metadata as a single-space suffix.

    Returns the empty string when ``meta`` is falsy or carries no
    recognised keys. Unknown keys are silently ignored so adding new gate
    inputs upstream never breaks the daily-log contract.
    """
    if not meta:
        return ""
    parts: list[str] = []
    bias = meta.get("htf_bias")
    align = meta.get("htf_align")
    mode = meta.get("htf_align_mode")
    if bias:
        parts.append(f"htf_bias={bias}")
    if align or mode:
        parts.append(f"htf={align or '?'}({mode or '?'})")
    return (" " + " ".join(parts)) if parts else ""


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
    """Log a freshly filled order with pip distances + TP R-multiple.

    Output (single line):
        [TRADE OPENED] SYM TF ALPHA DIR ticket=N entry=P lots=L
            soft_sl=P (Np) catastrophe_sl=P (Np) tp_mech=P (X.XR, +Np)
            risk=X.XX%

    The soft SL is the agent-managed real risk; the catastrophe SL is the
    wide broker backstop. ``tp_mech`` is the validated mechanical TP at
    ``target_rr × stop`` — the structural ladder (if any) is emitted on a
    separate ``[LADDER]`` line.
    """
    soft_pips = _pips(entry - soft_sl)
    cata_pips = _pips(entry - catastrophe_sl)
    tp_pips = _pips(tp - entry)
    stop_pips = _pips(entry - soft_sl)
    tp_rr = (tp_pips / stop_pips) if stop_pips > 0 else 0.0
    log.info(
        "[TRADE OPENED] %s %s %s %s ticket=%d entry=%.5f lots=%.2f "
        "soft_sl=%.5f (%.0fp) catastrophe_sl=%.5f (%.0fp) "
        "tp_mech=%.5f (%.1fR, +%.0fp) risk=%.2f%%",
        symbol, timeframe, alpha, direction.upper(), ticket,
        entry, lots, soft_sl, soft_pips, catastrophe_sl, cata_pips,
        tp, tp_rr, tp_pips, risk_pct * 100,
    )


def log_position_adopted(
    log: logging.Logger,
    *,
    symbol: str,
    ticket: int,
    direction: str,
    lots: float,
    entry: float,
    broker_sl: float,
    tp: float,
    profit: float,
    soft_sl: float | None = None,
) -> None:
    """Log a broker-side position the agent inherited at startup.

    Adopted tickets pre-date the current process so the agent has no
    ``entry_ctx`` of its own. When ``soft_sl`` is supplied (the monitor
    successfully inferred one from the broker SL), the line shows it tagged
    ``inferred`` so it can't be mistaken for an agent-sized trade; when it
    isn't, the line stays honest with ``soft_sl=unknown (adopted)``. The
    catastrophe (broker) stop is the only stop on the broker side either way.
    """
    if broker_sl > 0:
        sl_part = f"broker_sl={broker_sl:.5f} ({_pips(entry - broker_sl):.0f}p)"
    else:
        sl_part = "broker_sl=none"
    if tp > 0:
        tp_part = f"tp={tp:.5f} ({_pips(tp - entry):.0f}p)"
    else:
        tp_part = "tp=none"
    if soft_sl is not None and soft_sl > 0:
        soft_part = (f"soft_sl={soft_sl:.5f} "
                     f"({_pips(entry - soft_sl):.0f}p, inferred)")
    else:
        soft_part = "soft_sl=unknown (adopted)"
    log.info(
        "[POSITION ADOPTED] %s ticket=%d %s %.2f lots entry=%.5f %s %s "
        "%s profit=%+.2f (opened before this process started)",
        symbol, ticket, direction.upper(), lots, entry,
        sl_part, tp_part, soft_part, profit,
    )


def log_soft_stop_armed(
    log: logging.Logger,
    *,
    symbol: str,
    ticket: int,
    soft_sl: float,
    source: str = "inferred",
) -> None:
    """Announce that an agent-managed soft stop is now armed on a ticket.

    Emitted once on adoption when inference produces a soft level. Makes the
    in-the-moment behaviour obvious in a ``tail -f`` so the operator can see
    that the soft-stop / breakeven / trailing layer is back online.
    """
    log.info("[SOFT SL ARMED] %s ticket=%d soft_sl=%.5f source=%s",
             symbol, ticket, soft_sl, source)


def log_adopted_breach(
    log: logging.Logger,
    *,
    symbol: str,
    ticket: int,
    current_price: float,
    soft_sl: float,
) -> None:
    """Warn when an adopted ticket's price is already past the inferred soft
    stop at startup — the next monitor tick will close it as overshoot."""
    log.warning(
        "[ADOPTED — SOFT SL ALREADY BREACHED] %s ticket=%d price=%.5f "
        "past inferred soft_sl=%.5f — will close on next monitor tick",
        symbol, ticket, current_price, soft_sl,
    )


def log_position_restored(
    log: logging.Logger,
    *,
    symbol: str,
    ticket: int,
    direction: str,
    entry: float,
    soft_sl: float | None,
    broker_sl: float | None,
    tp: float | None,
    be_applied: bool,
) -> None:
    """Log a ticket restored from the persisted state sidecar.

    Mirrors the ``[TRADE OPENED]`` field layout so the daily log shows the
    full risk picture for a ticket that survived a restart. Any unknown
    field is emitted as ``X=unknown`` rather than skipped.
    """
    if soft_sl is not None and soft_sl > 0:
        soft_part = f"soft_sl={soft_sl:.5f} ({_pips(entry - soft_sl):.0f}p)"
        stop_pips = _pips(entry - soft_sl)
    else:
        soft_part = "soft_sl=unknown"
        stop_pips = 0.0
    if broker_sl is not None and broker_sl > 0:
        broker_part = f"broker_sl={broker_sl:.5f} ({_pips(entry - broker_sl):.0f}p)"
    else:
        broker_part = "broker_sl=unknown"
    if tp is not None and tp > 0:
        tp_pips = _pips(tp - entry)
        if stop_pips > 0:
            tp_rr = tp_pips / stop_pips
            tp_part = f"tp_mech={tp:.5f} ({tp_rr:.1f}R, +{tp_pips:.0f}p)"
        else:
            tp_part = f"tp_mech={tp:.5f} (+{tp_pips:.0f}p)"
    else:
        tp_part = "tp_mech=unknown"
    log.info(
        "[POSITION RESTORED] %s ticket=%d %s entry=%.5f %s %s %s be_applied=%s",
        symbol, ticket, direction.upper(), entry,
        soft_part, broker_part, tp_part, be_applied,
    )


def log_ladder(
    log: logging.Logger,
    *,
    symbol: str,
    ticket: int,
    rungs: Sequence[dict],
    entry: float | None = None,
) -> None:
    """Mirror the journaled extension ladder onto the daily log.

    ``rungs`` is the exact dict list ``compute_target_ladder`` produced (and
    that lives in ``entry_ctx['target_ladder']`` / ``ladders/events.jsonl``)
    — this function never recomputes. ``entry`` is optional; when supplied it
    backstops rungs that lack a pre-baked ``distance_pips`` field. A rung
    whose source repeats in the list is emitted under the same key (grep
    ``swing=`` will still pull every swing rung).
    """
    parts: list[str] = []
    for r in rungs or []:
        if not isinstance(r, dict):
            continue
        try:
            source = str(r["source"])
            price = float(r["price"])
            r_mult = float(r["r_multiple"])
        except (KeyError, TypeError, ValueError):
            continue
        distance_pips: float | None = None
        if "distance_pips" in r:
            try:
                distance_pips = float(r["distance_pips"])
            except (TypeError, ValueError):
                distance_pips = None
        if distance_pips is None and entry is not None:
            distance_pips = abs(price - float(entry)) / PIP
        if distance_pips is None:
            parts.append(f"{source}={price:.5f}({r_mult:.1f}R)")
        else:
            parts.append(
                f"{source}={price:.5f}({distance_pips:.0f}p,{r_mult:.1f}R)"
            )
    if parts:
        log.info("[LADDER] %s ticket=%d n=%d %s",
                 symbol, ticket, len(parts), " ".join(parts))
    else:
        log.info("[LADDER] %s ticket=%d n=0 (no structural rungs beyond TP)",
                 symbol, ticket)


def log_ladder_unknown(
    log: logging.Logger,
    *,
    symbol: str,
    ticket: int,
    reason: str = "adopted",
) -> None:
    """Emit a ``status=unknown`` ladder line for tickets we did not size at
    fill time (typically adopted broker positions with no ``entry_ctx``)."""
    log.info("[LADDER] %s ticket=%d status=unknown (%s)", symbol, ticket, reason)


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
    """Map internal exit_reason to a log tag.

    "sl"/"catastrophe_sl" here mean a CONFIRMED broker-side stop fill —
    either read back from MT5's own trade history (authoritative) or
    matched by price proximity to a known level. "manual" is the honest
    fallback for a close the monitor could neither attribute to a broker
    history record nor a known price level — it must NOT be dressed up as
    a stop-loss just because the last-seen P&L happened to be negative
    (that mislabeled a real +$2.98 take-profit as a "CATASTROPHE SL" loss
    on 2026-07-02; see agent/live/monitor.py::_handle_close).
    """
    if exit_reason in ("soft_sl_close", "soft_sl_panic"):
        return "SOFT SL"
    if exit_reason == "soft_sl_inferred_overshoot":
        return "SOFT SL"
    if exit_reason == "tp":
        return "TP HIT"
    if exit_reason == "catastrophe_sl":
        return "CATASTROPHE SL"
    if exit_reason == "sl":
        return "CATASTROPHE SL"
    if exit_reason == "stop_out":
        return "MARGIN STOP-OUT"
    if exit_reason == "expert":
        return "EA/EXPERT CLOSE"
    if exit_reason in ("manual", "unknown"):
        return "CLOSED (cause unconfirmed)"
    if pnl > 0:
        return "TRADE CLOSED"
    if pnl < 0:
        return "TRADE CLOSED"
    return "TRADE CLOSED"
