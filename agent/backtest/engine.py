"""Event-driven backtester. Replays bars one at a time, asking the rule engine for a setup,
applying the risk manager, and simulating fills with spread/commission/slippage.

Strict no-lookahead: at decision bar i, we only show the engine bars[:i+1]. Entry uses next
bar's open if available (more realistic than same-bar fill)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from agent.config import Config, GATE_PROFILES, GATE_PROFILE_DEFAULT, GateProfile
from agent.backtest.metrics import PerfMetrics, compute_metrics
from agent.features.extractor import extract_features
from agent.journal.db import Journal
from agent.risk.manager import RiskDecision, RiskManager
from agent.rules.engine import RuleEngine, precompute
from agent.rules.filters import is_no_trade_day, in_no_trade_window
from agent.rules.htf_bias import HTFBiasComputer
from agent.strategy.registry import StrategyRouter, default_registry
from agent.types import Bar, Direction, Setup, Trade
from agent.utils import to_pips

log = logging.getLogger(__name__)

ScorerFn = Callable[[dict], float] | None


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: list[tuple[datetime, float]]
    metrics: PerfMetrics
    initial_balance: float
    skipped_signals: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)


class Backtester:
    def __init__(self, cfg: Config, scorer: ScorerFn = None, prob_threshold: float = 0.55,
                 journal: Journal | None = None, journal_mode: str = "backtest",
                 journal_symbol: str | None = None,
                 htf_biases: list[HTFBiasComputer] | None = None,
                 lzi_scorer: ScorerFn = None):
        """If `journal` is provided, every signal (taken or skipped), every trade open,
        every trade close, and equity snapshots are written to it. Lets you query the
        full reasoning behind any historical trade after the backtest is over.

        `htf_biases` is an optional list of higher-timeframe bias computers (typically
        one for D1 and one for H4). When cfg.rules.htf_bias_mode is 'advisory' or 'strict',
        the rule engine consults these to filter or tag setups.

        `lzi_scorer` is an optional LZI-specific scorer function. When provided,
        LiquidityGrabReversal setups are scored with this instead of the generic scorer."""
        self.cfg = cfg
        self.engine = RuleEngine(cfg, htf_biases=htf_biases)
        self.risk = RiskManager(cfg)
        self.scorer = scorer
        self.lzi_scorer = lzi_scorer
        self.prob_threshold = prob_threshold
        self.journal = journal
        self.journal_mode = journal_mode
        self.journal_symbol = journal_symbol or cfg.symbol
        self._strategy_router = StrategyRouter(default_registry())

    def run(self, bars: list[Bar]) -> BacktestResult:
        balance = self.cfg.backtest.initial_balance
        open_trade: Trade | None = None
        trades: list[Trade] = []
        equity: list[tuple[datetime, float]] = []
        skipped = 0
        skip_reasons: dict[str, int] = {}

        log.info("Precomputing detector context for %d bars...", len(bars))
        ctx = precompute(bars, self.cfg)
        log.info("  zones=%d fvgs=%d bos=%d trendlines=%d wicks=%d",
                 len(ctx.zones), len(ctx.fvgs), len(ctx.bos_list),
                 len(ctx.trendlines), len(ctx.wicks))

        # Track journal trade ids alongside in-memory trades so we can update the same
        # row when the trade closes.
        open_trade_journal_id: int | None = None

        for i, bar in enumerate(bars):
            if open_trade is not None:
                # Order matters: exit check first (uses stop set at end of prior bar);
                # if trade survives, then update MFE/MAE and migrate stop. This way the
                # BE migration cannot retroactively rescue a bar that would have hit the
                # original stop based on its low/high.
                exited = self._check_exit(open_trade, bar)
                if exited:
                    self._update_excursions(open_trade, bar, migrate=False)
                    balance += open_trade.pnl
                    self.risk.record_trade_pnl(open_trade.pnl)
                    if self.journal is not None and open_trade_journal_id is not None:
                        self.journal.log_trade_close(
                            open_trade_journal_id,
                            exit_time=open_trade.exit_time,
                            exit_price=open_trade.exit_price,
                            exit_reason=open_trade.exit_reason or "unknown",
                            pnl=open_trade.pnl,
                            pnl_pips=open_trade.pnl_pips,
                            commission=open_trade.commission,
                        )
                    trades.append(open_trade)
                    open_trade = None
                    open_trade_journal_id = None
                else:
                    self._update_excursions(open_trade, bar, migrate=True)

            if open_trade is None and i < len(bars) - 1:
                # --- Setup sourcing: rule engine + strategy router ---
                setup = self.engine.evaluate_precomputed(ctx, i)

                # Also check strategy router for strategy-produced setups.
                # If both the engine and a strategy fire, prefer the strategy
                # setup when it has a named profile (self-validating).
                strategy_setups = self._strategy_router.route(ctx, i, regime=None)
                strategy_setup = strategy_setups[0] if strategy_setups else None

                if strategy_setup is not None:
                    # Strategy setups go through profile-aware gate validation
                    profile = GATE_PROFILES.get(
                        strategy_setup.strategy_name or "", GATE_PROFILE_DEFAULT
                    )
                    passed, reason = self.engine.validate_setup_gates(
                        strategy_setup, bars, i, profile
                    )
                    if passed:
                        setup = strategy_setup
                    elif setup is None:
                        # Strategy setup failed gates and no engine setup either
                        skipped += 1
                        skip_reasons[f"strategy_gate_{reason}"] = (
                            skip_reasons.get(f"strategy_gate_{reason}", 0) + 1
                        )
                        if self.journal is not None:
                            self.journal.log_signal(
                                strategy_setup, self.journal_symbol,
                                f"skip_strategy_{reason}",
                                f"strategy {strategy_setup.strategy_name} "
                                f"failed gate: {reason}",
                            )
                        equity.append((bar.time, balance))
                        continue

                if setup is not None:
                    profile = GATE_PROFILES.get(
                        setup.strategy_name or "", GATE_PROFILE_DEFAULT
                    )
                    setup.features = extract_features(setup, bars, i)

                    # ---- False-breakout filter ----------------------------------
                    if (profile.reject_false_breakouts
                            and self.cfg.rules.reject_false_breakouts
                            and setup.zone is not None):
                        z = setup.zone
                        det = bars[i]
                        if setup.direction == Direction.LONG:
                            wicked_below = det.low < z.bottom
                            closed_back_inside = det.close > z.bottom
                            if wicked_below and closed_back_inside and (det.close - det.low) > 2 * (det.high - det.close):
                                skipped += 1
                                skip_reasons["false_breakout"] = skip_reasons.get("false_breakout", 0) + 1
                                if self.journal is not None:
                                    self.journal.log_signal(
                                        setup, self.journal_symbol, "skip_false_breakout",
                                        f"detection bar wicked below zone bottom {z.bottom:.5f} "
                                        f"(low={det.low:.5f}) but closed back inside ({det.close:.5f})",
                                    )
                                equity.append((bar.time, balance))
                                continue
                        else:
                            wicked_above = det.high > z.top
                            closed_back_inside = det.close < z.top
                            if wicked_above and closed_back_inside and (det.high - det.close) > 2 * (det.close - det.low):
                                skipped += 1
                                skip_reasons["false_breakout"] = skip_reasons.get("false_breakout", 0) + 1
                                if self.journal is not None:
                                    self.journal.log_signal(
                                        setup, self.journal_symbol, "skip_false_breakout",
                                        f"detection bar wicked above zone top {z.top:.5f} "
                                        f"(high={det.high:.5f}) but closed back inside ({det.close:.5f})",
                                    )
                                equity.append((bar.time, balance))
                                continue

                    # ---- Candle-close confirmation gate -------------------------
                    entry_bar_offset = 1  # default: enter on next bar
                    require_confirmation = (
                        profile.require_close_confirmation
                        and self.cfg.rules.require_close_confirmation
                    )
                    if require_confirmation:
                        if i >= len(bars) - 2:
                            equity.append((bar.time, balance))
                            continue
                        confirm_bar = bars[i + 1]
                        is_bullish_close = confirm_bar.close > confirm_bar.open
                        if setup.direction == Direction.LONG:
                            confirmed = is_bullish_close and confirm_bar.low > setup.stop
                        else:
                            confirmed = (not is_bullish_close) and confirm_bar.high < setup.stop
                        setup.entry_confirmation = {
                            "required": "True",
                            "confirm_bar_time": confirm_bar.time.isoformat(),
                            "confirm_bar_open": f"{confirm_bar.open:.5f}",
                            "confirm_bar_close": f"{confirm_bar.close:.5f}",
                            "confirm_candle_dir": "bullish" if is_bullish_close else "bearish",
                            "confirmed": "True" if confirmed else "False",
                            "stop_violated_during_confirmation": (
                                "True" if (
                                    (setup.direction == Direction.LONG and confirm_bar.low <= setup.stop)
                                    or (setup.direction == Direction.SHORT and confirm_bar.high >= setup.stop)
                                ) else "False"
                            ),
                        }
                        if not confirmed:
                            skipped += 1
                            skip_reasons["no_confirmation"] = skip_reasons.get("no_confirmation", 0) + 1
                            if self.journal is not None:
                                self.journal.log_signal(
                                    setup, self.journal_symbol, "skip_no_confirmation",
                                    f"bar {confirm_bar.time:%H:%M} closed "
                                    f"{'bullish' if is_bullish_close else 'bearish'} "
                                    f"vs required {'bullish' if setup.direction == Direction.LONG else 'bearish'}",
                                )
                            equity.append((bar.time, balance))
                            continue
                        entry_bar_offset = 2  # skip detection bar + confirmation bar
                    else:
                        setup.entry_confirmation = {"required": "False"}

                    if i + entry_bar_offset >= len(bars):
                        equity.append((bar.time, balance))
                        continue

                    # ---- ML scorer gate (profile-aware) -------------------------
                    score = None
                    if profile.apply_ml_scorer:
                        is_lzi = setup.strategy_name == "LiquidityGrabReversal"
                        active_scorer = (
                            self.lzi_scorer if (is_lzi and self.lzi_scorer is not None)
                            else self.scorer
                        )
                        if active_scorer is not None:
                            if is_lzi and self.lzi_scorer is not None:
                                from agent.features.lzi_extractor import LZI_FEATURE_COLUMNS, extract_lzi_features
                                from agent.detectors.liquidity_zones import LiquidityZone
                                lzi_zone = self._extract_lzi_zone(setup, ctx)
                                if lzi_zone is not None:
                                    lzi_feats = extract_lzi_features(
                                        bars, lzi_zone, i, setup.take_profit,
                                    )
                                    score = active_scorer(lzi_feats.to_dict())
                                else:
                                    score = active_scorer(setup.features)
                            else:
                                score = active_scorer(setup.features)
                            setup.ml_score = score
                            threshold = (
                                profile.ml_score_override
                                if profile.ml_score_override is not None
                                else self.prob_threshold
                            )
                            if score < threshold:
                                skipped += 1
                                skip_reasons["ml_below_threshold"] = skip_reasons.get("ml_below_threshold", 0) + 1
                                if self.journal is not None:
                                    self.journal.log_signal(
                                        setup, self.journal_symbol, "skip_ml",
                                        f"ml score {score:.3f} < {threshold:.2f}",
                                        ml_score=score,
                                    )
                                equity.append((bar.time, balance))
                                continue

                    decision = self.risk.evaluate(
                        setup=setup,
                        account_balance=balance,
                        open_positions=0,
                        now=bar.time,
                    )
                    if decision.decision != RiskDecision.APPROVED:
                        skipped += 1
                        skip_reasons[decision.decision] = skip_reasons.get(decision.decision, 0) + 1
                        if self.journal is not None:
                            self.journal.log_signal(
                                setup, self.journal_symbol, decision.decision,
                                decision.reason, lot_size=decision.lot_size,
                                actual_risk_pct=decision.actual_risk_pct, ml_score=score,
                            )
                    else:
                        entry_bar = bars[i + entry_bar_offset]
                        open_trade = self._open_trade(setup, entry_bar, decision.lot_size)
                        if self.journal is not None:
                            sig_id = self.journal.log_signal(
                                setup, self.journal_symbol, "approved", "",
                                lot_size=decision.lot_size,
                                actual_risk_pct=decision.actual_risk_pct, ml_score=score,
                            )
                            open_trade_journal_id = self.journal.log_trade_open(
                                sig_id, self.journal_symbol, open_trade, mode=self.journal_mode,
                            )

            equity.append((bar.time, balance + (self._unrealized(open_trade, bar) if open_trade else 0)))

        if open_trade is not None and open_trade.exit_time is None:
            last = bars[-1]
            self._force_close(open_trade, last, "end_of_data")
            balance += open_trade.pnl
            if self.journal is not None and open_trade_journal_id is not None:
                self.journal.log_trade_close(
                    open_trade_journal_id,
                    exit_time=open_trade.exit_time,
                    exit_price=open_trade.exit_price,
                    exit_reason="end_of_data",
                    pnl=open_trade.pnl, pnl_pips=open_trade.pnl_pips,
                    commission=open_trade.commission,
                )
            trades.append(open_trade)

        metrics = compute_metrics(trades, self.cfg.backtest.initial_balance)
        return BacktestResult(
            trades=trades,
            equity_curve=equity,
            metrics=metrics,
            initial_balance=self.cfg.backtest.initial_balance,
            skipped_signals=skipped,
            skipped_reasons=skip_reasons,
        )

    def _extract_lzi_zone(self, setup: Setup, ctx) -> "LiquidityZone | None":
        """Find the triggered LZI zone that produced this setup (for LZI feature extraction)."""
        from agent.detectors.liquidity_zones import LiquidityZone
        liq_zones = getattr(ctx, "liquidity_zones", None) or []
        for z in liq_zones:
            if z.status == "triggered" and z.displacement_bar_index == setup.detected_bar_index:
                if z.trade_direction == setup.direction:
                    return z
        return None

    def _open_trade(self, setup: Setup, next_bar: Bar, lot: float) -> Trade:
        spread = self.cfg.backtest.spread_pips * 0.0001
        slip = self.cfg.backtest.slippage_pips * 0.0001
        if setup.direction == Direction.LONG:
            fill = next_bar.open + spread / 2 + slip
        else:
            fill = next_bar.open - spread / 2 - slip

        commission = lot * self.cfg.backtest.commission_per_lot

        trade = Trade(
            setup=setup,
            direction=setup.direction,
            entry_time=next_bar.time,
            entry_price=fill,
            stop_price=setup.stop,
            tp_price=setup.take_profit,
            lot_size=lot,
            commission=commission,
        )
        return trade

    def _check_exit(self, trade: Trade, bar: Bar) -> bool:
        """Detect SL or TP hit on this bar. If both possible, assume the worst (SL) for safety."""
        if trade.direction == Direction.LONG:
            hit_sl = bar.low <= trade.stop_price
            hit_tp = bar.high >= trade.tp_price
            if hit_sl and hit_tp:
                exit_price = trade.stop_price
                reason = "sl"
            elif hit_sl:
                exit_price = trade.stop_price
                reason = "sl"
            elif hit_tp:
                exit_price = trade.tp_price
                reason = "tp"
            else:
                return False
        else:
            hit_sl = bar.high >= trade.stop_price
            hit_tp = bar.low <= trade.tp_price
            if hit_sl and hit_tp:
                exit_price = trade.stop_price
                reason = "sl"
            elif hit_sl:
                exit_price = trade.stop_price
                reason = "sl"
            elif hit_tp:
                exit_price = trade.tp_price
                reason = "tp"
            else:
                return False

        trade.exit_time = bar.time
        trade.exit_price = exit_price
        trade.exit_reason = reason
        if trade.direction == Direction.LONG:
            pip_diff = to_pips(exit_price - trade.entry_price)
        else:
            pip_diff = to_pips(trade.entry_price - exit_price)
        trade.pnl_pips = pip_diff
        trade.pnl = pip_diff * trade.lot_size * self.cfg.backtest.pip_value_per_lot - trade.commission
        return True

    def _force_close(self, trade: Trade, bar: Bar, reason: str) -> None:
        exit_price = bar.close
        trade.exit_time = bar.time
        trade.exit_price = exit_price
        trade.exit_reason = reason
        if trade.direction == Direction.LONG:
            pip_diff = to_pips(exit_price - trade.entry_price)
        else:
            pip_diff = to_pips(trade.entry_price - exit_price)
        trade.pnl_pips = pip_diff
        trade.pnl = pip_diff * trade.lot_size * self.cfg.backtest.pip_value_per_lot - trade.commission

    def _unrealized(self, trade: Trade | None, bar: Bar) -> float:
        if trade is None:
            return 0.0
        if trade.direction == Direction.LONG:
            return to_pips(bar.close - trade.entry_price) * trade.lot_size * self.cfg.backtest.pip_value_per_lot
        return to_pips(trade.entry_price - bar.close) * trade.lot_size * self.cfg.backtest.pip_value_per_lot

    def _update_excursions(self, trade: Trade, bar: Bar, migrate: bool = True) -> None:
        """Track max adverse / max favorable excursion in pips. Also handle break-even
        stop migration when configured: once MFE crosses `move_be_at_r * stop_pips`,
        ratchet the stop to entry + `be_lock_r * stop_pips` in our favor.

        `migrate=False` is used when the trade just exited on this bar so we record the
        final MAE/MFE without changing the stop (the trade is already closed)."""
        trade.bars_held += 1
        if trade.direction == Direction.LONG:
            adverse_pips = to_pips(trade.entry_price - bar.low)
            favor_pips = to_pips(bar.high - trade.entry_price)
        else:
            adverse_pips = to_pips(bar.high - trade.entry_price)
            favor_pips = to_pips(trade.entry_price - bar.low)
        if adverse_pips > trade.mae_pips:
            trade.mae_pips = adverse_pips
        if favor_pips > trade.mfe_pips:
            trade.mfe_pips = favor_pips

        if not migrate:
            return

        be_trigger_r = self.cfg.backtest.move_be_at_r
        if be_trigger_r and be_trigger_r > 0:
            stop_pips = trade.setup.stop_pips
            if stop_pips > 0 and trade.mfe_pips >= be_trigger_r * stop_pips:
                lock_pips = self.cfg.backtest.be_lock_r * stop_pips
                if trade.direction == Direction.LONG:
                    new_stop = trade.entry_price + lock_pips * 0.0001
                    if new_stop > trade.stop_price:
                        trade.stop_price = new_stop
                else:
                    new_stop = trade.entry_price - lock_pips * 0.0001
                    if new_stop < trade.stop_price:
                        trade.stop_price = new_stop
