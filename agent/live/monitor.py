"""Position monitoring: breakeven, trailing stops, daily DD halt, kill switch.

Runs as a background asyncio task alongside the signal loop, checking
open positions every few seconds for management actions.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from agent.config import Config
from agent.live.broker import BrokerConnection, Position
from agent.live.config import LiveConfig
from agent.live.soft_stop import SoftStopConfig, evaluate_soft_stop
from agent.notifications.telegram import TelegramNotifier
from agent.types import Direction
from agent.utils import kill_switch_active

log = logging.getLogger(__name__)


class PositionMonitor:
    """Monitors open positions for management actions.

    Responsibilities:
    - Move stop to breakeven when price reaches 1R in profit
    - Optional trailing stop after breakeven
    - Close all positions if daily drawdown limit hit
    - Close all positions if kill switch file appears
    - Detect SL/TP fills and send notifications
    """

    def __init__(
        self,
        broker: BrokerConnection,
        config: Config,
        live_config: LiveConfig,
        notifier: TelegramNotifier | None = None,
        check_interval: float = 5.0,
        trade_closed_cb: Callable[[int, dict], None] | None = None,
        soft_stop_cfg: SoftStopConfig | None = None,
    ):
        self.broker = broker
        self.config = config
        self.live_config = live_config
        self.notifier = notifier or TelegramNotifier.from_env(dry_run=True)
        self.check_interval = check_interval
        # Optional callback invoked when an open position closes, with
        # (ticket, exit_info dict). Used to journal exits + feed learning.
        self.trade_closed_cb = trade_closed_cb
        # Synthetic ("soft") stop layer — agent-managed wick-proof exits.
        self.soft_stop_cfg = soft_stop_cfg or SoftStopConfig(enabled=False)

        # Track which positions we've already moved to breakeven
        self._breakeven_applied: set[int] = set()
        # Track which positions have already booked a partial scale-out
        self._partial_applied: set[int] = set()
        # Exit reason recorded when WE close a position (soft stop / breakeven)
        # so the close handler journals the true cause, not an inferred one.
        self._forced_exit_reason: dict[int, str] = {}
        # Per-cycle cache of the latest closed bar by timeframe (soft-stop eval).
        self._last_closed_bar_cache: dict[str, object] = {}
        # Track known open tickets to detect closes
        self._known_tickets: set[int] = set()
        # Per-ticket entry context registered by the signal loop (signature,
        # source, stop/tp, conviction…) so we can journal a rich exit.
        self._entry_ctx: dict[int, dict] = {}
        # Per-ticket running excursion + last-seen state for exit reconstruction.
        self._excursion: dict[int, dict] = {}
        # Daily P&L tracking
        self._day_start_balance: float = 0.0
        self._current_day: str = ""
        self._kill_switch_handled: bool = False
        # Last account/position snapshot from the 5s monitor cycle, exposed so
        # the signal loop's heartbeat can log balance/equity/open-position
        # count without an extra broker round-trip.
        self.last_account = None
        self.last_open_position_count: int | None = None

    def register_entry(self, ticket: int, context: dict) -> None:
        """Record entry context so an eventual close can be journaled richly."""
        self._entry_ctx[ticket] = context
        self._excursion[ticket] = {
            "mae_pips": 0.0,
            "mfe_pips": 0.0,
            "last_price": context.get("entry", 0.0),
            "last_profit": 0.0,
        }

    async def run(self) -> None:
        """Background monitoring loop. Call as asyncio.create_task(monitor.run())."""
        log.info("Position monitor started (check every %.1fs)", self.check_interval)
        try:
            while True:
                await self._check_positions()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            log.info("Position monitor stopped")

    async def _check_positions(self) -> None:
        """Single monitoring iteration."""
        try:
            # Kill switch check — emergency close all
            kill_path = Path(self.live_config.kill_file)
            if kill_switch_active(kill_path) or kill_switch_active(self.config.kill_switch_file):
                # Only react once to avoid repeated notifications/log spam.
                if not self._kill_switch_handled:
                    self._kill_switch_handled = True
                    await self._emergency_close_all("Kill switch activated", create_kill_file=False)
                return

            symbol = self.live_config.symbol
            positions = await self.broker.get_open_positions(symbol)
            account = await self.broker.get_account_info()
            self.last_account = account
            self.last_open_position_count = len(positions)

            # Daily DD check
            await self._check_daily_dd(account.balance, account.equity, positions)

            # Update running excursion for each open position BEFORE detecting
            # closes, so the last-seen MAE/MFE is current when a close happens.
            for pos in positions:
                self._track_excursion(pos)

            # Detect closed positions (were open, now gone)
            current_tickets = {p.ticket for p in positions}
            closed_tickets = self._known_tickets - current_tickets
            if closed_tickets:
                for ticket in closed_tickets:
                    log.info("Position %d closed (SL/TP or manual)", ticket)
                    self._handle_close(ticket)
                self._breakeven_applied -= closed_tickets
                self._partial_applied -= closed_tickets

            # Update known tickets
            self._known_tickets = current_tickets

            # Refresh the closed-bar cache once per cycle for soft-stop checks.
            self._last_closed_bar_cache = {}

            # Manage each open position: soft stop first (may close), then the
            # legacy breakeven/trailing logic for anything still open.
            for pos in positions:
                closed = await self._manage_soft_stop(pos)
                if closed:
                    continue
                if self.live_config.partial_exit_enabled:
                    await self._manage_partial_scaleout(pos)
                await self._manage_position(pos)

        except Exception as e:
            log.debug("Monitor check error: %s", e)

    async def _latest_closed_price(self, symbol: str, timeframe: str) -> float | None:
        """Return the close of the most recent CLOSED bar for a timeframe,
        cached for the current monitoring cycle."""
        if timeframe in self._last_closed_bar_cache:
            cached = self._last_closed_bar_cache[timeframe]
            return cached if cached is not None else None
        try:
            bars = await self.broker.get_latest_bars(symbol, timeframe, count=3)
        except Exception:
            bars = []
        close = None
        if bars and len(bars) >= 2:
            close = bars[-2].close  # exclude the still-forming bar
        elif bars:
            close = bars[-1].close
        self._last_closed_bar_cache[timeframe] = close
        return close

    async def _manage_soft_stop(self, pos: Position) -> bool:
        """Evaluate the agent-managed soft stop for a position. Closes via a
        market order when the soft level is confirmed broken (close beyond it)
        or blown clean through intrabar (panic). Returns True if it closed."""
        if not self.soft_stop_cfg.enabled:
            return False
        ctx = self._entry_ctx.get(pos.ticket)
        if not ctx:
            return False
        soft_stop = ctx.get("soft_stop")
        if soft_stop is None:
            return False
        entry = ctx.get("entry", pos.open_price)
        is_long = pos.direction == Direction.LONG
        timeframe = ctx.get("timeframe") or (
            self.live_config.timeframes[0] if self.live_config.timeframes else "H1"
        )
        last_closed_price = await self._latest_closed_price(pos.symbol, timeframe)

        decision = evaluate_soft_stop(
            direction_is_long=is_long,
            entry=entry,
            soft_stop=soft_stop,
            last_closed_price=last_closed_price,
            current_price=pos.current_price,
            cfg=self.soft_stop_cfg,
        )
        if not decision.should_close:
            return False

        log.info("SOFT STOP fired for ticket=%d: %s", pos.ticket, decision.detail)
        result = await self.broker.close_position(pos.ticket, pos.symbol)
        if result.success:
            self._forced_exit_reason[pos.ticket] = decision.reason
            self.notifier.notify_text(
                f"*Soft stop exit* ticket=`{pos.ticket}`\n`{decision.detail}`"
            )
            return True
        log.error("Soft stop close FAILED for ticket=%d: %s — broker catastrophe "
                  "stop remains as backstop", pos.ticket, result.message)
        return False

    def _track_excursion(self, pos: Position) -> None:
        """Update running MAE/MFE (in pips) and last-seen state for a position."""
        exc = self._excursion.get(pos.ticket)
        if exc is None:
            # Position we didn't register (e.g. opened before this run). Track
            # it anyway so a close is still journaled with best-effort data.
            exc = {"mae_pips": 0.0, "mfe_pips": 0.0,
                   "last_price": pos.open_price, "last_profit": 0.0}
            self._excursion[pos.ticket] = exc
        if pos.direction == Direction.LONG:
            fav = (pos.current_price - pos.open_price) * 10000
            adv = (pos.open_price - pos.current_price) * 10000
        else:
            fav = (pos.open_price - pos.current_price) * 10000
            adv = (pos.current_price - pos.open_price) * 10000
        exc["mfe_pips"] = max(exc["mfe_pips"], fav)
        exc["mae_pips"] = max(exc["mae_pips"], adv)
        exc["last_price"] = pos.current_price
        exc["last_profit"] = pos.profit
        exc["open_price"] = pos.open_price
        exc["direction"] = pos.direction.value

    def _handle_close(self, ticket: int) -> None:
        """Reconstruct exit info for a closed ticket and fire the callback."""
        exc = self._excursion.pop(ticket, None)
        ctx = self._entry_ctx.pop(ticket, None)
        forced_reason = self._forced_exit_reason.pop(ticket, None)
        if self.trade_closed_cb is None:
            return
        exc = exc or {}
        ctx = ctx or {}
        exit_price = exc.get("last_price", ctx.get("entry", 0.0))
        entry_price = ctx.get("entry", exc.get("open_price", exit_price))
        # Risk is defined by the SOFT stop (the agent's real exit), not the wide
        # broker catastrophe stop, so R-multiples reflect the intended risk.
        stop = ctx.get("soft_stop", ctx.get("stop"))
        tp = ctx.get("take_profit")
        direction = ctx.get("direction", exc.get("direction", "long"))
        if direction == "long":
            pnl_pips = (exit_price - entry_price) * 10000
        else:
            pnl_pips = (entry_price - exit_price) * 10000
        stop_pips = abs(entry_price - stop) * 10000 if stop else 0.0
        r_multiple = (pnl_pips / stop_pips) if stop_pips > 0 else 0.0
        pnl = exc.get("last_profit", 0.0)

        # Prefer the true reason if WE closed it (soft stop / breakeven); else
        # infer from proximity to TP/SL.
        if forced_reason:
            reason = forced_reason
        else:
            reason = "manual"
            if tp is not None and abs(exit_price - tp) * 10000 <= 3:
                reason = "tp"
            elif stop is not None and abs(exit_price - stop) * 10000 <= 3:
                reason = "sl"
            elif pnl_pips > 0:
                reason = "tp"
            elif pnl_pips < 0:
                reason = "sl"

        info = {
            "exit_price": exit_price,
            "exit_reason": reason,
            "pnl": pnl,
            "pnl_pips": pnl_pips,
            "r_multiple": r_multiple,
            "mae_pips": exc.get("mae_pips", 0.0),
            "mfe_pips": exc.get("mfe_pips", 0.0),
            "entry_ctx": ctx,
        }
        try:
            self.trade_closed_cb(ticket, info)
        except Exception as e:  # never let journaling crash the monitor
            log.warning("trade_closed_cb failed for ticket %d: %s", ticket, e)

    def _r_multiple(self, pos: Position) -> tuple[float, float]:
        """Return (R-multiple of current MFE, stop distance in pips) for a
        position, measured against the SOFT stop (real risk) when present."""
        if pos.direction == Direction.LONG:
            mfe_pips = (pos.current_price - pos.open_price) * 10000
        else:
            mfe_pips = (pos.open_price - pos.current_price) * 10000
        ctx = self._entry_ctx.get(pos.ticket) or {}
        soft_stop = ctx.get("soft_stop")
        entry = ctx.get("entry", pos.open_price)
        if soft_stop is not None:
            stop_distance_pips = abs(entry - soft_stop) * 10000
        else:
            stop_distance_pips = abs(pos.open_price - pos.stop_loss) * 10000
        if stop_distance_pips == 0:
            return 0.0, 0.0
        return mfe_pips / stop_distance_pips, stop_distance_pips

    async def _manage_partial_scaleout(self, pos: Position) -> bool:
        """Book a partial at `partial_at_r` R and (optionally) push the rest to
        break-even, letting the runner chase the draw. Phase C — DEFAULT OFF; see
        LiveConfig.partial_exit_enabled for why. Returns True if it scaled out."""
        if pos.ticket in self._partial_applied:
            return False
        r_multiple, _ = self._r_multiple(pos)
        if r_multiple < self.live_config.partial_at_r:
            return False

        close_vol = round(pos.volume * self.live_config.partial_fraction, 2)
        if close_vol <= 0 or close_vol >= pos.volume:
            return False  # too small to split (or would close the whole thing)

        result = await self.broker.close_position(pos.ticket, pos.symbol, volume=close_vol)
        if not result.success:
            log.warning("Partial scale-out failed for ticket=%d: %s", pos.ticket, result.message)
            return False
        self._partial_applied.add(pos.ticket)
        log.info("PARTIAL scale-out: ticket=%d closed %.2f of %.2f lots at %.2fR",
                 pos.ticket, close_vol, pos.volume, r_multiple)
        self.notifier.notify_text(
            f"*Partial scale-out* ticket=`{pos.ticket}`\n"
            f"closed `{close_vol:.2f}` lots at `{r_multiple:.1f}R`, runner chasing draw"
        )

        # Push the runner to break-even so the banked move can't turn into a loss.
        if self.live_config.partial_move_to_be and pos.ticket not in self._breakeven_applied:
            new_stop = pos.open_price
            if self._is_better_stop(pos, new_stop):
                be = await self.broker.modify_position(pos.ticket, pos.symbol, stop=new_stop)
                if be.success:
                    self._breakeven_applied.add(pos.ticket)
                    if pos.ticket in self._entry_ctx and self._entry_ctx[pos.ticket].get("soft_stop") is not None:
                        self._entry_ctx[pos.ticket]["soft_stop"] = new_stop
        return True

    async def _manage_position(self, pos: Position) -> None:
        """Apply breakeven and trailing stop logic to a single position."""
        # Calculate how far price has moved in our favor (in pips)
        if pos.direction == Direction.LONG:
            mfe_pips = (pos.current_price - pos.open_price) * 10000
        else:
            mfe_pips = (pos.open_price - pos.current_price) * 10000

        # R is measured against the SOFT stop (real risk) when we have one, not
        # the wide broker catastrophe stop — otherwise breakeven would trigger
        # far too late.
        ctx = self._entry_ctx.get(pos.ticket) or {}
        soft_stop = ctx.get("soft_stop")
        entry = ctx.get("entry", pos.open_price)
        if soft_stop is not None:
            stop_distance_pips = abs(entry - soft_stop) * 10000
        else:
            stop_distance_pips = abs(pos.open_price - pos.stop_loss) * 10000
        if stop_distance_pips == 0:
            return

        r_multiple = mfe_pips / stop_distance_pips

        # Move to breakeven at configured R threshold
        be_trigger = self.live_config.move_be_at_r
        if be_trigger > 0 and r_multiple >= be_trigger and pos.ticket not in self._breakeven_applied:
            # Move stop to entry (+ small buffer in our favor)
            buffer = self.config.backtest.be_lock_r * stop_distance_pips * 0.0001
            if pos.direction == Direction.LONG:
                new_stop = pos.open_price + buffer
            else:
                new_stop = pos.open_price - buffer

            # Only modify if new stop is better than current
            if self._is_better_stop(pos, new_stop):
                result = await self.broker.modify_position(
                    pos.ticket, pos.symbol, stop=new_stop
                )
                if result.success:
                    self._breakeven_applied.add(pos.ticket)
                    # Pull the in-memory soft stop up to breakeven too, so the
                    # agent-managed exit also protects the locked-in level.
                    if soft_stop is not None and pos.ticket in self._entry_ctx:
                        self._entry_ctx[pos.ticket]["soft_stop"] = new_stop
                    log.info(
                        "Moved to breakeven: ticket=%d new_sl=%.5f (was %.5f, at %.1fR)",
                        pos.ticket, new_stop, pos.stop_loss, r_multiple,
                    )
                    self.notifier.notify_text(
                        f"*BE Move* ticket=`{pos.ticket}`\n"
                        f"SL: `{pos.stop_loss:.5f}` → `{new_stop:.5f}` ({r_multiple:.1f}R)"
                    )

        # Trailing stop (only after breakeven is applied)
        if (
            self.live_config.trailing_stop_enabled
            and pos.ticket in self._breakeven_applied
            and r_multiple > be_trigger + 0.5
        ):
            trail_distance = self.live_config.trailing_stop_distance_pips * 0.0001
            if pos.direction == Direction.LONG:
                trail_stop = pos.current_price - trail_distance
            else:
                trail_stop = pos.current_price + trail_distance

            if self._is_better_stop(pos, trail_stop):
                result = await self.broker.modify_position(
                    pos.ticket, pos.symbol, stop=trail_stop
                )
                if result.success:
                    log.debug(
                        "Trailing stop: ticket=%d sl=%.5f -> %.5f",
                        pos.ticket, pos.stop_loss, trail_stop,
                    )

    @staticmethod
    def _is_better_stop(pos: Position, new_stop: float) -> bool:
        """Check if new_stop is tighter (more protective) than current."""
        if pos.direction == Direction.LONG:
            return new_stop > pos.stop_loss
        else:
            return new_stop < pos.stop_loss

    async def _check_daily_dd(
        self, balance: float, equity: float, positions: list[Position]
    ) -> None:
        """Check if daily drawdown limit has been breached."""
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        # Reset on new day
        if today != self._current_day:
            self._current_day = today
            self._day_start_balance = balance
            return

        if self._day_start_balance <= 0:
            self._day_start_balance = balance
            return

        # Calculate DD from day-start balance to current equity
        dd_pct = (self._day_start_balance - equity) / self._day_start_balance
        max_dd = self.live_config.max_daily_dd_pct / 100.0

        if dd_pct >= max_dd:
            log.warning(
                "Daily DD limit reached: %.2f%% >= %.2f%%. Closing all positions.",
                dd_pct * 100, max_dd * 100,
            )
            await self._emergency_close_all(
                f"Daily DD halt: {dd_pct*100:.1f}% (limit {max_dd*100:.1f}%)"
            )

    async def _emergency_close_all(self, reason: str, *, create_kill_file: bool = True) -> None:
        """Close all open positions immediately."""
        log.warning("EMERGENCY CLOSE ALL: %s", reason)
        symbol = self.live_config.symbol
        positions = await self.broker.get_open_positions(symbol)

        for pos in positions:
            result = await self.broker.close_position(pos.ticket, pos.symbol)
            if result.success:
                log.info("Emergency closed ticket=%d", pos.ticket)
            else:
                log.error("Failed to close ticket=%d: %s", pos.ticket, result.message)

        self.notifier.notify_text(f"*EMERGENCY CLOSE*\n`{reason}`\nClosed {len(positions)} positions")

        # Create kill switch to prevent re-entry (only once).
        if create_kill_file:
            kill_path = Path(self.live_config.kill_file)
            if not kill_path.exists():
                kill_path.write_text(f"Auto-kill: {reason}\n{datetime.now(tz=timezone.utc).isoformat()}\n")
                log.warning("Kill switch file created at %s", kill_path)
