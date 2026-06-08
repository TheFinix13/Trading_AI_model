"""Adaptive, risk-based position sizing for the live loop.

The legacy ``--lot`` flag hard-codes one lot size for every trade regardless of
stop distance — a 10-pip stop and a 60-pip stop risked wildly different amounts.
The :class:`PositionSizer` instead computes the lot size that risks *exactly* a
chosen percentage of the live balance given the trade's actual stop distance,
then:

  * respects broker constraints (min lot, lot step, max lot),
  * never exceeds available free margin under the account leverage, and
  * scales the risk percentage within a band based on signal conviction so
    high-conviction setups get more size and marginal ones get less.

It pulls the live balance from the broker each time it is called.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

PIP = 0.0001

log = logging.getLogger(__name__)


@dataclass
class SymbolConstraints:
    """Broker lot constraints + contract metadata for one symbol."""

    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 100.0
    contract_size: float = 100_000.0  # 1.0 lot = 100k units for EURUSD
    pip_value_per_lot: float = 10.0  # $ per pip per 1.0 lot (USD quote)


@dataclass
class SizingResult:
    """Full sizing math, surfaced to the explainer/logs for transparency."""

    lot: float
    risk_pct: float            # the conviction-scaled risk fraction applied
    risk_amount: float         # $ risked at the computed lot
    stop_distance_pips: float
    balance: float
    conviction: float
    margin_required: float
    free_margin: float
    capped_by: str = ""        # which constraint bound the size, if any
    notes: list[str] = field(default_factory=list)

    @property
    def actual_risk_pct(self) -> float:
        if self.balance <= 0:
            return 0.0
        return self.risk_amount / self.balance

    def summary(self) -> str:
        return (
            f"balance=${self.balance:,.2f} | conviction={self.conviction:.2f} "
            f"-> risk={self.risk_pct * 100:.2f}% (${self.risk_amount:.2f}) | "
            f"stop={self.stop_distance_pips:.0f}p | lot={self.lot:.2f} | "
            f"margin=${self.margin_required:.2f}/${self.free_margin:.2f} free"
            + (f" | capped:{self.capped_by}" if self.capped_by else "")
        )


class PositionSizer:
    """Conviction-scaled, risk-based lot sizing with broker-constraint safety."""

    def __init__(
        self,
        min_risk_pct: float = 0.005,
        max_risk_pct: float = 0.02,
        margin_buffer: float = 0.90,
    ):
        """``min_risk_pct`` / ``max_risk_pct`` bound the conviction band (e.g.
        0.5%–2.0%). ``margin_buffer`` is the fraction of free margin we are
        willing to commit (0.90 = never use more than 90% of free margin)."""
        self.min_risk_pct = min_risk_pct
        self.max_risk_pct = max_risk_pct
        self.margin_buffer = margin_buffer

    def risk_pct_for_conviction(self, conviction: float) -> float:
        """Linearly map conviction in [0, 1] into the risk band."""
        c = max(0.0, min(1.0, conviction))
        return self.min_risk_pct + (self.max_risk_pct - self.min_risk_pct) * c

    def calculate_lot(
        self,
        balance: float,
        stop_distance_pips: float,
        *,
        conviction: float = 0.5,
        risk_pct: float | None = None,
        pip_value: float = 10.0,
        price: float = 1.0,
        leverage: int = 500,
        free_margin: float | None = None,
        constraints: SymbolConstraints | None = None,
        manual_cap: float | None = None,
        max_risk_pct_hard: float | None = None,
    ) -> SizingResult:
        """Compute the lot size that risks ``risk_pct`` of ``balance``.

        Formula: ``lot = (balance * risk_pct) / (stop_distance_pips * pip_value)``.

        When ``risk_pct`` is None it is derived from ``conviction`` via the
        configured band. The result is rounded down to the broker lot step,
        clamped to [min_lot, max_lot], capped by available free margin under the
        given leverage, and optionally capped by a manual ``--lot`` override.

        ``max_risk_pct_hard`` is an independent oversize ceiling (decoupled from
        the conviction band): if the final lot would risk more than this
        fraction of balance, it is clamped down so the trade risks at most
        ``max_risk_pct_hard`` — but never below the broker minimum lot, so a
        small account can still trade its smallest size. This is the guard that
        turns a 1.0-lot-on-$100 mistake into a 0.01-lot trade.
        """
        c = constraints or SymbolConstraints()
        pv = pip_value or c.pip_value_per_lot
        notes: list[str] = []
        capped_by = ""

        if risk_pct is None:
            risk_pct = self.risk_pct_for_conviction(conviction)

        if balance <= 0 or stop_distance_pips <= 0 or pv <= 0:
            return SizingResult(
                lot=0.0, risk_pct=risk_pct, risk_amount=0.0,
                stop_distance_pips=stop_distance_pips, balance=balance,
                conviction=conviction, margin_required=0.0,
                free_margin=free_margin or 0.0, capped_by="invalid_inputs",
                notes=["non-positive balance/stop/pip_value"],
            )

        risk_amount = balance * risk_pct
        raw_lot = risk_amount / (stop_distance_pips * pv)

        # Round DOWN to the lot step so we never exceed the risk budget.
        lot = _floor_to_step(raw_lot, c.lot_step)

        # Below the broker minimum: snap to minimum only if the resulting risk
        # stays within ~1.5x the requested budget (protects a tiny account).
        if lot < c.min_lot:
            risk_at_min = (c.min_lot * stop_distance_pips * pv) / balance
            if risk_at_min <= risk_pct * 1.5 or risk_at_min <= self.max_risk_pct:
                lot = c.min_lot
                capped_by = "min_lot"
                notes.append(
                    f"raw lot {raw_lot:.4f} < min {c.min_lot}; snapped to min "
                    f"(risk {risk_at_min * 100:.2f}%)"
                )
            else:
                notes.append(
                    f"raw lot {raw_lot:.4f} < min {c.min_lot} and min-lot risk "
                    f"{risk_at_min * 100:.2f}% exceeds budget; skip"
                )
                return SizingResult(
                    lot=0.0, risk_pct=risk_pct, risk_amount=0.0,
                    stop_distance_pips=stop_distance_pips, balance=balance,
                    conviction=conviction, margin_required=0.0,
                    free_margin=free_margin if free_margin is not None else balance,
                    capped_by="risk_too_high", notes=notes,
                )

        # Manual cap (legacy --lot override acts as an upper bound).
        if manual_cap is not None and lot > manual_cap:
            lot = _floor_to_step(manual_cap, c.lot_step)
            capped_by = "manual_cap"
            notes.append(f"capped to manual --lot {manual_cap}")

        # Broker max lot.
        if lot > c.max_lot:
            lot = c.max_lot
            capped_by = "max_lot"

        # Free-margin / leverage cap.
        lev = max(1, leverage)
        avail = free_margin if free_margin is not None else balance
        margin_per_lot = (c.contract_size * price) / lev
        if margin_per_lot > 0:
            max_lot_by_margin = (avail * self.margin_buffer) / margin_per_lot
            max_lot_by_margin = _floor_to_step(max_lot_by_margin, c.lot_step)
            if lot > max_lot_by_margin:
                if max_lot_by_margin < c.min_lot:
                    notes.append(
                        f"free margin ${avail:.2f} can't cover even min lot "
                        f"(needs ${margin_per_lot * c.min_lot:.2f}); skip"
                    )
                    return SizingResult(
                        lot=0.0, risk_pct=risk_pct, risk_amount=0.0,
                        stop_distance_pips=stop_distance_pips, balance=balance,
                        conviction=conviction,
                        margin_required=margin_per_lot * c.min_lot,
                        free_margin=avail, capped_by="insufficient_margin",
                        notes=notes,
                    )
                lot = max_lot_by_margin
                capped_by = "free_margin"
                notes.append(f"capped to {lot:.2f} by free margin ${avail:.2f}")

        lot = round(lot, 2)
        final_risk_amount = lot * stop_distance_pips * pv
        margin_required = margin_per_lot * lot

        # Oversize hard ceiling — clamp DOWN any lot that would risk more than
        # ``max_risk_pct_hard`` of balance, but never below the broker minimum
        # (the minimum is already the smallest tradeable, safest size).
        if (max_risk_pct_hard is not None and max_risk_pct_hard > 0
                and balance > 0 and lot > c.min_lot):
            hard_amount = balance * max_risk_pct_hard
            if final_risk_amount > hard_amount * (1 + 1e-9):
                hard_lot = _floor_to_step(hard_amount / (stop_distance_pips * pv), c.lot_step)
                hard_lot = max(c.min_lot, hard_lot)
                if hard_lot < lot:
                    notes.append(
                        f"oversize: {lot:.2f} risks "
                        f"{final_risk_amount / balance * 100:.1f}% > hard cap "
                        f"{max_risk_pct_hard * 100:.1f}%; clamped to {hard_lot:.2f}"
                    )
                    lot = hard_lot
                    capped_by = "max_risk_hard"
                    final_risk_amount = lot * stop_distance_pips * pv
                    margin_required = margin_per_lot * lot

        return SizingResult(
            lot=lot,
            risk_pct=risk_pct,
            risk_amount=final_risk_amount,
            stop_distance_pips=stop_distance_pips,
            balance=balance,
            conviction=conviction,
            margin_required=margin_required,
            free_margin=avail,
            capped_by=capped_by,
            notes=notes,
        )


def _floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return round(value, 2)
    # Use a tiny epsilon so values that land essentially on a step boundary
    # (e.g. 0.019999999) don't get floored to the wrong step.
    return round((int((value + 1e-9) / step)) * step, 2)
