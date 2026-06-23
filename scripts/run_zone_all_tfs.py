"""Zone-alpha definitive grid across every available TF and session.

Now that ``detect_bos`` and ``detect_liquidity_sweeps`` are 100-200x faster
and the precompute drops the ~10-min ``auto_fib`` waste, running zone on
{D1, H4, H1, M30, M15} × {all sessions} × {baseline, HTF-against-strict}
takes ~5 minutes total. This is the cell pool we'll cite when deciding
which TF/session pockets to deploy to live.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.alphas.concepts import SupplyDemandAlpha
from agent.alphas.grid import ALL_SESSIONS, AblationCell, format_grid, run_grid
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.types import Timeframe

logging.basicConfig(level=logging.WARNING)


def _parse(d: str) -> datetime:
    return datetime.fromisoformat(d).replace(tzinfo=timezone.utc)


def main() -> None:
    cfg = load_config()
    loader = BarLoader(cache_root=cfg.data_dir)
    start = _parse(cfg.eval.dev_start)
    end = _parse(cfg.eval.dev_end)

    tfs = [Timeframe.D1, Timeframe.H4, Timeframe.H1, Timeframe.M15, Timeframe.M5]
    bars_by_tf: dict[str, list] = {}
    for tf in tfs:
        df = loader.get(cfg.symbol, tf, start, end, refresh=False)
        bars_by_tf[tf.value] = df_to_bars(df, tf)
        print(f"  loaded {tf.value}: {len(bars_by_tf[tf.value]):,} bars")

    print(f"\n{'=' * 100}\nZONE ALPHA — DEFINITIVE GRID   {cfg.symbol}   "
          f"{cfg.eval.dev_start} → {cfg.eval.dev_end}\n{'=' * 100}\n")

    factories = {
        "zone":              lambda c: SupplyDemandAlpha(c),
        "zone_d1_against":   lambda c: SupplyDemandAlpha(
            c, htf_align="D1", htf_align_mode="against",
            htf_lookback=10, htf_min_move_pips=60.0,
        ),
    }
    cells = []
    for name, fac in factories.items():
        for tf in tfs:
            for sess in ALL_SESSIONS:
                cells.append(AblationCell(
                    alpha_name=name, timeframe=tf.value, session=sess,
                    alpha_factory=fac,
                ))

    def _progress(k, n, cell):
        if k == 1 or k == n or k % 5 == 0:
            print(f"  [{k:>3}/{n}] {cell.label}", flush=True)

    grid = run_grid(cells, bars_by_tf, cfg, n_resamples=1000, progress=_progress)
    print()
    print(format_grid(grid))


if __name__ == "__main__":
    main()
