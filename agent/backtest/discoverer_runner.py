"""Run a backtest where the trade signals come from the Discoverer model rather than
the rule engine. Reuses the same fill simulation, risk manager, and per-trade tracking.

Used by scripts/iterate.py and scripts/run_discovered.py."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from agent.backtest.engine import BacktestResult
from agent.backtest.metrics import compute_metrics
from agent.config import Config
from agent.model.discoverer import Discoverer, DiscoveredSetup
from agent.risk.manager import RiskDecision, RiskManager
from agent.types import Bar, Direction, Setup, Trade
from agent.utils import to_pips

log = logging.getLogger(__name__)


def _to_setup(d: DiscoveredSetup) -> Setup:
    """Adapt a DiscoveredSetup into the rule-engine Setup shape so downstream code
    (risk manager, trade tracker, journal) doesn't need to care about the source."""
    s = Setup(
        direction=d.direction,
        timeframe=d.timeframe,
        detected_at=d.detected_at,
        detected_bar_index=d.bar_index,
        entry=d.entry,
        stop=d.stop,
        take_profit=d.take_profit,
        confluences=["discoverer"],
        features=d.features,
        ml_score=d.long_prob if d.direction == Direction.LONG else d.short_prob,
    )
    return s


def run_discoverer_backtest(
    cfg: Config,
    bars: list[Bar],
    discoverer: Discoverer,
) -> BacktestResult:
    """Replay bars; at each bar use the discoverer's prediction as a setup signal.

    One position at a time. Same fill mechanics (next-bar-open, spread, slippage,
    commission) as the rule engine backtester."""
    from agent.backtest.engine import Backtester

    setups = discoverer.emit_setups(bars)
    setups_by_idx = {s.bar_index: s for s in setups}
    log.info("Discoverer emitted %d setup candidates over %d bars", len(setups), len(bars))

    bt = Backtester(cfg)
    risk = RiskManager(cfg)
    balance = cfg.backtest.initial_balance
    open_trade: Trade | None = None
    trades: list[Trade] = []
    equity: list[tuple[datetime, float]] = []
    skipped = 0
    skip_reasons: dict[str, int] = {}

    for i, bar in enumerate(bars):
        if open_trade is not None:
            # Same ordering as Backtester.run: exit-check uses prior-bar stop, BE
            # migration only affects subsequent bars.
            if bt._check_exit(open_trade, bar):
                bt._update_excursions(open_trade, bar, migrate=False)
                balance += open_trade.pnl
                risk.record_trade_pnl(open_trade.pnl)
                trades.append(open_trade)
                open_trade = None
            else:
                bt._update_excursions(open_trade, bar, migrate=True)

        if open_trade is None and i < len(bars) - 1 and i in setups_by_idx:
            setup = _to_setup(setups_by_idx[i])
            decision = risk.evaluate(setup=setup, account_balance=balance,
                                     open_positions=0, now=bar.time)
            if decision.decision != RiskDecision.APPROVED:
                skipped += 1
                skip_reasons[decision.decision] = skip_reasons.get(decision.decision, 0) + 1
            else:
                open_trade = bt._open_trade(setup, bars[i + 1], decision.lot_size)

        equity.append((bar.time, balance + (bt._unrealized(open_trade, bar) if open_trade else 0)))

    if open_trade is not None and open_trade.exit_time is None:
        bt._force_close(open_trade, bars[-1], "end_of_data")
        balance += open_trade.pnl
        trades.append(open_trade)

    metrics = compute_metrics(trades, cfg.backtest.initial_balance)
    return BacktestResult(
        trades=trades, equity_curve=equity, metrics=metrics,
        initial_balance=cfg.backtest.initial_balance,
        skipped_signals=skipped, skipped_reasons=skip_reasons,
    )
