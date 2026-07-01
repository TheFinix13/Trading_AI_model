"""V2 signal loop — lean scaffold around the `Alpha` framework.

Replaces the 1898-line v1 orchestrator that wired in `StrategyRouter`,
`GATE_PROFILES`, `MLConfig.scorer_paths`, `HTFAnalyzer`, `PerformanceMemory`,
the explainer, and the MQL5 overlay drawer. The v2 reset (see
`docs/audit/preservation_list.md` §E) burns all of that and preserves only six
surgical pieces:

    1. `SignalLoop.run()` / `stop()`   — async lifecycle
    2. `_connect_with_retry`           — broker connect with backoff
    3. `_resolve_and_verify_symbol`    — startup symbol sanity check
    4. `_ensure_sl_tp`                 — mandatory SL/TP guarantee
    5. `_on_trade_closed`              — post-loss guard wiring
    6. The per-iteration alpha dispatch loop

Per-strategy ablation cells (the 224-cell grid) plug in by passing one or more
`Alpha` instances at construction. The loop is intentionally vocabulary-free —
it does not know LZI from FVG from BOS; it just polls each alpha for a signal
at each new bar close, gates the signal, sizes it, and routes the order.
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from agent.alphas.base import Alpha, AlphaContext, AlphaSignal
from agent.config import Config, load_config
from agent.live.state_store import StateStore
from agent.journal.target_ladder import (
    compute_target_ladder,
    ladder_summary,
    ladder_summary_from_dicts,
    score_rungs,
)
from agent.journal.vault import VaultRecorder
from agent.live.broker import BrokerConnection, MT5Broker, create_broker
from agent.live.config import LiveConfig
from agent.live.monitor import PositionMonitor
from agent.live.position_sizer import PositionSizer, SymbolConstraints
from agent.live.soft_stop import SoftStopConfig, catastrophe_stop
from agent.live.trade_events import (
    log_ladder,
    log_near_miss,
    log_order_rejected,
    log_signal_detected,
    log_trade_opened,
)
from agent.notifications.telegram import TelegramConfig, TelegramNotifier
from agent.risk.manager import RiskDecision, RiskManager
from agent.risk.post_loss_guard import GuardConfig, PostLossGuard
from agent.rules.engine import precompute
from agent.types import Direction, Setup, Timeframe
from agent.utils import kill_switch_active

log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 15 * 60


def next_h4_close_utc(now: datetime) -> datetime:
    """Next H4 candle boundary (00/04/08/12/16/20 UTC) strictly after ``now``."""
    floor = now.replace(minute=0, second=0, microsecond=0)
    floor -= timedelta(hours=now.hour % 4)
    return floor + timedelta(hours=4)


@dataclass
class _RoutedSignal:
    """Internal: an alpha signal paired with the alpha that produced it."""
    alpha: Alpha
    signal: AlphaSignal
    timeframe: str


class SignalLoop:
    """Async live/paper trading loop driven by one or more `Alpha` instances."""

    def __init__(
        self,
        alphas: Sequence[Alpha],
        *,
        config: Config | None = None,
        live_config: LiveConfig | None = None,
        broker: BrokerConnection | None = None,
        risk_scales: dict[str, float] | None = None,
        verbose: bool = False,
        vault: VaultRecorder | None = None,
        state_store_path: Path | None = None,
    ) -> None:
        if not alphas:
            raise ValueError("SignalLoop requires at least one Alpha")
        self.alphas: list[Alpha] = list(alphas)
        # Observation-only near-miss/loss vault (None = no recording). Pure
        # logging: it is only ever consulted AFTER a gate has already decided.
        self.vault = vault
        # Per-alpha risk multiplier (alpha name -> scale), e.g. the routing
        # table's risk_scale. Alphas not listed trade at 1.0.
        self.risk_scales: dict[str, float] = dict(risk_scales or {})
        self.config = config or load_config()
        self.live_config = live_config or LiveConfig()
        self.verbose = verbose
        # Crash-resilient state sidecar (None = persistence disabled).
        self._state_store: StateStore | None = (
            StateStore(state_store_path) if state_store_path is not None else None
        )

        self.broker = broker or create_broker(
            broker_type=self.live_config.broker_type,
            login=self.live_config.mt5_login,
            password=self.live_config.mt5_password,
            server=self.live_config.mt5_server,
            path=self.live_config.mt5_path,
            initial_balance=self.live_config.paper_initial_balance,
            data_dir=self.config.data_dir,
        )

        self.risk_manager = RiskManager(self.config, self.config.kill_switch_file)
        self.post_loss_guard = PostLossGuard(GuardConfig(
            enabled=self.live_config.revenge_guard_enabled,
            cooldown_minutes=self.live_config.post_loss_cooldown_minutes,
            cooldown_bars=self.live_config.post_loss_cooldown_bars,
            loss_risk_multiplier=self.live_config.post_loss_risk_multiplier,
            max_consecutive_losses=self.live_config.max_consecutive_losses,
            catastrophic_loss_frac=self.live_config.catastrophic_loss_frac,
            halt_on_stop_out=self.live_config.halt_on_stop_out,
            cooldown_override_conviction=self.live_config.post_loss_cooldown_override_conviction,
            cooldown_override_opposite_only=self.live_config.post_loss_cooldown_override_opposite_only,
        ))
        self.position_sizer = PositionSizer(
            min_risk_pct=self.live_config.risk_min_pct,
            max_risk_pct=self.live_config.risk_max_pct,
        )

        tcfg = TelegramConfig.from_env() if self.live_config.telegram_enabled else TelegramConfig()
        self.notifier = TelegramNotifier(tcfg)

        self.soft_stop_cfg = SoftStopConfig(
            enabled=self.live_config.soft_stop_enabled,
            confirm_on_close=self.live_config.soft_stop_confirm_on_close,
            catastrophe_mult=self.live_config.catastrophe_stop_mult,
            panic_mult=self.live_config.soft_stop_panic_mult,
            min_catastrophe_pips=self.live_config.soft_stop_min_catastrophe_pips,
        )
        self.monitor = PositionMonitor(
            broker=self.broker,
            config=self.config,
            live_config=self.live_config,
            notifier=self.notifier,
            soft_stop_cfg=self.soft_stop_cfg,
            trade_closed_cb=self._on_trade_closed,
            on_state_change=(
                self._persist_state if self._state_store is not None else None
            ),
        )

        self._last_bar_times: dict[str, datetime] = {}
        # Latest closed-bar series per timeframe, kept so vault snapshots
        # (rendered from a sync close callback) have chart data available.
        self._last_bars: dict[str, list] = {}
        self._running = False
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        self._last_balance: float | None = None
        self._last_heartbeat: datetime | None = None

    # ------------------------------------------------------------------
    # Crash-resilient state persistence
    # ------------------------------------------------------------------

    def _collect_state(self) -> dict:
        """Build the full state dict from all components. Pure read — no I/O."""
        now = datetime.now(tz=timezone.utc)
        return {
            "schema": 1,
            "symbol": self.live_config.symbol,
            "saved_at": now.isoformat(),
            "position_monitor": self.monitor.get_persist_state(),
            "post_loss_guard": self.post_loss_guard.get_persist_state(),
            "risk_manager": self.risk_manager.get_persist_state(),
            "signal_loop": {
                "last_bar_times": {
                    tf: t.isoformat()
                    for tf, t in self._last_bar_times.items()
                },
            },
        }

    def _persist_state(self) -> None:
        """Collect and atomically write the full state sidecar. Never raises."""
        if self._state_store is None:
            return
        try:
            self._state_store.save(self._collect_state())
        except Exception as exc:
            log.warning("[STATE SAVE FAILED] unexpected error: %s", exc)

    def _restore_state(self) -> None:
        """Load the state sidecar and restore each component.

        Called once at startup before the monitor task starts.
        PostLossGuard and RiskManager are only restored when the persisted
        day matches today UTC (their circuit-breaker / daily-DD logic is
        day-scoped).  PositionMonitor ctx is always restored and verified
        against open positions on the first monitor cycle.
        ``_last_bar_times`` timestamps are restored regardless of day but
        discarded if older than 2 days (clearly stale).
        """
        if self._state_store is None:
            return
        state = self._state_store.load()
        if state is None:
            return
        today = datetime.now(tz=timezone.utc).date().isoformat()

        # ── PositionMonitor ─────────────────────────────────────────────
        pm_data = state.get("position_monitor")
        if pm_data and isinstance(pm_data, dict):
            try:
                self.monitor.restore_from_persist_state(pm_data)
            except Exception as exc:
                log.warning("[STATE LOADED] position_monitor restore failed: %s", exc)

        # ── PostLossGuard (same-day only) ────────────────────────────────
        plg_data = state.get("post_loss_guard")
        if plg_data and isinstance(plg_data, dict):
            plg_day = plg_data.get("day")
            if plg_day == today:
                try:
                    self.post_loss_guard.restore_from_persist_state(plg_data)
                except Exception as exc:
                    log.warning(
                        "[STATE LOADED] post_loss_guard restore failed: %s", exc
                    )
            else:
                log.info(
                    "[STATE LOADED] post_loss_guard state is from %s (today %s) — discarded",
                    plg_day, today,
                )

        # ── RiskManager (same-day only) ──────────────────────────────────
        rm_data = state.get("risk_manager")
        if rm_data and isinstance(rm_data, dict):
            rm_day = rm_data.get("day")
            if rm_day == today:
                try:
                    self.risk_manager.restore_from_persist_state(rm_data)
                except Exception as exc:
                    log.warning(
                        "[STATE LOADED] risk_manager restore failed: %s", exc
                    )
            else:
                log.info(
                    "[STATE LOADED] risk_manager state is from %s (today %s) — discarded",
                    rm_day, today,
                )

        # ── SignalLoop._last_bar_times (up to 2 days old) ────────────────
        sl_data = state.get("signal_loop", {})
        if isinstance(sl_data, dict):
            now = datetime.now(tz=timezone.utc)
            cutoff = now - timedelta(days=2)
            restored_tfs: list[str] = []
            for tf, iso_str in sl_data.get("last_bar_times", {}).items():
                try:
                    ts = datetime.fromisoformat(iso_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= cutoff:
                        self._last_bar_times[tf] = ts
                        restored_tfs.append(f"{tf}={ts.isoformat()}")
                except (ValueError, TypeError):
                    pass
            if restored_tfs:
                log.info(
                    "[STATE LOADED] signal_loop last_bar_times: %s",
                    ", ".join(restored_tfs),
                )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop — runs until ``stop()`` is called or fatal error."""
        self._running = True
        self._last_heartbeat = datetime.now(tz=timezone.utc)
        self._restore_state()

        log.info("=" * 60)
        log.info("Signal loop starting (v2 scaffold)")
        log.info("  Broker: %s", self.live_config.broker_type)
        log.info("  Symbol: %s", self.live_config.symbol)
        log.info("  Timeframes: %s", self.live_config.timeframes)
        log.info("  Alphas: %s", ", ".join(a.name for a in self.alphas))
        log.info("  Check interval: %ds", self.live_config.check_interval_seconds)
        log.info("  Kill file: %s", self.live_config.kill_file)
        log.info("=" * 60)

        if not await self._connect_with_retry():
            log.error("Failed to connect to broker. Exiting.")
            return

        resolved = await self._resolve_and_verify_symbol()
        if resolved:
            self.live_config.symbol = resolved

        self.notifier.notify_text(
            f"*Agent ONLINE*\nBroker: `{self.live_config.broker_type}`\n"
            f"Symbol: `{self.live_config.symbol}`\n"
            f"Alphas: `{', '.join(a.name for a in self.alphas)}`"
        )

        monitor_task = asyncio.create_task(self.monitor.run())

        try:
            while self._running:
                await self._iteration()
                self._maybe_heartbeat()
                await asyncio.sleep(self.live_config.check_interval_seconds)
        except asyncio.CancelledError:
            log.info("Signal loop cancelled")
        except KeyboardInterrupt:
            log.info("Keyboard interrupt received")
        finally:
            self._running = False
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            await self.broker.disconnect()
            self.notifier.notify_text("*Agent OFFLINE*")
            log.info("Signal loop stopped")

    async def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Broker plumbing
    # ------------------------------------------------------------------

    async def _connect_with_retry(self) -> bool:
        for attempt in range(1, self.live_config.max_reconnect_attempts + 1):
            log.info("Broker connect attempt %d/%d",
                     attempt, self.live_config.max_reconnect_attempts)
            try:
                if await self.broker.connect():
                    return True
            except Exception as e:
                log.warning("Connection attempt %d failed: %s", attempt, e)
            if attempt < self.live_config.max_reconnect_attempts:
                delay = self.live_config.reconnect_delay_seconds * (2 ** (attempt - 1))
                log.info("Retrying in %ds...", delay)
                await asyncio.sleep(delay)
        return False

    async def _resolve_and_verify_symbol(self) -> str | None:
        base = self.live_config.symbol
        resolved = base
        if isinstance(self.broker, MT5Broker):
            resolved = await self.broker.resolve_symbol(base)
            if resolved != base:
                log.info("Symbol: %s (resolved from %s)", resolved, base)
        tf = self.live_config.timeframes[0] if self.live_config.timeframes else "H1"
        test_bars = await self.broker.get_latest_bars(resolved, tf, count=5)
        if test_bars:
            log.info("Startup bar test OK: %d bars for %s %s (latest %.5f @ %s)",
                     len(test_bars), resolved, tf,
                     test_bars[-1].close, test_bars[-1].time.isoformat())
        else:
            log.error("Cannot fetch bars for %s %s — check Market Watch.", resolved, tf)
        return resolved

    # ------------------------------------------------------------------
    # Iteration
    # ------------------------------------------------------------------

    async def _iteration(self) -> None:
        try:
            kill_path = Path(self.live_config.kill_file)
            if kill_switch_active(kill_path) or kill_switch_active(self.config.kill_switch_file):
                log.warning("Kill switch active — skipping iteration")
                return
            for tf in self.live_config.timeframes:
                await self._check_for_signals(tf)
            self._consecutive_errors = 0
        except Exception as e:
            self._consecutive_errors += 1
            log.error("Iteration error (%d/%d): %s\n%s",
                      self._consecutive_errors, self._max_consecutive_errors,
                      e, traceback.format_exc())
            if self._consecutive_errors >= self._max_consecutive_errors:
                log.critical("Too many consecutive errors. Halting.")
                self.notifier.notify_text(
                    f"*CRITICAL: Agent halted*\n"
                    f"{self._max_consecutive_errors} consecutive errors.\n"
                    f"Last: `{str(e)[:200]}`"
                )
                self._running = False

    async def _check_for_signals(self, timeframe: str) -> None:
        """Single-TF tick: poll each alpha and route any returned signal."""
        symbol = self.live_config.symbol
        bars = await self.broker.get_latest_bars(symbol, timeframe, count=300)
        if len(bars) < 100:
            return

        last_closed = bars[-2] if len(bars) >= 2 else bars[-1]
        if self._last_bar_times.get(timeframe) == last_closed.time:
            return
        self._last_bar_times[timeframe] = last_closed.time
        self._persist_state()

        closed = bars[:-1]
        if len(closed) < 30:
            return
        self._last_bars[timeframe] = closed

        ctx = precompute(closed, self.config)
        actx = AlphaContext(bars=closed, ctx=ctx, cfg=self.config)
        at_index = len(closed) - 1

        any_signal = False
        for alpha in self.alphas:
            try:
                signal = alpha.signal(actx, at_index)
            except Exception as e:
                log.warning("alpha %s failed: %s", alpha.name, e)
                continue
            if signal is None:
                continue
            any_signal = True
            await self._route_signal(_RoutedSignal(alpha, signal, timeframe),
                                     last_closed, bars=closed, ctx=ctx)
        if not any_signal:
            # One line per evaluated candle close so the log shows the agent
            # IS working between trades (pure logging, no behaviour change).
            try:
                close_dt = last_closed.time + timedelta(
                    minutes=Timeframe(timeframe).minutes)
                close_label = close_dt.strftime("%H:%M")
            except (ValueError, KeyError):
                close_label = last_closed.time.strftime("%H:%M")
            log.info("%s close %s UTC: evaluated, no setup (alphas checked: %s)",
                     timeframe, close_label,
                     ", ".join(a.name for a in self.alphas))

    # ------------------------------------------------------------------
    # Risk gates + execution
    # ------------------------------------------------------------------

    async def _route_signal(self, routed: _RoutedSignal, last_closed,
                            bars: list | None = None, ctx=None) -> None:
        symbol = self.live_config.symbol
        alpha, signal, timeframe = routed.alpha, routed.signal, routed.timeframe

        err = self._ensure_sl_tp(signal)
        if err:
            log.info("[%s] %s rejected: %s", timeframe, alpha.name, err)
            return

        account = await self.broker.get_account_info()
        self._last_balance = account.balance
        now = datetime.now(tz=timezone.utc)

        guard = self.post_loss_guard.pre_trade_check(
            now=now,
            reaction_conviction=signal.conviction,
            direction=signal.direction.value,
        )
        if not guard.allowed:
            log.info("[%s] %s blocked by post-loss guard: %s",
                     timeframe, alpha.name, guard.reason)
            log_near_miss(log, symbol=symbol, timeframe=timeframe,
                          alpha=alpha.name, reason="post_loss_guard",
                          detail=str(guard.reason))
            self._record_near_miss("post_loss_guard", routed, last_closed,
                                   bars, detail=str(guard.reason))
            return

        positions = await self.broker.get_open_positions(symbol)
        risk_result = self.risk_manager.evaluate(
            setup=self._to_setup(signal, alpha.name, last_closed.time, timeframe),
            account_balance=account.balance,
            open_positions=len(positions),
            now=now,
        )
        if risk_result.decision != RiskDecision.APPROVED:
            log.info("[%s] %s blocked by RiskManager: %s (%s)",
                     timeframe, alpha.name, risk_result.decision, risk_result.reason)
            log_near_miss(log, symbol=symbol, timeframe=timeframe,
                          alpha=alpha.name, reason="risk_manager",
                          detail=f"{risk_result.decision}: {risk_result.reason}")
            self._record_near_miss(
                "risk_manager", routed, last_closed, bars,
                detail=f"{risk_result.decision}: {risk_result.reason}")
            return

        constraints = SymbolConstraints(
            min_lot=self.config.risk.lot_min,
            max_lot=self.config.risk.lot_hard_cap,
            lot_step=self.config.risk.lot_step,
            pip_value_per_lot=self.config.backtest.pip_value_per_lot,
        )
        risk_mult = self.post_loss_guard.risk_multiplier()
        route_scale = self.risk_scales.get(alpha.name, 1.0)
        risk_pct = (self.position_sizer.risk_pct_for_conviction(signal.conviction)
                    * risk_mult * route_scale)
        sizing = self.position_sizer.calculate_lot(
            balance=account.balance,
            stop_distance_pips=signal.stop_pips,
            conviction=signal.conviction,
            risk_pct=risk_pct,
            pip_value=constraints.pip_value_per_lot,
            price=signal.entry,
            leverage=account.leverage or 500,
            free_margin=account.free_margin,
            constraints=constraints,
            max_risk_pct_hard=self.live_config.max_trade_risk_pct,
        )
        if sizing.lot <= 0:
            log.info("[%s] %s sized to zero lots: %s",
                     timeframe, alpha.name, sizing.summary())
            log_near_miss(log, symbol=symbol, timeframe=timeframe,
                          alpha=alpha.name, reason="sizing_skip",
                          detail=sizing.summary())
            self._record_near_miss("sizing_skip", routed, last_closed,
                                   bars, detail=sizing.summary())
            return

        # Portfolio-wide open-risk ceiling (Wave 2.2, 2026-07-01). Sum of
        # active risk across every ticket the broker is holding (all symbols
        # on this account) must not exceed cfg.risk.portfolio_max_open_risk_pct
        # AFTER adding the freshly-sized ticket. Because the 3 pair processes
        # are independent, the broker itself is the single source of truth
        # for the aggregate exposure - no shared-state file is needed.
        all_positions = await self.broker.get_open_positions(None)
        portfolio_check = self.risk_manager.evaluate_portfolio_ceiling(
            positions=all_positions,
            account_balance=account.balance,
            prospective_stop_pips=signal.stop_pips,
            prospective_lot=sizing.lot,
        )
        if portfolio_check.decision != RiskDecision.APPROVED:
            log.info("[%s] %s blocked by portfolio risk cap: %s",
                     timeframe, alpha.name, portfolio_check.reason)
            log_near_miss(log, symbol=symbol, timeframe=timeframe,
                          alpha=alpha.name, reason="portfolio_risk_cap",
                          detail=portfolio_check.reason)
            self._record_near_miss(
                "portfolio_risk_cap", routed, last_closed, bars,
                detail=portfolio_check.reason,
            )
            return

        log_signal_detected(
            log, symbol=symbol, timeframe=timeframe, alpha=alpha.name,
            direction=signal.direction.value, entry=signal.entry,
            soft_sl=signal.stop, tp=signal.take_profit,
            conviction=signal.conviction,
            meta=getattr(signal, "meta", None),
        )

        broker_stop = catastrophe_stop(
            direction_is_long=signal.direction == Direction.LONG,
            entry=signal.entry,
            soft_stop=signal.stop,
            cfg=self.soft_stop_cfg,
        )
        result = await self.broker.place_order(
            symbol=symbol,
            direction=signal.direction,
            lot=sizing.lot,
            stop=broker_stop,
            tp=signal.take_profit,
            comment=f"v2/{alpha.name}",
        )
        if not result.success:
            log_order_rejected(log, symbol=symbol, timeframe=timeframe,
                               alpha=alpha.name, message=result.message)
            # Vault the rejection. From the strategy's point of view this
            # was a valid setup; broker plumbing (AutoTrading off,
            # retcode=10027, no margin, no connection, …) erased it. We
            # don't want these silently dropped from the evidence stream.
            log_near_miss(log, symbol=symbol, timeframe=timeframe,
                          alpha=alpha.name, reason="broker_reject",
                          detail=str(result.message))
            self._record_near_miss("broker_reject", routed, last_closed,
                                   bars, detail=str(result.message))
            return

        fill = result.fill_price or signal.entry
        log_trade_opened(
            log, symbol=symbol, timeframe=timeframe, alpha=alpha.name,
            direction=signal.direction.value, ticket=result.ticket,
            entry=fill, lots=sizing.lot, soft_sl=signal.stop,
            catastrophe_sl=broker_stop, tp=signal.take_profit,
            risk_pct=sizing.actual_risk_pct,
        )

        # Observation-only extension ladder: structural levels beyond the
        # mechanical TP, journaled for later MFE scoring. Computed strictly
        # AFTER the order is placed — it can never influence the trade.
        ladder = self._compute_ladder(routed, ctx, bars,
                                      fill_price=result.fill_price)
        log_ladder(log, symbol=symbol, ticket=result.ticket,
                   rungs=ladder, entry=fill)

        self.monitor.register_entry(result.ticket, {
            "alpha": alpha.name,
            "timeframe": timeframe,
            "direction": signal.direction.value,
            "entry": result.fill_price or signal.entry,
            "entry_time": now.isoformat(),
            "soft_stop": signal.stop,
            "stop": broker_stop,
            "take_profit": signal.take_profit,
            "conviction": signal.conviction,
            "signal_reason": signal.reason,
            "target_ladder": ladder,
        })
        self._persist_state()
        ladder_note = ""
        if ladder:
            ladder_note = ("\nExtension ladder (opinion only): "
                           f"`{ladder_summary_from_dicts(ladder)}`")
        self.notifier.notify_text(
            f"*Trade OPENED* `{alpha.name}` `{signal.direction.value.upper()}`\n"
            f"Entry: `{result.fill_price or signal.entry:.5f}` Lots: `{sizing.lot:.2f}`\n"
            f"Soft SL: `{signal.stop:.5f}` Catastrophe SL: `{broker_stop:.5f}` TP: `{signal.take_profit:.5f}`\n"
            f"Risk: `{sizing.actual_risk_pct * 100:.2f}%`"
            f"{ladder_note}"
        )
        self._record_ladder_entry(result.ticket, routed, ladder, now, bars)

    def _ensure_sl_tp(self, signal: AlphaSignal) -> str:
        """Mandatory SL/TP guarantee. Returns "" if tradeable, or a reason string."""
        entry, stop, tp = signal.entry, signal.stop, signal.take_profit
        if entry is None or entry <= 0:
            return "no entry price"
        is_long = signal.direction == Direction.LONG

        def _valid_stop(s) -> bool:
            return s is not None and s > 0 and (s < entry if is_long else s > entry)

        def _valid_tp(t) -> bool:
            return t is not None and t > 0 and (t > entry if is_long else t < entry)

        if not _valid_stop(stop):
            return "invalid stop"
        if not _valid_tp(tp):
            return "invalid take-profit"
        return ""

    @staticmethod
    def _to_setup(signal: AlphaSignal, alpha_name: str,
                  decision_time: datetime, timeframe: str) -> Setup:
        """Minimal Setup adapter so the existing `RiskManager.evaluate` API can be reused.
        Only the fields RiskManager touches (entry / stop / take_profit / direction)
        are populated; everything else stays at its dataclass default."""
        return Setup(
            direction=signal.direction,
            timeframe=Timeframe(timeframe),
            detected_at=decision_time,
            detected_bar_index=0,
            entry=signal.entry,
            stop=signal.stop,
            take_profit=signal.take_profit,
            strategy_name=alpha_name,
        )

    # ------------------------------------------------------------------
    # Observation vaults (pure logging — gates have already decided)
    # ------------------------------------------------------------------

    def _compute_ladder(self, routed: _RoutedSignal, ctx, bars,
                        fill_price: float | None = None) -> list[dict]:
        """Compute the extension ladder for a just-filled trade. Pure
        observation — never raises, returns [] on any failure."""
        if ctx is None or bars is None:
            return []
        try:
            s = routed.signal
            rungs = compute_target_ladder(
                ctx, len(bars) - 1,
                direction=s.direction,
                entry=fill_price or s.entry,
                stop=s.stop,
                take_profit=s.take_profit,
            )
            if rungs:
                log.info("[%s] %s extension ladder (opinion only): %s",
                         routed.timeframe, routed.alpha.name,
                         ladder_summary(rungs))
            return [r.to_dict() for r in rungs]
        except Exception as e:
            log.warning("target ladder computation failed: %s", e)
            return []

    def _record_ladder_entry(self, ticket, routed: _RoutedSignal,
                             ladder: list[dict], now: datetime,
                             bars: list | None) -> None:
        """Vault the entry-time ladder opinion. Never raises."""
        if self.vault is None or not ladder:
            return
        try:
            s = routed.signal
            self.vault.record_ladder({
                "ts": now.isoformat(),
                "tf": routed.timeframe,
                "phase": "entry",
                "ticket": ticket,
                "alpha": routed.alpha.name,
                "direction": s.direction.value,
                "entry": s.entry,
                "stop": s.stop,
                "take_profit": s.take_profit,
                "conviction": s.conviction,
                "rungs": ladder,
            }, bars)
        except Exception as e:
            log.warning("ladder vault record failed: %s", e)

    def _record_ladder_close(self, ticket: int, info: dict, ctx: dict) -> None:
        """Score the journaled rungs against realised MFE at close. Never
        raises."""
        if self.vault is None:
            return
        ladder = ctx.get("target_ladder") or []
        if not ladder:
            return
        try:
            entry = float(ctx.get("entry") or 0.0)
            mfe_pips = float(info.get("mfe_pips", 0.0))
            scored = score_rungs(ladder, entry=entry, mfe_pips=mfe_pips)
            n_reached = sum(1 for r in scored if r.get("reached"))
            log.info("ladder resolution ticket=%s: %d/%d rungs reached "
                     "(mfe=%.1fp, exit=%s)",
                     ticket, n_reached, len(scored), mfe_pips,
                     info.get("exit_reason", "?"))
            tf = str(ctx.get("timeframe") or (
                self.live_config.timeframes[0] if self.live_config.timeframes else "H4"))
            self.vault.record_ladder({
                "ts": datetime.now(tz=timezone.utc).isoformat(),
                "tf": tf,
                "phase": "close",
                "ticket": ticket,
                "alpha": ctx.get("alpha"),
                "direction": ctx.get("direction"),
                "entry_time": ctx.get("entry_time"),
                "entry": ctx.get("entry"),
                "stop": ctx.get("soft_stop", ctx.get("stop")),
                "take_profit": ctx.get("take_profit"),
                "exit_price": info.get("exit_price"),
                "exit_reason": info.get("exit_reason", ""),
                "pnl_pips": info.get("pnl_pips", 0.0),
                "mfe_pips": mfe_pips,
                "rungs": scored,
            }, self._last_bars.get(tf))
        except Exception as e:
            log.warning("ladder close record failed: %s", e)

    def _record_near_miss(self, reason: str, routed: _RoutedSignal,
                          last_closed, bars: list | None,
                          detail: str = "") -> None:
        """Vault a downstream-rejected alpha signal. Never raises."""
        if self.vault is None:
            return
        try:
            s = routed.signal
            event = {
                "ts": last_closed.time.isoformat(),
                "tf": routed.timeframe,
                "reason": reason,
                "direction": s.direction.value,
                "entry": s.entry,
                "stop": s.stop,
                "take_profit": s.take_profit,
                "conviction": s.conviction,
                "signal_reason": s.reason,
                "alpha": routed.alpha.name,
                "detail": detail,
            }
            # Surface decision metadata (HTF gate inputs) the alpha
            # attached. Same shape the alpha's own htf_gate near-miss
            # hook uses, so the resolver / chart caption code stays
            # uniform across reason tags.
            meta = getattr(s, "meta", None) or {}
            for k in ("htf_bias", "htf_align", "htf_align_mode"):
                if meta.get(k) is not None:
                    event[k] = meta[k]
            self.vault.record_near_miss(event, bars)
        except Exception as e:
            log.warning("near-miss vault record failed: %s", e)

    def _record_loss(self, ticket: int, info: dict, ctx: dict,
                     pnl: float, r: float) -> None:
        """Vault a losing close (loss vault). Never raises."""
        if self.vault is None:
            return
        try:
            tf = str(ctx.get("timeframe") or (
                self.live_config.timeframes[0] if self.live_config.timeframes else "H4"))
            self.vault.record_loss({
                "ts": datetime.now(tz=timezone.utc).isoformat(),
                "tf": tf,
                "ticket": ticket,
                "direction": ctx.get("direction"),
                "entry_time": ctx.get("entry_time"),
                "entry": ctx.get("entry"),
                "exit_time": datetime.now(tz=timezone.utc).isoformat(),
                "exit_price": info.get("exit_price"),
                "stop": ctx.get("soft_stop", ctx.get("stop")),
                "take_profit": ctx.get("take_profit"),
                "pnl": pnl,
                "pnl_pips": info.get("pnl_pips", 0.0),
                "r_multiple": r,
                "mae_pips": info.get("mae_pips", 0.0),
                "mfe_pips": info.get("mfe_pips", 0.0),
                "exit_reason": info.get("exit_reason", ""),
                "conviction": ctx.get("conviction"),
                "alpha": ctx.get("alpha"),
                "signal_reason": ctx.get("signal_reason"),
            }, self._last_bars.get(tf))
        except Exception as e:
            log.warning("loss vault record failed: %s", e)

    # ------------------------------------------------------------------
    # Close callback
    # ------------------------------------------------------------------

    def _on_trade_closed(self, ticket: int, info: dict) -> None:
        """Monitor callback: feed PnL into the post-loss guard and notify."""
        ctx = info.get("entry_ctx", {}) or {}
        pnl = float(info.get("pnl", 0.0))
        r = float(info.get("r_multiple", 0.0))
        try:
            self.post_loss_guard.register_close(
                pnl=pnl, r_multiple=r,
                exit_reason=str(info.get("exit_reason", "")),
                now=datetime.now(tz=timezone.utc),
                account_balance=self._last_balance or None,
                direction=str(ctx.get("direction", "")) or None,
            )
            try:
                self.risk_manager.record_trade_pnl(pnl)
            except Exception:
                pass
            gs = self.post_loss_guard.status()
            if gs.get("session_halted"):
                log.warning("Risk guard: session halted (%s) — no new entries today",
                            gs.get("halt_reason"))
        except Exception as e:
            log.warning("post-loss guard register_close failed for %s: %s", ticket, e)
        # Persist the updated PLG / RM state (plus the now-closed position
        # ctx already removed from the monitor) as a single atomic write.
        self._persist_state()
        if pnl < 0:
            self._record_loss(ticket, info, ctx, pnl, r)
        self._record_ladder_close(ticket, info, ctx)
        outcome = "WIN" if pnl > 0 else "LOSS"
        self.notifier.notify_text(
            f"*Trade CLOSED* `{outcome}` ticket=`{ticket}`\n"
            f"P&L: `{pnl:+.2f}` ({info.get('pnl_pips', 0):+.0f}p, {r:+.2f}R)\n"
            f"Exit: `{info.get('exit_reason', '?')}`"
        )

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _maybe_heartbeat(self) -> None:
        """Periodic 'I am alive' INFO line (pure logging, no broker calls).

        Balance/equity/position count come from the monitor's last 5s cycle
        snapshot, so the heartbeat adds zero broker round-trips; if the
        monitor has not completed a cycle yet, the account part is omitted.
        """
        now = datetime.now(tz=timezone.utc)
        if self._last_heartbeat is None:
            self._last_heartbeat = now
            return
        if (now - self._last_heartbeat).total_seconds() < _HEARTBEAT_INTERVAL_SECONDS:
            return
        self._last_heartbeat = now
        account = getattr(self.monitor, "last_account", None)
        n_open = getattr(self.monitor, "last_open_position_count", None)
        if account is not None:
            status = (f"balance=${account.balance:.2f} "
                      f"equity=${account.equity:.2f} "
                      f"open_positions={n_open if n_open is not None else '?'}")
        else:
            status = "running (account snapshot pending)"
        log.info("heartbeat: %s | next H4 close ~%s UTC",
                 status, next_h4_close_utc(now).strftime("%H:%M"))
