"""Extension-target ladder — observation-only structural TP opinions.

When a live trade fires, the agent's order keeps its validated mechanical TP
(``target_rr`` × stop). This module *additionally* computes a ladder of
structural levels BEYOND that TP — the places a discretionary trader would
mark as "if it keeps going, it pauses here":

* ``swing``       — prior opposite-side swing highs/lows (resting liquidity)
* ``zone_edge``   — the near edge of the next opposite-side supply/demand zone
* ``trendline``   — a fitted trendline projected N bars ahead
* ``fib_ext``     — 1.272 / 1.618 extensions of the most recent fib impulse leg
* ``daily_level`` — PDH/PDL/PWH/PWL/midpoint anchors

Each rung is expressed both in price and in R-multiples of the trade's SOFT
stop, so "swing 1.15700 (2.9R)" reads directly against the 1.5R mechanical TP.

Hard contract (same as the vaults): pure observation. Nothing here is allowed
to touch order placement — the ladder is journaled, drawn and scored against
realised MFE after the trade closes. The per-source reach rates it accumulates
are hypothesis-generating evidence for a future ``target_rr`` /
``target_via_structure`` study through the full validation pipeline; they are
never a reason to move a live TP by hand.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Sequence

from agent.types import Direction

log = logging.getLogger(__name__)

PIP = 0.0001

# Fib extensions of the impulse leg (1.0 = the leg's end itself).
FIB_EXTENSIONS = (1.272, 1.618)


@dataclass(frozen=True)
class TargetRung:
    """One structural level beyond the mechanical TP."""

    price: float
    source: str        # swing | zone_edge | trendline | fib_ext | daily_level
    r_multiple: float  # distance from entry in units of the soft-stop risk
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "source": self.source,
            "r_multiple": self.r_multiple,
            "detail": self.detail,
        }

    def label(self) -> str:
        return f"{self.source} {self.price:.5f} ({self.r_multiple:.1f}R)"


def compute_target_ladder(
    ctx: Any,
    at_index: int,
    *,
    direction: Direction,
    entry: float,
    stop: float,
    take_profit: float,
    lookback: int = 200,
    trendline_lookahead: int = 20,
    max_rungs: int = 6,
    dedupe_pips: float = 3.0,
) -> list[TargetRung]:
    """Assemble the extension ladder from a ``PrecomputedContext``.

    Returns rungs strictly BEYOND ``take_profit`` (above for longs, below for
    shorts), nearest first, deduped within ``dedupe_pips`` and capped at
    ``max_rungs``. ``stop`` must be the SOFT stop so R units match the rest of
    the system. Defensive throughout: any malformed detector output is skipped,
    never raised.
    """
    risk = abs(entry - stop)
    if risk <= 0 or entry <= 0 or take_profit <= 0:
        return []
    is_long = direction == Direction.LONG

    def beyond_tp(price: float) -> bool:
        return price > take_profit if is_long else price < take_profit

    candidates: list[tuple[float, str, str]] = []

    # -- swings: prior opposite-side swing points (resting liquidity) --------
    for s in getattr(ctx, "swings", None) or []:
        try:
            if s.bar_index >= at_index or s.bar_index < at_index - lookback:
                continue
            if is_long != bool(s.is_high):
                continue
            if beyond_tp(s.price):
                kind = "high" if s.is_high else "low"
                candidates.append(
                    (float(s.price), "swing", f"swing {kind} @ bar {s.bar_index}"))
        except (AttributeError, TypeError):
            continue

    # -- zone edges: near edge of the next opposite-side zone ----------------
    for z in getattr(ctx, "zones", None) or []:
        try:
            if z.created_bar_index >= at_index or getattr(z, "mitigated", False):
                continue
            # A long runs into SUPPLY (Direction.SHORT zones); its near edge
            # is the bottom. A short runs into demand; near edge is the top.
            if is_long and z.direction == Direction.SHORT:
                edge = float(z.bottom)
            elif (not is_long) and z.direction == Direction.LONG:
                edge = float(z.top)
            else:
                continue
            if beyond_tp(edge):
                candidates.append(
                    (edge, "zone_edge",
                     f"{'supply' if is_long else 'demand'} zone edge "
                     f"@ bar {z.created_bar_index}"))
        except (AttributeError, TypeError):
            continue

    # -- trendlines: projected N bars ahead -----------------------------------
    for t in getattr(ctx, "trendlines", None) or []:
        try:
            if not getattr(t, "valid", True):
                continue
            proj = float(t.price_at(at_index + trendline_lookahead))
            if beyond_tp(proj):
                candidates.append(
                    (proj, "trendline",
                     f"trendline proj +{trendline_lookahead} bars "
                     f"(slope {t.slope:+.7f})"))
        except (AttributeError, TypeError, ValueError):
            continue

    # -- fib extensions of the most recent impulse leg ------------------------
    fib_map = getattr(ctx, "fib_by_index", None) or {}
    fib_keys = [k for k in fib_map if isinstance(k, int) and k <= at_index]
    if fib_keys:
        fib = fib_map[max(fib_keys)]
        try:
            leg_start = float(fib.impulse_start)
            leg_end = float(fib.impulse_end)
            for ext in FIB_EXTENSIONS:
                price = leg_start + (leg_end - leg_start) * ext
                if beyond_tp(price):
                    candidates.append((price, "fib_ext", f"fib {ext} extension"))
        except (AttributeError, TypeError, ValueError):
            pass

    # -- daily/weekly anchor levels -------------------------------------------
    daily = getattr(ctx, "daily_levels", None) or []
    if 0 <= at_index < len(daily) and daily[at_index] is not None:
        try:
            for name, price in daily[at_index].levels_dict().items():
                if beyond_tp(float(price)):
                    candidates.append((float(price), "daily_level", name))
        except (AttributeError, TypeError):
            pass

    # -- sort nearest-first, dedupe, cap, convert to R -------------------------
    candidates.sort(key=lambda c: abs(c[0] - entry))
    rungs: list[TargetRung] = []
    for price, source, detail in candidates:
        if len(rungs) >= max_rungs:
            break
        if any(abs(price - r.price) < dedupe_pips * PIP for r in rungs):
            continue
        rungs.append(TargetRung(
            price=round(price, 5),
            source=source,
            r_multiple=round(abs(price - entry) / risk, 2),
            detail=detail,
        ))
    return rungs


def ladder_summary(rungs: Sequence[TargetRung]) -> str:
    """One-line, log/Telegram-friendly rendering of the ladder."""
    return " · ".join(r.label() for r in rungs)


def ladder_summary_from_dicts(rung_dicts: Sequence[dict]) -> str:
    """Same as :func:`ladder_summary` but for journaled rung dicts."""
    parts = []
    for r in rung_dicts:
        try:
            parts.append(f"{r['source']} {float(r['price']):.5f} "
                         f"({float(r['r_multiple']):.1f}R)")
        except (KeyError, TypeError, ValueError):
            continue
    return " · ".join(parts)


def score_rungs(
    rung_dicts: Sequence[dict],
    *,
    entry: float,
    mfe_pips: float,
) -> list[dict]:
    """Mark each journaled rung as reached/not given the trade's realised MFE.

    A rung counts as reached when the favourable excursion covered the full
    distance from entry to the rung. Returns new dicts with ``reached`` and
    ``distance_pips`` added; malformed rungs are passed through unmarked.
    """
    out: list[dict] = []
    for r in rung_dicts:
        scored = dict(r)
        try:
            distance_pips = abs(float(r["price"]) - float(entry)) / PIP
            scored["distance_pips"] = round(distance_pips, 1)
            scored["reached"] = bool(mfe_pips >= distance_pips)
        except (KeyError, TypeError, ValueError):
            pass
        out.append(scored)
    return out
