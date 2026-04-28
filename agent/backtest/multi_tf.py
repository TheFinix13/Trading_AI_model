"""Multi-timeframe backtest aggregation.

Runs the rule engine independently per timeframe (so each TF sees its own structure),
then merges all generated trades into a single chronological stream and replays them
under a unified one-position-at-a-time portfolio. This is the closest backtest you can
get to a real account that watches multiple TFs and only opens one trade at a time.

Lower TFs typically generate more signals; higher TFs catch macro setups. The merge
prefers the trade that triggered first; concurrent signals across TFs are deduplicated
by direction (no opposing positions stacked)."""
from __future__ import annotations

import logging
from contextlib import nullcontext as _nullcontext
from dataclasses import dataclass, field
from datetime import datetime

from agent.backtest.engine import Backtester
from agent.backtest.metrics import PerfMetrics, compute_metrics
from agent.config import Config
from agent.data.loader import df_to_bars
from agent.journal.db import Journal
from agent.rules.htf_bias import HTFBiasComputer
from agent.types import Bar, Direction, Timeframe, Trade

log = logging.getLogger(__name__)


@dataclass
class MultiTFResult:
    trades: list[Trade]
    per_tf_trades: dict[str, list[Trade]] = field(default_factory=dict)
    metrics: PerfMetrics | None = None
    initial_balance: float = 0.0


def _merge_chronological(per_tf: dict[Timeframe, list[Trade]]) -> list[Trade]:
    """Replay all trades from all TFs as one stream with global single-position semantics.

    Algorithm:
      1. Pool all trades from every TF into a list.
      2. Sort by entry_time.
      3. Walk the list; if a trade's entry_time is during another trade's [entry, exit]
         window already accepted into the merged stream, drop it.
      4. Result: at most one position open at any moment, taking the earliest signal."""
    pooled: list[Trade] = []
    for tf, ts in per_tf.items():
        for t in ts:
            if t.entry_time is None or t.exit_time is None:
                continue
            pooled.append(t)
    pooled.sort(key=lambda t: t.entry_time)

    accepted: list[Trade] = []
    last_exit: datetime | None = None
    for t in pooled:
        if last_exit is not None and t.entry_time < last_exit:
            continue  # would overlap an already-accepted position
        accepted.append(t)
        last_exit = t.exit_time
    return accepted


def run_multi_tf(
    cfg: Config,
    bars_by_tf: dict[Timeframe, list[Bar]],
    journal: Journal | None = None,
    scorer=None,
    score_threshold: float = 0.55,
    bias_only_tfs: set[Timeframe] | None = None,
) -> MultiTFResult:
    """Run an independent backtest per provided timeframe, then merge.

    If `journal` is provided, every signal/trade from every TF is recorded with the TF
    embedded in the `mode` column ('backtest_M15', 'backtest_H1', etc.) so you can later
    query trades by source TF.

    HTF bias: when both LTF (M15/H1) and HTF (D1, H4) bars are provided AND
    cfg.rules.htf_bias_mode != 'off', the LTF backtests automatically consult the HTF
    bars for trend / active-zone confirmation.

    `bias_only_tfs`: TFs that contribute to HTF bias / zones but never generate their
    own entries. Default: {H4, D1}. Trades on the daily are unrealistic for retail
    sub-$1k accounts (stops are too wide, hold times too long, drawdown too volatile).
    Higher timeframes are ONLY for analysis — directional bias and zone/level mapping —
    and entries fire on the lower timeframes (M5/M15/H1) where you can actually manage
    risk and exit positions intra-day."""
    if bias_only_tfs is None:
        bias_only_tfs = {Timeframe.H4, Timeframe.D1}
    # Pre-build HTF bias computers from any D1/H4 bars we have. M15/H1/M5/M1 backtests
    # will receive them and the rule engine will consult them per setup.
    htf_biases: list[HTFBiasComputer] = []
    if cfg.rules.htf_bias_mode != "off":
        for htf_tf in (Timeframe.D1, Timeframe.H4):
            htf_bars = bars_by_tf.get(htf_tf)
            if htf_bars:
                hb = HTFBiasComputer.build(
                    htf_bars,
                    zone_min_impulse_pips=cfg.detectors.zone_min_impulse_pips,
                    zone_max_age_bars=cfg.detectors.zone_max_age_bars,
                    min_trend_slope_pips=cfg.rules.htf_bias_min_slope_pips,
                )
                htf_biases.append(hb)
                log.info("HTF bias enabled from %s (%d bars, %d zones)",
                         htf_tf.value, len(htf_bars), len(hb.zones))
        if not htf_biases:
            log.warning("HTF bias mode is '%s' but no D1/H4 bars were provided",
                        cfg.rules.htf_bias_mode)

    per_tf_trades: dict[Timeframe, list[Trade]] = {}
    # Batch journal writes: SQLite per-row commits are 100-1000x slower than batched.
    # The context-manager defers fsync until backtest end.
    batch_ctx = journal.batch() if journal is not None else _nullcontext()
    with batch_ctx:
        for tf, bars in bars_by_tf.items():
            if not bars:
                log.warning("Multi-TF: no bars for %s, skipping", tf.value)
                continue
            if tf in bias_only_tfs:
                log.info("Multi-TF: %s is bias-only — no entries generated from this TF", tf.value)
                per_tf_trades[tf] = []
                continue
            log.info("Multi-TF backtest: %s (%d bars)", tf.value, len(bars))
            # D1/H4 don't consume HTF bias (they ARE the HTF). M15/H1/M5/M1 do.
            biases_for_this = htf_biases if tf.value in ("M1", "M5", "M15", "H1") else None
            bt = Backtester(cfg, journal=journal,
                            journal_mode=f"backtest_{tf.value}",
                            htf_biases=biases_for_this,
                            scorer=scorer, prob_threshold=score_threshold)
            result = bt.run(bars)
            per_tf_trades[tf] = result.trades
            log.info("  -> %s yielded %d trades", tf.value, len(result.trades))

    merged = _merge_chronological(per_tf_trades)
    metrics = compute_metrics(merged, cfg.backtest.initial_balance)

    return MultiTFResult(
        trades=merged,
        per_tf_trades={tf.value: ts for tf, ts in per_tf_trades.items()},
        metrics=metrics,
        initial_balance=cfg.backtest.initial_balance,
    )
