"""Real-time trading signal detection and execution loop.

Architecture:
1. Every N seconds (configurable, default 60s for H1), fetch latest bars
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

from agent.config import Config, load_config
from agent.features.extractor import extract_features
from agent.journal.db import Journal
from agent.live.broker import BrokerConnection, OrderResult, create_broker
from agent.live.config import LiveConfig
from agent.live.monitor import PositionMonitor
from agent.model.scorer import SetupScorer
from agent.notifications.telegram import TelegramNotifier
from agent.risk.manager import RiskDecision, RiskManager
from agent.rules.engine import RuleEngine
from agent.types import Bar, Timeframe
from agent.utils import kill_switch_active

log = logging.getLogger(__name__)


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
    ):
        self.config = config
        self.live_config = live_config
        self.broker = broker
        self.notifier = notifier or TelegramNotifier.from_env(dry_run=not live_config.telegram_enabled)
        self.journal = journal or Journal(config.journal_db)

        self.engine = RuleEngine(config)
        self.risk = RiskManager(config)
        self.scorer = self._load_scorer()
        self.monitor = PositionMonitor(
            broker=broker,
            config=config,
            live_config=live_config,
            notifier=self.notifier,
        )

        self._running = False
        self._last_bar_times: dict[str, datetime | None] = {}
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10

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

    async def run(self) -> None:
        """Main loop — runs until killed or fatal error."""
        self._running = True
        log.info("=" * 60)
        log.info("Signal loop starting")
        log.info("  Broker: %s", self.live_config.broker_type)
        log.info("  Symbol: %s", self.live_config.symbol)
        log.info("  Timeframes: %s", self.live_config.timeframes)
        log.info("  Check interval: %ds", self.live_config.check_interval_seconds)
        log.info("  ML scorer: %s", "loaded" if self.scorer else "disabled")
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
        """Single timeframe check: fetch bars, detect setup, evaluate, maybe trade."""
        symbol = self.live_config.symbol
        tf = Timeframe(timeframe)

        # Fetch latest bars (need ~200 for detectors to work properly)
        bars = await self.broker.get_latest_bars(symbol, timeframe, count=300)
        if len(bars) < 100:
            log.debug("Insufficient bars for %s %s (%d)", symbol, timeframe, len(bars))
            return

        # Check if we have a new closed bar since last check
        last_closed = bars[-2] if len(bars) >= 2 else bars[-1]
        prev_time = self._last_bar_times.get(timeframe)
        if prev_time == last_closed.time:
            return  # Already processed this bar

        self._last_bar_times[timeframe] = last_closed.time
        log.debug("New bar on %s: %s", timeframe, last_closed.time.isoformat())

        # Run rule engine on closed bars (exclude current forming bar)
        closed_bars = bars[:-1]
        bar_index = len(closed_bars) - 1

        setup = self.engine.evaluate(closed_bars, bar_index)
        if setup is None:
            return

        log.info(
            "Setup detected on %s: %s entry=%.5f stop=%.5f tp=%.5f confluences=%s",
            timeframe, setup.direction.value, setup.entry, setup.stop, setup.take_profit,
            setup.confluences,
        )

        # ML scoring gate
        setup.features = extract_features(setup, closed_bars, bar_index)
        ml_score = None
        if self.scorer is not None:
            ml_score = self.scorer(setup.features)
            setup.ml_score = ml_score
            threshold = self.live_config.score_threshold
            if ml_score < threshold:
                log.info("ML gate rejected: score=%.3f < threshold=%.3f", ml_score, threshold)
                self.journal.log_signal(
                    setup, symbol, "skip_ml",
                    f"score {ml_score:.3f} < {threshold}",
                    ml_score=ml_score,
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
            return

        # Execute trade
        log.info(
            "EXECUTING: %s %s %.2f lots (risk=%.2f%%)",
            setup.direction.value.upper(), symbol, decision.lot_size,
            decision.actual_risk_pct * 100,
        )

        result = await self.broker.place_order(
            symbol=symbol,
            direction=setup.direction,
            lot=decision.lot_size,
            stop=setup.stop,
            tp=setup.take_profit,
            comment=f"ai-agent {timeframe} {','.join(setup.confluences[:3])}",
        )

        if result.success:
            log.info("Order filled: ticket=%s price=%.5f", result.ticket, result.fill_price)
            self.journal.log_signal(
                setup, symbol, RiskDecision.APPROVED, "executed",
                lot_size=decision.lot_size, actual_risk_pct=decision.actual_risk_pct,
                ml_score=ml_score,
            )
            # Notify
            self.notifier.notify_text(
                f"*Trade OPEN* `{setup.direction.value.upper()}` {symbol}\n"
                f"TF: `{timeframe}` | Lot: `{decision.lot_size:.2f}`\n"
                f"Entry: `{result.fill_price:.5f}`\n"
                f"SL: `{setup.stop:.5f}` | TP: `{setup.take_profit:.5f}`\n"
                f"R:R = `1:{setup.rr:.1f}`\n"
                f"Score: `{ml_score:.3f}`" if ml_score else
                f"*Trade OPEN* `{setup.direction.value.upper()}` {symbol}\n"
                f"TF: `{timeframe}` | Lot: `{decision.lot_size:.2f}`\n"
                f"Entry: `{result.fill_price:.5f}`\n"
                f"SL: `{setup.stop:.5f}` | TP: `{setup.take_profit:.5f}`\n"
                f"R:R = `1:{setup.rr:.1f}`"
            )
        else:
            log.error("Order rejected by broker: %s", result.message)
            self.notifier.notify_text(f"*Order REJECTED*\n`{result.message}`")


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------


async def run_signal_loop(
    broker_type: str = "paper",
    timeframes: list[str] | None = None,
    config_path: str | None = None,
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
    )

    await loop.run()
