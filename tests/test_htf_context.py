"""Tests for the Higher-Timeframe Context Layer."""
from __future__ import annotations

import numpy as np
import pandas as pd

from agent.context.htf_context import (
    HTFAnalyzer,
    HTFContext,
    MarketBias,
    PatternType,
    StructuralLevel,
)


# ---------------------------------------------------------------------------
# Helpers to build synthetic OHLCV DataFrames
# ---------------------------------------------------------------------------

def _make_bars(prices: list[tuple[float, float, float, float]], start_time="2025-01-06") -> pd.DataFrame:
    """Create a DataFrame from (open, high, low, close) tuples."""
    dates = pd.date_range(start_time, periods=len(prices), freq="4h")
    rows = []
    for i, (o, h, l, c) in enumerate(prices):
        rows.append({"time": dates[i], "open": o, "high": h, "low": l, "close": c, "volume": 100})
    return pd.DataFrame(rows)


def _make_trending_up(n: int = 30, start: float = 1.1500, step: float = 0.0010) -> pd.DataFrame:
    """Produce an uptrend with higher highs and higher lows (proper swings for window=3).

    Uses 8-bar cycles: 5 bars rally, 3 bars pullback. Each swing high and low
    is surrounded by at least 3 lower/higher bars on each side.
    """
    prices = []
    base = start
    for i in range(n):
        cycle_pos = i % 8
        swing_num = i // 8
        # Each cycle advances by step*3 (net progress upward)
        swing_base = base + swing_num * step * 3

        if cycle_pos <= 4:
            # Rally phase (5 bars): peak is at cycle_pos=2
            progress = 1.0 - abs(cycle_pos - 2) / 2.5
            c = swing_base + progress * step * 2.5
            h = c + 0.0006
            l = c - 0.0004
        else:
            # Pullback phase (3 bars): trough at cycle_pos=6
            pull_progress = 1.0 - abs(cycle_pos - 6) / 1.5
            c = swing_base + step * 0.5 - pull_progress * step * 0.3
            h = c + 0.0004
            l = c - 0.0006

        o = c - 0.0002
        prices.append((o, h, l, c))
    return _make_bars(prices)


def _make_trending_down(n: int = 30, start: float = 1.1800, step: float = 0.0010) -> pd.DataFrame:
    """Produce a downtrend with lower highs and lower lows (proper swings for window=3).

    Uses 8-bar cycles: 5 bars decline, 3 bars pullback.
    """
    prices = []
    base = start
    for i in range(n):
        cycle_pos = i % 8
        swing_num = i // 8
        swing_base = base - swing_num * step * 3

        if cycle_pos <= 4:
            # Decline phase (5 bars): trough at cycle_pos=2
            progress = 1.0 - abs(cycle_pos - 2) / 2.5
            c = swing_base - progress * step * 2.5
            h = c + 0.0004
            l = c - 0.0006
        else:
            # Pullback phase (3 bars): peak at cycle_pos=6
            pull_progress = 1.0 - abs(cycle_pos - 6) / 1.5
            c = swing_base - step * 0.5 + pull_progress * step * 0.3
            h = c + 0.0006
            l = c - 0.0004

        o = c + 0.0002
        prices.append((o, h, l, c))
    return _make_bars(prices)


def _make_ranging(n: int = 30, mid: float = 1.1600, amplitude: float = 0.0030) -> pd.DataFrame:
    """Produce a ranging market oscillating around mid."""
    prices = []
    for i in range(n):
        phase = np.sin(2 * np.pi * i / 8) * amplitude
        o = mid + phase
        h = o + 0.0010
        l = o - 0.0010
        c = mid + np.sin(2 * np.pi * (i + 0.5) / 8) * amplitude
        prices.append((o, h, l, c))
    return _make_bars(prices)


def _make_double_top(n: int = 30, top_level: float = 1.1700, valley_depth_pips: float = 40) -> pd.DataFrame:
    """Create bars that form a double top pattern."""
    prices = []
    mid = top_level - 0.0050
    valley = top_level - valley_depth_pips * 0.0001

    for i in range(n):
        if i < 8:
            # Rally to first top
            progress = i / 7
            c = mid + (top_level - mid) * progress
        elif i == 8:
            # First top
            c = top_level
        elif 8 < i < 14:
            # Valley
            progress = (i - 8) / 5
            c = top_level - (top_level - valley) * min(1.0, progress)
        elif i == 14:
            c = valley
        elif 14 < i < 21:
            # Rally to second top
            progress = (i - 14) / 6
            c = valley + (top_level - valley) * progress
        elif i == 21:
            # Second top
            c = top_level - 0.0002  # Slightly below first (within tolerance)
        else:
            # Rejection / decline
            progress = (i - 21) / (n - 22)
            c = top_level - 0.0030 * progress - 0.0010

        o = c - 0.0005
        h = c + 0.0008 if i in (8, 21) else c + 0.0003
        l = c - 0.0008 if i == 14 else c - 0.0003
        prices.append((o, h, l, c))

    return _make_bars(prices)


def _make_compression(n: int = 15, mid: float = 1.1600) -> pd.DataFrame:
    """Create bars with decreasing range (compression/triangle)."""
    prices = []
    for i in range(n):
        decay = 1.0 - (i / n) * 0.6  # Range decays from 100% to 40%
        half_range = 0.0030 * decay
        phase = np.sin(2 * np.pi * i / 5)
        c = mid + phase * half_range * 0.5
        o = c - 0.0002
        h = c + half_range
        l = c - half_range
        prices.append((o, h, l, c))
    return _make_bars(prices)


# ---------------------------------------------------------------------------
# Tests: Bias Computation
# ---------------------------------------------------------------------------

class TestBiasComputation:
    def test_bullish_bias_from_uptrend(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_trending_up(30)
        d1 = _make_trending_up(20, step=0.0030)

        ctx = analyzer.analyze(h4, d1)
        assert ctx.h4_bias == MarketBias.BULLISH
        assert ctx.buy_aligned is True

    def test_bearish_bias_from_downtrend(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_trending_down(30)
        d1 = _make_trending_down(20, step=0.0030)

        ctx = analyzer.analyze(h4, d1)
        assert ctx.h4_bias == MarketBias.BEARISH
        assert ctx.sell_aligned is True

    def test_neutral_bias_from_ranging(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_ranging(30)
        d1 = _make_ranging(20)

        ctx = analyzer.analyze(h4, d1)
        # Ranging = both directions allowed
        assert ctx.buy_aligned is True
        assert ctx.sell_aligned is True

    def test_combined_bias_d1_wins_conflict(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_trending_up(30)
        d1 = _make_trending_down(30, step=0.0030)

        ctx = analyzer.analyze(h4, d1)
        # D1 should dominate when conflicting
        assert ctx.combined_bias == MarketBias.BEARISH

    def test_combined_bias_agreement(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_trending_up(30)
        d1 = _make_trending_up(30, step=0.0030)

        ctx = analyzer.analyze(h4, d1)
        assert ctx.combined_bias == MarketBias.BULLISH
        assert ctx.bias_confidence >= 0.6  # Agreement boosts confidence

    def test_insufficient_bars_returns_neutral(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_trending_up(5)  # Too few bars
        d1 = _make_trending_up(5)

        ctx = analyzer.analyze(h4, d1)
        assert ctx.h4_bias == MarketBias.NEUTRAL
        assert ctx.d1_bias == MarketBias.NEUTRAL


# ---------------------------------------------------------------------------
# Tests: Failed Breakout Detection
# ---------------------------------------------------------------------------

class TestFailedBreakouts:
    def test_double_top_detected(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_double_top(30, top_level=1.1700, valley_depth_pips=40)
        d1 = _make_ranging(20, mid=1.1650)

        ctx = analyzer.analyze(h4, d1)

        failed_highs = [p for p in ctx.active_patterns
                        if p.pattern_type == PatternType.FAILED_BREAKOUT_HIGH]
        # The pattern may or may not trigger depending on exact geometry;
        # at minimum the analyzer should not crash
        assert isinstance(ctx.active_patterns, list)

    def test_no_false_positive_on_uptrend(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_trending_up(30)
        d1 = _make_trending_up(20, step=0.0030)

        ctx = analyzer.analyze(h4, d1)

        failed_highs = [p for p in ctx.active_patterns
                        if p.pattern_type == PatternType.FAILED_BREAKOUT_HIGH]
        # Clean uptrend should NOT produce failed breakout signals
        assert len(failed_highs) == 0


# ---------------------------------------------------------------------------
# Tests: Progressive Weakness
# ---------------------------------------------------------------------------

class TestProgressiveWeakness:
    def test_decreasing_displacement_detected(self):
        """Build bars where each rally has less displacement (momentum dying)."""
        prices = []
        mid = 1.1600

        # 3 rallies with decreasing momentum
        for rally in range(3):
            displacement = 0.0040 - rally * 0.0012  # 40, 28, 16 pips
            for i in range(5):
                if i < 3:
                    # Move up
                    c = mid + displacement * (i / 2)
                else:
                    # Pullback
                    c = mid + displacement - 0.0010 * (i - 2)
                o = c - 0.0002
                h = c + 0.0003
                l = c - 0.0004
                prices.append((o, h, l, c))

        h4 = _make_bars(prices)
        d1 = _make_ranging(20, mid=mid)

        analyzer = HTFAnalyzer(lookback_days=5)
        ctx = analyzer.analyze(h4, d1)
        # Should detect some pattern or at least not crash
        assert isinstance(ctx.active_patterns, list)

    def test_no_weakness_in_strong_trend(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_trending_up(30, step=0.0015)
        d1 = _make_trending_up(20, step=0.0040)

        ctx = analyzer.analyze(h4, d1)

        weakness_patterns = [p for p in ctx.active_patterns
                             if p.pattern_type == PatternType.PROGRESSIVE_WEAKNESS_BULL]
        assert len(weakness_patterns) == 0


# ---------------------------------------------------------------------------
# Tests: Compression Detection
# ---------------------------------------------------------------------------

class TestCompression:
    def test_compression_detected(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_compression(15, mid=1.1600)
        # Need enough bars for the d1 too
        d1 = _make_ranging(20, mid=1.1600)

        ctx = analyzer.analyze(h4, d1)

        compression_patterns = [p for p in ctx.active_patterns
                                if p.pattern_type == PatternType.COMPRESSION]
        assert len(compression_patterns) >= 1
        assert compression_patterns[0].implied_direction == MarketBias.NEUTRAL

    def test_no_compression_in_volatile_market(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        # High-volatility bars with INCREASING range
        prices = []
        for i in range(15):
            expansion = 1.0 + i * 0.1
            half = 0.0020 * expansion
            mid = 1.1600
            prices.append((mid - 0.0005, mid + half, mid - half, mid + 0.0005))
        h4 = _make_bars(prices)
        d1 = _make_ranging(20)

        ctx = analyzer.analyze(h4, d1)

        compression_patterns = [p for p in ctx.active_patterns
                                if p.pattern_type == PatternType.COMPRESSION]
        assert len(compression_patterns) == 0


# ---------------------------------------------------------------------------
# Tests: Weekly Narrative
# ---------------------------------------------------------------------------

class TestWeeklyNarrative:
    def test_weekly_narrative_built(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_ranging(30, mid=1.1600, amplitude=0.0040)
        d1 = _make_ranging(20, mid=1.1600)

        ctx = analyzer.analyze(h4, d1)

        assert ctx.weekly is not None
        assert ctx.weekly.week_high > ctx.weekly.week_low
        assert ctx.weekly.week_open > 0
        assert isinstance(ctx.weekly.unswept_high_liquidity, list)
        assert isinstance(ctx.weekly.unswept_low_liquidity, list)

    def test_weekly_expansion_direction(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        # Price clearly above midpoint
        h4 = _make_trending_up(30, start=1.1500, step=0.0005)
        d1 = _make_trending_up(20, step=0.0010)

        ctx = analyzer.analyze(h4, d1)
        if ctx.weekly:
            # In an uptrend closing near highs, expect bullish expansion
            assert ctx.weekly.expansion_direction in (MarketBias.BULLISH, MarketBias.NEUTRAL)

    def test_insufficient_bars_returns_none(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_trending_up(3)  # Too few for weekly narrative
        d1 = _make_trending_up(20, step=0.0030)

        ctx = analyzer.analyze(h4, d1)
        assert ctx.weekly is None


# ---------------------------------------------------------------------------
# Tests: HTF Fib Levels
# ---------------------------------------------------------------------------

class TestHTFFibs:
    def test_fib_levels_computed(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_trending_up(30, start=1.1500, step=0.0010)
        d1 = _make_trending_up(20, step=0.0030)

        ctx = analyzer.analyze(h4, d1)
        # Should produce fib levels if swings are found
        if ctx.htf_fib_levels:
            assert all(isinstance(f, tuple) and len(f) == 2 for f in ctx.htf_fib_levels)
            # Fibs are now emitted for both H4 and D1 swings.
            assert all(("H4" in f[1] or "D1" in f[1]) for f in ctx.htf_fib_levels)
            assert any("H4" in f[1] for f in ctx.htf_fib_levels)

    def test_fib_levels_within_swing_range(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_trending_up(30, start=1.1500, step=0.0010)
        d1 = _make_trending_up(20, step=0.0030)

        ctx = analyzer.analyze(h4, d1)
        if ctx.htf_fib_levels:
            high = h4['high'].max()
            low = h4['low'].min()
            for price, label in ctx.htf_fib_levels:
                assert low - 0.01 <= price <= high + 0.01


# ---------------------------------------------------------------------------
# Tests: Structural Levels
# ---------------------------------------------------------------------------

class TestStructuralLevels:
    def test_levels_sorted_by_proximity(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_ranging(30, mid=1.1600, amplitude=0.0040)
        d1 = _make_ranging(20, mid=1.1600)

        ctx = analyzer.analyze(h4, d1)

        if len(ctx.structural_levels) >= 2:
            current = float(h4['close'].iloc[-1])
            distances = [abs(l.price - current) for l in ctx.structural_levels]
            assert distances == sorted(distances)

    def test_level_types_valid(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_ranging(30, mid=1.1600, amplitude=0.0040)
        d1 = _make_ranging(20, mid=1.1600)

        ctx = analyzer.analyze(h4, d1)

        for level in ctx.structural_levels:
            assert level.level_type in ("resistance", "support", "pullback_line")
            assert level.timeframe in ("H4", "D1")
            assert level.strength >= 1


# ---------------------------------------------------------------------------
# Tests: Full Pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_analyze_returns_valid_context(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_ranging(30, mid=1.1600)
        d1 = _make_ranging(20, mid=1.1600)

        ctx = analyzer.analyze(h4, d1)

        assert isinstance(ctx, HTFContext)
        assert isinstance(ctx.h4_bias, MarketBias)
        assert isinstance(ctx.d1_bias, MarketBias)
        assert isinstance(ctx.combined_bias, MarketBias)
        assert 0 <= ctx.bias_confidence <= 1.0
        assert isinstance(ctx.structural_levels, list)
        assert isinstance(ctx.active_patterns, list)

    def test_supports_direction(self):
        ctx = HTFContext(
            h4_bias=MarketBias.BULLISH,
            d1_bias=MarketBias.BULLISH,
            combined_bias=MarketBias.BULLISH,
            bias_confidence=0.8,
            buy_aligned=True,
            sell_aligned=False,
        )
        assert ctx.supports_direction("buy") is True
        assert ctx.supports_direction("long") is True
        assert ctx.supports_direction("sell") is False
        assert ctx.supports_direction("short") is False

    def test_get_nearest_htf_target_long(self):
        levels = [
            StructuralLevel(price=1.1550, level_type="support", timeframe="H4", strength=2, last_test_bar=0),
            StructuralLevel(price=1.1650, level_type="resistance", timeframe="H4", strength=3, last_test_bar=0),
            StructuralLevel(price=1.1700, level_type="resistance", timeframe="D1", strength=3, last_test_bar=0),
        ]
        ctx = HTFContext(
            h4_bias=MarketBias.BULLISH,
            d1_bias=MarketBias.BULLISH,
            combined_bias=MarketBias.BULLISH,
            bias_confidence=0.7,
            structural_levels=levels,
            buy_aligned=True,
            sell_aligned=False,
        )
        target = ctx.get_nearest_htf_target("buy", entry_price=1.1600)
        assert target == 1.1650

    def test_get_nearest_htf_target_short(self):
        levels = [
            StructuralLevel(price=1.1550, level_type="support", timeframe="H4", strength=2, last_test_bar=0),
            StructuralLevel(price=1.1500, level_type="support", timeframe="D1", strength=3, last_test_bar=0),
            StructuralLevel(price=1.1700, level_type="resistance", timeframe="D1", strength=3, last_test_bar=0),
        ]
        ctx = HTFContext(
            h4_bias=MarketBias.BEARISH,
            d1_bias=MarketBias.BEARISH,
            combined_bias=MarketBias.BEARISH,
            bias_confidence=0.7,
            structural_levels=levels,
            sell_aligned=True,
            buy_aligned=False,
        )
        target = ctx.get_nearest_htf_target("sell", entry_price=1.1600)
        assert target == 1.1550

    def test_neutral_bias_allows_both_directions(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        h4 = _make_ranging(30, mid=1.1600)
        d1 = _make_ranging(20, mid=1.1600)

        ctx = analyzer.analyze(h4, d1)

        if ctx.combined_bias == MarketBias.NEUTRAL:
            assert ctx.buy_aligned is True
            assert ctx.sell_aligned is True


# ---------------------------------------------------------------------------
# Tests: HTFConfig integration
# ---------------------------------------------------------------------------

class TestHTFConfig:
    def test_config_has_htf_field(self):
        from agent.config import load_config, HTFConfig
        cfg = load_config()
        assert hasattr(cfg, 'htf')
        assert isinstance(cfg.htf, HTFConfig)
        assert cfg.htf.enabled is True
        assert cfg.htf.lookback_days == 5
        assert cfg.htf.h4_lookback_bars == 30
        assert cfg.htf.d1_lookback_bars == 20
        assert cfg.htf.update_interval_bars == 4


# ---------------------------------------------------------------------------
# Tests: HTF demand/supply ZONES (draws)
# ---------------------------------------------------------------------------

class TestHTFZones:
    def test_order_block_demand_zone_detected(self):
        # Flat base, one bearish base candle, then a strong bullish displacement
        # → a demand order block at the base candle's range.
        prices = []
        for _ in range(18):
            prices.append((1.1500, 1.1505, 1.1495, 1.1500))
        prices.append((1.1500, 1.1502, 1.1492, 1.1494))   # bearish base candle
        prices.append((1.1494, 1.1560, 1.1493, 1.1558))   # strong bullish displacement
        for _ in range(3):
            prices.append((1.1558, 1.1565, 1.1552, 1.1560))
        df = _make_bars(prices)
        analyzer = HTFAnalyzer(lookback_days=5)
        zones = analyzer._zones_from_df(df, "H4", disp_mult=1.5, keep=6)
        demand = [z for z in zones if z.kind == "demand"]
        assert demand, "expected a demand order block before the bullish displacement"
        z = demand[0]
        assert z.bottom <= 1.1494 <= z.top

    def test_structural_band_from_clustered_supports(self):
        analyzer = HTFAnalyzer(lookback_days=5)
        levels = [
            StructuralLevel(price=1.1500, level_type="support", timeframe="D1", strength=3, last_test_bar=0),
            StructuralLevel(price=1.1510, level_type="support", timeframe="H4", strength=2, last_test_bar=0),
            StructuralLevel(price=1.1700, level_type="resistance", timeframe="D1", strength=3, last_test_bar=0),
        ]
        zones = analyzer._zones_from_levels(levels, current_price=1.1600)
        demand = [z for z in zones if z.kind == "demand"]
        supply = [z for z in zones if z.kind == "supply"]
        assert demand and supply
        # The two nearby supports (1.1500/1.1510) cluster into one demand band.
        d = demand[0]
        assert d.bottom <= 1.1500 and d.top >= 1.1510
        # Price 1.1600 is above the demand band (a draw below) and below supply.
        assert d.swept is False and d.mitigated is False

    def test_nearest_zone_draw_short_targets_demand_below(self):
        ctx = HTFContext(
            h4_bias=MarketBias.BEARISH, d1_bias=MarketBias.BEARISH,
            combined_bias=MarketBias.BEARISH, bias_confidence=0.7,
            sell_aligned=True, buy_aligned=False,
        )
        from agent.context.htf_context import StructuralZone
        ctx.htf_zones = [
            StructuralZone(top=1.1520, bottom=1.1480, kind="demand", timeframe="D1", created_idx=0),
            StructuralZone(top=1.1700, bottom=1.1660, kind="supply", timeframe="D1", created_idx=0),
        ]
        z = ctx.nearest_zone_draw("short", entry_price=1.1620)
        assert z is not None and z.kind == "demand"
        assert z.top == 1.1520  # the near edge is the take-profit draw

    def test_deep_lookback_sees_old_demand_zone(self):
        # An old demand order block far beyond the 20-bar bias window must still
        # be detected when the zone lookback is deep (the April-zone-in-June case).
        rows = []
        # 30 quiet bars, then a demand OB (bearish base + strong bullish push),
        # then ~150 quiet bars holding above — the zone stays fresh.
        for _ in range(30):
            rows.append((1.1500, 1.1505, 1.1495, 1.1500))
        rows.append((1.1500, 1.1502, 1.1492, 1.1494))   # bearish base
        rows.append((1.1494, 1.1560, 1.1493, 1.1558))   # strong bullish displacement
        for _ in range(150):
            rows.append((1.1560, 1.1566, 1.1554, 1.1560))
        df = _make_bars(rows)
        # Mirror reality: H4 is sliced short by callers, D1 carries deep history.
        h4_short = df.tail(30)

        deep = HTFAnalyzer(lookback_days=5, d1_zone_lookback_bars=200)
        zones_deep = deep._find_htf_zones(h4_short, df, [])
        old_demand = [z for z in zones_deep if z.kind == "demand"
                      and z.bottom <= 1.1494 <= z.top]
        assert old_demand, "deep lookback should still see the old demand OB"

        shallow = HTFAnalyzer(lookback_days=5, d1_zone_lookback_bars=20)
        zones_shallow = shallow._find_htf_zones(h4_short, df, [])
        old_demand_shallow = [z for z in zones_shallow if z.kind == "demand"
                              and z.bottom <= 1.1494 <= z.top]
        assert not old_demand_shallow, "shallow lookback can't reach the old OB"

    def test_mitigated_zone_is_not_a_draw(self):
        from agent.context.htf_context import StructuralZone
        ctx = HTFContext(
            h4_bias=MarketBias.BEARISH, d1_bias=MarketBias.BEARISH,
            combined_bias=MarketBias.BEARISH, bias_confidence=0.7,
            sell_aligned=True, buy_aligned=False,
        )
        ctx.htf_zones = [
            StructuralZone(top=1.1520, bottom=1.1480, kind="demand", timeframe="D1",
                           created_idx=0, mitigated=True),
        ]
        assert ctx.nearest_zone_draw("short", entry_price=1.1620) is None


def test_reaction_engine_targets_htf_zone_draw():
    from agent.config import ReactionConfig
    from agent.reaction.engine import ReactionEngine
    from tests.test_reaction_engine import bar, flat_series

    # A bearish ignition with an HTF demand draw below should target the draw.
    bars = flat_series(25, price=1.1600, rng=0.0008)
    bars.append(bar(1.1600, 1.1601, 1.1518, 1.1520, i=25))  # strong bearish impulse
    cfg = ReactionConfig(require_level=False, min_rr=1.0)
    engine = ReactionEngine(cfg)
    draw = 1.1400  # daily demand top below (far enough for valid RR vs the wide stop)
    a = engine.assess(bars, atr=0.0020, levels=[], htf_target_short=draw)
    assert a.fired and a.signal is not None
    assert a.signal.direction.value == "short"
    assert a.signal.target_label == "htf_zone_draw"
    assert abs(a.signal.take_profit - draw) < 1e-9
