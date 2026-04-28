"""Query the trade journal. The complete audit trail of every signal and trade
the bot has ever considered, with full reasoning attached.

Examples:
  # Last 20 trades, summary form
  python scripts/journal_query.py --last 20

  # All losing trades grouped by hour-of-day
  python scripts/journal_query.py --losers --by hour

  # All winning trades on H1
  python scripts/journal_query.py --winners --tf H1

  # Everything in the last week
  python scripts/journal_query.py --since 2026-04-21

  # Detailed narrative for trade ID 142
  python scripts/journal_query.py --explain 142

  # Setups that were detected but rejected by the risk manager / ML
  python scripts/journal_query.py --skipped

  # Signals rejected for a specific reason
  python scripts/journal_query.py --skipped --reason skip_risk_too_high
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from agent.analysis.explain import (
    ExplanationLine,
    TradeExplanation,
    format_explanation,
)
from agent.config import load_config


def _connect(path: Path):
    import sqlite3
    if not path.exists():
        print(f"ERROR: journal not found at {path}", file=sys.stderr)
        print("Tip: run with `python scripts/run_multitf.py --journal` first.", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _query_trades(conn, args) -> list[dict]:
    where = ["exit_time IS NOT NULL"]
    params: list = []
    if args.tf:
        where.append("mode LIKE ?")
        params.append(f"%{args.tf}%")
    if args.since:
        where.append("entry_time >= ?")
        params.append(args.since)
    if args.until:
        where.append("entry_time <= ?")
        params.append(args.until)
    if args.winners:
        where.append("pnl > 0")
    if args.losers:
        where.append("pnl <= 0")
    if args.symbol:
        where.append("symbol = ?")
        params.append(args.symbol)

    sql = f"""
        SELECT t.*, s.confluences, s.features_json, s.ml_score, s.timeframe AS sig_tf,
               s.detected_at, s.stop_pips, s.rr
        FROM trades t LEFT JOIN signals s ON t.signal_id = s.id
        WHERE {' AND '.join(where)}
        ORDER BY entry_time DESC
        LIMIT ?
    """
    params.append(args.last)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _query_skipped(conn, args) -> list[dict]:
    where = ["decision != 'approved'"]
    params: list = []
    if args.tf:
        where.append("timeframe = ?")
        params.append(args.tf)
    if args.reason:
        where.append("decision = ?")
        params.append(args.reason)
    if args.since:
        where.append("detected_at >= ?")
        params.append(args.since)
    sql = f"""
        SELECT * FROM signals
        WHERE {' AND '.join(where)}
        ORDER BY detected_at DESC
        LIMIT ?
    """
    params.append(args.last)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _print_summary_row(t: dict):
    et = t["entry_time"][:16]
    xt = (t["exit_time"] or "")[:16]
    pnl_pips = t.get("pnl_pips") or 0
    pnl = t.get("pnl") or 0
    sym = "WIN " if pnl > 0 else "LOSS"
    confs = json.loads(t.get("confluences") or "[]")
    confs_str = "+".join(confs) if confs else "-"
    tf = t.get("sig_tf") or "-"
    direction = (t.get("direction") or "?").upper()[:5]
    mlscore = t.get("ml_score")
    ml_str = f" ml={mlscore:.2f}" if mlscore is not None else ""
    print(f"  #{t['id']:5d}  {et}  exit {xt}  {direction:5s} [{tf:>3s}]  "
          f"{sym}  {pnl_pips:+6.1f}p  ${pnl:+7.2f}{ml_str}  {confs_str}")


def _group_summary(trades: list[dict], by: str):
    buckets: dict = defaultdict(lambda: {"win": 0, "loss": 0, "pnl": 0.0, "pips": 0.0})
    for t in trades:
        et = t.get("entry_time") or ""
        try:
            dt = datetime.fromisoformat(et)
        except Exception:
            continue
        if by == "hour":
            k = f"{dt.hour:02d}:00"
        elif by == "day":
            k = _DAY_NAMES[dt.weekday()] if dt.weekday() < 7 else "?"
        elif by == "tf":
            k = t.get("sig_tf") or "?"
        elif by == "direction":
            k = (t.get("direction") or "?")
        elif by == "month":
            k = f"{dt:%Y-%m}"
        else:
            k = "all"
        b = buckets[k]
        if (t.get("pnl") or 0) > 0:
            b["win"] += 1
        else:
            b["loss"] += 1
        b["pnl"] += t.get("pnl") or 0
        b["pips"] += t.get("pnl_pips") or 0
    print(f"\nGrouped by {by}:")
    print(f"  {'key':>10s}  {'W':>4s} {'L':>4s} {'WR':>6s}  {'pips':>9s}  {'pnl':>10s}")
    for k in sorted(buckets.keys()):
        b = buckets[k]
        n = b["win"] + b["loss"]
        wr = (100 * b["win"] / n) if n else 0.0
        print(f"  {str(k):>10s}  {b['win']:>4d} {b['loss']:>4d} {wr:>5.1f}%  "
              f"{b['pips']:>9.1f}  ${b['pnl']:>+9.2f}")


def _fmt_time(iso_str: str | None, tz_name: str = "America/New_York") -> str:
    """Render an ISO UTC timestamp in user-friendly local time. Falls back to UTC
    on any parse failure."""
    if not iso_str:
        return "—"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone as _tz
        tz = _tz.utc
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return iso_str[:16]


def _explain_trade_row(conn, trade_id: int, tz_name: str = "America/New_York"):
    """Print a compact, human-readable narrative for a single trade.

    Format mirrors the dashboard /trade/{id} page exactly so users see the same
    output whether they're in the terminal or the browser. Output blocks:
        title bar         — id, detected time (TZ), symbol, TF, direction
        compact one-line  — entry, stop+pips, tp+rr, lot, ML score
        WHY THIS TRADE WAS TAKEN
        OUTCOME
    """
    row = conn.execute(
        """SELECT t.*, s.confluences, s.features_json, s.ml_score, s.timeframe AS sig_tf,
                  s.detected_at, s.stop_pips, s.rr
           FROM trades t LEFT JOIN signals s ON t.signal_id = s.id
           WHERE t.id = ?""", (trade_id,)
    ).fetchone()
    if row is None:
        print(f"No trade with id {trade_id}", file=sys.stderr)
        sys.exit(1)
    t = dict(row)
    confs = json.loads(t.get("confluences") or "[]")
    feats = json.loads(t.get("features_json") or "{}")

    detected_str = _fmt_time(t.get("detected_at") or t.get("entry_time"), tz_name)
    title = (f"Trade #{t['id']}  |  {detected_str}  |  {t['symbol']} "
             f"{t.get('sig_tf') or '?'}  |  {(t.get('direction') or '?').upper()}")

    # Compact one-line summary. Round prices to 5dp, pips to 1dp.
    entry = t.get("entry_price") or 0
    stop = t.get("stop_price") or 0
    tp = t.get("tp_price") or 0
    stop_pips = t.get("stop_pips") or 0
    rr = t.get("rr") or 0
    lot = t.get("lot_size") or 0
    summary_one_line = (f"Entry: {entry:.5f}  Stop: {stop:.5f} ({stop_pips:.1f} pips)"
                         f"  TP: {tp:.5f} (R:R 1:{rr:.2f})  Lot: {lot}")
    summary = [summary_one_line]
    if t.get("ml_score") is not None:
        summary.append(f"ML score: {t['ml_score']:.3f}")

    why: list[ExplanationLine] = []
    if confs:
        for c in confs:
            why.append(ExplanationLine(text=f"confluence: {c}"))
    else:
        why.append(ExplanationLine(text="(no confluences recorded — discoverer or rule with empty list)"))
    if feats:
        # Top 6 features by |magnitude| in 2-column chunks, matching the report layout.
        important = sorted(feats.items(), key=lambda kv: -abs(float(kv[1] or 0)))[:6]
        why.append(ExplanationLine(text=""))
        why.append(ExplanationLine(text="market state at entry (top features):"))
        # Pair them into rows of 2 for compact output.
        rows = []
        cur: list[str] = []
        for name, value in important:
            try:
                cell = f"{name:>20s} = {float(value):+.2f}"
            except (ValueError, TypeError):
                cell = f"{name:>20s} = {value}"
            cur.append(cell)
            if len(cur) == 2:
                rows.append(cur)
                cur = []
        if cur:
            rows.append(cur)
        for r in rows:
            why.append(ExplanationLine(text="  ".join(r)))

    outcome: list[str] = []
    if t.get("exit_time"):
        is_force_closed = t.get("exit_reason") == "end_of_data"
        if is_force_closed:
            verdict = "INCOMPLETE"
        elif (t.get("pnl") or 0) > 0:
            verdict = "WIN"
        else:
            verdict = "LOSS"
        exit_price = t.get("exit_price") or 0
        pnl_pips = t.get("pnl_pips") or 0
        pnl = t.get("pnl") or 0
        commission = t.get("commission") or 0
        exit_str = _fmt_time(t.get("exit_time"), tz_name)
        outcome = [
            "",
            "OUTCOME",
            f"  Exited at {exit_price:.5f} on {exit_str}  (reason: {t.get('exit_reason')})",
            f"  P&L: {pnl_pips:+.1f} pips = ${pnl:+.2f}  |  "
            f"Commission: ${commission:.2f}  |  Result: {verdict}",
        ]
        if is_force_closed:
            outcome.append("  ⚠  Force-closed (backtest dataset ended). Trade never hit SL or TP — "
                           "do NOT count as a real win/loss.")

    e = TradeExplanation(title=title, summary_lines=summary,
                          why_taken=why, risk_lines=[], outcome_lines=outcome)
    print(format_explanation(e))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--journal-path", type=Path, default=None)
    parser.add_argument("--last", type=int, default=20, help="max rows to return")
    parser.add_argument("--since", type=str, default=None, help="ISO timestamp / YYYY-MM-DD")
    parser.add_argument("--until", type=str, default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--tf", default=None, help="filter by timeframe (M15/H1/H4/D1)")
    parser.add_argument("--winners", action="store_true")
    parser.add_argument("--losers", action="store_true")
    parser.add_argument("--by", choices=["hour", "day", "tf", "direction", "month"],
                        help="group results by this dimension")
    parser.add_argument("--explain", type=int, help="print full narrative for trade ID")
    parser.add_argument("--skipped", action="store_true",
                        help="show signals that were detected but not taken")
    parser.add_argument("--reason", default=None,
                        help="filter --skipped by decision reason "
                             "(e.g. skip_risk_too_high, skip_daily_halt, ml_below_threshold)")
    args = parser.parse_args()

    cfg = load_config()
    path = args.journal_path or cfg.journal_db
    conn = _connect(path)

    if args.explain:
        _explain_trade_row(conn, args.explain)
        return

    if args.skipped:
        rows = _query_skipped(conn, args)
        print(f"\n{len(rows)} skipped signals" + (f" (reason={args.reason})" if args.reason else ""))
        for r in rows:
            confs = json.loads(r.get("confluences") or "[]")
            stop = r.get("stop_pips") or 0
            print(f"  {r['detected_at'][:16]}  {r['timeframe']:>3s}  "
                  f"{r['direction']:5s}  stop={stop:.0f}p  "
                  f"reason={r['decision']}  ({r.get('decision_reason') or '-'})  "
                  f"confs={'+'.join(confs) if confs else '-'}")
        return

    trades = _query_trades(conn, args)
    print(f"\n{len(trades)} trade(s) match.\n")
    if not args.by:
        for t in trades:
            _print_summary_row(t)
    else:
        _group_summary(trades, args.by)


if __name__ == "__main__":
    main()
