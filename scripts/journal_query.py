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


def _explain_trade_row(conn, trade_id: int):
    """Reconstruct a TradeExplanation from journal rows. Doesn't reconstruct full
    Setup objects (we don't store the raw zone/fvg objects), but renders all the
    information we have: timestamps, prices, confluences, ML score, MAE/MFE-equivalent."""
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

    title = (f"Trade #{t['id']}  |  {t['detected_at']}  |  {t['symbol']} {t.get('sig_tf','?')}  "
             f"|  {(t.get('direction') or '?').upper()}")
    summary = [
        f"Entry  : {t.get('entry_price')}  at {t.get('entry_time')}",
        f"Stop   : {t.get('stop_price')}   ({t.get('stop_pips')} pips)",
        f"TP     : {t.get('tp_price')}     (R:R 1:{t.get('rr')})",
        f"Lot    : {t.get('lot_size')}",
    ]
    if t.get("ml_score") is not None:
        summary.append(f"ML score: {t['ml_score']:.3f}")

    why = [ExplanationLine(text=f"confluence: {c}") for c in confs]
    if not confs:
        why = [ExplanationLine(text="(no confluences recorded — discoverer or rule with empty list)")]
    if feats:
        # Show top 5 feature values so the user can see what state the market was in
        important = sorted(feats.items(), key=lambda kv: -abs(float(kv[1] or 0)))[:5]
        why.append(ExplanationLine(text=""))
        why.append(ExplanationLine(text="market state at entry (top features):"))
        for name, value in important:
            try:
                why.append(ExplanationLine(text=f"  {name} = {float(value):+.4f}"))
            except (ValueError, TypeError):
                why.append(ExplanationLine(text=f"  {name} = {value}"))

    outcome: list[str] = []
    if t.get("exit_time"):
        is_win = (t.get("pnl") or 0) > 0
        outcome = [
            "",
            "OUTCOME",
            f"  Exited at {t.get('exit_price')} on {t.get('exit_time')}  (reason: {t.get('exit_reason')})",
            f"  P&L: {t.get('pnl_pips'):+.1f} pips = ${t.get('pnl'):+.2f}",
            f"  Result: {'WIN' if is_win else 'LOSS'}",
        ]

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
