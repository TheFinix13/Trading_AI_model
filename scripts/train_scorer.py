"""Train the rule-engine setup scorer with walk-forward validation.

The scorer ranks rule-engine setups: it doesn't generate new ones. Workflow:

  1. Pull cached bars for one timeframe.
  2. Split into train / validation chunks.
  3. Run a no-scorer backtest on each split to collect (features, win/loss) pairs.
  4. Train a calibrated XGBoost / sklearn classifier on the train split.
  5. Evaluate on validation: PF, calibration (Brier, ECE).
  6. Save the model when validation looks honest.

Usage:
  python scripts/train_scorer.py --tf D1 --use-cache-only
  python scripts/train_scorer.py --tf H1 --train-frac 0.7 --threshold 0.55"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

from agent.analysis.calibration import calibration_report
from agent.backtest.engine import Backtester
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.features.extractor import FEATURE_COLUMNS
from agent.model.scorer import collect_training_data, train_scorer
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("train_scorer")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--tf", default="D1")
    parser.add_argument("--use-cache-only", action="store_true")
    parser.add_argument("--train-frac", type=float, default=0.70,
                        help="fraction of bars used for training; rest is held-out validation")
    parser.add_argument("--threshold", type=float, default=0.55,
                        help="probability threshold for taking a setup at backtest time")
    parser.add_argument("--no-calibrate", action="store_true",
                        help="disable isotonic probability calibration (NOT recommended)")
    parser.add_argument("--start-date", type=str, default=None,
                        help="restrict bars to this start date (YYYY-MM-DD). "
                             "Useful for training on recent regimes only.")
    parser.add_argument("--end-date", type=str, default=None,
                        help="restrict bars to this end date (YYYY-MM-DD).")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    cfg = load_config()
    symbol = args.symbol or cfg.symbol
    tf = Timeframe(args.tf)

    loader = BarLoader(cache_root=cfg.data_dir)
    df = loader.cache.load(symbol, tf)
    if df.empty:
        log.error("No cached %s data; run scripts/download_data.py first", tf.value)
        sys.exit(1)
    bars = df_to_bars(df, tf)
    log.info("Loaded %d bars %s %s", len(bars), symbol, tf.value)

    if args.start_date or args.end_date:
        from datetime import datetime, timezone
        if args.start_date:
            sd = datetime.fromisoformat(args.start_date).replace(tzinfo=timezone.utc)
            bars = [b for b in bars if b.time >= sd]
        if args.end_date:
            ed = datetime.fromisoformat(args.end_date).replace(tzinfo=timezone.utc)
            bars = [b for b in bars if b.time < ed]
        log.info("After date filter: %d bars [%s .. %s]",
                 len(bars), bars[0].time, bars[-1].time)

    cut = int(len(bars) * args.train_frac)
    train_bars = bars[:cut]
    val_bars = bars[cut:]
    log.info("Train: %d bars (%s..%s)", len(train_bars), train_bars[0].time, train_bars[-1].time)
    log.info("Val:   %d bars (%s..%s)", len(val_bars), val_bars[0].time, val_bars[-1].time)

    log.info("Collecting training labels (no-scorer backtest on train slice)...")
    train_data = collect_training_data(cfg, train_bars)
    if len(train_data) < 50:
        log.error("Not enough training setups (%d). Try a longer history or lower confluence.",
                  len(train_data))
        sys.exit(2)

    log.info("Training scorer (calibrate=%s)...", not args.no_calibrate)
    scorer = train_scorer(train_data, calibrate=not args.no_calibrate)

    log.info("Validating with scorer threshold=%.2f...", args.threshold)
    bt_val = Backtester(cfg, scorer=scorer, prob_threshold=args.threshold)
    result = bt_val.run(val_bars)
    m = result.metrics

    log.info("Validation: trades=%d  PF=%.2f  win=%.1f%%  exp=$%.2f  DD=%.1f%%",
             m.n_trades, m.profit_factor, m.win_rate*100, m.expectancy,
             m.max_drawdown_pct*100)

    # Calibration check on the validation slice
    val_data = collect_training_data(cfg, val_bars)
    if len(val_data) >= 30:
        probs = np.array([scorer(row.to_dict()) for _, row in val_data.X.iterrows()])
        rep = calibration_report(probs, val_data.y)
        print()
        print(rep)

    out = args.out or (cfg.model_dir / f"scorer_{symbol}_{tf.value}.joblib")
    out.parent.mkdir(parents=True, exist_ok=True)
    scorer.save(out)
    log.info("Saved scorer to %s", out)
    log.info("Use it with: Backtester(cfg, scorer=SetupScorer.load(%r), prob_threshold=%.2f)",
             str(out), args.threshold)


if __name__ == "__main__":
    main()
