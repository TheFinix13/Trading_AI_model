"""Cheap, per-bar regime classifier.

The router (see `agent.strategy.registry.StrategyRouter`) consults this
detector to pick which strategy is allowed to fire on the current bar.
The classifier is deliberately stateless and feature-light:

* 50-bar slope (linregress on closes) -- in pips per 50 bars
* ATR ratio                            -- ATR(14) / ATR(50) on the current bar
* Body-pct-of-range                    -- mean over last 20 bars (chop signal)
* NY-local hour                        -- maps to session

Output is a `RegimeLabel` with three orthogonal axes. See the design doc
section 3 for thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from agent.types import Bar

PrimaryRegime = Literal["trending_up", "trending_down", "chop", "low_vol", "high_vol", "unknown"]
Session = Literal["asia", "london", "ny", "overlap", "off"]


# ---------------------------------------------------------------------------
# Thresholds (pips per 50 bars, ATR ratio). Documented in section 3.1 of
# docs/regime_router_design.md. Re-tune after gathering per-strategy stats.
# ---------------------------------------------------------------------------
SLOPE_TREND_PIPS = 3.0
ATR_HIGH_VOL_RATIO = 1.4
ATR_LOW_VOL_RATIO = 0.7
SLOPE_LOOKBACK = 50
ATR_SHORT = 14
ATR_LONG = 50
BODY_LOOKBACK = 20


@dataclass(frozen=True)
class RegimeLabel:
    """Three orthogonal regime axes for the current bar.

    Attributes:
        primary:    Volatility / trend cluster.
        session:    NY-local session bucket.
        kill_zone:  True iff session in {london, ny, overlap}.
        slope_pips: 50-bar slope in pips (signed). Surfaced for logging.
        atr_ratio:  ATR(14)/ATR(50). Surfaced for logging.
        body_pct:   Mean body / range over the body lookback. 0..1.
    """
    primary: PrimaryRegime
    session: Session
    kill_zone: bool
    slope_pips: float
    atr_ratio: float
    body_pct: float

    def __str__(self) -> str:
        kz = "kill" if self.kill_zone else "off"
        return (
            f"{self.primary}/{self.session}/{kz}"
            f" slope={self.slope_pips:+.1f}p atr={self.atr_ratio:.2f} body={self.body_pct:.2f}"
        )


# ---------------------------------------------------------------------------
# Cheap feature primitives. Kept as pure functions so tests can call
# them with synthetic series.
# ---------------------------------------------------------------------------


def _slope_pips(closes: list[float], lookback: int) -> float:
    """Linear-regression slope over the last `lookback` bars, expressed
    in *pips per 50 bars* (so the threshold is in human units regardless
    of `lookback`)."""
    n = min(len(closes), lookback)
    if n < 5:
        return 0.0
    series = closes[-n:]
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(series) / n
    num = sum((xs[i] - mean_x) * (series[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den <= 0:
        return 0.0
    slope_per_bar = num / den
    # slope_per_bar is independent of window length; multiply by 50 to
    # express the result in pips-per-50-bars (the human-friendly unit
    # the threshold table uses).
    return slope_per_bar * 10000.0 * 50.0


def _atr(bars: list[Bar], period: int, end_index: int) -> float:
    """Simple-MA ATR ending at `end_index` (inclusive). Returns 0.0 when
    there isn't enough history."""
    if end_index < 1 or period < 1:
        return 0.0
    start = max(1, end_index - period + 1)
    trs: list[float] = []
    for j in range(start, end_index + 1):
        h = bars[j].high
        l = bars[j].low
        pc = bars[j - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    return sum(trs) / len(trs)


def _body_pct_avg(bars: list[Bar], end_index: int, lookback: int) -> float:
    start = max(0, end_index - lookback + 1)
    window = bars[start: end_index + 1]
    ratios: list[float] = []
    for b in window:
        rng = b.range
        if rng <= 0:
            continue
        ratios.append(b.body / rng)
    if not ratios:
        return 0.0
    return sum(ratios) / len(ratios)


def _ny_session(t: datetime) -> Session:
    """Bucket UTC `t` into one of {asia, london, ny, overlap, off}.

    Off = weekend (Sat/Sun outside FX hours). London open is ~07:00 UTC
    in summer, NY open ~13:00 UTC. We use coarse UTC hour boundaries
    that are accurate enough for routing (the engine still has its own
    NY-local hour gate)."""
    weekday = t.weekday()
    if weekday >= 5:  # Sat / Sun
        return "off"
    h = t.hour
    if 0 <= h < 6:
        return "asia"
    if 6 <= h < 12:
        return "london"
    if 12 <= h < 16:
        return "overlap"
    if 16 <= h < 21:
        return "ny"
    return "asia"  # 21..23 wraps back to next-day Asia


def _classify_primary(slope_pips: float, atr_ratio: float) -> PrimaryRegime:
    if abs(slope_pips) > SLOPE_TREND_PIPS:
        return "trending_up" if slope_pips > 0 else "trending_down"
    # Volatility split for ranges.
    if atr_ratio > ATR_HIGH_VOL_RATIO:
        return "high_vol"
    if atr_ratio < ATR_LOW_VOL_RATIO:
        return "low_vol"
    return "chop"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class RegimeDetector:
    """Stateless classifier. Construct once; call `label(bars, i)` per bar.

    `label()` is O(period) per call (no global precompute), so it's safe
    to invoke on every bar of a multi-year backtest."""

    def __init__(
        self,
        *,
        slope_lookback: int = SLOPE_LOOKBACK,
        atr_short: int = ATR_SHORT,
        atr_long: int = ATR_LONG,
        body_lookback: int = BODY_LOOKBACK,
        slope_trend_pips: float = SLOPE_TREND_PIPS,
        atr_high_ratio: float = ATR_HIGH_VOL_RATIO,
        atr_low_ratio: float = ATR_LOW_VOL_RATIO,
    ):
        self.slope_lookback = slope_lookback
        self.atr_short = atr_short
        self.atr_long = atr_long
        self.body_lookback = body_lookback
        self.slope_trend_pips = slope_trend_pips
        self.atr_high_ratio = atr_high_ratio
        self.atr_low_ratio = atr_low_ratio

    def label(self, bars: list[Bar], at_index: int) -> RegimeLabel:
        if not bars or at_index < 0:
            return RegimeLabel("unknown", "off", False, 0.0, 1.0, 0.0)
        at_index = min(at_index, len(bars) - 1)

        closes = [b.close for b in bars[: at_index + 1]]
        slope = _slope_pips(closes, self.slope_lookback)

        atr_short = _atr(bars, self.atr_short, at_index)
        atr_long = _atr(bars, self.atr_long, at_index)
        atr_ratio = (atr_short / atr_long) if atr_long > 0 else 1.0

        body_pct = _body_pct_avg(bars, at_index, self.body_lookback)

        # Apply override-aware thresholds.
        primary = self._classify_primary_with_overrides(slope, atr_ratio)
        session = _ny_session(bars[at_index].time)
        kill = session in ("london", "ny", "overlap")

        return RegimeLabel(
            primary=primary,
            session=session,
            kill_zone=kill,
            slope_pips=slope,
            atr_ratio=atr_ratio,
            body_pct=body_pct,
        )

    def _classify_primary_with_overrides(self, slope_pips: float, atr_ratio: float) -> PrimaryRegime:
        if abs(slope_pips) > self.slope_trend_pips:
            return "trending_up" if slope_pips > 0 else "trending_down"
        if atr_ratio > self.atr_high_ratio:
            return "high_vol"
        if atr_ratio < self.atr_low_ratio:
            return "low_vol"
        return "chop"


__all__ = ["RegimeDetector", "RegimeLabel", "PrimaryRegime", "Session"]
