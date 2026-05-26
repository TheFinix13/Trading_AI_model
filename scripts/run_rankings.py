#!/usr/bin/env python3
"""CLI: Load trades from SQLite, run all ranking systems, print leaderboard, save JSON.

Usage:
    python scripts/run_rankings.py                          # uses default DB
    python scripts/run_rankings.py --db data/custom.db      # custom DB path
    python scripts/run_rankings.py --out data/rankings/     # custom output dir
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.ranking import generate_full_report
from agent.config import RankingConfig


DEFAULT_DB = PROJECT_ROOT / "data" / "agent_3yr_v10_perTF.db"
DEFAULT_OUT = PROJECT_ROOT / "data" / "rankings"


def load_trades_from_db(db_path: Path) -> list[dict]:
    """Load all closed trades from a backtest SQLite database.

    Handles two schemas:
      1. Flat schema (has r_multiple, mae_pips, confluences_json directly in trades)
      2. Split schema (trades + signals tables linked via signal_id)
    In case 2, we JOIN on signals to pull timeframe, confluences, stop_pips, rr
    and compute r_multiple from pnl_pips / stop_pips.
    """
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
    except sqlite3.OperationalError:
        print(f"ERROR: No 'trades' table in {db_path}")
        conn.close()
        sys.exit(1)

    has_signals = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='signals'"
    ).fetchone())

    if "confluences_json" in cols and "timeframe" in cols:
        rows = conn.execute(
            "SELECT * FROM trades WHERE exit_time IS NOT NULL ORDER BY entry_time"
        ).fetchall()
        trades = [dict(r) for r in rows]
    elif has_signals and "signal_id" in cols:
        rows = conn.execute("""
            SELECT t.*,
                   s.timeframe,
                   s.confluences AS confluences_json,
                   s.stop_pips,
                   s.rr AS signal_rr,
                   s.ml_score
            FROM trades t
            JOIN signals s ON t.signal_id = s.id
            WHERE t.exit_time IS NOT NULL
            ORDER BY t.entry_time
        """).fetchall()
        trades = []
        for r in rows:
            d = dict(r)
            stop_pips = d.get("stop_pips") or 0
            pnl_pips = d.get("pnl_pips") or 0
            if stop_pips and stop_pips > 0:
                d["r_multiple"] = pnl_pips / stop_pips
            else:
                d["r_multiple"] = 0.0
            d.setdefault("mae_pips", 0.0)
            trades.append(d)
    else:
        rows = conn.execute(
            "SELECT * FROM trades WHERE exit_time IS NOT NULL ORDER BY entry_time"
        ).fetchall()
        trades = [dict(r) for r in rows]

    conn.close()
    return trades


def print_leaderboard(report_dict: dict) -> None:
    """Pretty-print the ranking report to stdout."""
    summary = report_dict["summary"]
    print("\n" + "=" * 70)
    print("  STRATEGY QUALITY SCORE (SQS) — FULL RANKING REPORT")
    print("=" * 70)
    print(f"\n  Total trades: {summary['total_trades']}  |  "
          f"Wins: {summary['total_wins']}  |  "
          f"Overall Avg SQS: {summary['overall_avg_sqs']:.1f}/100")

    # Strategy leaderboard
    print("\n" + "-" * 70)
    print("  STRATEGY LEADERBOARD (by Avg SQS)")
    print("-" * 70)
    print(f"  {'#':<3} {'Strategy':<25} {'Trades':<8} {'WR%':<8} "
          f"{'AvgSQS':<8} {'AvgR':<7} {'Pips':<10}")
    print(f"  {'—'*3} {'—'*25} {'—'*8} {'—'*8} {'—'*8} {'—'*7} {'—'*10}")
    for row in report_dict["strategy_leaderboard"]:
        print(f"  {row['rank']:<3} {row['strategy']:<25} {row['n_trades']:<8} "
              f"{row['win_rate']*100:>5.1f}%  {row['avg_sqs']:>6.1f}  "
              f"{row['avg_r']:>5.2f}  {row['total_pips']:>+8.1f}")

    # Timeframe leaderboard
    print("\n" + "-" * 70)
    print("  TIMEFRAME LEADERBOARD (by Total Score)")
    print("-" * 70)
    print(f"  {'#':<3} {'TF':<8} {'Score':<8} {'Trades':<8} {'WR%':<8} "
          f"{'Sharpe':<8} {'AvgSQS':<8} {'Consist':<8}")
    print(f"  {'—'*3} {'—'*8} {'—'*8} {'—'*8} {'—'*8} {'—'*8} {'—'*8} {'—'*8}")
    for row in report_dict["timeframe_leaderboard"]:
        print(f"  {row['rank']:<3} {row['timeframe']:<8} {row['total_score']:>6.1f}  "
              f"{row['n_trades']:<8} {row['win_rate']*100:>5.1f}%  "
              f"{row['sharpe']:>6.3f}  {row['avg_sqs']:>6.1f}  "
              f"{row['consistency']:>5.0%}")

    # Session leaderboard
    print("\n" + "-" * 70)
    print("  SESSION LEADERBOARD (by Total Score)")
    print("-" * 70)
    print(f"  {'#':<3} {'Session':<22} {'Hours':<18} {'Score':<8} "
          f"{'Trades':<8} {'WR%':<8} {'AvgR':<7} {'AvgSQS':<8}")
    print(f"  {'—'*3} {'—'*22} {'—'*18} {'—'*8} {'—'*8} {'—'*8} {'—'*7} {'—'*8}")
    for row in report_dict["session_leaderboard"]:
        print(f"  {row['rank']:<3} {row['session']:<22} {row['hour_range']:<18} "
              f"{row['total_score']:>6.1f}  {row['n_trades']:<8} "
              f"{row['win_rate']*100:>5.1f}%  {row['avg_r']:>5.2f}  "
              f"{row['avg_sqs']:>6.1f}")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Run SQS ranking system on backtest trades."
    )
    parser.add_argument(
        "--db", type=str, default=str(DEFAULT_DB),
        help=f"Path to SQLite database with trades table (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--out", type=str, default=str(DEFAULT_OUT),
        help=f"Output directory for rankings JSON (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)

    print(f"Loading trades from: {db_path}")
    trades = load_trades_from_db(db_path)
    print(f"Loaded {len(trades)} closed trades.")

    if not trades:
        print("No trades found. Nothing to rank.")
        sys.exit(0)

    cfg = RankingConfig()
    report = generate_full_report(trades, cfg=cfg)
    report_dict = report.to_dict()

    print_leaderboard(report_dict)

    # Save to JSON
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest.json"
    with open(out_path, "w") as f:
        json.dump(report_dict, f, indent=2)
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
