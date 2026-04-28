"""Long-wick liquidity grab detection.

A long-wick candle that pierces a recent swing high/low and then closes back inside,
with wick:body ratio >= threshold. These are stop-hunt areas that price often revisits."""
from __future__ import annotations

from agent.detectors.swings import detect_swings
from agent.types import Bar, Direction, LiquidityWick


def detect_liquidity_wicks(
    bars: list[Bar],
    min_wick_ratio: float = 2.0,
    swing_lookback: int = 5,
    pierce_buffer_pips: float = 2.0,
) -> list[LiquidityWick]:
    swings = detect_swings(bars, lookback=swing_lookback)
    if not swings:
        return []

    wicks: list[LiquidityWick] = []
    buf = pierce_buffer_pips * 0.0001

    for i, bar in enumerate(bars):
        body = max(bar.body, 1e-9)

        prior_highs = [s for s in swings if s.is_high and s.bar_index < i - swing_lookback]
        if prior_highs:
            ref_high = max(prior_highs[-3:], key=lambda s: s.price) if len(prior_highs) >= 1 else prior_highs[-1]
            if (
                bar.high > ref_high.price + buf
                and bar.close < ref_high.price
                and bar.upper_wick / body >= min_wick_ratio
            ):
                wicks.append(
                    LiquidityWick(
                        direction=Direction.LONG,  # buyside liquidity grabbed (above highs)
                        wick_top=bar.high,
                        wick_bottom=ref_high.price,
                        time=bar.time,
                        bar_index=i,
                        wick_to_body_ratio=bar.upper_wick / body,
                    )
                )

        prior_lows = [s for s in swings if not s.is_high and s.bar_index < i - swing_lookback]
        if prior_lows:
            ref_low = min(prior_lows[-3:], key=lambda s: s.price) if len(prior_lows) >= 1 else prior_lows[-1]
            if (
                bar.low < ref_low.price - buf
                and bar.close > ref_low.price
                and bar.lower_wick / body >= min_wick_ratio
            ):
                wicks.append(
                    LiquidityWick(
                        direction=Direction.SHORT,  # sellside liquidity grabbed (below lows)
                        wick_top=ref_low.price,
                        wick_bottom=bar.low,
                        time=bar.time,
                        bar_index=i,
                        wick_to_body_ratio=bar.lower_wick / body,
                    )
                )

    return wicks
