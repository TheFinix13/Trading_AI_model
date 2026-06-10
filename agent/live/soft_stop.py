"""Synthetic ("soft") stop-loss layer — the stop-hunt mitigation.

Why this exists
---------------
The Jun 2026 post-mortem surfaced a real, recurring fear: *institutions hunt
stop losses*. The observation is half-true. Liquidity genuinely pools just
beyond obvious swing highs/lows and round numbers, and price often wicks into
that pool to fill size before reversing. A resting broker stop sitting *inside*
that pool can be swept on a wick and then watch price go to target without it.

The wrong fix (what blew the account) was to trade with **no stop at all**. The
professional fix is a two-layer stop:

* **Soft stop (primary, agent-managed).** The real risk level is held in the
  agent's memory — like a TradingView alert — not as a resting order in the
  liquidity pool. The agent watches price and only exits when the level is
  *confirmed* (a bar **closes** beyond it), so a single hunting wick does not
  take the trade out. This is the "mental stop, automated" the user asked for.

* **Catastrophe stop (backstop, on the broker).** A real broker stop placed
  much further out (``catastrophe_mult`` × the soft distance). It exists only so
  that if the agent/VM/connection dies, the account can never be margin-called.
  It is insurance, not the trade's real risk — position size is computed from
  the *soft* distance, so the soft stop defines the actual money at risk.

A small **panic** rule closes intrabar if price blows clean through the soft
level by ``panic_mult`` × the soft distance, so we never sit and wait a full
hour for a bar to close while a genuine breakdown runs toward the catastrophe.

This module is pure and unit-tested; the :class:`PositionMonitor` consults it
every cycle with the latest *closed* bar.
"""
from __future__ import annotations

from dataclasses import dataclass

PIP = 0.0001


@dataclass
class SoftStopConfig:
    """Tunables for the synthetic stop layer."""

    enabled: bool = True
    # Only exit when a bar CLOSES beyond the soft level (survives hunting wicks).
    # When False the soft stop behaves like a normal stop but is executed by the
    # agent as a market order rather than resting in the pool.
    confirm_on_close: bool = True
    # Broker catastrophe stop distance = catastrophe_mult × soft distance.
    catastrophe_mult: float = 2.5
    # Intrabar emergency: if price runs past the soft level by panic_mult × the
    # soft distance, close immediately without waiting for the bar to close.
    panic_mult: float = 1.0
    # Never place the broker backstop tighter than this many pips from entry.
    min_catastrophe_pips: float = 8.0


@dataclass
class SoftStopDecision:
    """Outcome of evaluating the soft stop against the latest price action."""

    should_close: bool
    reason: str = ""   # "" | "soft_sl_close" | "soft_sl_panic"
    detail: str = ""


def catastrophe_stop(
    direction_is_long: bool, entry: float, soft_stop: float, cfg: SoftStopConfig
) -> float:
    """Return the wide broker backstop price for a given soft stop.

    Placed ``catastrophe_mult`` × the soft distance beyond entry (and never
    closer than ``min_catastrophe_pips``), so a resting order never sits in the
    liquidity pool the soft stop is protecting against.
    """
    dist = abs(entry - soft_stop)
    cata_dist = max(dist * cfg.catastrophe_mult, cfg.min_catastrophe_pips * PIP)
    return entry - cata_dist if direction_is_long else entry + cata_dist


def evaluate_soft_stop(
    *,
    direction_is_long: bool,
    entry: float,
    soft_stop: float,
    last_closed_price: float | None,
    current_price: float | None,
    cfg: SoftStopConfig,
) -> SoftStopDecision:
    """Decide whether an agent-managed exit should fire this cycle.

    Two ways to trigger:
      1. **Confirmed close** beyond the soft level (the wick-proof exit).
      2. **Panic** — price has run past the soft level by ``panic_mult`` × the
         soft distance intrabar, so we don't wait for the close.

    When ``confirm_on_close`` is False, any intrabar touch of the soft level
    triggers (agent-executed market stop, still not a resting order).
    """
    if not cfg.enabled or soft_stop is None or entry is None:
        return SoftStopDecision(False)

    dist = abs(entry - soft_stop)
    if dist <= 0:
        return SoftStopDecision(False)

    # Panic level sits beyond the soft stop, between it and the catastrophe stop.
    if direction_is_long:
        panic_level = soft_stop - cfg.panic_mult * dist
    else:
        panic_level = soft_stop + cfg.panic_mult * dist

    # 1) Intrabar panic — price has clearly broken down/through the level.
    if current_price is not None:
        breached_panic = (
            current_price <= panic_level if direction_is_long
            else current_price >= panic_level
        )
        if breached_panic:
            return SoftStopDecision(
                True, "soft_sl_panic",
                f"price {current_price:.5f} blew through soft stop {soft_stop:.5f} "
                f"by >{cfg.panic_mult:.1f}× — exiting now (not waiting for close)",
            )

    # 2) Confirmed close beyond the soft level (wick-proof).
    if cfg.confirm_on_close:
        if last_closed_price is None:
            return SoftStopDecision(False)
        breached_close = (
            last_closed_price < soft_stop if direction_is_long
            else last_closed_price > soft_stop
        )
        if breached_close:
            return SoftStopDecision(
                True, "soft_sl_close",
                f"bar closed at {last_closed_price:.5f} beyond soft stop "
                f"{soft_stop:.5f} — level confirmed broken (survived wicks)",
            )
        return SoftStopDecision(False)

    # confirm_on_close == False: agent-executed touch stop.
    if current_price is not None:
        touched = (
            current_price <= soft_stop if direction_is_long
            else current_price >= soft_stop
        )
        if touched:
            return SoftStopDecision(
                True, "soft_sl_close",
                f"price {current_price:.5f} touched soft stop {soft_stop:.5f}",
            )
    return SoftStopDecision(False)
