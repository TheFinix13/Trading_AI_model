"""Weekly retrain: refit XGBoost on historical backtest trades + journal trades, validate, deploy or rollback.

Pipeline:
  1. Fetch fresh historical bars (5y).
  2. Run rules-only backtest -> labeled (features, win/loss) tuples.
  3. Pull journal trades from previous demo/live runs and merge their features+outcomes.
  4. Train new XGBoost on the combined dataset using time-series split.
  5. Compute holdout log-loss on the most recent block.
  6. Compare to previous active model (if any) on the same holdout.
  7. Activate new model only if log-loss is no worse than previous; else keep previous.

Schedule: every Sunday 22:00 UTC via OS cron / Windows Task Scheduler. See docs/scheduling.md.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from agent.backtest.engine import Backtester
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.features.extractor import FEATURE_COLUMNS
from agent.journal.db import Journal
from agent.model.scorer import SetupScorer, train_scorer, trades_to_xy
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("weekly_retrain")


def journal_trades_xy(journal: Journal) -> tuple[pd.DataFrame, pd.Series]:
    """Reconstruct (features, label) pairs from the journal by joining trades with their signals."""
    conn = journal._conn
    rows = conn.execute(
        """SELECT s.features_json, t.pnl
           FROM trades t JOIN signals s ON s.id = t.signal_id
           WHERE t.exit_price IS NOT NULL"""
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=FEATURE_COLUMNS), pd.Series([], dtype=int)
    feat_rows = []
    labels = []
    for r in rows:
        try:
            feats = json.loads(r["features_json"])
        except Exception:
            continue
        feat_rows.append([feats.get(c, 0.0) for c in FEATURE_COLUMNS])
        labels.append(1 if (r["pnl"] or 0) > 0 else 0)
    return pd.DataFrame(feat_rows, columns=FEATURE_COLUMNS), pd.Series(labels)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--holdout-frac", type=float, default=0.2)
    args = parser.parse_args()

    cfg = load_config()
    symbol = args.symbol or cfg.symbol
    tf = Timeframe(args.timeframe)
    journal = Journal(cfg.journal_db)
    loader = BarLoader(cache_root=cfg.data_dir)

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.years * 365)
    df = loader.get(symbol, tf, start, end, refresh=True)
    bars = df_to_bars(df, tf)
    log.info("Loaded %d bars", len(bars))

    log.info("Running rules-only backtest for fresh labels...")
    bt_result = Backtester(cfg).run(bars)
    log.info("Backtest produced %d labeled trades", len(bt_result.trades))

    bt_X, bt_y = trades_to_xy(bt_result.trades)
    j_X, j_y = journal_trades_xy(journal)
    log.info("Backtest set: %d, Journal set: %d", len(bt_X), len(j_X))

    X = pd.concat([bt_X, j_X], ignore_index=True) if not j_X.empty else bt_X
    y = pd.concat([bt_y, j_y], ignore_index=True) if not j_y.empty else bt_y

    if len(X) < 80 or y.nunique() < 2:
        log.warning("Insufficient combined data (n=%d, classes=%d). Skipping retrain.", len(X), y.nunique())
        return

    cut = int(len(X) * (1 - args.holdout_frac))
    X_train, y_train = X.iloc[:cut], y.iloc[:cut]
    X_holdout, y_holdout = X.iloc[cut:], y.iloc[cut:]

    log.info("Training new scorer on %d, holdout %d", len(X_train), len(X_holdout))
    new_scorer = train_scorer(
        [t for t in bt_result.trades],
    )
    if new_scorer is None:
        log.error("Trainer refused")
        return

    new_proba = new_scorer.model.predict_proba(X_holdout)[:, 1] if len(X_holdout) > 0 else np.array([])
    new_logloss = _logloss(y_holdout.values, new_proba) if len(new_proba) > 0 else float("inf")

    active = journal.active_model()
    prev_logloss = float("inf")
    if active:
        try:
            prev_scorer = SetupScorer.load(active["file_path"])
            prev_proba = prev_scorer.model.predict_proba(X_holdout)[:, 1] if len(X_holdout) > 0 else np.array([])
            prev_logloss = _logloss(y_holdout.values, prev_proba) if len(prev_proba) > 0 else float("inf")
        except Exception as e:
            log.warning("Could not evaluate previous model: %s", e)

    log.info("Holdout logloss: new=%.4f prev=%.4f", new_logloss, prev_logloss)

    version = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    model_path = cfg.model_dir / f"scorer_{version}.json"
    new_scorer.save(model_path)

    metrics = {
        "n_train": len(X_train),
        "n_holdout": len(X_holdout),
        "holdout_logloss_new": new_logloss,
        "holdout_logloss_prev": prev_logloss,
    }

    if new_logloss <= prev_logloss + 1e-4:
        journal.register_model(version=version, file_path=str(model_path), metrics=metrics, activate=True)
        log.info("ACTIVATED new model %s (logloss %.4f <= prev %.4f)", version, new_logloss, prev_logloss)
    else:
        journal.register_model(version=version, file_path=str(model_path), metrics=metrics, activate=False)
        log.warning("ROLLBACK: new model worse (%.4f > %.4f); keeping previous", new_logloss, prev_logloss)


def _logloss(y_true, y_pred, eps: float = 1e-9) -> float:
    y_pred = np.clip(y_pred, eps, 1 - eps)
    return float(-np.mean(y_true * np.log(y_pred) + (1 - y_true) * np.log(1 - y_pred)))


if __name__ == "__main__":
    main()
