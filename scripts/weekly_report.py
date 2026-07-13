"""ONE-COMMAND weekly review bundle across every deployed symbol.

Run this ON THE VM once a week and send the single zip it produces:

    python scripts/weekly_report.py --days 7

It replaces hand-collecting per-symbol logs, events.jsonl files, near-miss
charts, loss records and ladder records. The zip
(``weekly_report_<start>_to_<end>.zip``) contains:

* ``REPORT.md`` — self-contained markdown: executive summary, one section
  per symbol (trade table, signal/rejection breakdown, near-miss vault
  metadata, H4 coverage, downtime windows, balance curve), a cross-symbol
  account section (merged balance/equity timeline, external/manual equity
  moves, agent-vs-external P&L split, kill-switch cascades), the active
  parameter snapshot per symbol, and an auto-flagged review checklist.
* The raw daily ``.log`` files for the window, per symbol.
* The window's near-miss / loss / ladder JSONL records AND matching chart
  PNGs, per symbol (filtered by date — never the whole vault history).
* ``state.json`` and any ``kill.txt`` found, per symbol.

Usage:
    python scripts/weekly_report.py                      # last 7 days, all symbols
    python scripts/weekly_report.py --days 14
    python scripts/weekly_report.py --start 2026-07-01 --end 2026-07-07
    python scripts/weekly_report.py --symbols EURUSD,GBPUSD
    python scripts/weekly_report.py --log-root D:\\TradingAgentLogs --out weekly.zip

Everything here is OBSERVATION-ONLY: it reads files and writes one zip.
Nothing it does can affect trading behaviour. Missing days / symbols /
vault folders degrade to a "MISSING" note in the report, never a crash.

``scripts/compile_review_bundle.py`` remains for ad-hoc single-symbol
deep-dives; this script is the weekly entry point.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daily_summary import (  # noqa: E402
    DEFAULT_SYMBOLS,
    RE_HEARTBEAT,
    RE_H4_NO_SETUP,
    RE_NEAR_MISS,
    RE_ORDER_REJECTED,
    RE_SIGNAL,
    RE_TRADE_OPENED,
    _iter_jsonl,
    _log_path,
    _read_state,
    _resolve_days,
    _vault_dir,
)
from compile_review_bundle import (  # noqa: E402
    SymbolEvents,
    _parse_line_ts,
    scan_downtime_and_incidents,
)

from agent.journal.vault import DEFAULT_VAULT_ROOT  # noqa: E402

VAULT_SUBDIRS = ("near_misses", "losses", "ladders")

# Every close tag classify_exit_tag() can emit (daily_summary's close regex
# only knows four of them; MARGIN STOP-OUT etc. must not vanish here).
RE_TRADE_CLOSED_FULL = re.compile(
    r"\[(?P<tag>TP HIT|SOFT SL|CATASTROPHE SL|MARGIN STOP-OUT|"
    r"EA/EXPERT CLOSE|CLOSED \(cause unconfirmed\)|TRADE CLOSED)\] "
    r"(?P<sym>\S+) ticket=(?P<ticket>\d+) (?P<alpha>\S+) (?P<dir>LONG|SHORT) "
    r"exit=(?P<exit>[\d.]+) pnl=(?P<pnl>[+-]?[\d.]+) "
    r"\((?P<pips>[+-]?\d+)p, (?P<r>[+-]?[\d.]+)R\) cause=(?P<cause>\S+)"
)


# ---------------------------------------------------------------------------
# Per-symbol structured week
# ---------------------------------------------------------------------------
@dataclass
class TradeRow:
    ticket: str
    direction: str = "?"
    lots: float | None = None
    entry: float | None = None
    exit: float | None = None
    soft_sl: float | None = None
    catastrophe_sl: float | None = None
    tp: float | None = None
    risk_pct: float | None = None
    pnl: float | None = None
    pips: float | None = None
    r: float | None = None
    exit_tag: str | None = None
    cause: str | None = None
    opened_ts: datetime | None = None
    closed_ts: datetime | None = None


@dataclass
class SymbolWeek:
    symbol: str
    log_files: list[Path] = field(default_factory=list)
    missing_days: list[date] = field(default_factory=list)
    trades: dict[str, TradeRow] = field(default_factory=dict)
    signals: list[dict] = field(default_factory=list)
    near_misses: list[dict] = field(default_factory=list)      # log lines
    order_rejects: list[dict] = field(default_factory=list)
    heartbeats: list[dict] = field(default_factory=list)
    h4_no_setup: int = 0
    events: SymbolEvents | None = None
    state: dict | None = None
    kill_txt: str | None = None
    vault_dir: Path | None = None
    vault_near_misses: list[dict] = field(default_factory=list)  # jsonl records

    @property
    def closed_rows(self) -> list[TradeRow]:
        return [t for t in self.trades.values() if t.pnl is not None]

    @property
    def closed_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_rows)

    @property
    def rejection_breakdown(self) -> Counter:
        """Rejection reasons: near-miss buckets (risk_manager split into
        max_positions when the detail says so) + broker rejects."""
        c: Counter = Counter()
        for nm in self.near_misses:
            reason = nm["reason"]
            detail = (nm.get("detail") or "").lower()
            if reason == "risk_manager" and "max_positions" in detail:
                reason = "max_positions"
            c[reason] += 1
        if self.order_rejects:
            c["broker_reject_line"] += len(self.order_rejects)
        return c


def parse_symbol_week(symbol: str, root: Path, days: list[date]) -> SymbolWeek:
    """Walk the symbol's daily logs + vault for the window. Never raises on
    missing files — absent evidence becomes MISSING notes downstream."""
    wk = SymbolWeek(symbol=symbol)
    wk.vault_dir = _vault_dir(root, symbol)
    if wk.vault_dir is not None:
        wk.state = _read_state(wk.vault_dir)
        kill_path = wk.vault_dir / "kill.txt"
        if kill_path.exists():
            try:
                wk.kill_txt = kill_path.read_text(
                    encoding="utf-8", errors="replace").strip()
            except OSError:
                wk.kill_txt = "(kill.txt present but unreadable)"

    for day in days:
        lp = _log_path(root, symbol, day)
        if lp is None:
            wk.missing_days.append(day)
        else:
            wk.log_files.append(lp)
            _parse_log(lp, wk)

    if wk.log_files:
        wk.events = scan_downtime_and_incidents(wk.log_files)

    if wk.vault_dir is not None:
        day_strs = {d.isoformat() for d in days}
        for rec in _iter_jsonl(wk.vault_dir / "near_misses" / "events.jsonl"):
            if str(rec.get("ts", ""))[:10] in day_strs:
                wk.vault_near_misses.append(rec)
    return wk


def _parse_log(path: Path, wk: SymbolWeek) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for raw in lines:
        ts = _parse_line_ts(raw)

        m = RE_TRADE_OPENED.search(raw)
        if m:
            row = wk.trades.setdefault(m.group("ticket"),
                                       TradeRow(ticket=m.group("ticket")))
            row.direction = m.group("dir")
            row.lots = float(m.group("lots"))
            row.entry = float(m.group("entry"))
            row.soft_sl = float(m.group("soft"))
            row.catastrophe_sl = float(m.group("cata"))
            row.tp = float(m.group("tp"))
            row.risk_pct = float(m.group("risk"))
            row.opened_ts = ts
            continue

        m = RE_TRADE_CLOSED_FULL.search(raw)
        if m:
            row = wk.trades.setdefault(m.group("ticket"),
                                       TradeRow(ticket=m.group("ticket")))
            row.direction = m.group("dir")
            row.exit = float(m.group("exit"))
            row.pnl = float(m.group("pnl"))
            row.pips = float(m.group("pips"))
            row.r = float(m.group("r"))
            row.exit_tag = m.group("tag")
            row.cause = m.group("cause")
            row.closed_ts = ts
            continue

        m = RE_SIGNAL.search(raw)
        if m:
            wk.signals.append({"ts": ts, **m.groupdict()})
            continue

        m = RE_NEAR_MISS.search(raw)
        if m:
            wk.near_misses.append({"ts": ts, **m.groupdict()})
            continue

        m = RE_ORDER_REJECTED.search(raw)
        if m:
            wk.order_rejects.append({"ts": ts, **m.groupdict()})
            continue

        if RE_H4_NO_SETUP.search(raw):
            wk.h4_no_setup += 1
            continue

        m = RE_HEARTBEAT.search(raw)
        if m and ts is not None:
            wk.heartbeats.append({
                "ts": ts,
                "symbol": wk.symbol,
                "balance": float(m.group("bal")),
                "equity": float(m.group("eq")),
                "open_positions": int(m.group("n")),
            })


# ---------------------------------------------------------------------------
# Cross-symbol account view
# ---------------------------------------------------------------------------
@dataclass
class AccountView:
    points: list[dict] = field(default_factory=list)   # merged heartbeats
    external_moves: list[dict] = field(default_factory=list)
    account_delta: float | None = None
    agent_pnl: float = 0.0
    external_pnl: float | None = None
    cascades: list[list[tuple[str, datetime]]] = field(default_factory=list)


# A residual smaller than this between a balance change and the agent trades
# that occurred in the same heartbeat gap is treated as rounding/swap noise,
# not an external trade.
EXTERNAL_MOVE_TOLERANCE_USD = 0.50


def build_account_view(weeks: dict[str, SymbolWeek]) -> AccountView:
    view = AccountView()
    points = sorted(
        (hb for wk in weeks.values() for hb in wk.heartbeats),
        key=lambda h: h["ts"],
    )
    view.points = points

    closes = sorted(
        ((t.closed_ts, t.pnl, wk.symbol, t.ticket)
         for wk in weeks.values() for t in wk.closed_rows
         if t.closed_ts is not None),
        key=lambda c: c[0],
    )
    view.agent_pnl = sum(t.pnl for wk in weeks.values() for t in wk.closed_rows)

    if points:
        view.account_delta = points[-1]["balance"] - points[0]["balance"]
        view.external_pnl = view.account_delta - _agent_pnl_between(
            closes, points[0]["ts"], points[-1]["ts"])

    open_by_symbol: dict[str, int] = {}
    prev: dict | None = None
    for pt in points:
        if prev is not None:
            delta = pt["balance"] - prev["balance"]
            if abs(delta) > 0.01:
                explained = _agent_pnl_between(closes, prev["ts"], pt["ts"])
                residual = delta - explained
                if abs(residual) > EXTERNAL_MOVE_TOLERANCE_USD:
                    known = {s: n for s, n in open_by_symbol.items()}
                    view.external_moves.append({
                        "from_ts": prev["ts"],
                        "to_ts": pt["ts"],
                        "delta": delta,
                        "agent_explained": explained,
                        "residual": residual,
                        "all_agent_flat": bool(known) and all(
                            n == 0 for n in known.values()),
                        "open_by_symbol": known,
                    })
        open_by_symbol[pt["symbol"]] = pt["open_positions"]
        prev = pt

    view.cascades = _kill_cascades(weeks)
    return view


def _agent_pnl_between(closes: list[tuple], start: datetime, end: datetime) -> float:
    return sum(pnl for ts, pnl, _, _ in closes if start < ts <= end)


CASCADE_WINDOW_MINUTES = 30.0


def _kill_cascades(weeks: dict[str, SymbolWeek]) -> list[list[tuple[str, datetime]]]:
    """Group kill-switch downtime starts across symbols that begin within
    CASCADE_WINDOW_MINUTES of each other. Groups spanning >= 2 symbols are
    cascades (one halt taking multiple pairs down)."""
    starts: list[tuple[datetime, str]] = []
    for sym, wk in weeks.items():
        if wk.events is None:
            continue
        for w in wk.events.downtime:
            starts.append((w.start, sym))
    starts.sort(key=lambda s: s[0])

    cascades: list[list[tuple[str, datetime]]] = []
    group: list[tuple[datetime, str]] = []
    for ts, sym in starts:
        if group and (ts - group[0][0]).total_seconds() > CASCADE_WINDOW_MINUTES * 60:
            if len({s for _, s in group}) >= 2:
                cascades.append([(s, t) for t, s in group])
            group = []
        group.append((ts, sym))
    if group and len({s for _, s in group}) >= 2:
        cascades.append([(s, t) for t, s in group])
    return cascades


# ---------------------------------------------------------------------------
# Parameter snapshot
# ---------------------------------------------------------------------------
def build_parameter_snapshot(symbols: list[str]) -> list[str]:
    """Static snapshot of the routing + risk parameters the live processes
    run with. Read from the same code paths run_live.py resolves, so the
    reviewer sees what produced the week's behaviour. Degrades to MISSING
    notes if any import fails (e.g. bundle generated off-repo)."""
    out = ["## Parameter snapshot (active configuration)", ""]

    try:
        from agent.alphas.zone_routing import survivors
        rows = [(s, tf, sess, e) for s, tf, sess, e in survivors()
                if s in symbols]
        out.append("### Routed cells (agent/alphas/zone_routing.py)")
        out.append("")
        out.append("| Symbol | TF | Session | Mode | risk_scale | Evidence | OOS exp (pips) | OOS p |")
        out.append("|---|---|---|---|---|---|---|---|")
        for s, tf, sess, e in rows:
            ev = e.evidence
            out.append(
                f"| {s} | {tf} | {sess} | {e.mode} | {e.risk_scale:.2f} "
                f"| {ev.source if ev else 'MISSING'} "
                f"| {ev.oos_expectancy if ev else '-'} "
                f"| {ev.oos_p if ev else '-'} |")
        missing = [s for s in symbols if s not in {r[0] for r in rows}]
        if missing:
            out.append("")
            out.append(f"MISSING: no deployed routing cell for: {', '.join(missing)}")
        out.append("")
        out.append("Mode `htf_against` = SupplyDemandAlpha with htf_align=D1, "
                   "htf_align_mode=against, htf_lookback=10, "
                   "htf_min_move_pips=60; fixed conviction 0.65 per signal.")
    except Exception as e:  # pragma: no cover - only on broken checkout
        out.append(f"MISSING: routing table unavailable ({e})")
    out.append("")

    try:
        from agent.config import load_config
        cfg = load_config()
        r = cfg.risk
        out.append("### Risk config (agent/config.py + config/default.yaml + .env)")
        out.append("")
        out.append(f"- risk pct_target: {r.pct_target:.4f} "
                   f"(floor {r.pct_floor:.4f} below "
                   f"${r.pct_floor_threshold_account:.0f} accounts)")
        out.append(f"- daily_dd_halt_pct: {r.daily_dd_halt_pct:.4f}")
        out.append(f"- max_open_positions: {r.max_open_positions}")
        out.append(f"- portfolio_max_open_risk_pct: {r.portfolio_max_open_risk_pct:.4f}")
        out.append(f"- lot caps: min {r.lot_min}, <$300 cap {r.lot_hard_cap_under_300}, "
                   f"<$1000 cap {r.lot_hard_cap_under_1000}, hard cap {r.lot_hard_cap}")
    except Exception as e:
        out.append(f"MISSING: risk config unavailable ({e})")
    out.append("")

    try:
        from agent.live.config import LiveConfig
        lc = LiveConfig()
        out.append("### Live loop defaults (agent/live/config.py, as run_live.py builds them)")
        out.append("")
        out.append(f"- conviction-scaled risk band: {lc.risk_min_pct:.4f} - "
                   f"{lc.risk_max_pct:.4f} of balance "
                   f"(single-trade hard cap {lc.max_trade_risk_pct:.4f})")
        out.append(f"- post-loss guard: enabled={lc.revenge_guard_enabled}, "
                   f"cooldown {lc.post_loss_cooldown_minutes:.0f} min / "
                   f"{lc.post_loss_cooldown_bars} bars, "
                   f"next-trade risk x{lc.post_loss_risk_multiplier}, "
                   f"halt after {lc.max_consecutive_losses} consecutive losses, "
                   f"catastrophic single-loss halt at "
                   f"{lc.catastrophic_loss_frac:.0%} of balance")
        out.append(f"- soft-stop layer: enabled={lc.soft_stop_enabled}, "
                   f"catastrophe stop x{lc.catastrophe_stop_mult}, "
                   f"panic overshoot x{lc.soft_stop_panic_mult}, "
                   f"min catastrophe distance {lc.soft_stop_min_catastrophe_pips}p")
        out.append(f"- breakeven move at {lc.move_be_at_r}R; partial exits "
                   f"enabled={lc.partial_exit_enabled}")
    except Exception as e:
        out.append(f"MISSING: live config unavailable ({e})")
    out.append("")
    return out


# ---------------------------------------------------------------------------
# Review checklist (auto-flagged anomalies)
# ---------------------------------------------------------------------------
DOWNTIME_FLAG_HOURS = 12.0
RISK_FLAG_ABS_PCT = 2.0     # above the single-trade hard cap
RISK_FLAG_REL_MULT = 1.5    # or 1.5x the week's median trade risk


def build_checklist(weeks: dict[str, SymbolWeek],
                    account: AccountView) -> list[str]:
    flags: list[str] = []

    for sym, wk in weeks.items():
        if not wk.log_files:
            flags.append(f"[{sym}] NO LOG FILES found in the window - symbol "
                         "not deployed, process down all week, or wrong --log-root.")
            continue
        if wk.missing_days:
            missing = ", ".join(d.isoformat() for d in wk.missing_days)
            flags.append(f"[{sym}] missing daily log(s): {missing} "
                         "(process down or log rotated away).")
        if wk.kill_txt is not None:
            flags.append(f"[{sym}] kill.txt PRESENT at report time - the agent "
                         f"is halted right now. Content: {wk.kill_txt!r}")
        ev = wk.events
        if ev is not None:
            for w in ev.downtime:
                if w.duration_hours > DOWNTIME_FLAG_HOURS:
                    flags.append(
                        f"[{sym}] downtime window > {DOWNTIME_FLAG_HOURS:.0f}h: "
                        f"{w.start:%Y-%m-%d %H:%M} -> {w.end:%Y-%m-%d %H:%M} UTC "
                        f"({w.duration_hours:.1f}h, reason: {w.reason})")
            if ev.autotrading_rejects:
                flags.append(f"[{sym}] {len(ev.autotrading_rejects)} order(s) "
                             "rejected with AutoTrading disabled in MT5.")
            if ev.dd_halts:
                flags.append(f"[{sym}] daily drawdown halt hit "
                             f"{len(ev.dd_halts)} time(s).")
            if ev.soft_sl_panics:
                flags.append(f"[{sym}] {len(ev.soft_sl_panics)} soft-SL panic "
                             "exit(s) (price blew through the soft stop).")
        if wk.order_rejects:
            flags.append(f"[{sym}] {len(wk.order_rejects)} [ORDER REJECTED] "
                         "line(s) - see the rejection breakdown.")

        risks = [t.risk_pct for t in wk.trades.values() if t.risk_pct is not None]
        if risks:
            median_risk = statistics.median(risks)
            for t in wk.trades.values():
                if t.risk_pct is None:
                    continue
                if t.risk_pct > RISK_FLAG_ABS_PCT or (
                        len(risks) >= 3
                        and t.risk_pct > RISK_FLAG_REL_MULT * median_risk):
                    flags.append(
                        f"[{sym}] trade ticket={t.ticket} risk={t.risk_pct:.2f}% "
                        f"above the norm (week median {median_risk:.2f}%, "
                        f"hard cap {RISK_FLAG_ABS_PCT:.1f}%).")

    for mv in account.external_moves:
        where = ("all agent symbols FLAT" if mv["all_agent_flat"]
                 else f"open positions {mv['open_by_symbol']}")
        flags.append(
            f"[ACCOUNT] external/manual equity move: balance changed "
            f"{mv['delta']:+.2f} between {mv['from_ts']:%Y-%m-%d %H:%M} and "
            f"{mv['to_ts']:%Y-%m-%d %H:%M} UTC, agent trades explain "
            f"{mv['agent_explained']:+.2f}, unexplained {mv['residual']:+.2f} "
            f"({where}).")

    for grp in account.cascades:
        syms = ", ".join(sorted({s for s, _ in grp}))
        first = min(t for _, t in grp)
        flags.append(f"[ACCOUNT] kill-switch cascade: halts on {syms} all "
                     f"started within {CASCADE_WINDOW_MINUTES:.0f} min of "
                     f"{first:%Y-%m-%d %H:%M} UTC.")

    if not account.points:
        flags.append("[ACCOUNT] no heartbeat balance data found in any log - "
                     "balance curve and external-move detection unavailable.")

    return flags


# ---------------------------------------------------------------------------
# Rendering helpers (all plain ASCII markdown)
# ---------------------------------------------------------------------------
def _fmt(v, spec: str = "") -> str:
    if v is None:
        return "-"
    if not spec:
        return str(v)
    try:
        return format(float(v) if isinstance(v, str) else v, spec)
    except (TypeError, ValueError):
        return str(v)


def _fmt_ts(ts: datetime | None) -> str:
    return ts.strftime("%Y-%m-%d %H:%M") if ts is not None else "-"


def _rr(entry, stop, tp) -> float | None:
    try:
        risk = abs(entry - stop)
        reward = abs(tp - entry)
        return reward / risk if risk > 0 else None
    except (TypeError, ZeroDivisionError):
        return None


def render_symbol_section(wk: SymbolWeek, days: list[date]) -> list[str]:
    out = [f"## {wk.symbol}", ""]

    if not wk.log_files:
        out.append("MISSING: no daily log files found for this symbol in the "
                   "window (not deployed, process never ran, or logs live "
                   "somewhere other than --log-root).")
        out.append("")
        return out

    out.append(f"Log files parsed: {', '.join(p.name for p in wk.log_files)}")
    if wk.missing_days:
        out.append("MISSING days (no log file): "
                   + ", ".join(d.isoformat() for d in wk.missing_days))
    out.append("")

    # -- Trade table --
    out.append("### Trades")
    out.append("")
    if wk.trades:
        out.append("| Ticket | Side | Lots | Entry | Exit | Soft SL | Cata SL "
                   "| TP | Risk% | PnL $ | Pips | R | Exit tag | Cause |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for t in sorted(wk.trades.values(),
                        key=lambda t: (t.opened_ts or t.closed_ts
                                       or datetime.min.replace(tzinfo=timezone.utc))):
            out.append(
                f"| {t.ticket} | {t.direction} | {_fmt(t.lots, '.2f')} "
                f"| {_fmt(t.entry, '.5f')} | {_fmt(t.exit, '.5f')} "
                f"| {_fmt(t.soft_sl, '.5f')} | {_fmt(t.catastrophe_sl, '.5f')} "
                f"| {_fmt(t.tp, '.5f')} | {_fmt(t.risk_pct, '.2f')} "
                f"| {_fmt(t.pnl, '+.2f')} | {_fmt(t.pips, '+.0f')} "
                f"| {_fmt(t.r, '+.2f')} | {t.exit_tag or 'OPEN/UNKNOWN'} "
                f"| {t.cause or '-'} |")
        closed = wk.closed_rows
        if closed:
            wins = sum(1 for t in closed if (t.r or 0) > 0)
            out.append("")
            out.append(f"Closed: {len(closed)} (wins {wins}, losses "
                       f"{len(closed) - wins}), net {wk.closed_pnl:+.2f} USD, "
                       f"expectancy {statistics.fmean(t.r for t in closed):+.2f}R.")
        still_open = [t for t in wk.trades.values() if t.pnl is None]
        if still_open:
            out.append(f"Still open / close not seen in window: "
                       f"{', '.join(t.ticket for t in still_open)}.")
    else:
        out.append("No trades opened or closed in this window.")
    out.append("")

    # -- Signals vs rejections --
    out.append("### Signals emitted vs rejected")
    out.append("")
    out.append(f"- Signals emitted ([SIGNAL] lines): {len(wk.signals)}")
    breakdown = wk.rejection_breakdown
    total_rej = sum(breakdown.values())
    out.append(f"- Rejections (near-miss + broker): {total_rej}")
    for reason, n in breakdown.most_common():
        label = {
            "htf_gate": "htf_gate (HTF alignment gate)",
            "max_positions": "max_positions (risk manager)",
            "post_loss_guard": "post_loss_guard (cooldown / circuit breaker)",
            "risk_manager": "risk_manager (other)",
            "sizing_skip": "sizing_skip",
            "portfolio_risk_cap": "portfolio_risk_cap",
            "broker_reject": "broker_reject (near-miss record)",
            "broker_reject_line": "[ORDER REJECTED] broker lines",
        }.get(reason, reason)
        out.append(f"  - {label}: {n}")
    if wk.order_rejects:
        for rej in wk.order_rejects[:5]:
            out.append(f"    - {_fmt_ts(rej['ts'])} UTC: {rej['detail']}")
        if len(wk.order_rejects) > 5:
            out.append(f"    - ... and {len(wk.order_rejects) - 5} more")
    out.append("")

    # -- Near-miss vault metadata --
    out.append("### Near misses (vault metadata)")
    out.append("")
    if wk.vault_near_misses:
        out.append(f"{len(wk.vault_near_misses)} vault record(s) in window "
                   "(charts + full JSONL in the bundle):")
        out.append("")
        out.append("| Time (UTC) | Reason | Dir | Conviction | R:R "
                   "| Zone impulse (pips) | Zone age at event |")
        out.append("|---|---|---|---|---|---|---|")
        for rec in wk.vault_near_misses:
            zone = rec.get("zone") or {}
            rr = _rr(rec.get("entry"), rec.get("stop"), rec.get("take_profit"))
            age = "-"
            try:
                evt_ts = datetime.fromisoformat(str(rec.get("ts")))
                created = datetime.fromisoformat(str(zone.get("created_at")))
                if evt_ts.tzinfo is None:
                    evt_ts = evt_ts.replace(tzinfo=timezone.utc)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_h = (evt_ts - created).total_seconds() / 3600.0
                age = f"{age_h / 24:.1f}d" if age_h >= 48 else f"{age_h:.0f}h"
            except (TypeError, ValueError):
                pass
            conv = rec.get("conviction")
            out.append(
                f"| {str(rec.get('ts', '-'))[:16]} | {rec.get('reason', '-')} "
                f"| {rec.get('direction', '-')} "
                f"| {_fmt(float(conv), '.2f') if conv is not None else '-'} "
                f"| {_fmt(rr, '.2f')} "
                f"| {_fmt(zone.get('impulse_pips'), '.0f') if zone.get('impulse_pips') is not None else '-'} "
                f"| {age} |")
    elif wk.vault_dir is None:
        out.append("MISSING: no vault directory for this symbol.")
    else:
        out.append("No near-miss vault records in this window "
                   f"(log lines counted {len(wk.near_misses)}).")
    out.append("")

    # -- H4 coverage --
    out.append("### H4 candle coverage")
    out.append("")
    weekdays = sum(1 for d in days if d.weekday() < 5)
    expected = weekdays * 6  # six H4 closes per trading day
    evaluated = wk.h4_no_setup + len(wk.signals)
    out.append(f"- H4 closes evaluated, no setup: {wk.h4_no_setup}")
    out.append(f"- H4 closes producing a signal: {len(wk.signals)}")
    out.append(f"- Expected H4 closes in window: ~{expected} "
               f"({weekdays} weekday(s) x 6)")
    skipped = max(0, expected - evaluated)
    out.append(f"- Unaccounted (downtime / process off / market closed): ~{skipped}")
    out.append("")

    # -- Downtime --
    out.append("### Downtime windows (kill-switch halts)")
    out.append("")
    ev = wk.events
    if ev is not None and ev.downtime:
        window_hours = len(days) * 24.0
        total_down = sum(w.duration_hours for w in ev.downtime)
        out.append(f"Halted {total_down:.1f}h of the ~{window_hours:.0f}h window "
                   f"({total_down / window_hours * 100:.0f}% downtime, "
                   f"{len(ev.downtime)} window(s)):")
        out.append("")
        for w in ev.downtime:
            out.append(f"- {w.start:%Y-%m-%d %H:%M} -> {w.end:%Y-%m-%d %H:%M} UTC "
                       f"({w.duration_hours:.1f}h) - reason: {w.reason}")
    else:
        out.append("No kill-switch halts detected in this window.")
    if wk.kill_txt is not None:
        out.append("")
        out.append(f"kill.txt is PRESENT right now. Content: {wk.kill_txt!r}")
    out.append("")

    # -- Balance curve --
    out.append("### Balance curve (heartbeats)")
    out.append("")
    if wk.heartbeats:
        by_day: dict[date, dict] = {}
        for hb in wk.heartbeats:
            by_day[hb["ts"].date()] = hb   # keep the last heartbeat per day
        out.append("| Day | Last balance | Last equity | Open positions "
                   "| Heartbeats seen |")
        out.append("|---|---|---|---|---|")
        per_day_counts = Counter(hb["ts"].date() for hb in wk.heartbeats)
        for d in sorted(by_day):
            hb = by_day[d]
            out.append(f"| {d.isoformat()} | {hb['balance']:.2f} "
                       f"| {hb['equity']:.2f} | {hb['open_positions']} "
                       f"| {per_day_counts[d]} |")
    else:
        out.append("MISSING: no heartbeat lines found in this symbol's logs.")
    out.append("")

    # -- State sidecar --
    if wk.state:
        rm = wk.state.get("risk_manager") or {}
        plg = wk.state.get("post_loss_guard") or {}
        out.append("### state.json snapshot")
        out.append("")
        out.append(f"- saved_at: {wk.state.get('saved_at', 'unknown')}")
        out.append(f"- risk_manager: day={rm.get('day')} "
                   f"day_pnl={rm.get('day_pnl', 0):+.2f} "
                   f"halted_today={rm.get('halted_today')}")
        out.append(f"- post_loss_guard: consecutive_losses="
                   f"{plg.get('consecutive_losses', 0)} "
                   f"session_halted={plg.get('session_halted', False)} "
                   f"size_multiplier={plg.get('size_multiplier', 1.0)}")
        out.append("")
    return out


def render_account_section(view: AccountView,
                           weeks: dict[str, SymbolWeek]) -> list[str]:
    out = ["## Cross-symbol account view", ""]
    if not view.points:
        out.append("MISSING: no heartbeat data in any symbol's logs - cannot "
                   "build the merged account timeline.")
        out.append("")
        return out

    first, last = view.points[0], view.points[-1]
    out.append(f"Merged heartbeat timeline: {len(view.points)} points from "
               f"{_fmt_ts(first['ts'])} to {_fmt_ts(last['ts'])} UTC "
               "(all symbols log the same account).")
    out.append("")
    out.append(f"- Balance first seen : {first['balance']:.2f}")
    out.append(f"- Balance last seen  : {last['balance']:.2f}")
    out.append(f"- Account P&L (balance delta): {view.account_delta:+.2f}")
    out.append(f"- Agent P&L (sum of closed trades, all symbols): "
               f"{view.agent_pnl:+.2f}")
    ext = view.external_pnl if view.external_pnl is not None else 0.0
    out.append(f"- External / unexplained P&L inside the heartbeat span: "
               f"{ext:+.2f}")
    out.append("")

    out.append("### External / manual equity moves")
    out.append("")
    if view.external_moves:
        out.append("Balance changes the agent's own closed trades do NOT "
                   "explain (manual trades, other EAs, deposits/withdrawals):")
        out.append("")
        out.append("| From (UTC) | To (UTC) | Balance delta | Agent-explained "
                   "| Unexplained | Agent positions at the time |")
        out.append("|---|---|---|---|---|---|")
        for mv in view.external_moves:
            pos = ("all flat" if mv["all_agent_flat"]
                   else ", ".join(f"{s}={n}" for s, n
                                  in sorted(mv["open_by_symbol"].items()))
                   or "unknown")
            out.append(f"| {_fmt_ts(mv['from_ts'])} | {_fmt_ts(mv['to_ts'])} "
                       f"| {mv['delta']:+.2f} | {mv['agent_explained']:+.2f} "
                       f"| {mv['residual']:+.2f} | {pos} |")
    else:
        out.append("None detected - every balance change in the heartbeat "
                   "timeline is explained by the agent's own closed trades "
                   f"(tolerance {EXTERNAL_MOVE_TOLERANCE_USD:.2f} USD).")
    out.append("")

    out.append("### Kill-switch cascades across symbols")
    out.append("")
    if view.cascades:
        for grp in view.cascades:
            syms = ", ".join(f"{s} at {t:%Y-%m-%d %H:%M}" for s, t
                             in sorted(grp, key=lambda g: g[1]))
            out.append(f"- Cascade: {syms} UTC (halt starts within "
                       f"{CASCADE_WINDOW_MINUTES:.0f} min of each other)")
    else:
        out.append("None - no halt window started on two or more symbols "
                   f"within {CASCADE_WINDOW_MINUTES:.0f} minutes.")
    out.append("")
    return out


def render_report(weeks: dict[str, SymbolWeek], view: AccountView,
                  days: list[date], root: Path) -> str:
    all_closed = [t for wk in weeks.values() for t in wk.closed_rows]
    wins = sum(1 for t in all_closed if (t.r or 0) > 0)
    total_pnl = sum(t.pnl for t in all_closed)
    win_rate = (wins / len(all_closed) * 100) if all_closed else 0.0

    window_hours = len(days) * 24.0
    total_down = sum(
        w.duration_hours
        for wk in weeks.values() if wk.events is not None
        for w in wk.events.downtime)
    # Downtime percentage across symbols: each symbol contributes its own
    # window, so normalise by n_symbols * window.
    active_syms = [wk for wk in weeks.values() if wk.log_files]
    down_pct = (total_down / (window_hours * len(active_syms)) * 100
                if active_syms else 0.0)

    n_incidents = 0
    for wk in weeks.values():
        ev = wk.events
        if ev is None:
            continue
        n_incidents += (len(ev.autotrading_rejects) + len(ev.dd_halts)
                        + len(ev.soft_sl_panics) + len(ev.healthcheck_fails))

    checklist = build_checklist(weeks, view)

    lines: list[str] = [
        "# Weekly trading agent report",
        "",
        f"- Window: {days[0].isoformat()} to {days[-1].isoformat()} "
        f"({len(days)} day(s), UTC)",
        f"- Symbols: {', '.join(weeks)}",
        f"- Log root: {root}",
        f"- Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        "",
        "This report is OBSERVATION-ONLY evidence. Parameter changes still go",
        "through the validation pipeline; nothing here moves a gate by itself.",
        "",
        "## Executive summary",
        "",
        f"- Weekly agent P&L (closed trades): {total_pnl:+.2f} USD",
        f"- Trades closed: {len(all_closed)} (win rate {win_rate:.0f}%)",
        f"- Kill-switch downtime: {total_down:.1f}h total across symbols "
        f"({down_pct:.0f}% of the combined window)",
        f"- Incidents (broker rejects / DD halts / soft-SL panics / "
        f"healthcheck failures): {n_incidents}",
        f"- Review checklist flags: {len(checklist)}",
    ]
    if view.account_delta is not None:
        ext = view.external_pnl if view.external_pnl is not None else 0.0
        lines.append(f"- Account balance delta: {view.account_delta:+.2f} USD "
                     f"(agent {view.agent_pnl:+.2f}, external/unexplained "
                     f"{ext:+.2f})")
    lines.append("")

    for wk in weeks.values():
        lines.extend(render_symbol_section(wk, days))
    lines.extend(render_account_section(view, weeks))
    lines.extend(build_parameter_snapshot(list(weeks)))

    lines.append("## Review checklist (auto-flagged)")
    lines.append("")
    if checklist:
        for flag in checklist:
            lines.append(f"- [ ] {flag}")
    else:
        lines.append("Nothing auto-flagged this week.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bundling
# ---------------------------------------------------------------------------
def _date_prefix_in_window(name: str, day_strs: set[str]) -> bool:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_", name)
    return bool(m) and m.group(1) in day_strs


def write_bundle(zip_path: Path, report_text: str,
                 weeks: dict[str, SymbolWeek], days: list[date]) -> None:
    """Write everything into ONE zip. No staging folder, no symlinks - one
    pass with zipfile so it behaves identically on Windows."""
    day_strs = {d.isoformat() for d in days}
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("REPORT.md", report_text)

        for sym, wk in weeks.items():
            for lp in wk.log_files:
                zf.write(lp, f"{sym}/logs/{lp.name}")

            if wk.vault_dir is None:
                continue

            state_path = wk.vault_dir / "state.json"
            if state_path.exists():
                zf.write(state_path, f"{sym}/state.json")
            kill_path = wk.vault_dir / "kill.txt"
            if kill_path.exists():
                zf.write(kill_path, f"{sym}/kill.txt")

            for sub in VAULT_SUBDIRS:
                src = wk.vault_dir / sub
                if not src.is_dir():
                    continue
                for png in sorted(src.glob("*.png")):
                    if _date_prefix_in_window(png.name, day_strs):
                        zf.write(png, f"{sym}/{sub}/{png.name}")
                kept = [rec for rec in _iter_jsonl(src / "events.jsonl")
                        if str(rec.get("ts", ""))[:10] in day_strs]
                if kept:
                    body = "\n".join(json.dumps(r, default=str)
                                     for r in kept) + "\n"
                    zf.writestr(f"{sym}/{sub}/events.jsonl", body)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def discover_symbols(root: Path) -> list[str]:
    """Symbols with at least one daily log file under the log root. Folder
    names may carry the broker suffix (EURUSDm) - strip it. Falls back to
    the deployed default trio when nothing is found."""
    found: list[str] = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if not any(child.glob("*_????-??-??.log")):
                continue
            m = re.fullmatch(r"([A-Z]{6})m?", child.name)
            if m and m.group(1) not in found:
                found.append(m.group(1))
    return found or list(DEFAULT_SYMBOLS)


def _resolve_window(args: argparse.Namespace) -> list[date]:
    if args.start and args.end:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        if end < start:
            start, end = end, start
        return [start + timedelta(days=i)
                for i in range((end - start).days + 1)]
    end = (date.fromisoformat(args.end) if args.end
           else datetime.now(timezone.utc).date())
    if args.start:
        start = date.fromisoformat(args.start)
        return [start + timedelta(days=i)
                for i in range((end - start).days + 1)]
    return _resolve_days(end, max(1, args.days))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compile the ONE-COMMAND weekly review zip for all symbols.")
    p.add_argument("--days", "-d", type=int, default=7,
                   help="Number of UTC days back to include (default: 7). "
                        "Ignored when both --start and --end are given.")
    p.add_argument("--start", default=None,
                   help="Window start day (YYYY-MM-DD UTC).")
    p.add_argument("--end", default=None,
                   help="Window end / anchor day (YYYY-MM-DD UTC). "
                        "Default: today UTC.")
    p.add_argument("--symbols", default=None,
                   help="Comma-separated symbols (e.g. EURUSD,GBPUSD,USDCAD). "
                        "Default: every symbol with logs under --log-root.")
    p.add_argument("--log-root", default=None,
                   help=f"Log/vault root (default: {DEFAULT_VAULT_ROOT})")
    p.add_argument("--out", default=None,
                   help="Output zip path. Default: "
                        "<log-root>/reviews/weekly_report_<start>_to_<end>.zip")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.log_root) if args.log_root else DEFAULT_VAULT_ROOT
    days = _resolve_window(args)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")
                   if s.strip()]
    else:
        symbols = discover_symbols(root)

    weeks: dict[str, SymbolWeek] = {}
    for sym in symbols:
        weeks[sym] = parse_symbol_week(sym, root, days)

    view = build_account_view(weeks)
    report_text = render_report(weeks, view, days, root)

    stamp = f"{days[0].isoformat()}_to_{days[-1].isoformat()}"
    zip_path = (Path(args.out) if args.out
                else root / "reviews" / f"weekly_report_{stamp}.zip")
    write_bundle(zip_path, report_text, weeks, days)

    # Console output stays plain ASCII (Windows cp1252 consoles).
    all_closed = [t for wk in weeks.values() for t in wk.closed_rows]
    print(f"Window : {days[0].isoformat()} to {days[-1].isoformat()} (UTC)")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Closed trades: {len(all_closed)}, agent P&L "
          f"{sum(t.pnl for t in all_closed):+.2f} USD")
    flags = build_checklist(weeks, view)
    print(f"Checklist flags: {len(flags)}")
    for f in flags:
        print(f"  - {f}")
    print(f"\nBundle written to: {zip_path}")
    print("Send that ONE zip - it contains REPORT.md, all raw daily logs, "
          "vault JSONLs + chart PNGs for the window, state.json and any "
          "kill.txt, for every symbol.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
