"""Real-time trading signal detection and execution loop.

Architecture:
1. Every N seconds (configurable, default 30s), fetch latest bars
2. Run rule engine on latest bars (detectors + confluences)
3. If setup passes all gates + ML scorer → generate signal
4. Check risk manager (daily DD, open positions, kill switch)
5. If approved → execute via broker connection
6. Log everything to journal + send Telegram alert
7. Position monitor checks breakeven/trailing in parallel
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import Config, GATE_PROFILES, GATE_PROFILE_DEFAULT, GateProfile, load_config
from agent.context.htf_context import HTFAnalyzer, HTFContext, MarketBias
from agent.features.extractor import extract_features
from agent.journal.db import Journal
from agent.live.broker import BrokerConnection, OrderResult, create_broker
from agent.live.chart_drawer import ChartDrawer
from agent.live.config import LiveConfig
from agent.live.monitor import PositionMonitor
from agent.model.scorer import SetupScorer
from agent.notifications.telegram import TelegramNotifier
from agent.risk.manager import RiskDecision, RiskManager
from agent.rules.engine import RuleEngine, precompute
from agent.strategy.registry import StrategyRouter, default_registry
from agent.types import Bar, Timeframe
from agent.utils import kill_switch_active

log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 15 * 60  # 15 minutes


class SignalLoop:
    """Real-time trading signal detection and execution loop.

    Designed to be resilient:
    - Graceful error handling (network issues, broker disconnects)
    - Automatic reconnection with exponential backoff
    - Kill switch support (create kill.txt to halt all trading)
    - Proper shutdown on SIGINT/SIGTERM
    """

    def __init__(
        self,
        config: Config,
        live_config: LiveConfig,
        broker: BrokerConnection,
        notifier: TelegramNotifier | None = None,
        journal: Journal | None = None,
        verbose: bool = False,
    ):
        self.config = config
        self.live_config = live_config
        self.broker = broker
        self.notifier = notifier or TelegramNotifier.from_env(dry_run=not live_config.telegram_enabled)
        self.journal = journal or Journal(config.journal_db)
        self.verbose = verbose

        self.engine = RuleEngine(config)
        self.risk = RiskManager(config)
        self.scorer = self._load_scorer()
        self.lzi_scorer = self._load_lzi_scorer()
        self._strategy_router = StrategyRouter(default_registry())
        self.monitor = PositionMonitor(
            broker=broker,
            config=config,
            live_config=live_config,
            notifier=self.notifier,
        )

        # HTF context layer
        self._htf_analyzer = HTFAnalyzer(lookback_days=config.htf.lookback_days) if config.htf.enabled else None
        self._htf_context: HTFContext | None = None
        self._h1_bars_since_htf_update = 0

        # Chart visualization bridge (writes JSON for MQL5 EA)
        mt5_files_path = getattr(live_config, 'mt5_files_path', None)
        self._chart_drawer = ChartDrawer(mt5_data_path=mt5_files_path)

        self._running = False
        self._last_bar_times: dict[str, datetime | None] = {}
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10

        # Heartbeat / status tracking
        self._start_time = datetime.now(tz=timezone.utc)
        self._last_heartbeat = self._start_time
        self._bars_checked = 0
        self._trades_today = 0
        self._pnl_today = 0.0
        self._last_check_status: dict[str, str] = {}  # per-TF status from last cycle

    def _load_scorer(self) -> SetupScorer | None:
        """Load the ML scorer if available."""
        active = self.journal.active_model()
        if not active:
            log.info("No active ML model registered; running rules-only mode")
            return None
        path = Path(active["file_path"])
        if not path.exists():
            log.warning("Active model file missing: %s", path)
            return None
        try:
            scorer = SetupScorer.load(path)
            log.info("Loaded ML scorer: version=%s", active["version"])
            return scorer
        except Exception as e:
            log.warning("Failed to load scorer: %s", e)
            return None

    def _load_lzi_scorer(self) -> SetupScorer | None:
        """Load the LZI-specific scorer if available."""
        lzi_path = Path(self.config.ml.lzi_scorer_path)
        if not lzi_path.is_absolute():
            from agent.config import PROJECT_ROOT
            lzi_path = PROJECT_ROOT / lzi_path
        if not lzi_path.exists():
            log.info("LZI scorer not found at %s; LZI will use generic scorer", lzi_path)
            return None
        try:
            scorer = SetupScorer.load(lzi_path)
            log.info("Loaded LZI scorer: %s", lzi_path.name)
            return scorer
        except Exception as e:
            log.warning("Failed to load LZI scorer: %s", e)
            return None

    # ------------------------------------------------------------------
    # Heartbeat / status logging
    # ------------------------------------------------------------------

    def _uptime_str(self) -> str:
        delta = datetime.now(tz=timezone.utc) - self._start_time
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m"

    def _htf_bias_str(self) -> str:
        if self._htf_context is not None:
            bias = self._htf_context.combined_bias.value.upper()
            conf = self._htf_context.bias_confidence
            return f"{bias} (confidence: {conf:.2f})"
        return "N/A (HTF disabled)" if not self._htf_analyzer else "N/A (not yet computed)"

    def _zones_summary(self, ctx=None) -> str:
        """Summarize active zones from precomputed context."""
        parts: list[str] = []
        if ctx is not None:
            lzi_zones = getattr(ctx, "liquidity_zones", None) or []
            active_lzi = [z for z in lzi_zones if getattr(z, "status", "") in ("fresh", "triggered")]
            if active_lzi:
                parts.append(f"{len(active_lzi)} LZI")

            fvg_zones = getattr(ctx, "fvgs", None) or []
            if fvg_zones:
                parts.append(f"{len(fvg_zones)} FVG")

            sd_zones = getattr(ctx, "sd_zones", None) or getattr(ctx, "supply_demand_zones", None) or []
            if sd_zones:
                parts.append(f"{len(sd_zones)} SD")
        return ", ".join(parts) if parts else "0"

    def _patterns_summary(self) -> str:
        if self._htf_context is None:
            return "N/A"
        patterns = self._htf_context.active_patterns
        if not patterns:
            return "None"
        return ", ".join(str(p) for p in patterns[:4])

    def _next_bar_estimate(self) -> str:
        """Estimate when the next H1 bar closes."""
        now = datetime.now(tz=timezone.utc)
        next_hour = now.replace(minute=0, second=0, microsecond=0)
        from datetime import timedelta
        if next_hour <= now:
            next_hour += timedelta(hours=1)
        return next_hour.strftime("%H:%M")

    def _maybe_heartbeat(self) -> None:
        """Log a 15-minute heartbeat summary if enough time has elapsed."""
        now = datetime.now(tz=timezone.utc)
        elapsed = (now - self._last_heartbeat).total_seconds()
        if elapsed < _HEARTBEAT_INTERVAL_SECONDS:
            return

        self._last_heartbeat = now
        now_str = now.strftime("%H:%M")
        htf_bias = self._htf_bias_str()
        zones = self._zones_summary()
        patterns = self._patterns_summary()
        next_bar = self._next_bar_estimate()

        log.info(
            "\n"
            "─── %s HEARTBEAT ───\n"
            "Status: ALIVE | Uptime: %s | Bars checked: %d\n"
            "HTF Bias: %s\n"
            "Active zones: %s\n"
            "Patterns: %s\n"
            "Next check: waiting for H1 bar close at %s\n"
            "Trades today: %d | P&L: $%.2f\n"
            "────────────────────────",
            now_str,
            self._uptime_str(), self._bars_checked,
            htf_bias,
            zones,
            patterns,
            next_bar,
            self._trades_today, self._pnl_today,
        )

    def _log_cycle_status(self, tf: str, new_bar: bool, status: str,
                          ctx=None) -> None:
        """Log a per-cycle status line (always in verbose, signals always)."""
        now_str = datetime.now(tz=timezone.utc).strftime("%H:%M")
        htf_bias = self._htf_bias_str().split(" (")[0]  # just the bias name
        zones = self._zones_summary(ctx)

        if new_bar:
            bar_time = self._last_bar_times.get(tf)
            bar_str = bar_time.strftime("%H:%M") if bar_time else "?"
            prefix = f"{now_str} | NEW {tf} BAR {bar_str}"
        else:
            prefix = f"{now_str} | {tf} checked"

        line = f"{prefix} | HTF: {htf_bias} | Zones: {zones} | {status}"
        self._last_check_status[tf] = status

        is_signal = status.startswith("\u26a1")  # ⚡ prefix = signal found
        if self.verbose or is_signal:
            log.info(line)

    async def run(self) -> None:
        """Main loop — runs until killed or fatal error."""
        self._running = True
        self._start_time = datetime.now(tz=timezone.utc)
        self._last_heartbeat = self._start_time

        log.info("=" * 60)
        log.info("Signal loop starting")
        log.info("  Broker: %s", self.live_config.broker_type)
        log.info("  Symbol: %s", self.live_config.symbol)
        log.info("  Timeframes: %s", self.live_config.timeframes)
        log.info("  Check interval: %ds", self.live_config.check_interval_seconds)
        log.info("  ML scorer: %s", "loaded" if self.scorer else "disabled")
        log.info("  LZI scorer: %s", "loaded" if self.lzi_scorer else "disabled")
        log.info("  Strategies: %s", ", ".join(self._strategy_router.registry.names()))
        log.info("  HTF context: %s", "enabled" if self._htf_analyzer else "disabled")
        log.info("  Verbose: %s", "ON" if self.verbose else "OFF (heartbeat every 15m)")
        log.info("  Kill file: %s", self.live_config.kill_file)
        log.info("=" * 60)

        # Connect to broker
        connected = await self._connect_with_retry()
        if not connected:
            log.error("Failed to connect to broker after retries. Exiting.")
            return

        # Startup notification
        self.notifier.notify_text(
            f"*Agent ONLINE*\nBroker: `{self.live_config.broker_type}`\n"
            f"Symbol: `{self.live_config.symbol}`\n"
            f"Timeframes: `{', '.join(self.live_config.timeframes)}`"
        )

        # Start position monitor as a background task
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
        """Gracefully stop the loop."""
        self._running = False

    async def _connect_with_retry(self) -> bool:
        """Connect to broker with exponential backoff."""
        for attempt in range(1, self.live_config.max_reconnect_attempts + 1):
            log.info("Broker connection attempt %d/%d", attempt, self.live_config.max_reconnect_attempts)
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

    async def _iteration(self) -> None:
        """Single loop iteration: check kill switch, fetch bars, evaluate signals."""
        try:
            # Kill switch check
            kill_path = Path(self.live_config.kill_file)
            if kill_switch_active(kill_path) or kill_switch_active(self.config.kill_switch_file):
                log.warning("Kill switch active — skipping iteration")
                return

            # Check each configured timeframe
            for tf_str in self.live_config.timeframes:
                await self._check_for_signals(tf_str)

            # Update chart overlay with current analysis state
            self._update_chart_drawings()

            # Reset error counter on successful iteration
            self._consecutive_errors = 0

        except Exception as e:
            self._consecutive_errors += 1
            log.error(
                "Iteration error (%d/%d): %s\n%s",
                self._consecutive_errors, self._max_consecutive_errors,
                e, traceback.format_exc(),
            )
            if self._consecutive_errors >= self._max_consecutive_errors:
                log.critical("Too many consecutive errors. Halting.")
                self.notifier.notify_text(
                    f"*CRITICAL: Agent halted*\n"
                    f"{self._max_consecutive_errors} consecutive errors.\n"
                    f"Last: `{str(e)[:200]}`"
                )
                self._running = False

    async def _check_for_signals(self, timeframe: str) -> None:
        """Single timeframe check: fetch bars, detect setup, evaluate, maybe trade.

        Runs BOTH the generic rule engine AND the strategy router (LZI, FVG
        Retest, SD Zone Retest).  Strategy-produced setups get profile-aware
        gate validation and per-strategy ML thresholds, matching the backtest
        pipeline exactly.
        """
        symbol = self.live_config.symbol
        tf = Timeframe(timeframe)

        # Fetch latest bars (need ~300 for detectors + LZI lookback)
        bars = await self.broker.get_latest_bars(symbol, timeframe, count=300)
        if len(bars) < 100:
            log.debug("Insufficient bars for %s %s (%d)", symbol, timeframe, len(bars))
            return

        # Check if we have a new closed bar since last check
        last_closed = bars[-2] if len(bars) >= 2 else bars[-1]
        prev_time = self._last_bar_times.get(timeframe)
        if prev_time == last_closed.time:
            next_close = self._next_bar_estimate()
            self._log_cycle_status(
                timeframe, new_bar=False,
                f"No new bar since last check (waiting for {next_close} close)",
            )
            return

        self._last_bar_times[timeframe] = last_closed.time
        self._bars_checked += 1
        log.info("New bar on %s: %s (close=%.5f)",
                 timeframe, last_closed.time.isoformat(), last_closed.close)

        # Update HTF context every N H1 bars (= every H4 close)
        if self._htf_analyzer and self.config.htf.enabled:
            self._h1_bars_since_htf_update += 1
            if (self._htf_context is None or
                    self._h1_bars_since_htf_update >= self.config.htf.update_interval_bars):
                await self._update_htf_context()
                self._h1_bars_since_htf_update = 0

        # Run rule engine on closed bars (exclude current forming bar)
        closed_bars = bars[:-1]
        bar_index = len(closed_bars) - 1

        # Build precomputed context so strategies (LZI, FVG, SD) can run
        ctx = precompute(closed_bars, self.config)

        # Cache zone data for chart overlay
        self._last_lzi_zones = getattr(ctx, "liquidity_zones", None)
        self._last_fvg_zones = getattr(ctx, "fvgs", None)
        self._last_sd_zones = (
            getattr(ctx, "sd_zones", None) or getattr(ctx, "supply_demand_zones", None)
        )

        # --- Source 1: generic rule engine ---
        engine_setup = self.engine.evaluate_precomputed(ctx, bar_index)

        # --- Source 2: strategy router (LZI, FVG Retest, SD Zone, etc.) ---
        strategy_setups = self._strategy_router.route(ctx, bar_index, regime=None)
        strategy_setup = strategy_setups[0] if strategy_setups else None

        # Prefer the strategy setup when it passes its profile gates
        setup = None
        gate_rejection_reason: str | None = None
        if strategy_setup is not None:
            profile = GATE_PROFILES.get(
                strategy_setup.strategy_name or "", GATE_PROFILE_DEFAULT
            )
            passed, gate_reason = self.engine.validate_setup_gates(
                strategy_setup, closed_bars, bar_index, profile
            )
            if passed:
                setup = strategy_setup
                log.info(
                    "Strategy setup [%s] on %s: %s entry=%.5f stop=%.5f tp=%.5f confluences=%s",
                    setup.strategy_name, timeframe, setup.direction.value,
                    setup.entry, setup.stop, setup.take_profit, setup.confluences,
                )
            else:
                gate_rejection_reason = (
                    f"Strategy [{strategy_setup.strategy_name}] detected "
                    f"but failed gate: {gate_reason}"
                )
                log.info(
                    "Strategy [%s] detected but failed gate: %s",
                    strategy_setup.strategy_name, gate_reason,
                )

        if setup is None and engine_setup is not None:
            setup = engine_setup
            log.info(
                "Engine setup on %s: %s entry=%.5f stop=%.5f tp=%.5f confluences=%s",
                timeframe, setup.direction.value, setup.entry, setup.stop,
                setup.take_profit, setup.confluences,
            )

        if setup is None:
            # Build a descriptive "why no signal" message
            zones_str = self._zones_summary(ctx)
            if strategy_setup is not None and gate_rejection_reason:
                reason = gate_rejection_reason
            elif zones_str == "0":
                reason = "No active zones (no recent sweeps/retests in lookback)"
            else:
                reason = f"{zones_str} zone(s) active but no retest confirmed"
            self._log_cycle_status(timeframe, new_bar=True, status=f"No entry triggered — {reason}", ctx=ctx)
            return

        # HTF alignment check — boost/penalize or block based on context
        if self._htf_context is not None and self.config.htf.enabled:
            direction_str = "buy" if setup.direction.value == "long" else "sell"
            htf_aligned = self._htf_context.supports_direction(direction_str)

            if not htf_aligned and self.config.htf.require_htf_alignment:
                htf_bias_val = self._htf_context.combined_bias.value
                log.info("HTF gate BLOCKED: %s conflicts with HTF bias (%s)",
                         direction_str, htf_bias_val)
                self.journal.log_signal(
                    setup, symbol, "skip_htf",
                    f"direction {direction_str} conflicts with HTF bias "
                    f"{htf_bias_val}",
                )
                self._log_cycle_status(
                    timeframe, new_bar=True,
                    status=f"Signal found but HTF misaligned "
                           f"(bias {htf_bias_val.upper()}, signal {direction_str.upper()})",
                    ctx=ctx,
                )
                return

            # Apply HTF-informed TP target if available
            htf_target = self._htf_context.get_nearest_htf_target(direction_str, setup.entry)
            if htf_target is not None:
                log.info("HTF target available: %.5f (current TP: %.5f)", htf_target, setup.take_profit)

            # Store alignment info for ML score adjustment later
            setup._htf_aligned = htf_aligned  # type: ignore[attr-defined]

        # Resolve the gate profile for this setup
        profile = GATE_PROFILES.get(
            setup.strategy_name or "", GATE_PROFILE_DEFAULT
        )

        # ML scoring gate (profile-aware thresholds)
        setup.features = extract_features(setup, closed_bars, bar_index)
        ml_score = None
        if profile.apply_ml_scorer:
            is_lzi = setup.strategy_name == "LiquidityGrabReversal"
            active_scorer = (
                self.lzi_scorer if (is_lzi and self.lzi_scorer is not None)
                else self.scorer
            )

            if is_lzi and self.lzi_scorer is not None:
                try:
                    from agent.features.lzi_extractor import extract_lzi_features
                    from agent.detectors.liquidity_zones import LiquidityZone
                    lzi_zone = self._extract_lzi_zone(setup, ctx)
                    if lzi_zone is not None:
                        lzi_feats = extract_lzi_features(
                            closed_bars, lzi_zone, bar_index, setup.take_profit,
                        )
                        ml_score = active_scorer(lzi_feats.to_dict())
                    elif active_scorer is not None:
                        ml_score = active_scorer(setup.features)
                except Exception as e:
                    log.warning("LZI feature extraction failed, using generic: %s", e)
                    if active_scorer is not None:
                        ml_score = active_scorer(setup.features)
            elif active_scorer is not None:
                ml_score = active_scorer(setup.features)

            if ml_score is not None:
                # Apply HTF alignment boost/penalty to ML score
                htf_aligned = getattr(setup, '_htf_aligned', None)
                if htf_aligned is not None and self.config.htf.enabled:
                    if htf_aligned:
                        ml_score += self.config.htf.htf_alignment_boost
                        log.info("HTF alignment boost: +%.2f", self.config.htf.htf_alignment_boost)
                    else:
                        ml_score -= self.config.htf.htf_misalignment_penalty
                        log.info("HTF misalignment penalty: -%.2f", self.config.htf.htf_misalignment_penalty)

                setup.ml_score = ml_score
                threshold = (
                    profile.ml_score_override
                    if profile.ml_score_override is not None
                    else self.live_config.score_threshold
                )
                log.info(
                    "ML score: %.3f (threshold=%.3f, strategy=%s)",
                    ml_score, threshold, setup.strategy_name or "generic",
                )
                if ml_score < threshold:
                    log.info("ML gate rejected: score=%.3f < threshold=%.3f", ml_score, threshold)
                    self.journal.log_signal(
                        setup, symbol, "skip_ml",
                        f"score {ml_score:.3f} < {threshold} "
                        f"(strategy={setup.strategy_name or 'generic'})",
                        ml_score=ml_score,
                    )
                    self._log_cycle_status(
                        timeframe, new_bar=True,
                        status=f"Signal found but ML score {ml_score:.2f} < threshold {threshold:.2f}",
                        ctx=ctx,
                    )
                    return

        # Risk management gate
        account = await self.broker.get_account_info()
        positions = await self.broker.get_open_positions(symbol)
        now = datetime.now(tz=timezone.utc)

        decision = self.risk.evaluate(
            setup=setup,
            account_balance=account.balance,
            open_positions=len(positions),
            now=now,
        )

        if decision.decision != RiskDecision.APPROVED:
            log.info("Risk gate rejected: %s (%s)", decision.decision, decision.reason)
            self.journal.log_signal(
                setup, symbol, decision.decision, decision.reason,
                lot_size=decision.lot_size, actual_risk_pct=decision.actual_risk_pct,
                ml_score=ml_score,
            )
            self._log_cycle_status(
                timeframe, new_bar=True,
                status=f"Signal found but risk gate rejected: {decision.reason}",
                ctx=ctx,
            )
            return

        # Execute trade
        direction_label = setup.direction.value.upper()
        strategy_label = setup.strategy_name or "generic"
        score_str_short = f" | Score: {ml_score:.2f}" if ml_score is not None else ""
        self._log_cycle_status(
            timeframe, new_bar=True,
            status=(
                f"\u26a1 SIGNAL: {strategy_label} {direction_label} "
                f"@ {setup.entry:.5f}{score_str_short} | Sending to broker..."
            ),
            ctx=ctx,
        )

        log.info(
            "EXECUTING: %s %s %.2f lots (risk=%.2f%%) [%s]",
            direction_label, symbol, decision.lot_size,
            decision.actual_risk_pct * 100,
            strategy_label,
        )

        result = await self.broker.place_order(
            symbol=symbol,
            direction=setup.direction,
            lot=decision.lot_size,
            stop=setup.stop,
            tp=setup.take_profit,
            comment=f"ai-agent {timeframe} {strategy_label} "
                    f"{','.join(setup.confluences[:3])}",
        )

        if result.success:
            self._trades_today += 1
            self._last_signals = [setup]
            log.info("Order filled: ticket=%s price=%.5f", result.ticket, result.fill_price)
            self.journal.log_signal(
                setup, symbol, RiskDecision.APPROVED, "executed",
                lot_size=decision.lot_size, actual_risk_pct=decision.actual_risk_pct,
                ml_score=ml_score,
            )
            score_str = f"\nScore: `{ml_score:.3f}`" if ml_score is not None else ""
            self.notifier.notify_text(
                f"*Trade OPEN* `{direction_label}` {symbol}\n"
                f"Strategy: `{strategy_label}`\n"
                f"TF: `{timeframe}` | Lot: `{decision.lot_size:.2f}`\n"
                f"Entry: `{result.fill_price:.5f}`\n"
                f"SL: `{setup.stop:.5f}` | TP: `{setup.take_profit:.5f}`\n"
                f"R:R = `1:{setup.rr:.1f}`{score_str}"
            )
        else:
            log.error("Order rejected by broker: %s", result.message)
            self.notifier.notify_text(f"*Order REJECTED*\n`{result.message}`")

    async def _update_htf_context(self) -> None:
        """Fetch H4 and D1 bars and recompute HTF structural context."""
        import pandas as pd

        symbol = self.live_config.symbol
        try:
            h4_bars_raw = await self.broker.get_latest_bars(symbol, "H4", count=self.config.htf.h4_lookback_bars)
            d1_bars_raw = await self.broker.get_latest_bars(symbol, "D1", count=self.config.htf.d1_lookback_bars)

            if len(h4_bars_raw) < 10 or len(d1_bars_raw) < 5:
                log.debug("Insufficient HTF bars (H4=%d, D1=%d), skipping HTF update",
                          len(h4_bars_raw), len(d1_bars_raw))
                return

            h4_df = pd.DataFrame([
                {"time": b.time, "open": b.open, "high": b.high,
                 "low": b.low, "close": b.close, "volume": b.volume}
                for b in h4_bars_raw
            ])
            d1_df = pd.DataFrame([
                {"time": b.time, "open": b.open, "high": b.high,
                 "low": b.low, "close": b.close, "volume": b.volume}
                for b in d1_bars_raw
            ])

            self._htf_context = self._htf_analyzer.analyze(h4_df, d1_df)  # type: ignore[union-attr]
            log.info(
                "HTF context updated: H4=%s D1=%s combined=%s confidence=%.2f "
                "patterns=%d levels=%d buy_aligned=%s sell_aligned=%s",
                self._htf_context.h4_bias.value,
                self._htf_context.d1_bias.value,
                self._htf_context.combined_bias.value,
                self._htf_context.bias_confidence,
                len(self._htf_context.active_patterns),
                len(self._htf_context.structural_levels),
                self._htf_context.buy_aligned,
                self._htf_context.sell_aligned,
            )
        except Exception as e:
            log.warning("HTF context update failed: %s", e)

    def _update_chart_drawings(self) -> None:
        """Push current analysis state to the MT5 chart overlay."""
        if not self._chart_drawer.enabled:
            return
        try:
            self._chart_drawer.update_from_context(
                htf_context=self._htf_context,
                lzi_zones=getattr(self, '_last_lzi_zones', None),
                fvg_zones=getattr(self, '_last_fvg_zones', None),
                sd_zones=getattr(self, '_last_sd_zones', None),
                active_signals=getattr(self, '_last_signals', None),
            )
        except Exception as e:
            log.debug("Chart drawer update failed: %s", e)

    @staticmethod
    def _extract_lzi_zone(setup, ctx):
        """Extract the LiquidityZone from a strategy-produced setup for LZI
        feature extraction."""
        from agent.detectors.liquidity_zones import LiquidityZone
        lzi_zones = getattr(ctx, "liquidity_zones", None) or []
        for z in lzi_zones:
            if z.status == "triggered" and z.trade_direction == setup.direction:
                return z
        return None


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------


async def run_signal_loop(
    broker_type: str = "paper",
    timeframes: list[str] | None = None,
    config_path: str | None = None,
    verbose: bool = False,
    **overrides: Any,
) -> None:
    """High-level entry point for starting the signal loop."""
    config = load_config(config_path)

    live_config = LiveConfig(
        symbol=config.symbol,
        timeframes=timeframes or [config.primary_timeframe],
        broker_type=broker_type,
        mt5_login=int(config.mt5_login) if config.mt5_login else 0,
        mt5_password=config.mt5_password,
        mt5_server=config.mt5_server,
        mt5_path=config.mt5_path,
        risk_per_trade_pct=config.risk.pct_target * 100,
        max_daily_dd_pct=config.risk.daily_dd_halt_pct * 100,
        max_open_positions=config.risk.max_open_positions,
        score_threshold=config.ml.prob_threshold,
    )

    # Apply any CLI overrides
    for key, val in overrides.items():
        if hasattr(live_config, key) and val is not None:
            setattr(live_config, key, val)

    broker = create_broker(
        broker_type=live_config.broker_type,
        login=live_config.mt5_login,
        password=live_config.mt5_password,
        server=live_config.mt5_server,
        path=live_config.mt5_path,
        initial_balance=live_config.paper_initial_balance,
        data_dir=config.data_dir,
    )

    loop = SignalLoop(
        config=config,
        live_config=live_config,
        broker=broker,
        verbose=verbose,
    )

    await loop.run()
