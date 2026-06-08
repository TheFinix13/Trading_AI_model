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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import Config, GATE_PROFILES, GATE_PROFILE_DEFAULT, GateProfile, load_config
from agent.context.htf_context import HTFAnalyzer, HTFContext, MarketBias
from agent.features.extractor import extract_features
from agent.journal.db import Journal
from agent.journal.live_journal import LiveJournal
from agent.journal.performance_memory import PerformanceMemory, make_signature
from agent.live.broker import BrokerConnection, MT5Broker, OrderResult, create_broker
from agent.live.chart_drawer import ChartDrawer
from agent.live.config import LiveConfig
from agent.live.explainer import BarCheckExplainer, ExplainedDecision, GateCheckItem
from agent.live.monitor import PositionMonitor
from agent.live.position_sizer import PositionSizer, SymbolConstraints
from agent.model.scorer import SetupScorer
from agent.notifications.telegram import TelegramNotifier
from agent.reaction import LevelOfInterest, ReactionAssessment, ReactionEngine, ReactionSignal
from agent.risk.manager import RiskDecision, RiskManager
from agent.risk.post_loss_guard import GuardConfig, PostLossGuard
from agent.rules.engine import RuleEngine, precompute
from agent.strategy.base import StrategyResult
from agent.types import Bar, Direction, Setup, Timeframe
from agent.strategy.registry import StrategyRouter, default_registry
from agent.utils import kill_switch_active

log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 15 * 60  # 15 minutes

# Short, MT5-safe abbreviations for each strategy so the order comment stays
# well under MT5's 31-char limit and contains no special characters.
_STRATEGY_SHORTCODES = {
    "LiquidityGrabReversal": "LZI",
    "FVGRetest": "FVG",
    "BOSContinuation": "BOS",
    "FibRetracement": "FIB",
    "SDZoneRetest": "SD",
    "Reaction": "RXN",
    "generic": "GEN",
}


@dataclass
class AnticipationOutcome:
    """Result of the anticipation (strategy + gate) evaluation for one bar.

    Separates *detection* (what was anticipated, even if it failed a gate) from
    the *confirmed* tradeable setup, so the coordinator can run the reaction
    engine, apply the anticipation->reaction flip, and size/execute centrally.
    """

    confirmed_setup: Setup | None = None
    ml_score: float | None = None
    gate_checks: list = field(default_factory=list)
    gate_profile: str = ""
    rejection_reason: str = ""
    htf_aligned: bool | None = None
    pre_gate_direction: Direction | None = None
    pre_gate_entry: float | None = None
    pre_gate_level: float | None = None  # the anticipated structural level
    session_label: str = ""


@dataclass
class TradeAction:
    """A chosen, ready-to-execute trade (anticipation or reaction)."""

    source: str               # "anticipation" | "reaction"
    setup: Setup
    conviction: float
    ml_score: float | None = None
    reaction: ReactionSignal | None = None
    is_flip: bool = False
    rationale: str = ""


def _short_order_comment(strategy_label: str, timeframe: str, direction_label: str) -> str:
    """Build a compact, MT5-safe order comment, e.g. ``FVG H1 L``.

    The broker sanitizes/truncates again as a safety net, but keeping the
    comment short and meaningful here makes positions easy to identify in the
    MT5 terminal.
    """
    short = _STRATEGY_SHORTCODES.get(strategy_label, (strategy_label or "AI")[:6])
    side = "L" if direction_label.upper().startswith("L") else "S"
    return f"{short} {timeframe} {side}"


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
        reset_journal: bool = False,
    ):
        self.config = config
        self.live_config = live_config
        self.broker = broker
        self.notifier = notifier or TelegramNotifier.from_env(dry_run=not live_config.telegram_enabled)
        self.journal = journal or Journal(config.journal_db)
        self.verbose = verbose

        # Trading mode: anticipation | reaction | hybrid
        self.mode = (getattr(live_config, "mode", None) or config.reaction.mode).lower()

        self.engine = RuleEngine(config)
        self.risk = RiskManager(config)
        self.scorer = self._load_scorer()
        self.lzi_scorer = self._load_lzi_scorer()
        self._strategy_router = StrategyRouter(default_registry())

        # ── Reaction engine (present-tense commitment) ──
        self.reaction_engine = (
            ReactionEngine(config.reaction) if config.reaction.enabled else None
        )

        # ── Adaptive, risk-based position sizing ──
        self.position_sizer = PositionSizer(
            min_risk_pct=getattr(live_config, "risk_min_pct", 0.005),
            max_risk_pct=getattr(live_config, "risk_max_pct", 0.02),
        )
        # Hard ceiling on a single trade's risk (oversize block / clamp).
        self.max_trade_risk_pct = getattr(live_config, "max_trade_risk_pct", 0.02)

        # ── Post-loss cooldown / no-revenge guard ──
        self.post_loss_guard = PostLossGuard(GuardConfig(
            enabled=getattr(live_config, "revenge_guard_enabled", True),
            cooldown_minutes=getattr(live_config, "post_loss_cooldown_minutes", 60.0),
            cooldown_bars=getattr(live_config, "post_loss_cooldown_bars", 2),
            loss_risk_multiplier=getattr(live_config, "post_loss_risk_multiplier", 0.5),
            max_consecutive_losses=getattr(live_config, "max_consecutive_losses", 3),
            catastrophic_loss_frac=getattr(live_config, "catastrophic_loss_frac", 0.10),
            halt_on_stop_out=getattr(live_config, "halt_on_stop_out", True),
        ))
        self._last_balance: float = 0.0

        # ── Fresh live journal + online performance memory (learning) ──
        journal_root = Path(getattr(live_config, "journal_root", "data/journal/live"))
        self.live_journal = LiveJournal(root=journal_root, scope="live")
        if reset_journal:
            archived = self.live_journal.archive_existing()
            if archived:
                log.info("Reset live journal — archived prior data to %s", archived)
        self.perf_memory = PerformanceMemory(
            path=journal_root / "performance_memory.json"
        )
        if reset_journal and self.perf_memory.path and self.perf_memory.path.exists():
            self.perf_memory.path.unlink()
            self.perf_memory = PerformanceMemory(path=journal_root / "performance_memory.json")
        self._journaled_days: set[str] = set()

        self.monitor = PositionMonitor(
            broker=broker,
            config=config,
            live_config=live_config,
            notifier=self.notifier,
            trade_closed_cb=self._on_trade_closed,
        )

        # HTF context layer
        self._htf_analyzer = HTFAnalyzer(lookback_days=config.htf.lookback_days) if config.htf.enabled else None
        self._htf_context: HTFContext | None = None
        self._h1_bars_since_htf_update = 0

        # Chart visualization bridge (writes JSON for MQL5 EA)
        mt5_files_path = getattr(live_config, 'mt5_files_path', None)
        self._chart_drawer = ChartDrawer(mt5_data_path=mt5_files_path)

        # Explainable AI layer
        self._explainer = BarCheckExplainer()

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
        log.info("  Trading mode: %s", self.mode)
        log.info("  Reaction engine: %s (threshold %.2f)",
                 "enabled" if self.reaction_engine else "disabled",
                 self.config.reaction.conviction_threshold)
        log.info("  Sizing: risk-based %.1f%%-%.1f%% (conviction-scaled, hard cap %.1f%%)",
                 self.position_sizer.min_risk_pct * 100,
                 self.position_sizer.max_risk_pct * 100,
                 self.max_trade_risk_pct * 100)
        g = self.post_loss_guard.cfg
        log.info("  Risk guard: %s (cooldown %.0fm/%db, x%.2f after loss, breaker %d losses)",
                 "ON" if g.enabled else "OFF", g.cooldown_minutes, g.cooldown_bars,
                 g.loss_risk_multiplier, g.max_consecutive_losses)
        log.info("  Live journal: %s", self.live_journal.root)
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

        # Resolve symbol name (handles broker suffixes like EURUSDm, EURUSD.)
        resolved_symbol = await self._resolve_and_verify_symbol()
        if resolved_symbol:
            self.live_config.symbol = resolved_symbol

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

    async def _resolve_and_verify_symbol(self) -> str | None:
        """Resolve the broker's actual symbol name and verify bar access on startup."""
        base_symbol = self.live_config.symbol
        resolved = base_symbol

        if isinstance(self.broker, MT5Broker):
            resolved = await self.broker.resolve_symbol(base_symbol)
            if resolved != base_symbol:
                log.info("Symbol: %s (resolved from %s)", resolved, base_symbol)
            else:
                log.info("Symbol: %s (exact match)", resolved)

        # Test-fetch 1 bar to confirm data access
        tf = self.live_config.timeframes[0] if self.live_config.timeframes else "H1"
        test_bars = await self.broker.get_latest_bars(resolved, tf, count=5)
        if test_bars:
            log.info(
                "Startup bar test OK: %d bars fetched for %s %s "
                "(latest close=%.5f at %s)",
                len(test_bars), resolved, tf,
                test_bars[-1].close, test_bars[-1].time.isoformat(),
            )
        else:
            log.error(
                "ERROR: Cannot fetch bars for %s %s. "
                "Check MT5 Market Watch and ensure the symbol is visible.",
                resolved, tf,
            )

        return resolved

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

        In verbose mode, outputs a full 5-step explainable-AI breakdown on
        every new bar close.
        """
        symbol = self.live_config.symbol
        tf = Timeframe(timeframe)

        # Fetch latest bars (need ~300 for detectors + LZI lookback)
        bars = await self.broker.get_latest_bars(symbol, timeframe, count=300)
        if len(bars) < 100:
            if len(bars) == 0:
                log.warning(
                    "0 bars for %s %s — symbol may not be in Market Watch or "
                    "broker returned no data. Check MT5 terminal.",
                    symbol, timeframe,
                )
            else:
                log.debug("Insufficient bars for %s %s (%d)", symbol, timeframe, len(bars))
            return

        # Check if we have a new closed bar since last check
        last_closed = bars[-2] if len(bars) >= 2 else bars[-1]
        prev_time = self._last_bar_times.get(timeframe)
        if prev_time == last_closed.time:
            next_close = self._next_bar_estimate()
            if self.verbose:
                current_bar = bars[-1]
                waiting_line = self._explainer.format_waiting_line(
                    timeframe, current_bar.close, next_close,
                )
                log.info(waiting_line)
            else:
                self._log_cycle_status(
                    timeframe, new_bar=False,
                    status=f"No new bar since last check (waiting for {next_close} close)",
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

        # Session label for this bar
        session_label = ""
        if ctx.session_labels and bar_index < len(ctx.session_labels):
            session_label = ctx.session_labels[bar_index]

        # Open the daily journal with today's market read (once per calendar day)
        self._journal_day_open(last_closed, ctx, session_label)

        # ── Explainable AI: collect strategy results for verbose output ──
        strategy_explain_results: list[StrategyResult] = []
        if self.verbose:
            strategy_explain_results = self._strategy_router.route_explained(
                ctx, bar_index, regime=None,
            )

        # ── Anticipation: strategy/gate stack marks levels and may confirm ──
        ant = self._evaluate_anticipation(
            closed_bars, bar_index, ctx, timeframe, last_closed, symbol, session_label,
        )

        # ── Reaction: present-tense commitment at a marked level ──
        atr_price = ctx.atr_by_index.get(bar_index, 0.0)
        levels = self._collect_levels_of_interest(ctx, bar_index)
        rxn_assess: ReactionAssessment | None = None
        if self.reaction_engine is not None and self.mode in ("reaction", "hybrid"):
            daily_levels = (
                ctx.daily_levels[bar_index]
                if ctx.daily_levels and bar_index < len(ctx.daily_levels) else None
            )
            rxn_assess = self.reaction_engine.assess(
                closed_bars, atr=atr_price, levels=levels,
                anticipated_direction=ant.pre_gate_direction,
                daily_levels=daily_levels, swings=getattr(ctx, "swings", None),
            )
            if rxn_assess.fired:
                log.info(
                    "Reaction: %s conviction=%.2f (%s) at %s",
                    rxn_assess.direction.value.upper() if rxn_assess.direction else "?",
                    rxn_assess.conviction, rxn_assess.components.as_dict(),
                    rxn_assess.level.label if rxn_assess.level else "no level",
                )

        # ── Decide which path (if any) pulls the trigger ──
        action = self._decide_action(
            ant, rxn_assess, last_closed, bar_index, session_label,
        )

        if action is not None:
            await self._execute_signal(
                action, ctx, bar_index, timeframe, last_closed, symbol,
                ant, rxn_assess, strategy_explain_results, session_label,
            )
            return

        # ── No trade this bar — status + verbose breakdown ──
        reason = ant.rejection_reason or "No committed move at a marked level"
        if not ant.rejection_reason and rxn_assess is not None and rxn_assess.rejection:
            reason = f"Reaction held off: {rxn_assess.rejection}"
        self._log_cycle_status(
            timeframe, new_bar=True, status=f"No entry triggered \u2014 {reason}", ctx=ctx,
        )
        # Log declined setups lightly so an over-strict filter is visible later.
        self._journal_declines(ant, rxn_assess, last_closed, session_label)
        if self.verbose:
            self._log_explained_check(
                last_closed, timeframe, ctx, strategy_explain_results,
                signal=ant.confirmed_setup, gate_checks=ant.gate_checks,
                gate_profile=ant.gate_profile, trade_executed=False,
                execution_details={}, rejection_reason=reason,
                htf_aligned=ant.htf_aligned, reaction_assess=rxn_assess,
            )

    # ------------------------------------------------------------------
    # Anticipation evaluation (strategy + gate stack), no execution
    # ------------------------------------------------------------------

    def _evaluate_anticipation(
        self, closed_bars, bar_index, ctx, timeframe, last_closed, symbol,
        session_label,
    ) -> AnticipationOutcome:
        """Run the strategy router + rule engine + gate/ML stack and return a
        structured outcome. This NEVER places an order — sizing and execution
        are handled centrally so the reaction engine and the flip can compose."""
        out = AnticipationOutcome(session_label=session_label)

        engine_setup = self.engine.evaluate_precomputed(ctx, bar_index)
        strategy_setups = self._strategy_router.route(ctx, bar_index, regime=None)
        strategy_setup = strategy_setups[0] if strategy_setups else None

        # Record the anticipated direction even if it fails a gate (for the flip).
        pre = strategy_setup or engine_setup
        if pre is not None:
            out.pre_gate_direction = pre.direction
            out.pre_gate_entry = pre.entry
            out.pre_gate_level = pre.stop  # the anticipated invalidation level

        gate_checks: list[GateCheckItem] = []
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
                    "Strategy setup [%s] on %s: %s entry=%.5f stop=%.5f tp=%.5f",
                    setup.strategy_name, timeframe, setup.direction.value,
                    setup.entry, setup.stop, setup.take_profit,
                )
            else:
                gate_rejection_reason = (
                    f"Strategy [{strategy_setup.strategy_name}] detected "
                    f"but failed gate: {gate_reason}"
                )
                log.info("Strategy [%s] detected but failed gate: %s",
                         strategy_setup.strategy_name, gate_reason)

        if setup is None and engine_setup is not None:
            setup = engine_setup
            log.info("Engine setup on %s: %s entry=%.5f stop=%.5f tp=%.5f",
                     timeframe, setup.direction.value, setup.entry, setup.stop,
                     setup.take_profit)

        if setup is None:
            zones_str = self._zones_summary(ctx)
            if strategy_setup is not None and gate_rejection_reason:
                out.rejection_reason = gate_rejection_reason
            elif zones_str == "0":
                out.rejection_reason = "No active zones (no recent sweeps/retests in lookback)"
            else:
                out.rejection_reason = f"{zones_str} zone(s) active but no retest confirmed"
            out.gate_checks = gate_checks
            return out

        out.pre_gate_direction = setup.direction
        out.pre_gate_entry = setup.entry
        out.pre_gate_level = setup.stop

        # HTF alignment check
        htf_aligned: bool | None = None
        if self._htf_context is not None and self.config.htf.enabled:
            direction_str = "buy" if setup.direction.value == "long" else "sell"
            htf_aligned = self._htf_context.supports_direction(direction_str)
            out.htf_aligned = htf_aligned
            if not htf_aligned and self.config.htf.require_htf_alignment:
                htf_bias_val = self._htf_context.combined_bias.value
                log.info("HTF gate BLOCKED: %s conflicts with HTF bias (%s)",
                         direction_str, htf_bias_val)
                self.journal.log_signal(
                    setup, symbol, "skip_htf",
                    f"direction {direction_str} conflicts with HTF bias {htf_bias_val}",
                )
                gate_checks.append(GateCheckItem(
                    "htf_alignment", False,
                    f"{direction_str.upper()} conflicts with {htf_bias_val.upper()} bias",
                ))
                out.gate_checks = gate_checks
                out.rejection_reason = (
                    f"HTF misaligned ({htf_bias_val.upper()} vs {direction_str.upper()})"
                )
                return out
            gate_checks.append(GateCheckItem(
                "htf_alignment", True,
                f"ALIGNED ({self._htf_context.combined_bias.value.upper()} confirms "
                f"{direction_str.upper()})" if htf_aligned else "HTF neutral, proceeding",
            ))
            setup._htf_aligned = htf_aligned  # type: ignore[attr-defined]

        profile = GATE_PROFILES.get(setup.strategy_name or "", GATE_PROFILE_DEFAULT)
        out.gate_profile = profile.name

        gate_checks.append(GateCheckItem(
            "session_filter", True,
            f"{session_label.upper().replace('_', ' ') if session_label else 'UNKNOWN'} (allowed)",
        ))

        day_name = last_closed.time.strftime("%A")
        caution_days = getattr(self.config.session, "caution_days", [])
        if day_name.lower()[:3] in [d.lower()[:3] for d in caution_days]:
            gate_checks.append(GateCheckItem(
                "caution_day", True,
                f"{day_name} is a caution day, applying stricter thresholds",
            ))

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
                if htf_aligned is not None and self.config.htf.enabled:
                    if htf_aligned:
                        ml_score += self.config.htf.htf_alignment_boost
                    else:
                        ml_score -= self.config.htf.htf_misalignment_penalty
                setup.ml_score = ml_score
                threshold = (
                    profile.ml_score_override
                    if profile.ml_score_override is not None
                    else self.live_config.score_threshold
                )
                scorer_label = "LZI scorer" if is_lzi and self.lzi_scorer else "generic scorer"
                log.info("ML score: %.3f (threshold=%.3f, strategy=%s)",
                         ml_score, threshold, setup.strategy_name or "generic")
                ml_passed = ml_score >= threshold
                gate_checks.append(GateCheckItem(
                    "ml_score", ml_passed,
                    f"{ml_score:.2f} ({scorer_label}) {'>' if ml_passed else '<'} "
                    f"{threshold:.2f} threshold",
                ))
                if not ml_passed:
                    self.journal.log_signal(
                        setup, symbol, "skip_ml",
                        f"score {ml_score:.3f} < {threshold} "
                        f"(strategy={setup.strategy_name or 'generic'})",
                        ml_score=ml_score,
                    )
                    out.gate_checks = gate_checks
                    out.ml_score = ml_score
                    out.rejection_reason = (
                        f"ML score {ml_score:.2f} < threshold {threshold:.2f}"
                    )
                    return out

        out.confirmed_setup = setup
        out.ml_score = ml_score
        out.gate_checks = gate_checks
        return out

    # ------------------------------------------------------------------
    # Levels of interest + decision + execution
    # ------------------------------------------------------------------

    def _collect_levels_of_interest(self, ctx, bar_index) -> list[LevelOfInterest]:
        """Gather the pre-marked structural levels the reaction engine watches:
        HTF structural levels & fibs, LZI/SD zones, FVGs and daily anchors."""
        levels: list[LevelOfInterest] = []

        # HTF structural levels + fibs (marked by the anticipation/HTF layer).
        if self._htf_context is not None:
            for lv in getattr(self._htf_context, "structural_levels", []) or []:
                levels.append(LevelOfInterest(lv.price, f"{lv.level_type}", "htf"))
            for price, label in getattr(self._htf_context, "htf_fib_levels", []) or []:
                levels.append(LevelOfInterest(price, label, "htf_fib"))

        # LZI zones (mid-price of the zone band).
        for z in getattr(ctx, "liquidity_zones", None) or []:
            top = getattr(z, "zone_top", None)
            bot = getattr(z, "zone_bottom", None)
            if top is not None and bot is not None:
                levels.append(LevelOfInterest(
                    (top + bot) / 2, f"LZI {getattr(z, 'swept_label', 'zone')}", "lzi",
                ))

        # FVGs (unfilled) + SD/qualified zones.
        for f in getattr(ctx, "fvgs", None) or []:
            if getattr(f, "is_fully_filled", False) or getattr(f, "filled", False):
                continue
            levels.append(LevelOfInterest((f.top + f.bottom) / 2, "FVG", "fvg"))
        sd_zones = getattr(ctx, "qualified_zones", None) or getattr(ctx, "zones", None) or []
        for z in sd_zones:
            top = getattr(z, "top", None)
            bot = getattr(z, "bottom", None)
            if top is not None and bot is not None:
                levels.append(LevelOfInterest((top + bot) / 2, "SD zone", "sd"))

        # Daily/weekly anchors.
        if ctx.daily_levels and bar_index < len(ctx.daily_levels):
            for label, price in ctx.daily_levels[bar_index].levels_dict().items():
                levels.append(LevelOfInterest(price, label, "daily"))

        return levels

    def _anticipation_conviction(
        self, setup, ml_score: float | None, htf_aligned: bool | None
    ) -> float:
        """Blend HTF alignment + ML score + setup quality into [0, 1]."""
        conv = 0.5
        if ml_score is not None:
            conv = max(conv, min(1.0, ml_score))
        if htf_aligned is True:
            conv = min(1.0, conv + 0.10)
        elif htf_aligned is False:
            conv = max(0.0, conv - 0.10)
        conv = min(1.0, conv + 0.02 * max(0, len(setup.confluences) - 2))
        return conv

    def _apply_perf_adjustment(
        self, conviction: float, setup, source: str, session_label: str,
        htf_aligned: bool | None,
    ) -> tuple[float, str]:
        """Nudge conviction by the online performance memory for this signature.
        Returns (adjusted_conviction, signature)."""
        sig = make_signature(
            setup.strategy_name or "generic", setup.direction.value,
            session_label, htf_aligned, source,
        )
        adj = self.perf_memory.conviction_adjustment(sig)
        new = max(0.0, min(1.0, conviction + adj))
        if adj != 0.0:
            log.info("Perf-memory %s: %+.3f (conviction %.2f -> %.2f)", sig, adj,
                     conviction, new)
        return new, sig

    def _reaction_to_setup(self, rxn: ReactionSignal, timeframe, last_closed,
                           bar_index) -> Setup:
        """Wrap a ReactionSignal as a Setup so execution/journaling is uniform."""
        conf = ["reaction"]
        if rxn.level_label:
            conf.append(f"level:{rxn.level_kind}")
        if rxn.is_breakout:
            conf.append("breakout")
        tf = last_closed.timeframe
        setup = Setup(
            direction=rxn.direction,
            timeframe=tf,
            detected_at=last_closed.time,
            detected_bar_index=bar_index,
            entry=rxn.entry,
            stop=rxn.stop,
            take_profit=rxn.take_profit,
            confluences=conf,
            confluence_tfs={c: tf.value for c in conf},
            strategy_name="Reaction",
        )
        return setup

    def _decide_action(
        self, ant: AnticipationOutcome, rxn_assess: ReactionAssessment | None,
        last_closed, bar_index, session_label,
    ) -> TradeAction | None:
        """Choose the trade path for this bar based on mode + the flip rule."""
        rxn = rxn_assess.signal if rxn_assess is not None else None

        def _anticipation_action() -> TradeAction:
            conv = self._anticipation_conviction(
                ant.confirmed_setup, ant.ml_score, ant.htf_aligned
            )
            conv, sig = self._apply_perf_adjustment(
                conv, ant.confirmed_setup, "anticipation", session_label, ant.htf_aligned
            )
            return TradeAction(
                "anticipation", ant.confirmed_setup, conv, ml_score=ant.ml_score,
                rationale="Confirmed anticipation setup",
            )

        def _reaction_action(is_flip: bool) -> TradeAction:
            setup = self._reaction_to_setup(
                rxn, last_closed.timeframe, last_closed, bar_index
            )
            conv, sig = self._apply_perf_adjustment(
                rxn.conviction, setup, "reaction", session_label, ant.htf_aligned
            )
            return TradeAction(
                "reaction", setup, conv, reaction=rxn, is_flip=is_flip,
                rationale=rxn.rationale,
            )

        if self.mode == "anticipation":
            return _anticipation_action() if ant.confirmed_setup is not None else None

        if self.mode == "reaction":
            return _reaction_action(
                is_flip=(ant.pre_gate_direction is not None
                         and rxn is not None
                         and ant.pre_gate_direction != rxn.direction)
            ) if rxn is not None else None

        # hybrid
        if ant.confirmed_setup is not None:
            # Anticipation→reaction flip: a strong opposing reaction abandons the
            # anticipated setup and engages the dominant-momentum direction.
            if (rxn is not None and self.config.reaction.flip_enabled
                    and rxn.direction != ant.confirmed_setup.direction
                    and rxn.conviction >= self.config.reaction.flip_min_conviction):
                log.info("FLIP: reaction %s (conv %.2f) overrides anticipated %s",
                         rxn.direction.value, rxn.conviction,
                         ant.confirmed_setup.direction.value)
                return _reaction_action(is_flip=True)
            return _anticipation_action()
        if rxn is not None:
            return _reaction_action(
                is_flip=(ant.pre_gate_direction is not None
                         and ant.pre_gate_direction != rxn.direction)
            )
        return None

    def _ensure_sl_tp(self, setup: Setup, ctx, bar_index: int) -> str:
        """Guarantee the setup has a structural SL and TP on the correct side of
        entry, deriving them from ATR + an R:R target if the signal omitted them.
        Returns "" if the setup is tradeable, or a reason string if it cannot be
        made valid (the caller must then refuse the trade)."""
        entry = setup.entry
        if entry is None or entry <= 0:
            return "no entry price"
        is_long = setup.direction == Direction.LONG
        atr = ctx.atr_by_index.get(bar_index, 0.0) if ctx is not None else 0.0

        def _valid_stop(s) -> bool:
            return s is not None and s > 0 and (s < entry if is_long else s > entry)

        def _valid_tp(t) -> bool:
            return t is not None and t > 0 and (t > entry if is_long else t < entry)

        if not _valid_stop(setup.stop):
            stop_dist = (atr * self.config.reaction.stop_atr_mult) if atr > 0 else 0.0
            if stop_dist <= 0:
                stop_dist = self.config.rules.stop_buffer_pips * 4 * 0.0001  # ~20p fallback
            stop_dist += self.config.reaction.stop_buffer_pips * 0.0001
            setup.stop = entry - stop_dist if is_long else entry + stop_dist
            log.info("Derived structural SL for %s: %.5f (%.1f pips)",
                     setup.strategy_name or "setup", setup.stop, setup.stop_pips)
        if not _valid_tp(setup.take_profit):
            rr = max(self.config.reaction.min_rr, self.config.reaction.fallback_rr)
            risk = abs(entry - setup.stop)
            setup.take_profit = entry + rr * risk if is_long else entry - rr * risk
            log.info("Derived R:R target for %s: %.5f (1:%.1f)",
                     setup.strategy_name or "setup", setup.take_profit, rr)

        if not (_valid_stop(setup.stop) and _valid_tp(setup.take_profit)):
            return "could not derive a valid structural SL/TP"
        return ""

    async def _execute_signal(
        self, action: TradeAction, ctx, bar_index, timeframe, last_closed, symbol,
        ant: AnticipationOutcome, rxn_assess: ReactionAssessment | None,
        strategy_explain_results, session_label,
    ) -> None:
        """Risk-gate, size (risk-based + conviction-scaled), place, journal."""
        setup = action.setup
        direction_label = setup.direction.value.upper()
        strategy_label = setup.strategy_name or "generic"

        account = await self.broker.get_account_info()
        positions = await self.broker.get_open_positions(symbol)
        now = datetime.now(tz=timezone.utc)
        self._last_balance = account.balance

        # ── Post-loss / no-revenge guard (HIGHEST-priority pre-trade gate) ──
        guard_decision = self.post_loss_guard.pre_trade_check(now, bar_index)
        if not guard_decision.allowed:
            reason = f"Risk guard ({guard_decision.code}): {guard_decision.reason}"
            log.warning("BLOCKED by post-loss guard: %s", guard_decision.reason)
            self.journal.log_signal(setup, symbol, f"skip_{guard_decision.code}",
                                    guard_decision.reason, ml_score=action.ml_score)
            self.live_journal.note(
                last_closed.time,
                f"Entry BLOCKED by no-revenge guard ({guard_decision.code}): "
                f"{guard_decision.reason}", kind="note",
            )
            self._log_cycle_status(timeframe, new_bar=True, status=reason, ctx=ctx)
            if self.verbose:
                parts = [self._explainer.explain_guard(
                    self.post_loss_guard.status(), guard_decision.code, guard_decision.reason)]
                log.info("\n".join(parts))
            return

        # ── Mandatory SL/TP enforcement: derive if missing, refuse if impossible ──
        sltp_problem = self._ensure_sl_tp(setup, ctx, bar_index)
        if sltp_problem:
            log.error("Order REFUSED — %s [%s %s]", sltp_problem, strategy_label, direction_label)
            self.journal.log_signal(setup, symbol, "skip_no_sltp", sltp_problem,
                                    ml_score=action.ml_score)
            self.live_journal.note(
                last_closed.time,
                f"Order REFUSED (no valid SL/TP): {sltp_problem}", kind="note",
            )
            self._log_cycle_status(
                timeframe, new_bar=True,
                status=f"Signal found but refused (no SL/TP): {sltp_problem}", ctx=ctx,
            )
            return

        # Hard account gates only (kill switch / daily halt / max positions).
        decision = self.risk.evaluate(
            setup=setup, account_balance=account.balance,
            open_positions=len(positions), now=now,
        )
        hard_blocks = {
            RiskDecision.SKIP_KILL_SWITCH,
            RiskDecision.SKIP_DAILY_HALT,
            RiskDecision.SKIP_MAX_POSITIONS,
        }
        if decision.decision in hard_blocks:
            log.info("Risk gate rejected: %s (%s)", decision.decision, decision.reason)
            self.journal.log_signal(setup, symbol, decision.decision, decision.reason,
                                    ml_score=action.ml_score)
            self._log_cycle_status(
                timeframe, new_bar=True,
                status=f"Signal found but risk gate rejected: {decision.reason}", ctx=ctx,
            )
            if self.verbose:
                self._log_explained_check(
                    last_closed, timeframe, ctx, strategy_explain_results,
                    signal=setup, gate_checks=ant.gate_checks, gate_profile=ant.gate_profile,
                    trade_executed=False, execution_details={},
                    rejection_reason=f"Risk gate: {decision.reason}",
                    htf_aligned=ant.htf_aligned, reaction_assess=rxn_assess,
                )
            return

        # ── Adaptive, risk-based, conviction-scaled position sizing ──
        constraints = SymbolConstraints(
            min_lot=self.config.risk.lot_min,
            lot_step=self.config.risk.lot_step,
            max_lot=self.config.risk.lot_hard_cap,
            pip_value_per_lot=self.config.backtest.pip_value_per_lot,
        )
        # Post-loss size reduction: halve (or configured) risk after a loss.
        risk_mult = self.post_loss_guard.risk_multiplier()
        base_risk_pct = self.position_sizer.risk_pct_for_conviction(action.conviction)
        applied_risk_pct = base_risk_pct * risk_mult
        if risk_mult < 1.0:
            log.warning(
                "GUARD size reduction: risk x%.2f after %d consecutive loss(es) "
                "(%.2f%% -> %.2f%%)",
                risk_mult, self.post_loss_guard.consecutive_losses,
                base_risk_pct * 100, applied_risk_pct * 100,
            )
        sizing = self.position_sizer.calculate_lot(
            balance=account.balance,
            stop_distance_pips=setup.stop_pips,
            conviction=action.conviction,
            risk_pct=applied_risk_pct,
            pip_value=self.config.backtest.pip_value_per_lot,
            price=setup.entry,
            leverage=account.leverage or 500,
            free_margin=account.free_margin,
            constraints=constraints,
            manual_cap=self.live_config.lot_size_override,
            max_risk_pct_hard=self.max_trade_risk_pct,
        )
        log.info("SIZING: %s", sizing.summary())
        if sizing.capped_by == "max_risk_hard":
            log.warning("GUARD oversize block: lot clamped to %.2f to cap single-trade "
                        "risk at %.1f%%", sizing.lot, self.max_trade_risk_pct * 100)
        if sizing.lot <= 0:
            reason = f"sizing produced 0 lots ({sizing.capped_by})"
            self.journal.log_signal(setup, symbol, "skip_sizing", reason,
                                    ml_score=action.ml_score)
            self._log_cycle_status(
                timeframe, new_bar=True,
                status=f"Signal found but {reason}", ctx=ctx,
            )
            if self.verbose:
                self._log_explained_check(
                    last_closed, timeframe, ctx, strategy_explain_results,
                    signal=setup, gate_checks=ant.gate_checks, gate_profile=ant.gate_profile,
                    trade_executed=False, execution_details={"sizing_summary": sizing.summary()},
                    rejection_reason=reason, htf_aligned=ant.htf_aligned,
                    reaction_assess=rxn_assess,
                )
            return

        lot = sizing.lot
        flip_tag = " [FLIP]" if action.is_flip else ""
        score_str_short = f" | Score: {action.ml_score:.2f}" if action.ml_score is not None else ""
        self._log_cycle_status(
            timeframe, new_bar=True,
            status=(
                f"\u26a1 {action.source.upper()} SIGNAL{flip_tag}: {strategy_label} "
                f"{direction_label} @ {setup.entry:.5f} (conv {action.conviction:.2f})"
                f"{score_str_short} | lot {lot:.2f} | Sending to broker..."
            ),
            ctx=ctx,
        )
        log.info("EXECUTING [%s%s]: %s %s %.2f lots (risk=%.2f%% conviction=%.2f)",
                 action.source, flip_tag, direction_label, symbol, lot,
                 sizing.actual_risk_pct * 100, action.conviction)

        result = await self.broker.place_order(
            symbol=symbol, direction=setup.direction, lot=lot, stop=setup.stop,
            tp=setup.take_profit,
            comment=_short_order_comment(strategy_label, timeframe, direction_label),
        )

        exec_details: dict = {"lot_size": lot, "sizing_summary": sizing.summary()}
        if result.success:
            self._trades_today += 1
            self._last_signals = [setup]
            fill = result.fill_price or setup.entry
            log.info("Order filled: ticket=%s price=%.5f", result.ticket, fill)
            self.journal.log_signal(
                setup, symbol, RiskDecision.APPROVED, f"executed ({action.source})",
                lot_size=lot, actual_risk_pct=sizing.actual_risk_pct,
                ml_score=action.ml_score,
            )
            signature = make_signature(
                strategy_label, setup.direction.value, session_label,
                ant.htf_aligned, action.source,
            )
            # Fresh live journal entry (markdown + jsonl feature snapshot)
            self.live_journal.log_trade_entry(
                ticket=result.ticket, time=last_closed.time, symbol=symbol,
                direction=setup.direction.value, source=action.source,
                strategy=strategy_label, signature=signature, entry=fill,
                stop=setup.stop, take_profit=setup.take_profit, lot=lot,
                conviction=action.conviction, sizing_summary=sizing.summary(),
                rationale=action.rationale, features=setup.features,
                reaction_components=(action.reaction.components.as_dict()
                                     if action.reaction else None),
            )
            # Register entry context so the monitor can journal a rich exit.
            self.monitor.register_entry(result.ticket, {
                "signature": signature, "source": action.source,
                "strategy": strategy_label, "direction": setup.direction.value,
                "entry": fill, "stop": setup.stop, "take_profit": setup.take_profit,
                "session": session_label, "htf_aligned": ant.htf_aligned,
                "conviction": action.conviction, "time": last_closed.time,
            })
            score_str = f"\nScore: `{action.ml_score:.3f}`" if action.ml_score is not None else ""
            self.notifier.notify_text(
                f"*Trade OPEN* `{direction_label}` {symbol}{flip_tag}\n"
                f"Source: `{action.source}` | Strategy: `{strategy_label}`\n"
                f"TF: `{timeframe}` | Lot: `{lot:.2f}` | Conv: `{action.conviction:.2f}`\n"
                f"Entry: `{fill:.5f}`\n"
                f"SL: `{setup.stop:.5f}` | TP: `{setup.take_profit:.5f}`\n"
                f"R:R = `1:{setup.rr:.1f}`{score_str}"
            )
            exec_details["fill_price"] = fill
        else:
            log.error("Order rejected by broker [%s %s %s @ %.5f lot=%.2f]: %s",
                      strategy_label, direction_label, timeframe, setup.entry, lot,
                      result.message)
            self.notifier.notify_text(f"*Order REJECTED*\n`{result.message}`")
            self.live_journal.note(
                last_closed.time,
                f"Order REJECTED for {direction_label} {strategy_label}: {result.message}",
                kind="note",
            )
            exec_details["rejected"] = True
            exec_details["reject_reason"] = result.message

        if self.verbose:
            self._log_explained_check(
                last_closed, timeframe, ctx, strategy_explain_results,
                signal=setup, gate_checks=ant.gate_checks, gate_profile=ant.gate_profile,
                trade_executed=result.success, execution_details=exec_details,
                htf_aligned=ant.htf_aligned, reaction_assess=rxn_assess,
            )

    # ------------------------------------------------------------------
    # Learning journal hooks
    # ------------------------------------------------------------------

    def _journal_day_open(self, bar: Bar, ctx, session_label: str) -> None:
        """Write the day's market read into the live journal once per day."""
        day = bar.time.strftime("%Y-%m-%d")
        if day in self._journaled_days:
            return
        # New calendar day: roll up the previous day (calibration + scorecard).
        if self._journaled_days:
            prev = max(self._journaled_days)
            try:
                self.live_journal.log_daily_rollup(prev)
            except Exception as e:
                log.debug("daily rollup failed for %s: %s", prev, e)
        self._journaled_days.add(day)
        htf_bias = self._htf_bias_str()
        zones = self._zones_summary(ctx)
        try:
            self.live_journal.start_day(
                day, htf_bias=htf_bias,
                anticipated_view=(
                    f"HTF bias {htf_bias}; anticipate with-trend retests/sweeps at marked levels"
                ),
                reactive_view=(
                    "React to committed displacement+momentum at marked levels; "
                    "flip if price blows through the anticipated level"
                ),
                zones=zones, mode=self.mode,
            )
        except Exception as e:
            log.debug("live journal start_day failed: %s", e)

    def _journal_declines(
        self, ant: AnticipationOutcome, rxn_assess: ReactionAssessment | None,
        last_closed: Bar, session_label: str,
    ) -> None:
        """Record detected-but-not-taken setups (gate failed / conviction below
        threshold) so an over-strict filter shows up in the daily review."""
        try:
            # Anticipation: a setup was anticipated but never confirmed.
            if (ant.pre_gate_direction is not None and ant.confirmed_setup is None
                    and ant.rejection_reason):
                sig = make_signature(
                    "generic", ant.pre_gate_direction.value, session_label,
                    ant.htf_aligned, "anticipation",
                )
                self.live_journal.log_declined(
                    last_closed.time, signature=sig, reason=ant.rejection_reason,
                    source="anticipation", direction=ant.pre_gate_direction.value,
                )
            # Reaction: a directional near-miss at a level that didn't clear gate.
            if (rxn_assess is not None and not rxn_assess.fired
                    and rxn_assess.direction is not None and rxn_assess.level is not None
                    and rxn_assess.conviction >= 0.5 * rxn_assess.threshold):
                sig = make_signature(
                    "Reaction", rxn_assess.direction.value, session_label,
                    ant.htf_aligned, "reaction",
                )
                self.live_journal.log_declined(
                    last_closed.time, signature=sig,
                    reason=rxn_assess.rejection or "below threshold",
                    source="reaction", conviction=rxn_assess.conviction,
                    direction=rxn_assess.direction.value,
                )
        except Exception as e:
            log.debug("decline journaling failed: %s", e)

    def _on_trade_closed(self, ticket: int, info: dict) -> None:
        """Monitor callback: record the closed trade into the journal + the
        online performance memory so the agent learns from present-time results."""
        ctx = info.get("entry_ctx", {}) or {}
        signature = ctx.get("signature", "")
        r = float(info.get("r_multiple", 0.0))
        pnl = float(info.get("pnl", 0.0))
        self._pnl_today += pnl
        # Feed the outcome into the post-loss / no-revenge guard FIRST so the
        # cooldown / size reduction / circuit breaker are armed before any new bar.
        try:
            self.post_loss_guard.register_close(
                pnl=pnl, r_multiple=r, exit_reason=str(info.get("exit_reason", "")),
                now=datetime.now(tz=timezone.utc),
                account_balance=self._last_balance or None,
            )
            gs = self.post_loss_guard.status()
            if gs["session_halted"]:
                log.warning("Risk guard: session halted (%s) — no new entries today",
                            gs["halt_reason"])
        except Exception as e:
            log.warning("post-loss guard register_close failed for %s: %s", ticket, e)
        try:
            if signature:
                stats = self.perf_memory.record(signature, r)
                log.info(
                    "LEARN: %s -> %+.2fR | signature n=%d wr=%.0f%% exp=%+.2fR "
                    "next-adj=%+.3f",
                    signature, r, stats.n, stats.win_rate * 100,
                    stats.expectancy_r, self.perf_memory.conviction_adjustment(signature),
                )
            self.live_journal.log_trade_exit(
                ticket=ticket, time=datetime.now(tz=timezone.utc),
                exit_price=info.get("exit_price", 0.0),
                exit_reason=info.get("exit_reason", "manual"),
                pnl=pnl, pnl_pips=float(info.get("pnl_pips", 0.0)),
                r_multiple=r, mae_pips=float(info.get("mae_pips", 0.0)),
                mfe_pips=float(info.get("mfe_pips", 0.0)), signature=signature,
                conviction=ctx.get("conviction"), source=ctx.get("source", ""),
            )
        except Exception as e:
            log.warning("journal/learn on close failed for %s: %s", ticket, e)
        outcome = "WIN" if pnl > 0 else "LOSS"
        self.notifier.notify_text(
            f"*Trade CLOSED* `{outcome}` ticket=`{ticket}`\n"
            f"P&L: `{pnl:+.2f}` ({info.get('pnl_pips', 0):+.0f}p, {r:+.2f}R)\n"
            f"Exit: `{info.get('exit_reason', '?')}`"
        )

    # ------------------------------------------------------------------
    # Explainable AI: verbose bar-check output
    # ------------------------------------------------------------------

    def _log_explained_check(
        self,
        bar: Bar,
        timeframe: str,
        ctx,
        strategy_results: list[StrategyResult],
        *,
        signal=None,
        gate_checks: list[GateCheckItem] | None = None,
        gate_profile: str = "",
        trade_executed: bool = False,
        execution_details: dict | None = None,
        rejection_reason: str = "",
        htf_aligned: bool | None = None,
        reaction_assess: ReactionAssessment | None = None,
    ) -> None:
        """Compose and log the full explainable-AI output (incl. reaction +
        sizing steps) so the user can SEE the reasoning every bar."""
        bar_index = len(ctx.bars) - 1
        session_label = ""
        if ctx.session_labels and bar_index < len(ctx.session_labels):
            session_label = ctx.session_labels[bar_index]

        day_name = bar.time.strftime("%A")
        caution_days = getattr(self.config.session, "caution_days", [])
        is_caution = day_name.lower()[:3] in [d.lower()[:3] for d in caution_days]

        # ── Header ──
        bar_time_str = bar.time.strftime("%Y-%m-%d %H:%M UTC")
        session_disp = session_label.upper().replace("_", " ") if session_label else "UNKNOWN"
        caution_tag = " (CAUTION)" if is_caution else ""

        parts: list[str] = [
            "",
            f"\u2550\u2550\u2550 BAR CHECK: {bar_time_str} ({timeframe}) \u2550\u2550\u2550",
            f"Price: {bar.close:.5f} | Session: {session_disp} | Day: {day_name}{caution_tag}",
            "",
        ]

        # ── Step 0: Risk Guard (post-loss / no-revenge) ──
        gs = self.post_loss_guard.status()
        if gs["session_halted"] or gs["consecutive_losses"] or gs["size_multiplier"] != 1.0:
            parts.append(self._explainer.explain_guard(gs))

        # ── Step 1: Market Context ──
        step1_text, _ = self._explainer.explain_context(
            self._htf_context, bar, session_label,
        )
        parts.append(step1_text)

        # ── Step 2: Zone Detection ──
        step2_text, _ = self._explainer.explain_detections(ctx, bar_index)
        parts.append(step2_text)

        # ── Step 3: Strategy Evaluation ──
        step3_text = self._explainer.explain_strategies(strategy_results)
        parts.append(step3_text)

        # ── Step 3.5: Reaction Engine ──
        if reaction_assess is not None:
            ra = reaction_assess
            parts.append(self._explainer.explain_reaction(
                components=ra.components.as_dict(),
                conviction=ra.conviction, threshold=ra.threshold,
                direction=ra.direction.value if ra.direction else "",
                agreement=ra.agreement,
                level_label=ra.level.label if ra.level else "",
                is_breakout=ra.is_breakout, fired=ra.fired, rejection=ra.rejection,
            ))

        # ── Step 4: Gate Check ──
        step4_text = self._explainer.explain_gates(
            signal, gate_checks or [], gate_profile,
        )
        parts.append(step4_text)

        # ── Step 5: Decision ──
        nearest_setup = ""
        watching_for = ""
        hypothetical = ""

        # Find best "nearest" setup from strategy results
        watching_results = [sr for sr in strategy_results if sr.status == "WATCHING"]
        if watching_results:
            best_watching = watching_results[0]
            nearest_setup = f"{best_watching.strategy_name} needs confirmation"
            watching_for = best_watching.next_trigger
            if best_watching.zones_details:
                nearest_setup += f" ({best_watching.zones_details[0][:50]})"

        step5_text = self._explainer.explain_decision(
            trade_executed=trade_executed,
            signal=signal,
            execution_details=execution_details,
            rejection_reason=rejection_reason,
            nearest_setup=nearest_setup,
            watching_for=watching_for,
            hypothetical=hypothetical,
            htf_aligned=htf_aligned,
        )
        parts.append(step5_text)

        # ── Step 6: Position Sizing (when a sizing pass happened) ──
        if execution_details and execution_details.get("sizing_summary"):
            parts.append(self._explainer.explain_sizing(
                execution_details["sizing_summary"]
            ))

        log.info("\n".join(parts))

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

    # reset_journal is a SignalLoop arg, not a LiveConfig field — pop it out.
    reset_journal = bool(overrides.pop("reset_journal", False))

    live_config = LiveConfig(
        symbol=config.symbol,
        timeframes=timeframes or [config.primary_timeframe],
        broker_type=broker_type,
        mt5_login=int(config.mt5_login) if config.mt5_login else 0,
        mt5_password=config.mt5_password,
        mt5_server=config.mt5_server,
        mt5_path=config.mt5_path,
        mode=config.reaction.mode,
        risk_per_trade_pct=config.risk.pct_target * 100,
        max_daily_dd_pct=config.risk.daily_dd_halt_pct * 100,
        max_open_positions=config.risk.max_open_positions,
        score_threshold=config.ml.prob_threshold,
        risk_min_pct=config.live.risk_min_pct,
        risk_max_pct=config.live.risk_max_pct,
        max_trade_risk_pct=config.live.max_trade_risk_pct,
        revenge_guard_enabled=config.live.revenge_guard_enabled,
        post_loss_cooldown_minutes=config.live.post_loss_cooldown_minutes,
        post_loss_cooldown_bars=config.live.post_loss_cooldown_bars,
        post_loss_risk_multiplier=config.live.post_loss_risk_multiplier,
        max_consecutive_losses=config.live.max_consecutive_losses,
        catastrophic_loss_frac=config.live.catastrophic_loss_frac,
        halt_on_stop_out=config.live.halt_on_stop_out,
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
        reset_journal=reset_journal,
    )

    await loop.run()
