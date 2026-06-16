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
from agent.live.broker import BrokerConnection, OrderResult, Position
from agent.live.config import LiveConfig
from agent.live.soft_stop import SoftStopConfig, evaluate_soft_stop
from agent.live.trade_events import (
    classify_exit_tag,
    log_adopted_breach,
    log_breakeven_moved,
    log_ladder,
    log_ladder_unknown,
    log_partial_scaleout,
    log_position_adopted,
    log_position_restored,
    log_soft_stop_armed,
    log_soft_stop_fired,
    log_trade_closed,
)
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
        on_state_change: Callable[[], None] | None = None,
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
        # Optional callback invoked whenever monitor state changes (BE move,
        # partial exit) so the parent SignalLoop can persist the full state.
        self._on_state_change = on_state_change

        # Track which positions we've already moved to breakeven
        self._breakeven_applied: set[int] = set()
        # Track which positions have already booked a partial scale-out
        self._partial_applied: set[int] = set()
        # Exit reason recorded when WE close a position (soft stop / breakeven)
        # so the close handler journals the true cause, not an inferred one.
        self._forced_exit_reason: dict[int, str] = {}
        # When WE issue a market close we stash the broker's actual fill +
        # derived pnl here so the *next* monitor cycle's _handle_close emits
        # the real exit, not a 5s-stale tick (or worse, the entry price when
        # excursion has been clobbered for an adopted ticket).
        self._close_results: dict[int, dict[str, float]] = {}
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
        self._initial_scan_done: bool = False
        # Tickets restored from the state sidecar (not yet broker-verified).
        # Cleared after the first _check_positions cycle confirms them.
        self._restored_ctx_tickets: set[int] = set()
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

    def _record_close_result(
        self, pos: Position, ctx: dict, result: OrderResult,
    ) -> None:
        """Stash the broker's actual fill so _handle_close emits real numbers.

        Falls back to the last live tick price (``pos.current_price``) when
        the broker did not return a fill — but NEVER to the entry price,
        because that would silently mask a real loss as a $0 close.
        """
        fill_price = result.fill_price
        if not fill_price or fill_price <= 0:
            fill_price = pos.current_price or pos.open_price
        entry = ctx.get("entry", pos.open_price) or pos.open_price
        if pos.direction == Direction.LONG:
            pnl_pips = (fill_price - entry) * 10000
        else:
            pnl_pips = (entry - fill_price) * 10000
        pip_value = float(self.config.backtest.pip_value_per_lot)
        pnl_estimate = pnl_pips * pip_value * float(pos.volume)
        self._close_results[pos.ticket] = {
            "exit_price": float(fill_price),
            "pnl_pips": float(pnl_pips),
            "pnl_estimate": float(pnl_estimate),
            "lots": float(pos.volume),
        }

    # ------------------------------------------------------------------
    # Adopted-position handling (soft-SL inference)
    # ------------------------------------------------------------------

    # Minimum broker-stop distance below which we won't trust an inferred
    # soft level — anything tighter than this either is a degenerate
    # config or risks placing a soft stop on top of entry.
    _INFER_MIN_BROKER_PIPS: float = 4.0

    def _infer_soft_stop_from_broker(
        self, entry: float, broker_sl: float, is_long: bool,
    ) -> float | None:
        """Best-effort soft-stop reconstruction for an adopted ticket.

        Inverts the catastrophe formula:
            broker_sl ≈ entry ∓ catastrophe_mult × soft_dist
        Returns None when the broker SL is missing / zero / degenerately
        tight, so the caller can fall back to the legacy "unknown"
        behaviour.
        """
        if not broker_sl or broker_sl <= 0:
            return None
        cata_dist = abs(entry - broker_sl)
        if cata_dist < self._INFER_MIN_BROKER_PIPS * 0.0001:
            return None
        cata_mult = max(1.0, float(self.soft_stop_cfg.catastrophe_mult))
        soft_dist = cata_dist / cata_mult
        return entry - soft_dist if is_long else entry + soft_dist

    @staticmethod
    def _price_beyond_soft(
        is_long: bool, soft_stop: float, current_price: float | None,
    ) -> bool:
        """Has the market already moved past the soft level we just armed?"""
        if current_price is None or current_price <= 0:
            return False
        return (current_price <= soft_stop if is_long
                else current_price >= soft_stop)

    def _adopt_position(self, pos: Position) -> None:
        """Log + register a broker position the agent did not open.

        Tries to infer a soft stop from the broker SL so the soft-stop /
        breakeven / trailing / R-math come back online; if the inference
        fails (no broker SL, degenerate distance), the ticket stays in the
        legacy ``soft_sl=unknown`` mode and the agent only manages the
        catastrophe SL the broker is already holding.
        """
        is_long = pos.direction == Direction.LONG
        soft = self._infer_soft_stop_from_broker(
            pos.open_price, pos.stop_loss, is_long=is_long,
        )
        if soft is None:
            log_position_adopted(
                log, symbol=pos.symbol, ticket=pos.ticket,
                direction=pos.direction.value, lots=pos.volume,
                entry=pos.open_price, broker_sl=pos.stop_loss,
                tp=pos.take_profit, profit=pos.profit, soft_sl=None,
            )
            log_ladder_unknown(log, symbol=pos.symbol, ticket=pos.ticket,
                               reason="adopted")
            return

        breached = self._price_beyond_soft(
            is_long=is_long, soft_stop=soft, current_price=pos.current_price,
        )
        timeframe = (self.live_config.timeframes[0]
                     if self.live_config.timeframes else "H4")
        ctx = {
            "alpha": "adopted",
            "timeframe": timeframe,
            "direction": pos.direction.value,
            "entry": pos.open_price,
            "entry_time": (pos.open_time.isoformat()
                           if pos.open_time is not None else None),
            "soft_stop": soft,
            "stop": pos.stop_loss,
            "take_profit": pos.take_profit,
            "conviction": None,
            "signal_reason": "adopted",
            "target_ladder": [],
            "inferred": True,
            "pending_overshoot_close": breached,
        }
        self.register_entry(pos.ticket, ctx)
        # register_entry zeroes the excursion — refill from the live snapshot
        # so a subsequent close emits the real exit price / floating profit,
        # not the entry price / $0 (see `soft_sl_inferred_overshoot` bugfix).
        self._track_excursion(pos)
        log_position_adopted(
            log, symbol=pos.symbol, ticket=pos.ticket,
            direction=pos.direction.value, lots=pos.volume,
            entry=pos.open_price, broker_sl=pos.stop_loss,
            tp=pos.take_profit, profit=pos.profit, soft_sl=soft,
        )
        log_ladder_unknown(log, symbol=pos.symbol, ticket=pos.ticket,
                           reason="adopted")
        log_soft_stop_armed(log, symbol=pos.symbol, ticket=pos.ticket,
                            soft_sl=soft, source="inferred")
        if breached:
            log_adopted_breach(
                log, symbol=pos.symbol, ticket=pos.ticket,
                current_price=pos.current_price, soft_sl=soft,
            )
        if self._on_state_change is not None:
            try:
                self._on_state_change()
            except Exception as exc:
                log.debug("on_state_change failed after adoption: %s", exc)

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

            # First cycle after start: log restored / adopted positions and
            # discard any stale tickets from the state sidecar that are no
            # longer open at the broker.
            if not self._initial_scan_done:
                current_tickets = {p.ticket for p in positions}
                stale = self._restored_ctx_tickets - current_tickets
                for ticket in stale:
                    self._entry_ctx.pop(ticket, None)
                    self._excursion.pop(ticket, None)
                    self._breakeven_applied.discard(ticket)
                    self._partial_applied.discard(ticket)
                    log.info(
                        "[STATE LOADED] discarding stale restored ticket=%d "
                        "(no longer open at broker)", ticket,
                    )
                for pos in positions:
                    if pos.ticket in self._restored_ctx_tickets:
                        ctx = self._entry_ctx.get(pos.ticket, {})
                        entry_price = ctx.get("entry", pos.open_price)
                        log_position_restored(
                            log, symbol=pos.symbol, ticket=pos.ticket,
                            direction=pos.direction.value,
                            entry=entry_price,
                            soft_sl=ctx.get("soft_stop"),
                            broker_sl=ctx.get("stop", pos.stop_loss),
                            tp=ctx.get("take_profit", pos.take_profit),
                            be_applied=pos.ticket in self._breakeven_applied,
                        )
                        log_ladder(
                            log, symbol=pos.symbol, ticket=pos.ticket,
                            rungs=ctx.get("target_ladder") or [],
                            entry=entry_price,
                        )
                    elif pos.ticket not in self._entry_ctx:
                        self._adopt_position(pos)
                self._restored_ctx_tickets.clear()
                self._initial_scan_done = True

            # Detect closed positions (were open, now gone)
            current_tickets = {p.ticket for p in positions}
            closed_tickets = self._known_tickets - current_tickets
            if closed_tickets:
                for ticket in closed_tickets:
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
        or blown clean through intrabar (panic). Returns True if it closed.

        Adopted-position overshoot: if a ticket was adopted with an inferred
        soft stop AND price was already past that level at adoption time, the
        ctx carries ``pending_overshoot_close=True`` and we exit immediately
        with reason ``soft_sl_inferred_overshoot`` — the user can grep that
        cause tag later to find these one-shot exits.
        """
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

        # One-shot overshoot exit for an adopted ticket whose inferred soft
        # level was already broken at restart. We bypass confirm-on-close
        # because there's nothing to confirm — the breach predates us.
        if ctx.get("pending_overshoot_close") and ctx.get("inferred"):
            still_beyond = self._price_beyond_soft(
                is_long=is_long, soft_stop=soft_stop,
                current_price=pos.current_price,
            )
            if still_beyond:
                detail = (f"adopted ticket: price {pos.current_price:.5f} "
                          f"already past inferred soft {soft_stop:.5f} "
                          f"at restart — exiting")
                log_soft_stop_fired(log, symbol=pos.symbol, ticket=pos.ticket,
                                    detail=detail)
                result = await self.broker.close_position(pos.ticket, pos.symbol)
                if result.success:
                    self._record_close_result(pos, ctx, result)
                    self._forced_exit_reason[pos.ticket] = "soft_sl_inferred_overshoot"
                    ctx["pending_overshoot_close"] = False
                    self.notifier.notify_text(
                        f"*Adopted soft-stop exit* ticket=`{pos.ticket}`\n"
                        f"`{detail}`"
                    )
                    return True
                log.error("Adopted overshoot close FAILED for ticket=%d: %s",
                          pos.ticket, result.message)
                return False
            # Price snapped back inside the soft level before we could
            # close — clear the flag, fall through to the normal layer.
            ctx["pending_overshoot_close"] = False

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

        log_soft_stop_fired(log, symbol=pos.symbol, ticket=pos.ticket,
                            detail=decision.detail)
        result = await self.broker.close_position(pos.ticket, pos.symbol)
        if result.success:
            self._record_close_result(pos, ctx, result)
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
        close_result = self._close_results.pop(ticket, None)
        if self.trade_closed_cb is None:
            return
        exc = exc or {}
        ctx = ctx or {}
        close_result = close_result or {}
        entry_price = ctx.get("entry", exc.get("open_price", 0.0))
        direction = ctx.get("direction", exc.get("direction", "long"))
        # Risk is defined by the SOFT stop (the agent's real exit), not the wide
        # broker catastrophe stop, so R-multiples reflect the intended risk.
        stop = ctx.get("soft_stop", ctx.get("stop"))
        broker_stop = ctx.get("stop")
        tp = ctx.get("take_profit")
        # Prefer the broker's actual fill captured at the close site — that's
        # the authoritative exit. Fall back to the last tracked tick price
        # (close to fill within one cycle) and, only as a final resort, the
        # entry price. The last branch is suspicious: it means we missed BOTH
        # the close-result capture AND the excursion update.
        if close_result:
            exit_price = close_result["exit_price"]
            pnl_pips = close_result["pnl_pips"]
        else:
            exit_price = exc.get("last_price", entry_price)
            if direction == "long":
                pnl_pips = (exit_price - entry_price) * 10000
            else:
                pnl_pips = (entry_price - exit_price) * 10000
        stop_pips = abs(entry_price - stop) * 10000 if stop else 0.0
        r_multiple = (pnl_pips / stop_pips) if stop_pips > 0 else 0.0
        # Prefer the broker's reported floating profit at the most recent
        # tick (it's in account currency and handles non-USD quotes), but
        # never let a stale $0 mask a real loss — fall back to our pip-math
        # estimate from the actual fill_price in that case.
        pnl = exc.get("last_profit", 0.0)
        if (not pnl) and close_result:
            pnl = close_result.get("pnl_estimate", 0.0)

        # Prefer the true reason if WE closed it (soft stop / breakeven); else
        # infer from proximity to TP/SL.
        if forced_reason:
            reason = forced_reason
        else:
            tol_pips = 3.0
            reason = "manual"
            if tp is not None and abs(exit_price - tp) * 10000 <= tol_pips:
                reason = "tp"
            elif (broker_stop is not None
                  and abs(exit_price - broker_stop) * 10000 <= tol_pips):
                reason = "catastrophe_sl"
            elif (stop is not None and abs(exit_price - stop) * 10000 <= tol_pips):
                reason = "sl"
            elif pnl_pips > 0:
                reason = "tp"
            elif pnl_pips < 0:
                reason = "sl"

        exit_tag = classify_exit_tag(reason, pnl)
        alpha = ctx.get("alpha", "?")
        symbol = self.live_config.symbol
        log_trade_closed(
            log, symbol=symbol, ticket=ticket, alpha=alpha,
            direction=str(direction), exit_tag=exit_tag,
            exit_reason=reason, pnl=pnl, pnl_pips=pnl_pips,
            r_multiple=r_multiple, exit_price=exit_price,
        )

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
        log_partial_scaleout(log, symbol=pos.symbol, ticket=pos.ticket,
                             closed_lots=close_vol, total_lots=pos.volume,
                             r_multiple=r_multiple)
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

        if self._on_state_change is not None:
            self._on_state_change()
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
                    log_breakeven_moved(log, symbol=pos.symbol, ticket=pos.ticket,
                                        old_sl=pos.stop_loss, new_sl=new_stop,
                                        r_multiple=r_multiple)
                    self.notifier.notify_text(
                        f"*BE Move* ticket=`{pos.ticket}`\n"
                        f"SL: `{pos.stop_loss:.5f}` → `{new_stop:.5f}` ({r_multiple:.1f}R)"
                    )
                    if self._on_state_change is not None:
                        self._on_state_change()

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

    # ------------------------------------------------------------------
    # Crash-resilient persistence
    # ------------------------------------------------------------------

    def get_persist_state(self) -> dict:
        """Return a JSON-serialisable snapshot of all monitor mutable state."""
        return {
            "entry_ctx": {
                str(ticket): ctx
                for ticket, ctx in self._entry_ctx.items()
            },
            "breakeven_applied": list(self._breakeven_applied),
            "partial_applied": list(self._partial_applied),
            "excursion": {
                str(ticket): exc
                for ticket, exc in self._excursion.items()
            },
        }

    def restore_from_persist_state(self, data: dict) -> None:
        """Populate in-memory dicts from a previously persisted snapshot.

        Ticket context is not verified against open broker positions here —
        that happens on the first ``_check_positions`` cycle, which calls
        ``_initial_scan_done`` logic to prune tickets no longer at the broker
        and log ``[POSITION RESTORED]`` for those that remain.
        """
        for ticket_str, ctx in data.get("entry_ctx", {}).items():
            try:
                ticket = int(ticket_str)
            except (ValueError, TypeError):
                continue
            self._entry_ctx[ticket] = ctx
            self._restored_ctx_tickets.add(ticket)
        for ticket_val in data.get("breakeven_applied", []):
            try:
                self._breakeven_applied.add(int(ticket_val))
            except (ValueError, TypeError):
                pass
        for ticket_val in data.get("partial_applied", []):
            try:
                self._partial_applied.add(int(ticket_val))
            except (ValueError, TypeError):
                pass
        for ticket_str, exc in data.get("excursion", {}).items():
            try:
                ticket = int(ticket_str)
            except (ValueError, TypeError):
                continue
            self._excursion[ticket] = exc
        log.info(
            "[STATE LOADED] position_monitor restored: %d ticket(s) — %s",
            len(self._restored_ctx_tickets),
            ", ".join(str(t) for t in sorted(self._restored_ctx_tickets)) or "none",
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
