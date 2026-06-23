"""V2 evaluation entry point.

Replaces the v1 Phase-A walk-forward harness (purged WF + ML scorer retraining)
with a lean alpha-based out-of-sample reader. Walks the v2 alpha registry once
over the locked development span and prints a scorecard with bootstrap CIs per
alpha, plus the correlation-aware ensemble.

This file is the **rebuild target** flagged in
`docs/audit/preservation_list.md`. The 224-cell ablation grid will plug in
through `agent.alphas.registry` once it is reintroduced (the v1 registry was
burned because every entry mapped to a BURN strategy class).

Usage:
    python scripts/evaluate.py
    python scripts/evaluate.py --timeframe H1 --symbol EURUSD
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.alphas.allocator import allocate
from agent.alphas.backtest import run_alphas_chunked
from agent.alphas.reaction_alpha import ReactionAlpha
from agent.backtest.metrics import make_scorecard, scorecard_by_session
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("evaluate")


def _parse(d: str) -> datetime:
    return datetime.fromisoformat(d).replace(tzinfo=timezone.utc)


def _default_alphas(cfg) -> list:
    """V2 baseline. Extend with the 224-cell ablation grid as it is rebuilt."""
    return [ReactionAlpha(cfg, name="reaction")]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default=None)
    p.add_argument("--timeframe", default="H1")
    p.add_argument("--warmup", type=int, default=200)
    args = p.parse_args()

    cfg = load_config()
    ev = cfg.eval
    symbol = args.symbol or cfg.symbol
    tf = Timeframe(args.timeframe)

    loader = BarLoader(cache_root=cfg.data_dir)
    df = loader.get(symbol, tf, _parse(ev.dev_start), _parse(ev.dev_end), refresh=False)
    bars = df_to_bars(df, tf)
    if not bars:
        log.error("No bars in dev span. Run scripts/download_data.py first.")
        return

    print("=" * 80)
    print(f"V2 EVALUATION   {symbol} {tf.value}   "
          f"dev {ev.dev_start} → {ev.dev_end}  ({len(bars)} bars)")
    print("=" * 80)

    alphas = _default_alphas(cfg)

    def _progress(k: int, total: int) -> None:
        print(f"  chunk {k}/{total} precomputed…", flush=True)

    streams = run_alphas_chunked(
        alphas, bars, cfg, warmup=args.warmup, start_index=args.warmup,
        progress=_progress,
    )

    print("\n── PER-ALPHA OUT-OF-SAMPLE SCORECARDS ──")
    cards = [
        make_scorecard(a.name, streams[a.name], cfg.backtest.initial_balance,
                       n_resamples=ev.bootstrap_resamples, ci_level=ev.ci_level)
        for a in alphas
    ]
    for c in sorted(cards, key=lambda x: x.expectancy.value, reverse=True):
        print(" ", c)

    for alpha in alphas:
        by_sess = scorecard_by_session(
            alpha.name, streams[alpha.name], cfg.backtest.initial_balance,
            n_resamples=ev.bootstrap_resamples, ci_level=ev.ci_level,
        )
        if not by_sess:
            continue
        print(f"\n── SESSION SCORECARD — {alpha.name} ──")
        for sess, c in by_sess.items():
            print(f"  {sess:18} {c}")

    alloc = allocate(streams)
    if len(alloc.names) > 1:
        print("\n── CORRELATION-AWARE ENSEMBLE ──")
        for n, w in sorted(alloc.weights.items(), key=lambda x: x[1], reverse=True):
            print(f"  {n:<20} weight {w:6.1%}")
        print(f"\n  Ensemble Sharpe (ann.)   : {alloc.ensemble_sharpe:.2f}")
        print(f"  Best single alpha        : {alloc.best_single_name} "
              f"(Sharpe {alloc.best_single_sharpe:.2f})")


if __name__ == "__main__":
    main()
