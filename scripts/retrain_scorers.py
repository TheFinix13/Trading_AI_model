"""Quarterly retrain pipeline.

The walk-forward validation on 2026-05-03 proved the trading edge requires
fresh scorer training (last ~1.5 years of bars) to stay calibrated. A single
static scorer trained on 2021-2024 data does not generalise to 2025-2026.

This script:

  1. Loads the latest cached bars for the configured TFs.
  2. Trains a fresh scorer per TF on the trailing N years.
  3. Runs a walk-forward validation on each new scorer to confirm the edge
     before promoting it to production.
  4. Updates the production scorer files only if validation passes the gates.

Schedule via cron / launchd / GitHub Actions every 3 months::

    0 6 1 */3 *  cd /repo && PYTHONPATH=. ./.venv/bin/python scripts/retrain_scorers.py

Usage::

    python scripts/retrain_scorers.py                # use config defaults
    python scripts/retrain_scorers.py --tfs H1       # H1 only
    python scripts/retrain_scorers.py --dry-run      # validate without promoting
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.backtest.engine import Backtester
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.model.scorer import collect_training_data, train_scorer
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("retrain_scorers")

# Validation gates per TF — model must beat these to be promoted.
# Numbers are calibrated for a 3-month validation window (default).
# A typical H1 setup count is 8-15 in 3 months after all our gates fire.
PROMOTION_GATES = {
    "H1":  {"min_pf": 1.10, "min_wr": 0.50, "min_trades": 5, "max_dd": 0.10},
    "M15": {"min_pf": 1.00, "min_wr": 0.45, "min_trades": 3, "max_dd": 0.08},
}


def gates_pass(tf: str, n_trades: int, pf: float, wr: float, dd: float) -> tuple[bool, list[str]]:
    g = PROMOTION_GATES.get(tf, PROMOTION_GATES["H1"])
    failures = []
    if n_trades < g["min_trades"]:
        failures.append(f"n_trades={n_trades} < {g['min_trades']}")
    if pf < g["min_pf"]:
        failures.append(f"pf={pf:.2f} < {g['min_pf']}")
    if wr < g["min_wr"]:
        failures.append(f"wr={wr:.1%} < {g['min_wr']:.1%}")
    if dd > g["max_dd"]:
        failures.append(f"dd={dd:.1%} > {g['max_dd']:.1%}")
    return len(failures) == 0, failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tfs", nargs="+", default=["H1", "M15"], help="timeframes to retrain")
    ap.add_argument("--train-years", type=float, default=1.5,
                    help="years of bars to train on (default 1.5; walk-forward sweet spot)")
    ap.add_argument("--validate-months", type=int, default=3,
                    help="months of held-out data for validation (default 3)")
    ap.add_argument("--dry-run", action="store_true",
                    help="train + validate but don't overwrite production scorer")
    args = ap.parse_args()

    cfg = load_config()
    loader = BarLoader(cache_root=cfg.data_dir)

    today = datetime.now(timezone.utc)
    val_end = today
    val_start = today - timedelta(days=30 * args.validate_months)
    train_end = val_start
    train_start = train_end - timedelta(days=int(365 * args.train_years))
    log.info("Train: %s .. %s   Validate: %s .. %s",
             train_start.date(), train_end.date(),
             val_start.date(), val_end.date())

    manifest = {
        "retrained_at": today.isoformat(),
        "train_window": [train_start.isoformat(), train_end.isoformat()],
        "val_window": [val_start.isoformat(), val_end.isoformat()],
        "results": {},
    }

    for tf_str in args.tfs:
        tf = Timeframe(tf_str)
        log.info("\n%s===== %s =====", "\n", tf_str)
        df = loader.cache.load(cfg.symbol, tf)
        if df.empty:
            log.warning("%s: no cached bars; skipping", tf_str)
            continue
        bars = df_to_bars(df, tf)

        train_bars = [b for b in bars if train_start <= b.time < train_end]
        val_bars = [b for b in bars if val_start <= b.time < val_end]
        log.info("%s: train=%d bars  val=%d bars", tf_str, len(train_bars), len(val_bars))

        if len(train_bars) < 200 or len(val_bars) < 50:
            log.warning("%s: not enough bars; skipping", tf_str)
            continue

        train_data = collect_training_data(cfg, train_bars)
        if len(train_data) < 30:
            log.warning("%s: only %d training setups; skipping", tf_str, len(train_data))
            continue

        scorer = train_scorer(train_data, calibrate=True)
        log.info("%s: scorer trained on %d setups (%.1f%% winners)",
                 tf_str, len(train_data), train_data.y.mean() * 100)

        threshold = cfg.ml.score_thresholds.get(tf_str, 0.30)
        bt = Backtester(cfg, scorer=scorer, prob_threshold=threshold)
        res = bt.run(val_bars)
        m = res.metrics
        log.info("%s: validation trades=%d  PF=%.2f  WR=%.1f%%  DD=%.1f%%  ret=%+.1f%%",
                 tf_str, m.n_trades, m.profit_factor, m.win_rate * 100,
                 m.max_drawdown_pct * 100, m.total_return_pct * 100)

        ok, failures = gates_pass(tf_str, m.n_trades, m.profit_factor,
                                   m.win_rate, m.max_drawdown_pct)
        manifest["results"][tf_str] = {
            "n_trades": m.n_trades, "pf": m.profit_factor, "wr": m.win_rate,
            "dd": m.max_drawdown_pct, "ret": m.total_return_pct,
            "promoted": ok and not args.dry_run,
            "failures": failures,
        }

        if not ok:
            log.warning("%s: PROMOTION GATES FAILED: %s -- keeping current production scorer",
                        tf_str, "; ".join(failures))
            continue
        if args.dry_run:
            log.info("%s: would promote (--dry-run set)", tf_str)
            continue

        # Promote: write to versioned + canonical paths
        prod_path_str = cfg.ml.scorer_paths.get(tf_str)
        if not prod_path_str:
            log.warning("%s: no production path configured; skipping promotion", tf_str)
            continue
        prod_path = Path(prod_path_str)
        if not prod_path.is_absolute():
            prod_path = Path(__file__).resolve().parent.parent / prod_path
        prod_path.parent.mkdir(parents=True, exist_ok=True)

        # Backup the previous one
        if prod_path.exists():
            backup = prod_path.with_suffix(f".{today.strftime('%Y%m%d')}.bak.joblib")
            shutil.copy2(prod_path, backup)
            log.info("%s: backed up existing -> %s", tf_str, backup.name)

        scorer.save(prod_path)
        log.info("%s: PROMOTED -> %s", tf_str, prod_path)

    manifest_path = Path("models/last_retrain.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    log.info("\nManifest written to %s", manifest_path)


if __name__ == "__main__":
    sys.exit(main() or 0)
