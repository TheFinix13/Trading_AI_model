"""Print a plain-English narrative for a journal trade.

Two usage modes:

  1. By trade id (read journal):
       python scripts/explain.py --trade-id 142

  2. Pull a specific date and re-run the rule engine to show the live setup
     reasoning (useful when you want full Setup-aware output instead of the
     condensed journal-row form):
       python scripts/explain.py --replay --time 2025-04-05T14:00 --tf H1
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.analysis.explain import explain_setup, explain_trade, format_explanation
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.rules.engine import RuleEngine, precompute
from agent.rules.htf_bias import HTFBiasComputer
from agent.types import Bar, Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("explain")


def explain_by_journal_id(trade_id: int, journal_path: Path):
    # Delegate to the journal_query CLI logic
    from scripts.journal_query import _connect, _explain_trade_row
    conn = _connect(journal_path)
    _explain_trade_row(conn, trade_id)


def explain_by_replay(time_str: str, tf_str: str, symbol: str | None,
                      use_cache_only: bool, htf_mode: str):
    cfg = load_config()
    cfg.rules.htf_bias_mode = htf_mode
    symbol = symbol or cfg.symbol
    tf = Timeframe(tf_str)

    target = datetime.fromisoformat(time_str)
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)

    loader = BarLoader(cache_root=cfg.data_dir)
    if use_cache_only:
        df = loader.cache.load(symbol, tf)
    else:
        df = loader.get(symbol, tf, target - timedelta(days=365), target + timedelta(days=2))
    if df.empty:
        log.error("No %s bars cached for %s", tf.value, symbol)
        sys.exit(1)
    bars = df_to_bars(df, tf)

    # Build HTF context from cache if requested
    htf_biases: list[HTFBiasComputer] = []
    if htf_mode != "off":
        for htf_tf in (Timeframe.D1, Timeframe.H4):
            hdf = loader.cache.load(symbol, htf_tf)
            if not hdf.empty:
                hbars = df_to_bars(hdf, htf_tf)
                htf_biases.append(HTFBiasComputer.build(
                    hbars,
                    zone_min_impulse_pips=cfg.detectors.zone_min_impulse_pips,
                    zone_max_age_bars=cfg.detectors.zone_max_age_bars,
                    min_trend_slope_pips=cfg.rules.htf_bias_min_slope_pips,
                ))

    # Find the bar index closest to target time
    idx = -1
    for i, b in enumerate(bars):
        if b.time >= target:
            idx = i
            break
    if idx < 0:
        log.error("No bar found at or after %s in cached data (last bar: %s)",
                  target, bars[-1].time if bars else "?")
        sys.exit(1)

    log.info("Found bar at %s (idx=%d). Re-running detectors over %d bars...",
             bars[idx].time, idx, len(bars))
    ctx = precompute(bars, cfg)
    engine = RuleEngine(cfg, htf_biases=htf_biases)

    # Try the requested bar AND a small neighborhood, in case the user picked an
    # exact time that didn't trigger a setup. Show what we found.
    best = None
    for j in range(max(0, idx - 3), min(len(bars), idx + 4)):
        s = engine.evaluate_precomputed(ctx, j)
        if s is not None:
            best = s
            log.info("Setup found at bar idx %d (%s)", j, bars[j].time)
            break
    if best is None:
        print(f"\nNo confluence setup detected within ±3 bars of {target}.")
        print("Most recent bar prices nearby:")
        for j in range(max(0, idx - 2), min(len(bars), idx + 3)):
            print(f"  {bars[j].time}  O={bars[j].open:.5f} H={bars[j].high:.5f} "
                  f"L={bars[j].low:.5f} C={bars[j].close:.5f}")
        return

    print(format_explanation(explain_setup(best)))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trade-id", type=int, help="explain trade by journal row id")
    parser.add_argument("--journal-path", type=Path, default=None)
    parser.add_argument("--replay", action="store_true",
                        help="re-run the rule engine at a specific timestamp")
    parser.add_argument("--time", help="ISO time for --replay, e.g. 2025-04-05T14:00")
    parser.add_argument("--tf", default="H1")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--use-cache-only", action="store_true")
    parser.add_argument("--htf-bias", default="off",
                        choices=["off", "advisory", "strict"])
    args = parser.parse_args()

    if args.trade_id is not None:
        cfg = load_config()
        path = args.journal_path or cfg.journal_db
        explain_by_journal_id(args.trade_id, path)
    elif args.replay:
        if not args.time:
            log.error("--replay requires --time YYYY-MM-DDTHH:MM")
            sys.exit(2)
        explain_by_replay(args.time, args.tf, args.symbol, args.use_cache_only, args.htf_bias)
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
