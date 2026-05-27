"""Train the LZI-specific ML scorer.

End-to-end pipeline:
  1. Load H1 bars
  2. Run LZI detector → get zones
  3. Simulate retest entries → label WIN/LOSS
  4. Extract LZI features
  5. Walk-forward train XGBoost with Platt calibration
  6. Evaluate on hold-out test set
  7. Save model

Usage:
    PYTHONPATH=. .venv/bin/python scripts/train_lzi_scorer.py
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, precision_recall_curve

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.detectors.liquidity_zones import (
    LiquidityZone,
    check_retest_entries,
    detect_liquidity_zones,
)
from agent.detectors.pd_array import collect_opposite_liquidity_levels
from agent.detectors.swings import detect_swings
from agent.detectors.daily_levels import compute_daily_levels
from agent.features.lzi_extractor import LZI_FEATURE_COLUMNS, extract_lzi_features
from agent.types import Bar, Direction, Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PIP = 0.0001
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_h1_bars(start: str, end: str) -> list[Bar]:
    """Load H1 bars from parquet, filtered by date range."""
    path = PROJECT_ROOT / "data" / "parquet" / "EURUSD_H1.parquet"
    df = pd.read_parquet(path)
    # Time is in the index (DatetimeIndex)
    if "time" not in df.columns:
        df = df.reset_index()
        df.rename(columns={df.columns[0]: "time"}, inplace=True)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    mask = (df["time"] >= pd.Timestamp(start, tz="UTC")) & (df["time"] <= pd.Timestamp(end, tz="UTC"))
    df = df[mask].reset_index(drop=True)
    bars = []
    for _, row in df.iterrows():
        bars.append(Bar(
            time=row["time"].to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
            timeframe=Timeframe.H1,
        ))
    log.info("Loaded %d H1 bars from %s to %s", len(bars), start, end)
    return bars


def simulate_trade_outcome(
    bars: list[Bar],
    entry_bar_index: int,
    stop_price: float,
    tp_price: float,
    direction: Direction,
    max_bars: int = 200,
) -> str:
    """Simulate: after entry, does price hit TP or SL first? Returns 'win' or 'loss'."""
    for i in range(entry_bar_index + 1, min(entry_bar_index + max_bars + 1, len(bars))):
        bar = bars[i]
        if direction == Direction.LONG:
            if bar.low <= stop_price:
                return "loss"
            if bar.high >= tp_price:
                return "win"
        else:
            if bar.high >= stop_price:
                return "loss"
            if bar.low <= tp_price:
                return "win"
    return "loss"  # expired = loss


def generate_lzi_dataset(
    bars: list[Bar],
    min_wick_size_pips: float = 10.0,
) -> pd.DataFrame:
    """Run LZI detector on bars and generate labeled feature dataset."""
    log.info("Detecting liquidity zones (min_wick=%.1f pips)...", min_wick_size_pips)
    zones = detect_liquidity_zones(bars, min_wick_size_pips=min_wick_size_pips)
    log.info("  Found %d zones", len(zones))

    swings = detect_swings(bars, lookback=5)
    daily_levels_list = compute_daily_levels(bars)

    rows: list[dict] = []
    total_entries = 0

    for i in range(len(bars)):
        active = [z for z in zones if z.status not in ("triggered", "expired") and z.formation_bar_index < i]
        if not active:
            continue

        for direction in (Direction.LONG, Direction.SHORT):
            dir_zones = [z for z in active if z.trade_direction == direction]
            if not dir_zones:
                continue

            dl = daily_levels_list[i] if i < len(daily_levels_list) else None
            opp_levels = collect_opposite_liquidity_levels(
                bars, i, direction, daily_levels=dl, swings=swings,
            )

            entries = check_retest_entries(
                bars, dir_zones, i,
                opposite_liquidity_levels=opp_levels or None,
                retest_max_bars=50,
                retest_proximity_pips=5.0,
                consumption_min_bars=2,
                displacement_min_body_pct=0.60,
                displacement_min_pips=8.0,
                zone_expiry_bars=100,
                stop_buffer_pips=3.0,
                fallback_rr=2.0,
                use_pd_array_targeting=True,
            )

            for entry in entries:
                total_entries += 1
                outcome = simulate_trade_outcome(
                    bars, entry.entry_bar_index,
                    entry.stop_price, entry.tp_price,
                    entry.direction,
                )
                features = extract_lzi_features(
                    bars, entry.zone, entry.entry_bar_index, entry.tp_price,
                )
                row = features.to_dict()
                row["outcome"] = 1 if outcome == "win" else 0
                row["entry_time"] = bars[entry.entry_bar_index].time.isoformat()
                row["direction"] = entry.direction.value
                row["entry_price"] = entry.entry_price
                row["stop_price"] = entry.stop_price
                row["tp_price"] = entry.tp_price
                row["r_multiple"] = entry.r_multiple
                row["swept_label"] = entry.zone.swept_label
                rows.append(row)

    df = pd.DataFrame(rows)
    if len(df) > 0:
        wr = df["outcome"].mean() * 100
        log.info("Generated %d LZI trades: %.1f%% WR", len(df), wr)
    else:
        log.warning("No LZI trades generated!")
    return df


def walk_forward_train(df: pd.DataFrame) -> tuple:
    """Walk-forward cross-validation with 3 folds, then train final model on all data.

    Returns (final_model, fold_results).
    """
    df["entry_time_dt"] = pd.to_datetime(df["entry_time"])

    folds = [
        ("2020-06-01", "2022-06-30", "2022-07-01", "2023-03-31"),
        ("2020-06-01", "2023-03-31", "2023-04-01", "2023-09-30"),
        ("2020-06-01", "2023-09-30", "2023-10-01", "2023-12-31"),
    ]

    fold_results = []
    stable_features: dict[str, int] = {f: 0 for f in LZI_FEATURE_COLUMNS}

    for fold_idx, (train_start, train_end, test_start, test_end) in enumerate(folds):
        train_mask = (df["entry_time_dt"] >= train_start) & (df["entry_time_dt"] <= train_end)
        test_mask = (df["entry_time_dt"] >= test_start) & (df["entry_time_dt"] <= test_end)
        train_df = df[train_mask]
        test_df = df[test_mask]

        if len(train_df) < 30 or len(test_df) < 5:
            log.warning("Fold %d: insufficient data (train=%d, test=%d)", fold_idx + 1, len(train_df), len(test_df))
            fold_results.append({"fold": fold_idx + 1, "auc": 0.5, "skip": True})
            continue

        X_train = train_df[LZI_FEATURE_COLUMNS].values
        y_train = train_df["outcome"].values
        X_test = test_df[LZI_FEATURE_COLUMNS].values
        y_test = test_df["outcome"].values

        model = _build_xgb(y_train)
        model.fit(X_train, y_train)

        proba = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, proba) if len(np.unique(y_test)) > 1 else 0.5

        # Precision at recall ~0.25
        if len(np.unique(y_test)) > 1:
            prec, rec, _ = precision_recall_curve(y_test, proba)
            idx = np.where(rec >= 0.25)[0]
            p_at_r25 = float(prec[idx[-1]]) if len(idx) > 0 else 0.0
        else:
            p_at_r25 = 0.0

        # WR at threshold 0.25
        passed = proba >= 0.25
        wr_at_thresh = y_test[passed].mean() if passed.sum() > 0 else 0.0
        n_passed = int(passed.sum())

        # Feature importance for stability check
        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        else:
            importances = np.zeros(len(LZI_FEATURE_COLUMNS))
        top_features = np.argsort(importances)[-5:]
        for fi in top_features:
            stable_features[LZI_FEATURE_COLUMNS[fi]] += 1

        result = {
            "fold": fold_idx + 1,
            "train_n": len(train_df),
            "test_n": len(test_df),
            "auc": auc,
            "precision_at_recall_25": p_at_r25,
            "wr_at_threshold_25": wr_at_thresh,
            "n_passed_threshold": n_passed,
            "skip": False,
        }
        fold_results.append(result)
        log.info("Fold %d: AUC=%.3f, P@R25=%.3f, WR@0.25=%.1f%% (%d passed)",
                 fold_idx + 1, auc, p_at_r25, wr_at_thresh * 100, n_passed)

    # Feature stability
    log.info("Feature stability (predictive in 2+/3 folds):")
    for feat, count in sorted(stable_features.items(), key=lambda x: -x[1]):
        if count >= 2:
            log.info("  %s: %d/3 folds", feat, count)

    # Train final model on all training data with Platt calibration
    log.info("Training final model on full training set with Platt scaling...")
    X_all = df[LZI_FEATURE_COLUMNS].values
    y_all = df["outcome"].values

    base_model = _build_xgb(y_all)
    calibrated = CalibratedClassifierCV(base_model, method="sigmoid", cv=3)
    calibrated.fit(X_all, y_all)

    return calibrated, fold_results, stable_features


def _build_xgb(y_train: np.ndarray):
    """Build XGBClassifier with aggressive regularization for small samples."""
    try:
        from xgboost import XGBClassifier
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(
            max_iter=100, max_depth=3, learning_rate=0.05,
            l2_regularization=5.0, random_state=42,
        )

    pos = float(y_train.sum())
    neg = float(len(y_train) - pos)
    spw = neg / pos if pos > 0 else 1.0

    return XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.05,
        min_child_weight=10,
        subsample=0.7,
        colsample_bytree=0.8,
        reg_lambda=5.0,
        reg_alpha=1.0,
        scale_pos_weight=spw,
        eval_metric="logloss",
        tree_method="hist",
        random_state=42,
    )


def evaluate_on_test(model, test_df: pd.DataFrame, threshold: float = 0.25) -> dict:
    """Evaluate trained model on test set trades."""
    X_test = test_df[LZI_FEATURE_COLUMNS].values
    y_test = test_df["outcome"].values

    proba = model.predict_proba(X_test)[:, 1]
    test_df = test_df.copy()
    test_df["score"] = proba

    passed = proba >= threshold
    n_passed = int(passed.sum())
    n_failed = int((~passed).sum())

    wr_passed = y_test[passed].mean() if n_passed > 0 else 0.0
    wr_failed = y_test[~passed].mean() if n_failed > 0 else 0.0
    wr_all = y_test.mean()

    auc = roc_auc_score(y_test, proba) if len(np.unique(y_test)) > 1 else 0.5

    # Feature importance from base estimator
    importances = {}
    try:
        base = model.estimators_[0] if hasattr(model, "estimators_") else model
        if hasattr(base, "feature_importances_"):
            for i, col in enumerate(LZI_FEATURE_COLUMNS):
                importances[col] = float(base.feature_importances_[i])
    except Exception:
        pass

    results = {
        "total_trades": len(test_df),
        "n_passed": n_passed,
        "n_failed": n_failed,
        "wr_all": wr_all,
        "wr_passed": wr_passed,
        "wr_failed": wr_failed,
        "auc": auc,
        "feature_importances": importances,
    }
    return results


def main():
    # --- Phase 1: Generate training data ---
    log.info("=" * 60)
    log.info("PHASE 1: Generating LZI training data (2020-06 to 2023-12)")
    log.info("=" * 60)
    train_bars = load_h1_bars("2020-05-28", "2023-12-31")
    train_df = generate_lzi_dataset(train_bars, min_wick_size_pips=10.0)

    if len(train_df) < 50:
        log.error("Not enough training samples (%d). Need >= 50.", len(train_df))
        sys.exit(1)

    # Save training data for reproducibility
    train_csv_path = PROJECT_ROOT / "data" / "lzi_training_data.csv"
    train_df.to_csv(train_csv_path, index=False)
    log.info("Saved training data to %s", train_csv_path)

    # --- Phase 2: Walk-forward training ---
    log.info("=" * 60)
    log.info("PHASE 2: Walk-forward training (3 folds)")
    log.info("=" * 60)
    model, fold_results, stable_features = walk_forward_train(train_df)

    # Check OOS AUC
    valid_folds = [f for f in fold_results if not f.get("skip")]
    avg_auc = np.mean([f["auc"] for f in valid_folds]) if valid_folds else 0.5
    log.info("Average OOS AUC: %.3f", avg_auc)

    if avg_auc < 0.55:
        log.warning(
            "OOS AUC (%.3f) < 0.55 — features may not discriminate well. "
            "Consider (a) more data or (b) different features. Saving model anyway.",
            avg_auc,
        )

    # Save model
    model_path = PROJECT_ROOT / "models" / "scorer_EURUSD_LZI_H1_v1.joblib"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model,
        "feature_cols": LZI_FEATURE_COLUMNS,
        "backend": "xgboost_calibrated",
        "train_samples": len(train_df),
        "avg_oos_auc": avg_auc,
        "fold_results": fold_results,
    }, model_path)
    log.info("Saved model to %s", model_path)

    # --- Phase 3: Evaluate on test set ---
    log.info("=" * 60)
    log.info("PHASE 3: Evaluating on test set (2024-01 to 2026-05)")
    log.info("=" * 60)
    test_bars = load_h1_bars("2024-01-01", "2026-05-26")
    test_df = generate_lzi_dataset(test_bars, min_wick_size_pips=10.0)

    if len(test_df) == 0:
        log.error("No test set trades generated!")
        sys.exit(1)

    test_csv_path = PROJECT_ROOT / "data" / "lzi_test_data.csv"
    test_df.to_csv(test_csv_path, index=False)
    log.info("Saved test data to %s", test_csv_path)

    results = evaluate_on_test(model, test_df, threshold=0.25)

    log.info("=" * 60)
    log.info("TEST SET RESULTS")
    log.info("=" * 60)
    log.info("Total trades: %d", results["total_trades"])
    log.info("Baseline WR (all): %.1f%%", results["wr_all"] * 100)
    log.info("Trades passing threshold 0.25: %d / %d", results["n_passed"], results["total_trades"])
    log.info("WR of passed trades: %.1f%%", results["wr_passed"] * 100)
    log.info("WR of failed trades: %.1f%%", results["wr_failed"] * 100)
    log.info("OOS AUC: %.3f", results["auc"])
    log.info("")
    log.info("Feature importances:")
    for feat, imp in sorted(results["feature_importances"].items(), key=lambda x: -x[1])[:10]:
        log.info("  %s: %.4f", feat, imp)

    improvement = results["wr_passed"] - results["wr_all"]
    log.info("")
    if results["wr_passed"] >= 0.22:
        log.info("SUCCESS: Scorer pushes WR from %.1f%% to %.1f%% (+%.1f pp)",
                 results["wr_all"] * 100, results["wr_passed"] * 100, improvement * 100)
    else:
        log.warning("MARGINAL: WR only %.1f%% (target was 22%%+). Features may need revision.",
                    results["wr_passed"] * 100)

    # Anti-overfitting checklist
    log.info("")
    log.info("ANTI-OVERFITTING CHECKLIST:")
    log.info("  [%s] Max 15 features: %d features", "x" if len(LZI_FEATURE_COLUMNS) <= 15 else " ", len(LZI_FEATURE_COLUMNS))
    log.info("  [x] Walk-forward (never random split on time series)")
    stable_count = sum(1 for v in stable_features.values() if v >= 2)
    log.info("  [%s] Feature stability: %d/%d features predictive in 2+/3 folds",
             "x" if stable_count >= 5 else " ", stable_count, len(LZI_FEATURE_COLUMNS))
    log.info("  [x] max_depth=3, min_child_weight=10, reg_lambda=5.0")
    log.info("  [x] Platt calibration (sigmoid)")
    log.info("  [%s] OOS AUC > 0.55: %.3f", "x" if avg_auc > 0.55 else " ", avg_auc)


if __name__ == "__main__":
    main()
