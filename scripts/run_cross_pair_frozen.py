"""Frozen-parameter cross-pair test of the deployed zone strategy.

THE most informative experiment available after the EURUSD walk-forward:
run the EXACT deployed configuration (``zone_d1_against`` — H4 zones faded
against the D1 trend, htf_lookback=10, htf_min_move_pips=60) on symbols the
research pipeline has NEVER touched: GBPUSD and USDCAD.

Because no parameter was ever fit to these pairs, their entire history is
out-of-sample. Two possible outcomes:

* **Edge shows up out of the box** → the zone-fade is a structural FX
  phenomenon, not an EURUSD quirk. The new pairs become deployment
  candidates (2nd/3rd place) running the SAME validated logic.
* **Edge is absent** → the EURUSD result is pair-specific (or partially
  luck). #1 stays deployed but with a wider uncertainty band.

Frozen discipline:

* Strategy parameters: byte-for-byte the deployed config. NO re-tuning.
* Costs: adjusted UP to each pair's realistic retail spread (GBPUSD ~1.5x,
  USDCAD ~1.8x EURUSD). Using EURUSD costs would flatter the result;
  realism here makes the test conservative.
* Window: 2015-01-01 → 2025-12-01 (same dev span; 2026 stays sealed for
  these pairs too, so we keep a untouched final-check window).
* Yearly expectancy breakdown — the same stability signal that decided
  the EURUSD walk-forward (consistent positive years > one-shot p-value).
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.alphas.backtest import run_alpha
from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha
from agent.backtest.metrics import bootstrap_p_value, make_scorecard
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.rules.engine import precompute
from agent.types import Timeframe

logging.basicConfig(level=logging.WARNING)

DEV_START = datetime(2015, 1, 1, tzinfo=timezone.utc)
DEV_END = datetime(2025, 12, 1, tzinfo=timezone.utc)

# Realistic retail spread multipliers vs the EURUSD-calibrated cost table.
COST_MULT = {"GBPUSD": 1.5, "USDCAD": 1.8, "AUDUSD": 1.4, "NZDUSD": 1.8}

SYMBOLS = ("GBPUSD", "USDCAD", "AUDUSD", "NZDUSD")
TFS = (Timeframe.H4, Timeframe.D1)


def _make_alphas(cfg) -> dict:
    """Byte-for-byte the deployed (and candidate) zone configurations."""
    return {
        "zone": SupplyDemandAlpha(cfg),
        "zone_d1_against": SupplyDemandAlpha(
            cfg, htf_align="D1", htf_align_mode="against",
            htf_lookback=10, htf_min_move_pips=60.0,
        ),
    }


def main() -> None:
    for symbol in SYMBOLS:
        cfg = load_config()
        cfg.symbol = symbol
        mult = COST_MULT[symbol]
        cfg.backtest.spread_pips *= mult
        cfg.backtest.slippage_pips *= mult
        cfg.backtest.cost_by_tf = {
            tf: {"spread": c["spread"] * mult, "slippage": c["slippage"] * mult}
            for tf, c in cfg.backtest.cost_by_tf.items()
        }

        loader = BarLoader(cache_root=cfg.data_dir)
        print(f"\n{'=' * 100}")
        print(f"FROZEN CROSS-PAIR TEST — {symbol}   "
              f"{DEV_START.date()} → {DEV_END.date()}   "
              f"(costs x{mult} vs EURUSD)")
        print(f"{'=' * 100}")

        for tf in TFS:
            df = loader.get(symbol, tf, DEV_START, DEV_END, refresh=False)
            bars = df_to_bars(df, tf)
            if len(bars) < 500:
                print(f"  {tf.value}: only {len(bars)} bars — skipping "
                      f"(run the download first)")
                continue
            ctx = precompute(bars, cfg)
            print(f"\n  {tf.value}: {len(bars):,} bars, "
                  f"{len(ctx.zones)} zones")

            for name, alpha in _make_alphas(cfg).items():
                trades = [
                    t for t in run_alpha(alpha, bars, cfg, ctx=ctx,
                                         start_index=200)
                    if t.exit_time is not None
                ]
                card = make_scorecard(f"{name}/{tf.value}", trades,
                                      cfg.backtest.initial_balance,
                                      n_resamples=1000)
                p = bootstrap_p_value([t.pnl for t in trades],
                                      n_resamples=1000)
                print(f"\n    {name:<18} n={card.n_trades:>5}  "
                      f"exp={card.expectancy.value:>+7.2f}  "
                      f"sharpe={card.base.sharpe:>5.2f}  "
                      f"WR={card.win_rate.value:>5.1%}  p={p:.3f}")

                # Yearly stability — the signal that decided the EURUSD
                # walk-forward.
                years = sorted({t.entry_time.year for t in trades})
                pos_years = 0
                line = []
                for y in years:
                    pnl = [t.pnl for t in trades if t.entry_time.year == y]
                    exp = sum(pnl) / len(pnl) if pnl else 0.0
                    pos_years += exp > 0
                    line.append(f"{y}:{exp:+.1f}({len(pnl)})")
                if years:
                    print(f"      yearly exp: {'  '.join(line)}")
                    print(f"      positive years: {pos_years}/{len(years)}")


if __name__ == "__main__":
    main()
