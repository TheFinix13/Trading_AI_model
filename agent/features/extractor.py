"""Convert a Setup + market context into a feature vector for the ML scorer."""
from __future__ import annotations

from datetime import datetime

from agent.detectors.atr import atr
from agent.types import Bar, Direction, Setup
from agent.utils import to_pips


def extract_features(setup: Setup, bars: list[Bar], at_index: int) -> dict[str, float]:
    """Generate features at decision time. Strictly no future leakage:
    only use bars[:at_index+1]."""
    available = bars[: at_index + 1]
    if not available:
        return {}

    cur = available[-1]
    feats: dict[str, float] = {}

    feats["confluence_count"] = float(len(setup.confluences))
    feats["has_zone"] = float(setup.zone is not None)
    feats["has_fvg"] = float(setup.fvg is not None)
    feats["has_fib"] = float(setup.fib is not None)
    feats["has_trendline"] = float(setup.trendline is not None)
    feats["has_liquidity_wick"] = float(setup.liquidity_wick is not None)
    feats["has_bos"] = float(setup.bos is not None)

    feats["direction_long"] = float(setup.direction == Direction.LONG)

    feats["entry"] = setup.entry
    feats["stop_pips"] = setup.stop_pips
    feats["reward_pips"] = setup.reward_pips
    feats["rr"] = setup.rr

    a14 = atr(available, period=14)
    a50 = atr(available, period=min(50, len(available) - 1)) if len(available) > 2 else a14
    feats["atr_14_pips"] = to_pips(a14)
    feats["atr_50_pips"] = to_pips(a50)
    feats["atr_ratio"] = (a14 / a50) if a50 > 0 else 1.0

    if len(available) >= 21:
        ma21 = sum(b.close for b in available[-21:]) / 21
        feats["dist_to_ma21_pips"] = to_pips(cur.close - ma21)
        feats["above_ma21"] = float(cur.close > ma21)
    else:
        feats["dist_to_ma21_pips"] = 0.0
        feats["above_ma21"] = 0.0

    if len(available) >= 50:
        recent_highs = max(b.high for b in available[-50:])
        recent_lows = min(b.low for b in available[-50:])
        rng = max(recent_highs - recent_lows, 1e-9)
        feats["price_position_50"] = (cur.close - recent_lows) / rng  # 0..1
    else:
        feats["price_position_50"] = 0.5

    if setup.zone is not None:
        feats["dist_to_zone_pips"] = to_pips(abs(cur.close - setup.zone.mid))
        feats["zone_age_bars"] = float(at_index - setup.zone.created_bar_index)
        feats["zone_impulse_pips"] = setup.zone.impulse_pips
    else:
        feats["dist_to_zone_pips"] = 0.0
        feats["zone_age_bars"] = 0.0
        feats["zone_impulse_pips"] = 0.0

    if setup.fib is not None:
        for lvl, price in setup.fib.levels.items():
            feats[f"fib_{int(lvl*1000)}_dist_pips"] = to_pips(abs(cur.close - price))
    else:
        for lvl in (0.382, 0.5, 0.618, 0.786):
            feats[f"fib_{int(lvl*1000)}_dist_pips"] = 0.0

    if setup.bos is not None:
        feats["bos_age_bars"] = float(at_index - setup.bos.broken_bar_index)
        feats["bos_aligned"] = float(setup.bos.direction == setup.direction)
    else:
        feats["bos_age_bars"] = 0.0
        feats["bos_aligned"] = 0.0

    if setup.liquidity_wick is not None:
        feats["wick_ratio"] = setup.liquidity_wick.wick_to_body_ratio
        feats["wick_age_bars"] = float(at_index - setup.liquidity_wick.bar_index)
    else:
        feats["wick_ratio"] = 0.0
        feats["wick_age_bars"] = 0.0

    t: datetime = setup.detected_at
    feats["hour"] = float(t.hour)
    feats["dow"] = float(t.weekday())
    feats["is_london"] = float(7 <= t.hour < 16)
    feats["is_ny"] = float(13 <= t.hour < 22)
    feats["is_overlap"] = float(13 <= t.hour < 16)

    return feats


FEATURE_COLUMNS = [
    "confluence_count",
    "has_zone",
    "has_fvg",
    "has_fib",
    "has_trendline",
    "has_liquidity_wick",
    "has_bos",
    "direction_long",
    "entry",
    "stop_pips",
    "reward_pips",
    "rr",
    "atr_14_pips",
    "atr_50_pips",
    "atr_ratio",
    "dist_to_ma21_pips",
    "above_ma21",
    "price_position_50",
    "dist_to_zone_pips",
    "zone_age_bars",
    "zone_impulse_pips",
    "fib_382_dist_pips",
    "fib_500_dist_pips",
    "fib_618_dist_pips",
    "fib_786_dist_pips",
    "bos_age_bars",
    "bos_aligned",
    "wick_ratio",
    "wick_age_bars",
    "hour",
    "dow",
    "is_london",
    "is_ny",
    "is_overlap",
]
