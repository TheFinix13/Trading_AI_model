"""LZI-specific feature extractor for the Liquidity Zone of Interest scorer.

Extracts 15 features tailored to LZI trade quality — zone formation strength,
retest quality, displacement confirmation, and market context.  These replace
the generic zone/fib/BOS features that can't discriminate LZI winners from losers.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.detectors.liquidity_zones import LiquidityZone
from agent.types import Bar, Direction

PIP = 0.0001

# Level importance: institutional daily/weekly > structural swing > retail clusters
_LEVEL_IMPORTANCE: dict[str, int] = {
    "PDH": 3, "PDL": 3, "PWH": 3, "PWL": 3,
    "swing_high": 2, "swing_low": 2,
    "equal_highs": 1, "equal_lows": 1,
}

# Kill-zone windows (UTC hours)
_LONDON_OPEN = range(7, 10)
_NY_OPEN = range(13, 16)


@dataclass
class LZIFeatures:
    """Feature vector for a single LZI trade."""
    # Zone Quality
    wick_size_pips: float
    wick_body_ratio: float
    swept_level_importance: int
    zone_width_pips: float
    formation_hour_utc: int
    formation_is_killzone: bool

    # Retest Quality
    bars_to_retest: int
    consumption_bars: int
    retest_depth_pct: float

    # Displacement Quality
    displacement_body_pips: float
    displacement_body_pct: float
    displacement_is_killzone: bool

    # Context
    atr_14_pips: float
    trend_aligned: bool
    distance_to_target_pips: float

    def to_dict(self) -> dict[str, float]:
        return {
            "wick_size_pips": self.wick_size_pips,
            "wick_body_ratio": self.wick_body_ratio,
            "swept_level_importance": float(self.swept_level_importance),
            "zone_width_pips": self.zone_width_pips,
            "formation_hour_utc": float(self.formation_hour_utc),
            "formation_is_killzone": float(self.formation_is_killzone),
            "bars_to_retest": float(self.bars_to_retest),
            "consumption_bars": float(self.consumption_bars),
            "retest_depth_pct": self.retest_depth_pct,
            "displacement_body_pips": self.displacement_body_pips,
            "displacement_body_pct": self.displacement_body_pct,
            "displacement_is_killzone": float(self.displacement_is_killzone),
            "atr_14_pips": self.atr_14_pips,
            "trend_aligned": float(self.trend_aligned),
            "distance_to_target_pips": self.distance_to_target_pips,
        }


LZI_FEATURE_COLUMNS = [
    "wick_size_pips",
    "wick_body_ratio",
    "swept_level_importance",
    "zone_width_pips",
    "formation_hour_utc",
    "formation_is_killzone",
    "bars_to_retest",
    "consumption_bars",
    "retest_depth_pct",
    "displacement_body_pips",
    "displacement_body_pct",
    "displacement_is_killzone",
    "atr_14_pips",
    "trend_aligned",
    "distance_to_target_pips",
]


def _is_killzone(hour_utc: int) -> bool:
    return hour_utc in _LONDON_OPEN or hour_utc in _NY_OPEN


def _atr14(bars: list[Bar], at_index: int) -> float:
    """ATR(14) in pips, computed from bars up to at_index (inclusive)."""
    period = 14
    start = max(1, at_index - period + 1)
    trs: list[float] = []
    for i in range(start, at_index + 1):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    return (sum(trs) / len(trs)) / PIP


def extract_lzi_features(
    bars: list[Bar],
    zone: LiquidityZone,
    entry_bar_index: int,
    tp_price: float,
) -> LZIFeatures:
    """Extract LZI-specific features for a single trade.

    Parameters
    ----------
    bars : full bar series (must include formation bar through entry bar)
    zone : the LiquidityZone that triggered
    entry_bar_index : index of the displacement/entry bar
    tp_price : take-profit price for this trade
    """
    formation_bar = bars[zone.formation_bar_index]
    entry_bar = bars[entry_bar_index]

    # --- Zone Quality ---
    wick_size_pips = zone.wick_size_pips
    zone_width = (zone.zone_top - zone.zone_bottom) / PIP
    formation_body = abs(formation_bar.close - formation_bar.open)
    wick_body_ratio = (wick_size_pips * PIP / formation_body) if formation_body > 0 else 10.0
    swept_level_importance = _LEVEL_IMPORTANCE.get(zone.swept_label, 1)
    formation_hour = formation_bar.time.hour
    formation_is_kz = _is_killzone(formation_hour)

    # --- Retest Quality ---
    bars_to_retest = (zone.retest_bar_index or entry_bar_index) - zone.formation_bar_index
    consumption_bars = zone.consumption_bars

    # Retest depth: how deep into the zone did price penetrate during retest
    retest_depth_pct = 0.5  # default mid
    zone_height = zone.zone_top - zone.zone_bottom
    if zone_height > 0 and zone.retest_bar_index is not None:
        retest_end = zone.displacement_bar_index or entry_bar_index
        retest_start = zone.retest_bar_index
        if zone.trade_direction == Direction.LONG:
            deepest = min(bars[j].low for j in range(retest_start, min(retest_end + 1, len(bars))))
            retest_depth_pct = max(0.0, min(1.0, (zone.zone_top - deepest) / zone_height))
        else:
            deepest = max(bars[j].high for j in range(retest_start, min(retest_end + 1, len(bars))))
            retest_depth_pct = max(0.0, min(1.0, (deepest - zone.zone_bottom) / zone_height))

    # --- Displacement Quality ---
    disp_body = abs(entry_bar.close - entry_bar.open)
    disp_range = entry_bar.high - entry_bar.low
    displacement_body_pips = disp_body / PIP
    displacement_body_pct = (disp_body / disp_range) if disp_range > 0 else 0.0
    disp_hour = entry_bar.time.hour
    displacement_is_kz = _is_killzone(disp_hour)

    # --- Context ---
    atr_14_pips = _atr14(bars, entry_bar_index)

    # Trend alignment: does direction align with 50-bar simple moving average slope?
    lookback = min(50, entry_bar_index)
    if lookback >= 10:
        ma_start = sum(bars[entry_bar_index - lookback + j].close for j in range(5)) / 5
        ma_end = sum(bars[entry_bar_index - 4 + j].close for j in range(5)) / 5
        trend_up = ma_end > ma_start
        trend_aligned = (
            (zone.trade_direction == Direction.LONG and trend_up)
            or (zone.trade_direction == Direction.SHORT and not trend_up)
        )
    else:
        trend_aligned = False

    # Distance to target
    distance_to_target_pips = abs(tp_price - entry_bar.close) / PIP

    return LZIFeatures(
        wick_size_pips=wick_size_pips,
        wick_body_ratio=min(wick_body_ratio, 20.0),  # cap outliers
        swept_level_importance=swept_level_importance,
        zone_width_pips=zone_width,
        formation_hour_utc=formation_hour,
        formation_is_killzone=formation_is_kz,
        bars_to_retest=bars_to_retest,
        consumption_bars=consumption_bars,
        retest_depth_pct=retest_depth_pct,
        displacement_body_pips=displacement_body_pips,
        displacement_body_pct=displacement_body_pct,
        displacement_is_killzone=displacement_is_kz,
        atr_14_pips=atr_14_pips,
        trend_aligned=trend_aligned,
        distance_to_target_pips=distance_to_target_pips,
    )
