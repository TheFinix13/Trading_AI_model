"""Train the confluence optimizer on historical backtest data.

Usage:
    python scripts/run_confluence_optimizer.py --db data/backtest_lzi_relaxed_train.db
    python scripts/run_confluence_optimizer.py --db data/backtest_lzi_relaxed_train.db --db data/backtest_2024_2026_v8.db

Outputs:
    - data/optimizer/booster_scores.json (optimizer state)
    - data/optimizer/report.json (human-readable report)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.optimizer import ConfluenceOptimizer


def load_trades_from_db(db_path: str) -> list[dict]:
    """Load trades from a backtest SQLite database."""
    path = Path(db_path)
    if not path.exists():
        print(f"WARNING: DB not found: {db_path}")
        return []

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    trades: list[dict] = []

    # Try to load from signals table (has confluences)
    try:
        rows = conn.execute("""
            SELECT s.confluences, s.ml_score, s.direction, s.timeframe,
                   t.pnl, t.pnl_pips, t.exit_reason
            FROM trades t
            JOIN signals s ON t.signal_id = s.id
            WHERE t.exit_reason IS NOT NULL
        """).fetchall()

        for row in rows:
            confluences_raw = row["confluences"] or ""
            # Parse confluences (comma-separated or JSON list)
            if confluences_raw.startswith("["):
                try:
                    confluences = json.loads(confluences_raw)
                except (json.JSONDecodeError, ValueError):
                    confluences = [c.strip() for c in confluences_raw.split(",")]
            else:
                confluences = [c.strip() for c in confluences_raw.split(",") if c.strip()]

            pnl = row["pnl"] or 0.0
            is_winner = pnl > 0

            # Infer strategy from confluences
            strategy = _infer_strategy(confluences)

            # Compute approximate R-multiple
            r_multiple = 1.5 if is_winner else -1.0
            if row["pnl_pips"] and row["pnl_pips"] != 0:
                r_multiple = row["pnl_pips"] / 30.0 if row["pnl_pips"] > 0 else row["pnl_pips"] / 30.0

            trades.append({
                "strategy_name": strategy,
                "confluences": confluences,
                "is_winner": is_winner,
                "r_multiple": r_multiple,
                "pnl_pips": row["pnl_pips"] or 0.0,
            })

    except sqlite3.OperationalError as e:
        print(f"WARNING: Could not query {db_path}: {e}")
        # Try simpler query without join
        try:
            rows = conn.execute("""
                SELECT confluences, decision, ml_score, direction
                FROM signals
                WHERE decision = 'take'
            """).fetchall()

            for row in rows:
                confluences_raw = row["confluences"] or ""
                if confluences_raw.startswith("["):
                    try:
                        confluences = json.loads(confluences_raw)
                    except (json.JSONDecodeError, ValueError):
                        confluences = [c.strip() for c in confluences_raw.split(",")]
                else:
                    confluences = [c.strip() for c in confluences_raw.split(",") if c.strip()]

                strategy = _infer_strategy(confluences)
                trades.append({
                    "strategy_name": strategy,
                    "confluences": confluences,
                    "is_winner": True,  # Only taken signals, assume some success
                    "r_multiple": 0.5,
                })
        except sqlite3.OperationalError:
            pass

    conn.close()
    return trades


def _infer_strategy(confluences: list[str]) -> str:
    """Infer strategy name from confluences."""
    conf_set = set(confluences)
    if "lzi_retest" in conf_set or "liquidity_zone" in conf_set:
        return "LiquidityGrabReversal"
    if "fvg" in conf_set or "fvg_retest" in conf_set:
        return "FVGRetest"
    if "zone" in conf_set:
        return "SDZoneRetest"
    if "bos" in conf_set:
        return "BOSContinuation"
    return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Train confluence optimizer")
    parser.add_argument("--db", action="append", required=True, help="Path to backtest DB(s)")
    parser.add_argument("--output", default="data/optimizer", help="Output directory")
    args = parser.parse_args()

    all_trades: list[dict] = []
    for db_path in args.db:
        trades = load_trades_from_db(db_path)
        print(f"Loaded {len(trades)} trades from {db_path}")
        all_trades.extend(trades)

    if not all_trades:
        print("ERROR: No trades loaded. Check DB paths.")
        sys.exit(1)

    print(f"\nTotal trades: {len(all_trades)}")
    strategies = set(t["strategy_name"] for t in all_trades)
    for s in sorted(strategies):
        n = sum(1 for t in all_trades if t["strategy_name"] == s)
        wins = sum(1 for t in all_trades if t["strategy_name"] == s and t["is_winner"])
        wr = wins / n * 100 if n > 0 else 0
        print(f"  {s}: {n} trades, {wr:.1f}% WR")

    # Fit optimizer
    optimizer = ConfluenceOptimizer()
    optimizer.fit(all_trades)

    # Save results
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    optimizer.save(str(out_dir / "booster_scores.json"))
    print(f"\nSaved optimizer state to {out_dir / 'booster_scores.json'}")

    # Generate report
    report = optimizer.get_report()
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"Saved report to {report_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("CONFLUENCE OPTIMIZER RESULTS")
    print("=" * 60)

    for strategy, strat_data in report["strategies"].items():
        print(f"\n--- {strategy} ---")
        boosters = strat_data["boosters"]
        if not boosters:
            print("  (no boosters with enough data)")
            continue

        print(f"  Top boosters (by WR lift):")
        for b in boosters[:8]:
            arrow = "↑" if b["lift_pct"] > 0 else "↓"
            print(f"    {arrow} {b['name']:30s} {b['lift_pct']:+.1f}% lift  "
                  f"(n={b['sample_with']}, {b['confidence']})")

        combos = strat_data.get("top_combos", [])
        if combos:
            print(f"  Top combos:")
            for c in combos[:3]:
                tag = "ADDITIVE" if c["is_additive"] else "redundant"
                print(f"    {c['pair']:40s} {c['combined_lift']:+.1f}% [{tag}]")

        optimal = strat_data.get("optimal_menu", [])
        if optimal:
            print(f"  Optimal menu: {', '.join(optimal[:5])}")

    print("\nDone.")


if __name__ == "__main__":
    main()
