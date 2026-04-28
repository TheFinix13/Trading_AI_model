"""Run backtests and apply the strict gate.

Usage:
  python scripts/run_backtest.py --rules-only        # rules engine only
  python scripts/run_backtest.py --compare           # rules-only vs rules+ML
  python scripts/run_backtest.py --walkforward       # walk-forward with ML
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.backtest.engine import Backtester
from agent.backtest.metrics import PerfMetrics
from agent.backtest.walkforward import walk_forward
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.model.scorer import train_scorer
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run_backtest")


def print_metrics(name: str, m: PerfMetrics) -> None:
    print(f"\n{'='*60}")
    print(f"{name}")
    print(f"{'='*60}")
    print(f"  Trades            : {m.n_trades}")
    print(f"  Win rate          : {m.win_rate*100:.1f}%")
    print(f"  Profit factor     : {m.profit_factor:.2f}")
    print(f"  Expectancy        : ${m.expectancy:.2f} / {m.expectancy_pips:.1f} pips")
    print(f"  Avg win / loss    : ${m.avg_win:.2f} / ${m.avg_loss:.2f}")
    print(f"  Max drawdown      : ${m.max_drawdown:.2f} ({m.max_drawdown_pct*100:.1f}%)")
    print(f"  Final balance     : ${m.final_balance:.2f}")
    print(f"  Total return      : {m.total_return_pct*100:.1f}%")
    print(f"  Sharpe (ann.)     : {m.sharpe:.2f}")
    print(f"  Largest trade %   : {m.largest_trade_share*100:.1f}%")


def evaluate_gate(m: PerfMetrics, cfg) -> dict:
    gate = cfg.backtest_gate
    checks = {
        "profit_factor>=1.3": m.profit_factor >= gate.profit_factor_min,
        "max_dd<=20%": m.max_drawdown_pct <= gate.max_dd_pct,
        "n_trades>=100": m.n_trades >= gate.min_trades,
    }
    return checks


def load_bars(cfg, symbol: str, timeframe: Timeframe, years: int):
    loader = BarLoader(cache_root=cfg.data_dir)
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=years * 365)
    df = loader.get(symbol, timeframe, start, end, refresh=False)
    return df_to_bars(df, timeframe)


def run_rules_only(cfg, bars):
    bt = Backtester(cfg)
    return bt.run(bars)


def run_with_ml(cfg, bars):
    """Train on first half, test on second half."""
    half = len(bars) // 2
    train_bars = bars[:half]
    test_bars = bars[half:]

    log.info("Training scorer on first half (%d bars)...", len(train_bars))
    train_result = run_rules_only(cfg, train_bars)
    if not train_result.trades:
        log.warning("No training trades; skipping ML")
        return run_rules_only(cfg, test_bars)
    scorer = train_scorer(train_result.trades)
    if scorer is None:
        log.warning("Scorer training returned None; running rules-only on test set")
        return run_rules_only(cfg, test_bars)

    log.info("Running test backtest with ML scorer (threshold=%.2f)...", cfg.ml.prob_threshold)
    bt = Backtester(cfg, scorer=scorer, prob_threshold=cfg.ml.prob_threshold)
    return bt.run(test_bars)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--walkforward", action="store_true")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--out", default="reports/backtest")
    args = parser.parse_args()

    cfg = load_config()
    symbol = args.symbol or cfg.symbol
    tf = Timeframe(args.timeframe)
    bars = load_bars(cfg, symbol, tf, args.years)
    log.info("Loaded %d bars of %s %s", len(bars), symbol, tf.value)

    if not bars:
        log.error("No bars loaded. Run scripts/download_data.py first.")
        return

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.rules_only or (not args.compare and not args.walkforward):
        result = run_rules_only(cfg, bars)
        print_metrics("RULES-ONLY", result.metrics)
        gate = evaluate_gate(result.metrics, cfg)
        print("\nGate checks:")
        for k, v in gate.items():
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        (out_dir / "rules_only_metrics.json").write_text(json.dumps(result.metrics.to_dict(), default=str, indent=2))

    if args.compare:
        rules_result = run_rules_only(cfg, bars)
        ml_result = run_with_ml(cfg, bars)
        print_metrics("RULES-ONLY (full data)", rules_result.metrics)
        print_metrics("RULES + ML (test half)", ml_result.metrics)
        (out_dir / "compare.json").write_text(
            json.dumps(
                {
                    "rules_only": rules_result.metrics.to_dict(),
                    "rules_plus_ml": ml_result.metrics.to_dict(),
                },
                default=str,
                indent=2,
            )
        )

    if args.walkforward:
        log.info("Running walk-forward...")
        wf = walk_forward(
            cfg,
            bars,
            train_months=cfg.ml.walkforward_train_months,
            test_months=cfg.ml.walkforward_test_months,
            train_scorer=lambda trades: train_scorer(trades),
            prob_threshold=cfg.ml.prob_threshold,
        )
        print_metrics(f"WALK-FORWARD ({len(wf.folds)} folds, ML on)", wf.metrics)
        (out_dir / "walkforward.json").write_text(json.dumps(wf.metrics.to_dict(), default=str, indent=2))


if __name__ == "__main__":
    main()
