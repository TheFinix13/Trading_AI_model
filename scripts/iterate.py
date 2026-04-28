"""Iterative training loop for the pattern-discoverer.

Each iteration:
  1. Train Discoverer on the *training window* (in-sample).
  2. Backtest it on the *validation window* (out-of-sample, never trained on).
  3. Print key metrics + loss diagnostics.
  4. If validation expectancy improves, save as the new champion model.
  5. Bump the train window forward (walk-forward) and repeat.

This is true incremental learning: every iteration the model sees a new chunk of
data it hasn't seen before, and we keep only the version that survives OOS validation.

Stops when:
  - We run out of data (no more validation chunks)
  - Validation expectancy plateaus or worsens for `patience` iterations
  - --max-iters reached

Usage:
  python scripts/iterate.py --timeframe H1 --use-cache-only
  python scripts/iterate.py --timeframe M15 --train-bars 8000 --val-bars 2000
  python scripts/iterate.py --tfs M15 H1 H4    # train one model per TF
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.analysis.calibration import calibration_report
from agent.analysis.losses import analyze, format_report
from agent.backtest.discoverer_runner import run_discoverer_backtest
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.model.discoverer import Discoverer, DiscovererConfig, _build_feature_frame, _label_forward
from agent.types import Bar, Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("iterate")


def _walk_forward_iteration(
    cfg, bars: list[Bar], train_bars: int, val_bars: int, step: int,
    prob_threshold: float, max_iters: int, patience: int, model_dir: Path,
) -> dict:
    history: list[dict] = []
    champion_pf = -float("inf")
    plateau = 0
    start = 0
    iter_no = 0

    # Discoverer needs ~250 bars of warm-up (EMA200) before features are valid.
    # Prepend that many bars from the train slice to the val slice so the predictions
    # have proper warm-up context (without leaking train labels — only features).
    WARMUP = 260
    while start + train_bars + val_bars <= len(bars) and iter_no < max_iters:
        iter_no += 1
        train_slice = bars[start: start + train_bars]
        val_start_idx = start + train_bars
        # Include warm-up tail of the training window for valid feature computation
        warmup_start = max(0, val_start_idx - WARMUP)
        val_slice = bars[warmup_start: val_start_idx + val_bars]

        log.info("ITER %d  train=[%s..%s] (%d bars)  val=[%s..%s] (%d bars)",
                 iter_no,
                 train_slice[0].time.date(), train_slice[-1].time.date(), len(train_slice),
                 val_slice[0].time.date(), val_slice[-1].time.date(), len(val_slice))

        d_cfg = DiscovererConfig(prob_threshold=prob_threshold)
        disco = Discoverer.train(train_slice, d_cfg)
        if disco is None:
            log.warning("ITER %d: training failed; skipping", iter_no)
            start += step
            continue

        result = run_discoverer_backtest(cfg, val_slice, disco)
        m = result.metrics
        report = analyze(result.trades)

        # Calibration check: on the validation slice, do the model's predicted
        # probabilities actually match observed forward outcomes? This is our
        # anti-hallucination guard. Even a model with great backtest PF can be
        # poorly calibrated; a poorly calibrated model is brittle in live trading.
        try:
            preds = disco.predict_bars(val_slice)
            labels = _label_forward(val_slice,
                                     horizon=disco.cfg.horizon,
                                     stop_atr_mult=disco.cfg.stop_atr_mult,
                                     tp_atr_mult=disco.cfg.tp_atr_mult)
            # Align prediction and label indices (both are 0..n-1 of val_slice)
            labels.index = preds.index
            joined = preds.join(labels, how="inner").dropna()
            calib_long = calibration_report(
                joined["long_prob"].to_numpy(), joined["y_long"].to_numpy())
            calib_short = calibration_report(
                joined["short_prob"].to_numpy(), joined["y_short"].to_numpy())
        except Exception as e:
            log.warning("calibration check failed: %s", e)
            calib_long = calib_short = None

        log.info("ITER %d  val: trades=%d  PF=%.2f  win=%.1f%%  exp=$%.2f  DD=%.1f%%",
                 iter_no, m.n_trades, m.profit_factor, m.win_rate*100, m.expectancy,
                 m.max_drawdown_pct*100)
        if calib_long is not None:
            log.info("  calibration LONG : Brier=%.3f ECE=%.3f overconf=%s",
                     calib_long.brier, calib_long.ece, calib_long.is_overconfident_high_bins)
            log.info("  calibration SHORT: Brier=%.3f ECE=%.3f overconf=%s",
                     calib_short.brier, calib_short.ece, calib_short.is_overconfident_high_bins)

        record = {
            "iter": iter_no,
            "train_start": str(train_slice[0].time),
            "train_end": str(train_slice[-1].time),
            "val_start": str(val_slice[0].time),
            "val_end": str(val_slice[-1].time),
            "n_trades": m.n_trades,
            "profit_factor": m.profit_factor if m.profit_factor != float("inf") else 999.0,
            "win_rate": m.win_rate,
            "expectancy": m.expectancy,
            "max_dd_pct": m.max_drawdown_pct,
            "loss_categories": report.by_category,
            "calib_long_brier": calib_long.brier if calib_long else None,
            "calib_long_ece": calib_long.ece if calib_long else None,
            "calib_long_overconfident": calib_long.is_overconfident_high_bins if calib_long else None,
            "calib_short_brier": calib_short.brier if calib_short else None,
            "calib_short_ece": calib_short.ece if calib_short else None,
            "calib_short_overconfident": calib_short.is_overconfident_high_bins if calib_short else None,
        }
        history.append(record)

        # Champion criteria: improved PF, AT LEAST `min_validation_trades`, AND not
        # hallucinating confidence. The hallucination guard prevents us from
        # crowning a model whose predictions look great but won't generalize.
        is_calibrated = True
        if calib_long is not None and (calib_long.is_overconfident_high_bins
                                       or calib_long.brier > 0.27):
            is_calibrated = False
        if calib_short is not None and (calib_short.is_overconfident_high_bins
                                        or calib_short.brier > 0.27):
            is_calibrated = False

        improves = (m.n_trades >= 5
                     and record["profit_factor"] > champion_pf
                     and is_calibrated)
        if improves:
            champion_pf = record["profit_factor"]
            disco.save(model_dir / f"champion_iter_{iter_no:03d}")
            (model_dir / "champion_meta.json").write_text(json.dumps(record, indent=2, default=str))
            log.info("  new champion saved (PF=%.2f, calibrated)", champion_pf)
            plateau = 0
        else:
            if not is_calibrated:
                log.info("  rejected: model is overconfident in high-probability bins (hallucinating)")
            plateau += 1
            if plateau >= patience:
                log.info("Validation plateaued for %d iterations; stopping", patience)
                break

        start += step

    return {"history": history, "champion_pf": champion_pf, "n_iters": iter_no}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--tfs", nargs="+", default=["H1"])
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--use-cache-only", action="store_true")
    parser.add_argument("--train-bars", type=int, default=4000,
                        help="bars in each training window")
    parser.add_argument("--val-bars", type=int, default=1000,
                        help="bars in each validation window (held out from training)")
    parser.add_argument("--step", type=int, default=500,
                        help="how far to slide the window each iteration")
    parser.add_argument("--prob-threshold", type=float, default=0.55)
    parser.add_argument("--max-iters", type=int, default=20)
    parser.add_argument("--patience", type=int, default=5,
                        help="stop after N iterations without improving the champion")
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--initial-balance", type=float, default=None)
    args = parser.parse_args()

    cfg = load_config()
    if args.initial_balance is not None:
        cfg.backtest.initial_balance = args.initial_balance
    symbol = args.symbol or cfg.symbol

    loader = BarLoader(cache_root=cfg.data_dir)
    end = datetime.now(tz=timezone.utc)
    start_t = end - timedelta(days=args.years * 365)

    base_model_dir = args.model_dir or cfg.model_dir
    base_model_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict] = {}
    for tf_str in args.tfs:
        try:
            tf = Timeframe(tf_str)
        except ValueError:
            log.warning("Unknown timeframe: %s", tf_str)
            continue

        if args.use_cache_only:
            df = loader.cache.load(symbol, tf)
        else:
            df = loader.get(symbol, tf, start_t, end)
            if df.empty:
                df = loader.cache.load(symbol, tf)

        if df.empty:
            log.warning("No data for %s %s", symbol, tf.value)
            continue

        bars = df_to_bars(df, tf)
        if len(bars) < args.train_bars + args.val_bars:
            log.warning("Not enough bars for %s (have %d, need %d)",
                        tf.value, len(bars), args.train_bars + args.val_bars)
            continue

        log.info("=" * 60)
        log.info("TIMEFRAME %s  (%d bars)", tf.value, len(bars))
        log.info("=" * 60)
        model_dir = base_model_dir / f"discoverer_{symbol}_{tf.value}"
        result = _walk_forward_iteration(
            cfg, bars,
            train_bars=args.train_bars, val_bars=args.val_bars, step=args.step,
            prob_threshold=args.prob_threshold,
            max_iters=args.max_iters, patience=args.patience,
            model_dir=model_dir,
        )
        summary[tf.value] = result

    print()
    print("ITERATION SUMMARY")
    print("=" * 60)
    for tf_v, r in summary.items():
        cpf = r["champion_pf"]
        cpf_str = f"{cpf:.2f}" if cpf != -float("inf") else "n/a"
        print(f"  {tf_v:>4s}: iters={r['n_iters']}  best PF={cpf_str}")

    out = base_model_dir / "iterate_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nFull history written to {out}")


if __name__ == "__main__":
    main()
