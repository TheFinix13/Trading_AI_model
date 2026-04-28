"""Walk-forward validation: split data into rolling train/test windows.

For each window:
  - Train ML scorer on bars[start_train : end_train]
  - Test on bars[end_train : end_test]
The aggregated test trades are the unbiased out-of-sample performance.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from agent.backtest.engine import BacktestResult, Backtester
from agent.backtest.metrics import PerfMetrics, compute_metrics
from agent.config import Config
from agent.types import Bar, Trade

log = logging.getLogger(__name__)

ScorerTrainFn = Callable[[list[Trade]], Callable[[dict], float]]


@dataclass
class WalkForwardResult:
    folds: list[BacktestResult]
    aggregated_trades: list[Trade]
    metrics: PerfMetrics


def _slice_bars(bars: list[Bar], start: datetime, end: datetime) -> list[Bar]:
    return [b for b in bars if start <= b.time < end]


def walk_forward(
    cfg: Config,
    bars: list[Bar],
    train_months: int = 24,
    test_months: int = 3,
    train_scorer: ScorerTrainFn | None = None,
    prob_threshold: float = 0.55,
) -> WalkForwardResult:
    """Run walk-forward by repeatedly retraining the scorer on expanding history."""
    if not bars:
        empty = compute_metrics([], cfg.backtest.initial_balance)
        return WalkForwardResult([], [], empty)

    start = bars[0].time
    end = bars[-1].time
    fold_start = start + timedelta(days=train_months * 30)

    folds: list[BacktestResult] = []
    aggregated: list[Trade] = []

    cur = fold_start
    while cur < end:
        train_start = cur - timedelta(days=train_months * 30)
        train_end = cur
        test_end = min(cur + timedelta(days=test_months * 30), end)

        train_bars = _slice_bars(bars, train_start, train_end)
        test_bars = _slice_bars(bars, train_end, test_end)
        if not test_bars or len(train_bars) < 100:
            cur = test_end
            continue

        scorer = None
        if train_scorer is not None:
            train_result = Backtester(cfg).run(train_bars)
            if train_result.trades:
                scorer = train_scorer(train_result.trades)
            else:
                log.warning("No training trades in fold ending %s; running rules-only", train_end)

        bt = Backtester(cfg, scorer=scorer, prob_threshold=prob_threshold)
        result = bt.run(test_bars)
        folds.append(result)
        aggregated.extend(result.trades)
        cur = test_end

    metrics = compute_metrics(aggregated, cfg.backtest.initial_balance)
    return WalkForwardResult(folds=folds, aggregated_trades=aggregated, metrics=metrics)
