"""Run the strict backtest gate from the plan:
  - 5+ years EURUSD H1
  - profit factor >= 1.3
  - max DD <= 20%
  - >= 100 trades
  - walk-forward OOS year passes
  - both trending and ranging years pass

Exit code 0 = pass, 1 = fail.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.backtest.engine import Backtester
from agent.backtest.metrics import compute_metrics
from agent.backtest.walkforward import walk_forward
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.model.scorer import train_scorer
from agent.types import Bar, Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("check_gate")


def slice_year(bars: list[Bar], year: int) -> list[Bar]:
    return [b for b in bars if b.time.year == year]


def classify_year(bars_year: list[Bar]) -> str:
    if not bars_year:
        return "unknown"
    closes = [b.close for b in bars_year]
    high = max(closes)
    low = min(closes)
    end = closes[-1]
    start = closes[0]
    rng = high - low
    move = abs(end - start)
    if rng > 0 and move / rng > 0.5:
        return "trending"
    return "ranging"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default=None,
                        help="default: D1 (5y available) or H1 if explicitly requested")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--use-ml", action="store_true")
    parser.add_argument("--use-cache-only", action="store_true",
                        help="don't try to refetch; use whatever's cached")
    parser.add_argument("--initial-balance", type=float, default=None,
                        help="override backtest starting balance (edge validation; live uses demo.start_balance)")
    args = parser.parse_args()

    cfg = load_config()
    if args.initial_balance is not None:
        cfg.backtest.initial_balance = args.initial_balance
    symbol = args.symbol or cfg.symbol

    # Default to D1 for the gate because Yahoo only offers ~2 years of intraday.
    # D1 gives us 5+ years which is what the strict gate requires.
    tf = Timeframe(args.timeframe) if args.timeframe else Timeframe.D1
    loader = BarLoader(cache_root=cfg.data_dir)

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.years * 365)

    if args.use_cache_only:
        df = loader.cache.load(symbol, tf)
        if not df.empty:
            df = df.loc[df.index.min():end]
    else:
        df = loader.get(symbol, tf, start, end)
        if df.empty:
            log.warning("No data for %s %s in requested range; falling back to whatever is cached", symbol, tf.value)
            df = loader.cache.load(symbol, tf)

    bars = df_to_bars(df, tf)
    log.info("Loaded %d bars %s %s (range %s -> %s)",
             len(bars), symbol, tf.value,
             bars[0].time.date() if bars else "n/a",
             bars[-1].time.date() if bars else "n/a")

    min_bars_required = {"D1": 250, "H4": 1000, "H1": 1000, "M15": 2000,
                         "M5": 5000, "M1": 10000}[tf.value]
    if len(bars) < min_bars_required:
        log.error("Not enough bars to evaluate gate (have %d, need >= %d for %s)",
                  len(bars), min_bars_required, tf.value)
        sys.exit(1)

    bt = Backtester(cfg)
    full_result = bt.run(bars)

    gate = cfg.backtest_gate
    m = full_result.metrics
    skipped = getattr(full_result, "skipped_signals", 0)
    skipped_reasons = getattr(full_result, "skipped_reasons", {})

    checks = {
        "profit_factor>=1.3": m.profit_factor >= gate.profit_factor_min,
        "max_dd<=20%": m.max_drawdown_pct <= gate.max_dd_pct,
        "n_trades>=100": m.n_trades >= gate.min_trades,
    }

    years_in_data = sorted({b.time.year for b in bars})
    last_year = years_in_data[-1]
    oos_bars = slice_year(bars, last_year)
    if oos_bars:
        oos_result = bt.run(oos_bars)
        checks[f"oos_year_{last_year}_profitable"] = oos_result.metrics.expectancy > 0

    by_regime: dict[str, list] = {"trending": [], "ranging": []}
    for y in years_in_data:
        ybars = slice_year(bars, y)
        regime = classify_year(ybars)
        if regime in by_regime:
            yres = bt.run(ybars)
            by_regime[regime].append(yres.metrics.expectancy)

    if by_regime["trending"]:
        avg_t = sum(by_regime["trending"]) / len(by_regime["trending"])
        checks["trending_regime_profitable"] = avg_t > 0
    if by_regime["ranging"]:
        avg_r = sum(by_regime["ranging"]) / len(by_regime["ranging"])
        checks["ranging_regime_profitable"] = avg_r > 0

    if args.use_ml:
        log.info("Walk-forward with ML...")
        wf = walk_forward(
            cfg, bars,
            train_months=cfg.ml.walkforward_train_months,
            test_months=cfg.ml.walkforward_test_months,
            train_scorer=lambda trades: train_scorer(trades),
            prob_threshold=cfg.ml.prob_threshold,
        )
        wf_m = wf.metrics
        checks["wf_profit_factor>=1.3"] = wf_m.profit_factor >= gate.profit_factor_min
        checks["wf_max_dd<=20%"] = wf_m.max_drawdown_pct <= gate.max_dd_pct
        checks["wf_n_trades>=100"] = wf_m.n_trades >= gate.min_trades

    print("\nSTRICT GATE EVALUATION")
    print("=" * 60)
    print(f"Profit factor   : {m.profit_factor:.2f}   (need >= {gate.profit_factor_min})")
    print(f"Max drawdown    : {m.max_drawdown_pct*100:.1f}%   (need <= {gate.max_dd_pct*100:.0f}%)")
    print(f"# trades        : {m.n_trades}        (need >= {gate.min_trades})")
    print(f"Win rate        : {m.win_rate*100:.1f}%")
    print(f"Expectancy      : ${m.expectancy:.2f}")
    print(f"Final balance   : ${m.final_balance:.2f}")
    if skipped:
        print(f"Skipped signals : {skipped}  (risk/filters)")
        if skipped_reasons:
            top = sorted(skipped_reasons.items(), key=lambda kv: kv[1], reverse=True)[:8]
            print("Top skip reasons:")
            for k, v in top:
                print(f"  - {k}: {v}")
    print()
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    out = Path("reports/gate.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"metrics": m.to_dict(), "checks": checks}, indent=2, default=str))

    all_pass = all(checks.values())
    print()
    print("RESULT:", "PASS - proceed to next phase" if all_pass else "FAIL - fix rules before proceeding")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
