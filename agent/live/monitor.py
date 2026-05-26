"""Position monitoring: breakeven, trailing stops, daily DD halt, kill switch.

Runs as a background asyncio task alongside the signal loop, checking
open positions every few seconds for management actions.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from agent.config import Config
from agent.live.broker import BrokerConnection, Position
from agent.live.config import LiveConfig
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
    ):
        self.broker = broker
        self.config = config
        self.live_config = live_config
        self.notifier = notifier or TelegramNotifier.from_env(dry_run=True)
        self.check_interval = check_interval

        # Track which positions we've already moved to breakeven
        self._breakeven_applied: set[int] = set()
        # Track known open tickets to detect closes
        self._known_tickets: set[int] = set()
        # Daily P&L tracking
        self._day_start_balance: float = 0.0
        self._current_day: str = ""

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
                await self._emergency_close_all("Kill switch activated")
                return

            symbol = self.live_config.symbol
            positions = await self.broker.get_open_positions(symbol)
            account = await self.broker.get_account_info()

            # Daily DD check
            await self._check_daily_dd(account.balance, account.equity, positions)

            # Detect closed positions (were open, now gone)
            current_tickets = {p.ticket for p in positions}
            closed_tickets = self._known_tickets - current_tickets
            if closed_tickets:
                for ticket in closed_tickets:
                    log.info("Position %d closed (SL/TP or manual)", ticket)
                self._known_tickets = current_tickets
                self._breakeven_applied -= closed_tickets

            # Update known tickets
            self._known_tickets = current_tickets

            # Manage each open position
            for pos in positions:
                await self._manage_position(pos)

        except Exception as e:
            log.debug("Monitor check error: %s", e)

    async def _manage_position(self, pos: Position) -> None:
        """Apply breakeven and trailing stop logic to a single position."""
        # Calculate how far price has moved in our favor (in pips)
        if pos.direction == Direction.LONG:
            mfe_pips = (pos.current_price - pos.open_price) * 10000
        else:
            mfe_pips = (pos.open_price - pos.current_price) * 10000

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

    async def _emergency_close_all(self, reason: str) -> None:
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

        # Create kill switch to prevent re-entry
        kill_path = Path(self.live_config.kill_file)
        kill_path.write_text(f"Auto-kill: {reason}\n{datetime.now(tz=timezone.utc).isoformat()}\n")
        log.warning("Kill switch file created at %s", kill_path)
