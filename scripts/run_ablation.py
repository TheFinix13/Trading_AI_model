"""Generic Stage-1 ablation grid runner (1 alpha × 1 timeframe × 1 session
per cell). Cells are isolated (fresh detector context, fresh alpha instance)
and Benjamini-Hochberg correction is applied across the full grid.

The alpha pool is whatever's currently in :data:`ALL_CONCEPT_ALPHAS`, so the
script's behaviour tracks the live roster. As of v4 that's just ``zone``; if
you need a focused zone-only sweep across TFs use
``scripts/run_zone_all_tfs.py`` which also includes the HTF-against variant.

Usage:
    python scripts/run_ablation.py
    python scripts/run_ablation.py --alphas zone --timeframes H1 M15
    python scripts/run_ablation.py --sessions all london_ny_overlap --fdr 0.10
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from agent.alphas.concepts import ALL_CONCEPT_ALPHAS
from agent.alphas.grid import ALL_SESSIONS, AblationCell, format_grid, run_grid
from agent.config import Config, load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.types import Timeframe

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run_ablation")

DEFAULT_ALPHAS = tuple(ALL_CONCEPT_ALPHAS)
DEFAULT_TIMEFRAMES = ("H1", "M15", "M5", "H4", "D1")  # whatever parquet has

ALPHA_FACTORIES = {name: (lambda cfg, _cls=cls: _cls(cfg))
                   for name, cls in ALL_CONCEPT_ALPHAS.items()}


def _parse(d: str) -> datetime:
    return datetime.fromisoformat(d).replace(tzinfo=timezone.utc)


def _load_bars(cfg: Config, symbol: str, timeframes: tuple[str, ...]) -> dict[str, list]:
    """Load each requested TF's parquet once. Missing TFs are skipped (with
    a warning) rather than aborting — the grid keeps a rectangular layout."""
    loader = BarLoader(cache_root=cfg.data_dir)
    out: dict[str, list] = {}
    ev = cfg.eval
    for tf in timeframes:
        try:
            df = loader.get(symbol, Timeframe(tf), _parse(ev.dev_start),
                            _parse(ev.dev_end), refresh=False)
            bars = df_to_bars(df, Timeframe(tf))
            if bars:
                out[tf] = bars
            else:
                log.warning("no bars for %s %s — skipping", symbol, tf)
        except Exception as e:
            log.warning("skipping %s %s (%s)", symbol, tf, e)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default=None)
    p.add_argument("--alphas", nargs="+", default=list(DEFAULT_ALPHAS),
                   choices=sorted(ALPHA_FACTORIES))
    p.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES))
    p.add_argument("--sessions", nargs="+", default=list(ALL_SESSIONS))
    p.add_argument("--fdr", type=float, default=0.05,
                   help="Benjamini-Hochberg FDR floor (default 0.05)")
    p.add_argument("--warmup", type=int, default=200,
                   help="bars skipped before alphas start signalling")
    p.add_argument("--resamples", type=int, default=1000)
    args = p.parse_args()

    cfg = load_config()
    symbol = args.symbol or cfg.symbol

    print("=" * 88)
    print(f"V2 ABLATION GRID — Stage 1   {symbol}   "
          f"dev {cfg.eval.dev_start} → {cfg.eval.dev_end}")
    print(f"  alphas      : {', '.join(args.alphas)}")
    print(f"  timeframes  : {', '.join(args.timeframes)}")
    print(f"  sessions    : {', '.join(args.sessions)}")
    print(f"  cells       : {len(args.alphas)} \u00d7 {len(args.timeframes)} "
          f"\u00d7 {len(args.sessions)} = "
          f"{len(args.alphas) * len(args.timeframes) * len(args.sessions)}")
    print(f"  FDR floor   : {args.fdr:.2%} (Benjamini-Hochberg)")
    print("=" * 88)

    bars_by_tf = _load_bars(cfg, symbol, tuple(args.timeframes))
    if not bars_by_tf:
        log.error("No parquet data found for any requested TF. "
                  "Run scripts/download_data.py first.")
        return

    cells = [
        AblationCell(
            alpha_name=alpha, timeframe=tf, session=sess,
            alpha_factory=ALPHA_FACTORIES[alpha],
        )
        for alpha in args.alphas
        for tf in args.timeframes
        for sess in args.sessions
    ]

    def _progress(k: int, n: int, cell) -> None:
        if k == 1 or k == n or k % 10 == 0:
            print(f"  [{k:>3}/{n}] {cell.label}", flush=True)

    grid = run_grid(
        cells, bars_by_tf, cfg,
        fdr=args.fdr, start_index=args.warmup, n_resamples=args.resamples,
        progress=_progress,
    )

    print()
    print(format_grid(grid))

    if grid.survivors:
        print("\nBH-surviving cells:")
        for r in sorted(grid.survivors, key=lambda x: x.q_value):
            print(f"  {r.cell.label:<48} q={r.q_value:.4f}  "
                  f"exp={r.scorecard.expectancy.value:+.4f}  "
                  f"n={r.scorecard.n_trades}")
    else:
        print("\nNo cell survives at FDR ≤ "
              f"{args.fdr:.2%}. The honest read: this slice has no edge.")


if __name__ == "__main__":
    main()
