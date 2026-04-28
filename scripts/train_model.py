"""Train the XGBoost scorer on a backtest's labeled trades and save it.

Pipeline:
  1. Load cached bars for the configured symbol/timeframe.
  2. Run the rules-only backtester to produce labeled trades (features, win/loss).
  3. Fit XGBoost with walk-forward CV.
  4. Save model + register it in the journal.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.backtest.engine import Backtester
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.journal.db import Journal
from agent.model.scorer import train_scorer, trades_to_xy
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("train_model")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--version", default=None)
    args = parser.parse_args()

    cfg = load_config()
    symbol = args.symbol or cfg.symbol
    tf = Timeframe(args.timeframe)
    loader = BarLoader(cache_root=cfg.data_dir)
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.years * 365)
    df = loader.get(symbol, tf, start, end)
    bars = df_to_bars(df, tf)
    log.info("Loaded %d bars", len(bars))

    log.info("Running rules-only backtest to label trades...")
    bt = Backtester(cfg)
    result = bt.run(bars)
    log.info("Got %d labeled trades", len(result.trades))

    if len(result.trades) < 50:
        log.error("Not enough trades to train (n=%d, need >= 50)", len(result.trades))
        return

    log.info("Training XGBoost scorer...")
    scorer = train_scorer(result.trades)
    if scorer is None:
        log.error("Trainer refused (insufficient diversity)")
        return

    X, y = trades_to_xy(result.trades)
    train_acc = float((scorer.model.predict(X) == y).mean())

    version = args.version or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    model_path = cfg.model_dir / f"scorer_{version}.json"
    scorer.save(model_path)
    log.info("Saved model to %s", model_path)

    metrics = {
        "n_trades": len(result.trades),
        "train_accuracy": train_acc,
        "win_rate": result.metrics.win_rate,
        "profit_factor": result.metrics.profit_factor,
        "expectancy": result.metrics.expectancy,
    }
    journal = Journal(cfg.journal_db)
    journal.register_model(version=version, file_path=str(model_path), metrics=metrics, activate=True)
    log.info("Registered model version %s as active", version)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
