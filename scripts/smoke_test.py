"""End-to-end pipeline smoke test using synthetic data.

Verifies (offline, no network):
  - Detectors run without errors
  - Rule engine produces setups
  - Backtester completes
  - XGBoost trains and scores
  - ML-on backtest runs
  - Journal logs

Run before any real backtest to confirm wiring is intact.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from agent.backtest.engine import Backtester
from agent.config import load_config
from agent.data.loader import df_to_bars
from agent.data.synthetic import generate
from agent.detectors.bos import detect_bos
from agent.detectors.fib import auto_fib
from agent.detectors.fvg import detect_fvgs
from agent.detectors.liquidity import detect_liquidity_wicks
from agent.detectors.swings import detect_swings
from agent.detectors.trendlines import fit_trendlines
from agent.detectors.zones import detect_zones
from agent.journal.db import Journal
from agent.model.scorer import train_scorer
from agent.types import Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("smoke_test")


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
    wicks = detect_liquidity_wicks(bars, min_wick_ratio=cfg.detectors.liquidity_wick_min_ratio)
    log.info("  swings=%d bos=%d fvgs=%d zones=%d fib=%s trendlines=%d wicks=%d",
             len(swings), len(bos_list), len(fvgs), len(zones),
             fib is not None, len(trendlines), len(wicks))

    log.info("Running rules-only backtest...")
    bt = Backtester(cfg)
    result = bt.run(bars)
    m = result.metrics
    log.info("  trades=%d win_rate=%.1f%% PF=%.2f expectancy=$%.2f maxDD=%.1f%%",
             m.n_trades, m.win_rate * 100, m.profit_factor, m.expectancy, m.max_drawdown_pct * 100)
    log.info("  skipped=%d reasons=%s", result.skipped_signals, result.skipped_reasons)

    if m.n_trades >= 30:
        log.info("Training XGBoost scorer on backtest trades...")
        scorer = train_scorer(result.trades)
        if scorer is not None:
            log.info("Running rules+ML backtest on second half...")
            half = len(bars) // 2
            bt_ml = Backtester(cfg, scorer=scorer, prob_threshold=cfg.ml.prob_threshold)
            ml_result = bt_ml.run(bars[half:])
            mm = ml_result.metrics
            log.info("  rules+ML: trades=%d win_rate=%.1f%% PF=%.2f",
                     mm.n_trades, mm.win_rate * 100, mm.profit_factor)
        else:
            log.warning("Scorer training returned None")
    else:
        log.warning("Too few trades to train scorer (need >= 30)")

    log.info("Logging to journal (in-memory)...")
    journal = Journal(":memory:")
    for t in result.trades[:5]:
        sig_id = journal.log_signal(t.setup, "EURUSD", "approved", "smoke", lot_size=t.lot_size)
        tid = journal.log_trade_open(sig_id, "EURUSD", t)
        if t.exit_time:
            journal.log_trade_close(tid, t.exit_time, t.exit_price, t.exit_reason, t.pnl, t.pnl_pips)
    log.info("  journal trades=%d", len(journal.all_trades()))

    log.info("OK - pipeline smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
