"""End-to-end v2 pipeline smoke test on synthetic data.

Verifies (offline, no network):

  * Detectors run without errors.
  * `precompute` builds an alpha context.
  * The v2 alpha backtester closes trades cleanly.
  * `make_scorecard` produces a verdict.
  * The journal can ingest a v2 signal/trade pair.

Run before any real evaluation to confirm wiring is intact.
"""
from __future__ import annotations

import logging
import sys

from agent.alphas.backtest import run_alpha
from agent.alphas.base import Alpha, AlphaContext, AlphaSignal
from agent.backtest.metrics import make_scorecard
from agent.config import load_config
from agent.data.loader import df_to_bars
from agent.data.synthetic import generate
from agent.detectors.bos import detect_bos
from agent.detectors.fib import auto_fib
from agent.detectors.fvg import detect_fvgs
from agent.detectors.swings import detect_swings
from agent.detectors.trendlines import fit_trendlines
from agent.detectors.zones import detect_zones
from agent.journal.db import Journal
from agent.rules.engine import precompute
from agent.types import Direction, Timeframe

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("smoke_test")


class _AlwaysLong(Alpha):
    name = "smoke_always_long"

    def signal(self, actx: AlphaContext, i: int):
        bar = actx.bars[i]
        return AlphaSignal(
            direction=Direction.LONG, entry=bar.close,
            stop=bar.close - 0.0020, take_profit=bar.close + 0.0040,
            reason="smoke", conviction=0.5,
        )


def main() -> int:
    cfg = load_config()
    log.info("Generating synthetic data...")
    df = generate(timeframe=Timeframe.H1, n_bars=5000, seed=7)
    bars = df_to_bars(df, Timeframe.H1)
    log.info("  -> %d bars", len(bars))

    log.info("Running detectors...")
    swings = detect_swings(bars, lookback=cfg.detectors.swing_lookback)
    bos_list = detect_bos(bars, swing_lookback=cfg.detectors.swing_lookback)
    fvgs = detect_fvgs(bars, min_size_pips=cfg.detectors.fvg_min_size_pips)
    zones = detect_zones(bars, min_impulse_pips=cfg.detectors.zone_min_impulse_pips)
    fib = auto_fib(bars, swing_lookback=cfg.detectors.swing_lookback)
    trendlines = fit_trendlines(bars, swing_lookback=cfg.detectors.swing_lookback)
    log.info("  swings=%d bos=%d fvgs=%d zones=%d fib=%s trendlines=%d",
             len(swings), len(bos_list), len(fvgs), len(zones),
             fib is not None, len(trendlines))

    log.info("Running v2 alpha backtest...")
    ctx = precompute(bars, cfg)
    trades = run_alpha(_AlwaysLong(), bars, cfg, ctx=ctx, start_index=50)
    log.info("  -> %d closed trades", len(trades))
    if trades:
        card = make_scorecard("smoke", trades, cfg.backtest.initial_balance,
                              n_resamples=200)
        log.info("  scorecard: %s", card)

    log.info("Logging into an in-memory journal...")
    journal = Journal(":memory:")
    for t in trades[:5]:
        sig_id = journal.log_signal(t.setup, "EURUSD", "approved",
                                    "smoke", lot_size=t.lot_size)
        tid = journal.log_trade_open(sig_id, "EURUSD", t)
        if t.exit_time:
            journal.log_trade_close(tid, t.exit_time, t.exit_price,
                                    t.exit_reason, t.pnl, t.pnl_pips)
    log.info("  journal trades=%d", len(journal.all_trades()))

    log.info("OK - v2 smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
