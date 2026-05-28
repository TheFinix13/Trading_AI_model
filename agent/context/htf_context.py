"""
Higher-Timeframe Context Layer

Provides structural analysis on H4 and D1 to inform H1 entry decisions.
Implements pattern mechanics (not shape detection) based on order flow principles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


class MarketBias(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class PatternType(Enum):
    FAILED_BREAKOUT_HIGH = "failed_breakout_high"
    FAILED_BREAKOUT_LOW = "failed_breakout_low"
    PROGRESSIVE_WEAKNESS_BULL = "progressive_weakness_bull"
    PROGRESSIVE_WEAKNESS_BEAR = "progressive_weakness_bear"
    COMPRESSION = "compression"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    DISPLACEMENT_RETEST = "displacement_retest"


@dataclass
class StructuralLevel:
    price: float
    level_type: str  # "resistance", "support", "pullback_line"
    timeframe: str   # "H4", "D1"
    strength: int    # number of touches/tests
    last_test_bar: int
    swept: bool = False


@dataclass
class PatternSignal:
    pattern_type: PatternType
    timeframe: str
    confidence: float  # 0-1
    implied_direction: MarketBias
    key_level: float
    invalidation: float
    description: str


@dataclass
class WeeklyNarrative:
    """The story of the current trading week."""
    week_high: float
    week_low: float
    week_open: float
    current_price: float
    monday_range: Tuple[float, float]
    high_day: str
    low_day: str
    unswept_high_liquidity: List[float]
    unswept_low_liquidity: List[float]
    expansion_direction: Optional[MarketBias]


@dataclass
class HTFContext:
    """Complete higher-timeframe context passed to H1 entry layer."""
    h4_bias: MarketBias
    d1_bias: MarketBias
    combined_bias: MarketBias
    bias_confidence: float

    structural_levels: List[StructuralLevel] = field(default_factory=list)
    active_patterns: List[PatternSignal] = field(default_factory=list)
    weekly: Optional[WeeklyNarrative] = None
    htf_fib_levels: List[Tuple[float, str]] = field(default_factory=list)

    sell_aligned: bool = False
    buy_aligned: bool = False

    def supports_direction(self, direction: str) -> bool:
        """Check if HTF context supports the proposed trade direction."""
        if direction.lower() in ("buy", "long"):
            return self.buy_aligned
        elif direction.lower() in ("sell", "short"):
            return self.sell_aligned
        return False

    def get_nearest_htf_target(self, direction: str, entry_price: float) -> Optional[float]:
        """Get the nearest HTF structural level as a potential TP target."""
        if direction.lower() in ("buy", "long"):
            above = [l.price for l in self.structural_levels if l.price > entry_price]
            return min(above) if above else None
        else:
            below = [l.price for l in self.structural_levels if l.price < entry_price]
            return max(below) if below else None


class HTFAnalyzer:
    """
    Analyzes H4 and D1 data to produce structural context for H1 entries.

    Key principles:
    - HTF provides BIAS and LEVELS, never entry signals
    - Patterns are detected by their mechanics (order flow), not visual shape
    - 5-day lookback captures the full weekly narrative
    - Context updates every H4 bar close (every 4 hours)
    """

    def __init__(self, lookback_days: int = 5):
        self.lookback_days = lookback_days
        self.lookback_h4_bars = lookback_days * 6
        self.lookback_h1_bars = lookback_days * 24

    def analyze(self, h4_bars: pd.DataFrame, d1_bars: pd.DataFrame,
                h1_bars: Optional[pd.DataFrame] = None) -> HTFContext:
        """
        Main entry point. Analyze HTF data and return context.

        h4_bars: DataFrame with OHLCV, at least 30 bars (5 days)
        d1_bars: DataFrame with OHLCV, at least 20 bars
        h1_bars: Optional H1 bars for weekly narrative detail
        """
        h4_bias = self._compute_bias(h4_bars, "H4")
        d1_bias = self._compute_bias(d1_bars, "D1")
        combined_bias = self._combine_bias(h4_bias, d1_bias)

        levels = self._find_structural_levels(h4_bars, d1_bars)
        patterns = self._detect_patterns(h4_bars, levels)
        weekly = self._build_weekly_narrative(h4_bars, h1_bars)
        fibs = self._compute_htf_fibs(h4_bars, d1_bars)

        sell_aligned = combined_bias == MarketBias.BEARISH or any(
            p.implied_direction == MarketBias.BEARISH for p in patterns
        )
        buy_aligned = combined_bias == MarketBias.BULLISH or any(
            p.implied_direction == MarketBias.BULLISH for p in patterns
        )
        if combined_bias == MarketBias.NEUTRAL:
            sell_aligned = True
            buy_aligned = True

        confidence = self._compute_bias_confidence(h4_bias, d1_bias, patterns)

        return HTFContext(
            h4_bias=h4_bias,
            d1_bias=d1_bias,
            combined_bias=combined_bias,
            bias_confidence=confidence,
            structural_levels=levels,
            active_patterns=patterns,
            weekly=weekly,
            htf_fib_levels=fibs,
            sell_aligned=sell_aligned,
            buy_aligned=buy_aligned,
        )

    def _compute_bias(self, bars: pd.DataFrame, tf: str) -> MarketBias:
        """
        Determine trend bias using swing structure.
        Higher highs + higher lows = bullish
        Lower highs + lower lows = bearish
        Mixed = neutral
        """
        if len(bars) < 10:
            return MarketBias.NEUTRAL

        recent = bars.tail(20)
        highs = self._find_swing_points(recent, 'high', is_high=True)
        lows = self._find_swing_points(recent, 'low', is_high=False)

        if len(highs) < 2 or len(lows) < 2:
            return MarketBias.NEUTRAL

        higher_highs = highs[-1] > highs[-2]
        higher_lows = lows[-1] > lows[-2]
        lower_highs = highs[-1] < highs[-2]
        lower_lows = lows[-1] < lows[-2]

        if higher_highs and higher_lows:
            return MarketBias.BULLISH
        elif lower_highs and lower_lows:
            return MarketBias.BEARISH
        else:
            return MarketBias.NEUTRAL

    def _find_swing_points(self, bars: pd.DataFrame, col: str, is_high: bool,
                           window: int = 3) -> List[float]:
        """Find swing highs or lows using rolling window comparison."""
        values = bars[col].values
        swings: List[float] = []
        for i in range(window, len(values) - window):
            if is_high:
                if all(values[i] >= values[i - j] for j in range(1, window + 1)) and \
                   all(values[i] >= values[i + j] for j in range(1, window + 1)):
                    swings.append(float(values[i]))
            else:
                if all(values[i] <= values[i - j] for j in range(1, window + 1)) and \
                   all(values[i] <= values[i + j] for j in range(1, window + 1)):
                    swings.append(float(values[i]))
        return swings

    def _find_structural_levels(self, h4_bars: pd.DataFrame,
                                d1_bars: pd.DataFrame) -> List[StructuralLevel]:
        """
        Find key support/resistance levels from H4 and D1.
        A level is structural if price has reacted to it multiple times.
        """
        levels: List[StructuralLevel] = []
        current_price = float(h4_bars['close'].iloc[-1])
        tolerance = 15 * 0.0001  # 15 pips

        h4_highs = self._find_swing_points(h4_bars.tail(30), 'high', is_high=True)
        h4_lows = self._find_swing_points(h4_bars.tail(30), 'low', is_high=False)

        for price_level in h4_highs:
            touches = int(np.sum(np.abs(h4_bars['high'].values - price_level) < tolerance))
            if touches >= 2:
                swept = current_price > price_level + tolerance
                levels.append(StructuralLevel(
                    price=price_level,
                    level_type="resistance",
                    timeframe="H4",
                    strength=touches,
                    last_test_bar=len(h4_bars) - 1,
                    swept=swept,
                ))

        for price_level in h4_lows:
            touches = int(np.sum(np.abs(h4_bars['low'].values - price_level) < tolerance))
            if touches >= 2:
                swept = current_price < price_level - tolerance
                levels.append(StructuralLevel(
                    price=price_level,
                    level_type="support",
                    timeframe="H4",
                    strength=touches,
                    last_test_bar=len(h4_bars) - 1,
                    swept=swept,
                ))

        d1_highs = self._find_swing_points(d1_bars.tail(20), 'high', is_high=True, window=2)
        d1_lows = self._find_swing_points(d1_bars.tail(20), 'low', is_high=False, window=2)

        for price_level in d1_highs:
            levels.append(StructuralLevel(
                price=price_level,
                level_type="resistance",
                timeframe="D1",
                strength=3,
                last_test_bar=len(d1_bars) - 1,
                swept=current_price > price_level + tolerance,
            ))

        for price_level in d1_lows:
            levels.append(StructuralLevel(
                price=price_level,
                level_type="support",
                timeframe="D1",
                strength=3,
                last_test_bar=len(d1_bars) - 1,
                swept=current_price < price_level - tolerance,
            ))

        return sorted(levels, key=lambda l: abs(l.price - current_price))

    def _detect_patterns(self, h4_bars: pd.DataFrame,
                         levels: List[StructuralLevel]) -> List[PatternSignal]:
        """Detect pattern MECHANICS (not shapes) based on order flow principles."""
        patterns: List[PatternSignal] = []
        patterns.extend(self._detect_failed_breakouts(h4_bars))
        patterns.extend(self._detect_progressive_weakness(h4_bars))
        patterns.extend(self._detect_compression(h4_bars))
        patterns.extend(self._detect_displacement_retest(h4_bars))
        return patterns

    def _detect_failed_breakouts(self, bars: pd.DataFrame) -> List[PatternSignal]:
        """
        Failed breakout = two or more attempts to break a level, each rejected.
        Covers: double top, double bottom, H&S right shoulder.

        Mechanics: Market tries to break through, sweeps liquidity above/below,
        but fails to hold. Second failure = high conviction reversal.
        """
        patterns: List[PatternSignal] = []
        tolerance = 10 * 0.0001
        recent = bars.tail(self.lookback_h4_bars)

        if len(recent) < 10:
            return patterns

        # Find swing highs (potential double top)
        highs: List[Tuple[int, float]] = []
        for i in range(2, len(recent) - 2):
            if (recent['high'].iloc[i] >= recent['high'].iloc[i - 1] and
                recent['high'].iloc[i] >= recent['high'].iloc[i - 2] and
                recent['high'].iloc[i] >= recent['high'].iloc[i + 1] and
                recent['high'].iloc[i] >= recent['high'].iloc[i + 2]):
                highs.append((i, float(recent['high'].iloc[i])))

        for j in range(1, len(highs)):
            idx_a, price_a = highs[j - 1]
            idx_b, price_b = highs[j]

            if abs(price_a - price_b) < tolerance and (idx_b - idx_a) >= 3:
                valley = float(recent['low'].iloc[idx_a:idx_b + 1].min())
                valley_depth = max(price_a, price_b) - valley

                if valley_depth > 20 * 0.0001:
                    level = max(price_a, price_b)
                    current = float(recent['close'].iloc[-1])

                    if current < level - 5 * 0.0001:
                        patterns.append(PatternSignal(
                            pattern_type=PatternType.FAILED_BREAKOUT_HIGH,
                            timeframe="H4",
                            confidence=min(0.9, 0.5 + valley_depth / (100 * 0.0001)),
                            implied_direction=MarketBias.BEARISH,
                            key_level=level,
                            invalidation=level + 20 * 0.0001,
                            description=(
                                f"Failed breakout at {level:.5f} (double top mechanics). "
                                f"Two attempts swept liquidity above but couldn't hold. "
                                f"Valley depth: {valley_depth / 0.0001:.0f} pips. "
                                f"Expect reversal toward demand below."
                            ),
                        ))

        # Find swing lows (potential double bottom)
        lows: List[Tuple[int, float]] = []
        for i in range(2, len(recent) - 2):
            if (recent['low'].iloc[i] <= recent['low'].iloc[i - 1] and
                recent['low'].iloc[i] <= recent['low'].iloc[i - 2] and
                recent['low'].iloc[i] <= recent['low'].iloc[i + 1] and
                recent['low'].iloc[i] <= recent['low'].iloc[i + 2]):
                lows.append((i, float(recent['low'].iloc[i])))

        for j in range(1, len(lows)):
            idx_a, price_a = lows[j - 1]
            idx_b, price_b = lows[j]

            if abs(price_a - price_b) < tolerance and (idx_b - idx_a) >= 3:
                peak = float(recent['high'].iloc[idx_a:idx_b + 1].max())
                peak_height = peak - min(price_a, price_b)

                if peak_height > 20 * 0.0001:
                    level = min(price_a, price_b)
                    current = float(recent['close'].iloc[-1])

                    if current > level + 5 * 0.0001:
                        patterns.append(PatternSignal(
                            pattern_type=PatternType.FAILED_BREAKOUT_LOW,
                            timeframe="H4",
                            confidence=min(0.9, 0.5 + peak_height / (100 * 0.0001)),
                            implied_direction=MarketBias.BULLISH,
                            key_level=level,
                            invalidation=level - 20 * 0.0001,
                            description=(
                                f"Failed breakout at {level:.5f} (double bottom mechanics). "
                                f"Two attempts swept liquidity below but couldn't hold. "
                                f"Peak height: {peak_height / 0.0001:.0f} pips. "
                                f"Expect reversal toward supply above."
                            ),
                        ))

        return patterns

    def _detect_progressive_weakness(self, bars: pd.DataFrame) -> List[PatternSignal]:
        """
        Progressive weakness = each successive swing is weaker.
        Covers: H&S, rising wedge, descending triangle.

        Mechanics: Momentum dying = one side is being exhausted.
        """
        patterns: List[PatternSignal] = []
        recent = bars.tail(self.lookback_h4_bars)

        if len(recent) < 15:
            return patterns

        # Find highs with their displacement (momentum into that high)
        highs_with_momentum: List[Tuple[int, float, float]] = []
        for i in range(3, len(recent) - 2):
            if (recent['high'].iloc[i] >= recent['high'].iloc[i - 1] and
                    recent['high'].iloc[i] >= recent['high'].iloc[i + 1]):
                lookback_window = min(5, i)
                move_start = float(recent['low'].iloc[i - lookback_window:i].min())
                displacement = float(recent['high'].iloc[i]) - move_start
                highs_with_momentum.append((i, float(recent['high'].iloc[i]), displacement))

        if len(highs_with_momentum) >= 3:
            last_3 = highs_with_momentum[-3:]
            disp_values = [h[2] for h in last_3]

            if disp_values[0] > disp_values[1] > disp_values[2]:
                high_values = [h[1] for h in last_3]
                high_range = max(high_values) - min(high_values)

                if high_range < 50 * 0.0001:
                    patterns.append(PatternSignal(
                        pattern_type=PatternType.PROGRESSIVE_WEAKNESS_BULL,
                        timeframe="H4",
                        confidence=0.6,
                        implied_direction=MarketBias.BEARISH,
                        key_level=max(high_values),
                        invalidation=max(high_values) + 30 * 0.0001,
                        description=(
                            f"Progressive weakness on bullish side. "
                            f"Last 3 rallies show decreasing displacement "
                            f"({disp_values[0] / 0.0001:.0f} -> {disp_values[1] / 0.0001:.0f} -> "
                            f"{disp_values[2] / 0.0001:.0f} pips). "
                            f"Buyers exhausting. H&S/rising wedge mechanics."
                        ),
                    ))

        # Bearish side weakness (bullish signal)
        lows_with_momentum: List[Tuple[int, float, float]] = []
        for i in range(3, len(recent) - 2):
            if (recent['low'].iloc[i] <= recent['low'].iloc[i - 1] and
                    recent['low'].iloc[i] <= recent['low'].iloc[i + 1]):
                lookback_window = min(5, i)
                move_start = float(recent['high'].iloc[i - lookback_window:i].max())
                displacement = move_start - float(recent['low'].iloc[i])
                lows_with_momentum.append((i, float(recent['low'].iloc[i]), displacement))

        if len(lows_with_momentum) >= 3:
            last_3 = lows_with_momentum[-3:]
            disp_values = [l[2] for l in last_3]

            if disp_values[0] > disp_values[1] > disp_values[2]:
                low_values = [l[1] for l in last_3]
                low_range = max(low_values) - min(low_values)

                if low_range < 50 * 0.0001:
                    patterns.append(PatternSignal(
                        pattern_type=PatternType.PROGRESSIVE_WEAKNESS_BEAR,
                        timeframe="H4",
                        confidence=0.6,
                        implied_direction=MarketBias.BULLISH,
                        key_level=min(low_values),
                        invalidation=min(low_values) - 30 * 0.0001,
                        description=(
                            f"Progressive weakness on bearish side. "
                            f"Last 3 drops show decreasing displacement "
                            f"({disp_values[0] / 0.0001:.0f} -> {disp_values[1] / 0.0001:.0f} -> "
                            f"{disp_values[2] / 0.0001:.0f} pips). "
                            f"Sellers exhausting. Inverse H&S/falling wedge mechanics."
                        ),
                    ))

        return patterns

    def _detect_compression(self, bars: pd.DataFrame) -> List[PatternSignal]:
        """
        Compression = decreasing range with liquidity building on both sides.
        Covers: symmetric triangle, pennant, narrowing wedge.

        Mechanics: Market building liquidity above and below before a sweep.
        Expansion follows compression (volatility mean-reverts).
        """
        patterns: List[PatternSignal] = []
        recent = bars.tail(15)

        if len(recent) < 10:
            return patterns

        ranges = (recent['high'] - recent['low']).values
        first_half_avg = float(np.mean(ranges[:len(ranges) // 2]))
        second_half_avg = float(np.mean(ranges[len(ranges) // 2:]))

        if first_half_avg > 0 and second_half_avg < first_half_avg * 0.7:
            recent_high = float(recent['high'].tail(5).max())
            recent_low = float(recent['low'].tail(5).min())

            patterns.append(PatternSignal(
                pattern_type=PatternType.COMPRESSION,
                timeframe="H4",
                confidence=0.5,
                implied_direction=MarketBias.NEUTRAL,
                key_level=(recent_high + recent_low) / 2,
                invalidation=0,
                description=(
                    f"Range compression detected. "
                    f"Volatility decreased {((1 - second_half_avg / first_half_avg) * 100):.0f}%. "
                    f"Liquidity building above {recent_high:.5f} and below {recent_low:.5f}. "
                    f"Expect expansion — trade the sweep of whichever side breaks first."
                ),
            ))

        return patterns

    def _detect_displacement_retest(self, bars: pd.DataFrame) -> List[PatternSignal]:
        """
        Displacement + Retest = strong impulsive move followed by consolidation.
        Covers: bull/bear flags, pennants.

        Mechanics: Impulsive candle(s) create an imbalance (FVG).
        Price returns to the imbalance for retest = continuation expected.
        """
        patterns: List[PatternSignal] = []
        recent = bars.tail(20)

        if len(recent) < 10:
            return patterns

        atr = (recent['high'] - recent['low']).rolling(14).mean()

        for i in range(5, len(recent) - 3):
            body = abs(float(recent['close'].iloc[i]) - float(recent['open'].iloc[i]))
            current_atr = float(atr.iloc[i]) if not pd.isna(atr.iloc[i]) else 0.001

            if body > 2 * current_atr:
                bullish_displacement = recent['close'].iloc[i] > recent['open'].iloc[i]
                disp_mid = (float(recent['open'].iloc[i]) + float(recent['close'].iloc[i])) / 2
                subsequent = recent.iloc[i + 1:]

                if bullish_displacement:
                    retraced = any(row['low'] <= disp_mid for _, row in subsequent.iterrows())
                    if retraced and recent['close'].iloc[-1] > recent['open'].iloc[i]:
                        patterns.append(PatternSignal(
                            pattern_type=PatternType.DISPLACEMENT_RETEST,
                            timeframe="H4",
                            confidence=0.65,
                            implied_direction=MarketBias.BULLISH,
                            key_level=float(recent['open'].iloc[i]),
                            invalidation=float(recent['low'].iloc[i]),
                            description=(
                                f"Bullish displacement + retest on H4. "
                                f"Strong impulse candle ({body / 0.0001:.0f} pips body) "
                                f"followed by retest of displacement zone. "
                                f"Bull flag / continuation mechanics."
                            ),
                        ))
                else:
                    retraced = any(row['high'] >= disp_mid for _, row in subsequent.iterrows())
                    if retraced and recent['close'].iloc[-1] < recent['open'].iloc[i]:
                        patterns.append(PatternSignal(
                            pattern_type=PatternType.DISPLACEMENT_RETEST,
                            timeframe="H4",
                            confidence=0.65,
                            implied_direction=MarketBias.BEARISH,
                            key_level=float(recent['open'].iloc[i]),
                            invalidation=float(recent['high'].iloc[i]),
                            description=(
                                f"Bearish displacement + retest on H4. "
                                f"Strong impulse candle ({body / 0.0001:.0f} pips body) "
                                f"followed by retest of displacement zone. "
                                f"Bear flag / continuation mechanics."
                            ),
                        ))

        return patterns

    def _build_weekly_narrative(self, h4_bars: pd.DataFrame,
                                h1_bars: Optional[pd.DataFrame]) -> Optional[WeeklyNarrative]:
        """
        Build the current week's story: where did range form,
        what's been swept, what's still untouched.
        """
        week_bars = h4_bars.tail(30)
        if len(week_bars) < 5:
            return None

        week_high = float(week_bars['high'].max())
        week_low = float(week_bars['low'].min())
        week_open = float(week_bars['open'].iloc[0])
        current_price = float(week_bars['close'].iloc[-1])

        # Identify unswept liquidity
        swing_highs = self._find_swing_points(week_bars, 'high', is_high=True, window=2)
        swing_lows = self._find_swing_points(week_bars, 'low', is_high=False, window=2)

        unswept_highs = [sh for sh in swing_highs if current_price < sh]
        unswept_lows = [sl for sl in swing_lows if current_price > sl]

        # Determine expansion direction
        mid = (week_high + week_low) / 2
        if current_price > mid + 0.0010:
            expansion = MarketBias.BULLISH
        elif current_price < mid - 0.0010:
            expansion = MarketBias.BEARISH
        else:
            expansion = MarketBias.NEUTRAL

        monday_high = float(week_bars['high'].iloc[:6].max())
        monday_low = float(week_bars['low'].iloc[:6].min())

        return WeeklyNarrative(
            week_high=week_high,
            week_low=week_low,
            week_open=week_open,
            current_price=current_price,
            monday_range=(monday_low, monday_high),
            high_day="mid-week",
            low_day="early-week",
            unswept_high_liquidity=sorted(unswept_highs),
            unswept_low_liquidity=sorted(unswept_lows, reverse=True),
            expansion_direction=expansion,
        )

    def _compute_htf_fibs(self, h4_bars: pd.DataFrame,
                          d1_bars: pd.DataFrame) -> List[Tuple[float, str]]:
        """
        Compute Fibonacci levels from the most recent HTF swing.
        Uses the last significant swing high->low or low->high on H4.
        """
        fibs: List[Tuple[float, str]] = []
        recent = h4_bars.tail(30)

        swing_highs = self._find_swing_points(recent, 'high', is_high=True, window=3)
        swing_lows = self._find_swing_points(recent, 'low', is_high=False, window=3)

        if not swing_highs or not swing_lows:
            return fibs

        last_high = swing_highs[-1]
        last_low = swing_lows[-1]

        high_vals = recent['high'].values.tolist()
        low_vals = recent['low'].values.tolist()
        high_idx = len(high_vals) - 1 - high_vals[::-1].index(last_high) if last_high in high_vals else 0
        low_idx = len(low_vals) - 1 - low_vals[::-1].index(last_low) if last_low in low_vals else 0

        fib_levels = [0.236, 0.382, 0.5, 0.618, 0.786]

        if high_idx > low_idx:
            # Swing is low -> high, retracement goes down
            swing_range = last_high - last_low
            for fib in fib_levels:
                level = last_high - (swing_range * fib)
                fibs.append((level, f"H4 {fib * 100:.1f}%"))
        else:
            # Swing is high -> low, retracement goes up
            swing_range = last_high - last_low
            for fib in fib_levels:
                level = last_low + (swing_range * fib)
                fibs.append((level, f"H4 {fib * 100:.1f}%"))

        return fibs

    def _combine_bias(self, h4_bias: MarketBias, d1_bias: MarketBias) -> MarketBias:
        """Combine H4 and D1 bias. D1 has more weight."""
        if h4_bias == d1_bias:
            return h4_bias
        if d1_bias == MarketBias.NEUTRAL:
            return h4_bias
        if h4_bias == MarketBias.NEUTRAL:
            return d1_bias
        # Conflicting: D1 wins (higher timeframe = stronger)
        return d1_bias

    def _compute_bias_confidence(self, h4_bias: MarketBias, d1_bias: MarketBias,
                                 patterns: List[PatternSignal]) -> float:
        """Compute confidence in the combined bias."""
        conf = 0.5
        if h4_bias == d1_bias and h4_bias != MarketBias.NEUTRAL:
            conf += 0.2

        for p in patterns:
            conf += p.confidence * 0.1

        return min(1.0, conf)
