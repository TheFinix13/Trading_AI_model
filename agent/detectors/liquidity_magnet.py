"""External / Internal Range Liquidity ("ERL / IRL") and liquidity magnets.

This encodes the ICT framing the user shared (the "internal-to-external range
liquidity" reel) into measurable structure the reaction engine can act on:

* **External Range Liquidity (ERL).** The extremes of the current dealing range.
  Above the range high sits major **buy-side** liquidity; below the range low
  sits major **sell-side** liquidity. ERL is where price *wants to go* — the
  draw. We mark the highest high / lowest low over a lookback window as the two
  external pools.

* **Internal Range Liquidity (IRL).** Everything *inside* the range:
    - **Inefficiencies** — unfilled fair-value gaps. These are *not* liquidity;
      they are imbalances price returns to in order to rebalance / offer fair
      value. They explain *why price comes back* before continuing to the draw.
    - **Minor liquidity** — the stop pools resting just beyond internal swing
      highs / lows (minor buy-side above internal highs, minor sell-side below
      internal lows).

* **Liquidity magnet.** When an inefficiency (FVG) and a minor liquidity pool
  sit in close proximity, the area is a strong magnet: the algorithm can *raid*
  the stops and *rebalance* the gap in one move ("kill two birds"). These zones
  are high-probability reaction / target areas.

The detector is pure and causal (only uses bars up to ``at_index``) so it is
safe in both the live loop and the backtest. The reaction engine consumes:
  * the ERL extremes as :class:`~agent.reaction.engine.LevelOfInterest` draws,
    so an impulsive move *toward* an external pool registers as acting on a
    level and targets it; and
  * the magnets as additional internal levels + a confluence read.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.types import Bar, Direction, FVG, Swing

PIP = 0.0001


@dataclass
class RangeLiquidity:
    """The dealing-range extremes (ERL) and the minor pools inside it (IRL)."""

    erl_high: float                       # external buy-side liquidity (draw up)
    erl_low: float                        # external sell-side liquidity (draw down)
    irl_highs: list[float] = field(default_factory=list)  # internal minor BSL
    irl_lows: list[float] = field(default_factory=list)   # internal minor SSL

    @property
    def mid(self) -> float:
        return (self.erl_high + self.erl_low) / 2

    @property
    def height(self) -> float:
        return self.erl_high - self.erl_low

    def premium(self, price: float) -> bool:
        """True if price is in the upper half (premium) of the dealing range."""
        return price >= self.mid

    def draw(self, price: float) -> Direction:
        """The nearer-term external draw: from a premium price the path of least
        resistance is the discount (down) and vice-versa — but we report the
        *external pool price is heading toward*, i.e. the opposite extreme."""
        return Direction.SHORT if self.premium(price) else Direction.LONG


@dataclass
class LiquidityMagnet:
    """An FVG (inefficiency) sitting next to a minor liquidity pool (stops).

    ``side`` is the liquidity side being raided: ``buyside`` magnets sit above
    (price draws up into them), ``sellside`` below.
    """

    price: float          # blended centre of the magnet zone
    fvg_mid: float
    liquidity_price: float
    side: str             # "buyside" | "sellside"
    distance_pips: float  # |fvg_mid - liquidity_price|
    fvg_quality: float = 0.0


def compute_range_liquidity(
    bars: list[Bar],
    at_index: int,
    *,
    lookback_bars: int = 120,
    swings: list[Swing] | None = None,
    max_internal: int = 4,
) -> RangeLiquidity | None:
    """Mark the dealing range extremes and the minor liquidity inside it.

    ``lookback_bars`` defines the dealing range we measure ERL over. Internal
    minor pools come from swing highs/lows strictly *inside* the extremes; we
    keep the ``max_internal`` nearest to each extreme to avoid clutter.
    """
    if at_index < 0 or at_index >= len(bars):
        return None
    start = max(0, at_index - lookback_bars)
    window = bars[start : at_index + 1]
    if len(window) < 5:
        return None

    erl_high = max(b.high for b in window)
    erl_low = min(b.low for b in window)
    if erl_high - erl_low < PIP:
        return None

    irl_highs: list[float] = []
    irl_lows: list[float] = []
    if swings:
        for s in swings:
            if s.bar_index < start or s.bar_index > at_index:
                continue
            if s.is_high and s.price < erl_high - PIP:
                irl_highs.append(s.price)
            elif (not s.is_high) and s.price > erl_low + PIP:
                irl_lows.append(s.price)

    # De-dup near-equal pools (equal highs/lows are the same liquidity) and keep
    # the most prominent ones nearest the extremes.
    irl_highs = _dedup(sorted(set(irl_highs), reverse=True))[:max_internal]
    irl_lows = _dedup(sorted(set(irl_lows)))[:max_internal]

    return RangeLiquidity(
        erl_high=erl_high, erl_low=erl_low,
        irl_highs=irl_highs, irl_lows=irl_lows,
    )


def find_liquidity_magnets(
    fvgs: list[FVG],
    range_liq: RangeLiquidity,
    *,
    at_index: int,
    atr: float,
    proximity_atr_mult: float = 0.6,
) -> list[LiquidityMagnet]:
    """Pair each unfilled internal FVG with a nearby minor liquidity pool.

    A magnet exists when an inefficiency and a stop pool sit within
    ``proximity_atr_mult`` × ATR of each other — the raid-and-rebalance zone.
    """
    if atr <= 0 or not fvgs:
        return []
    prox = proximity_atr_mult * atr
    magnets: list[LiquidityMagnet] = []
    for f in fvgs:
        if f.created_bar_index > at_index or f.is_fully_filled:
            continue
        fmid = (f.top + f.bottom) / 2.0
        # Buy-side magnet: minor BSL above, near the gap.
        for hp in range_liq.irl_highs:
            if abs(hp - fmid) <= prox:
                magnets.append(LiquidityMagnet(
                    price=(fmid + hp) / 2.0, fvg_mid=fmid, liquidity_price=hp,
                    side="buyside", distance_pips=abs(hp - fmid) / PIP,
                    fvg_quality=f.quality_score,
                ))
        # Sell-side magnet: minor SSL below, near the gap.
        for lp in range_liq.irl_lows:
            if abs(lp - fmid) <= prox:
                magnets.append(LiquidityMagnet(
                    price=(fmid + lp) / 2.0, fvg_mid=fmid, liquidity_price=lp,
                    side="sellside", distance_pips=abs(lp - fmid) / PIP,
                    fvg_quality=f.quality_score,
                ))
    return magnets


def range_liquidity_levels(
    range_liq: RangeLiquidity,
) -> list[tuple[float, str, str]]:
    """Flatten ERL/IRL into ``(price, label, kind)`` triples for the reaction
    engine's level set. ERL uses kind ``erl`` (a major draw); IRL minor pools
    use kind ``irl``."""
    out: list[tuple[float, str, str]] = [
        (range_liq.erl_high, "ERL_high (buy-side draw)", "erl"),
        (range_liq.erl_low, "ERL_low (sell-side draw)", "erl"),
    ]
    for p in range_liq.irl_highs:
        out.append((p, "IRL_high (minor buy-side)", "irl"))
    for p in range_liq.irl_lows:
        out.append((p, "IRL_low (minor sell-side)", "irl"))
    return out


def _dedup(prices: list[float], tol_pips: float = 4.0) -> list[float]:
    """Collapse near-equal price levels (within ``tol_pips``) into one — equal
    highs/lows are the same liquidity pool."""
    out: list[float] = []
    tol = tol_pips * PIP
    for p in prices:
        if not any(abs(p - q) <= tol for q in out):
            out.append(p)
    return out
