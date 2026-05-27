"""Tests for the upgraded quality-graded Fibonacci detector.

Covers: impulse quality scoring, OTE zone detection, level weighting,
fib invalidation, quality thresholds, confluence-only behaviour, and FVG bonus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from agent.detectors.fib import (
    auto_fib,
    build_fib_zone,
    compute_impulse_quality,
    compute_level_weight,
    detect_graded_fibs,
    fib_confluence_tags,
    invalidate_fib_level,
    invalidate_fibs,
)
from agent.strategy.strategies.fib_retracement import FibRetracement
from agent.types import Bar, Direction, FibLevel, FibZone, GradedFibLevel, Timeframe, Zone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(t, o, h, l, c):
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=100, timeframe=Timeframe.H1)


def _make_impulse_bars(
    start_price: float = 1.1000,
    end_price: float = 1.1060,
    body_pct: float = 0.80,
    start_time: datetime | None = None,
    pullback_bars: int = 7,
) -> list[Bar]:
    """Build a bar series with a clear swing low → impulse → swing high structure.

    The swing detector (lookback=5) needs fractal patterns, so we create:
      1. 6 bars dipping DOWN to form a swing low at index ~6
      2. 4 impulse bars shooting UP to *end_price*
      3. *pullback_bars* bars pulling back slightly to confirm the swing high

    ``body_pct`` controls candle body / range ratio in the impulse.
    """
    t = start_time or datetime(2024, 6, 1)
    bars: list[Bar] = []
    dip = start_price - 0.0010
    hi = 0

    # Phase 1: drift down to create a swing low
    for i in range(7):
        p = start_price - (i * 0.00015)
        bars.append(_bar(t + timedelta(hours=hi), p + 0.0002, p + 0.0005, p - 0.0002, p))
        hi += 1
    low_price = bars[-1].close

    # Phase 2: impulse up from low to end_price in 4 bars
    impulse_n = 4
    step = (end_price - low_price) / impulse_n
    for i in range(impulse_n):
        o = low_price + step * i
        c = o + step
        rng = abs(step) / max(body_pct, 0.01)
        wick = (rng - abs(step)) / 2
        h = max(o, c) + wick
        l = min(o, c) - wick
        bars.append(_bar(t + timedelta(hours=hi), o, h, l, c))
        hi += 1

    # Phase 3: mild pullback to confirm the swing high
    peak = bars[-1].close
    for i in range(1, pullback_bars + 1):
        p = peak - i * 0.00015
        bars.append(_bar(t + timedelta(hours=hi), p + 0.0002, p + 0.0004, p - 0.0002, p))
        hi += 1

    return bars


@dataclass
class FakeCtx:
    """Minimal context object for strategy tests."""
    bars: list[Bar] = field(default_factory=list)
    fib_by_index: dict = field(default_factory=dict)
    atr_by_index: dict = field(default_factory=dict)
    zones: list = field(default_factory=list)
    fvgs: list = field(default_factory=list)
    bos_list: list = field(default_factory=list)
    liquidity_sweeps: list = field(default_factory=list)


# ====================================================================
# 1. Impulse quality scoring
# ====================================================================

class TestImpulseQuality:
    def test_fast_large_move_high_quality(self):
        """A 60-pip move in 4 bars with big bodies = high quality."""
        bars = _make_impulse_bars(start_price=1.1000, end_price=1.1060, body_pct=0.80)
        # Impulse occupies bars 7..10 (4 bars)
        quality, disp, body, fvg = compute_impulse_quality(bars, 7, 10)
        assert disp >= 40, f"Expected >=40 pips displacement, got {disp}"
        assert quality >= 55, f"Expected >=55, got {quality}"

    def test_slow_drift_low_quality(self):
        """A 5-pip drift over 20 bars with wicky candles = low quality."""
        t = datetime(2024, 6, 1)
        bars = []
        for i in range(25):
            p = 1.1000 + (i * 0.000025)
            bars.append(_bar(t + timedelta(hours=i), p, p + 0.0008, p - 0.0008, p))
        quality, disp, body, fvg = compute_impulse_quality(bars, 2, 22)
        assert disp < 10
        assert quality < 35, f"Expected <35, got {quality}"

    def test_medium_impulse(self):
        """A 25-pip move in 5 bars = moderate quality."""
        t = datetime(2024, 6, 1)
        bars = []
        for i in range(6):
            p = 1.1000
            bars.append(_bar(t + timedelta(hours=i), p, p + 0.0003, p - 0.0003, p))
        for i in range(5):
            o = 1.1000 + i * 0.0005
            c = o + 0.0005
            bars.append(_bar(t + timedelta(hours=6 + i), o, c + 0.0002, o - 0.0002, c))
        quality, disp, body, fvg = compute_impulse_quality(bars, 5, 10)
        assert 20 <= disp <= 35
        assert quality >= 30, f"Expected >=30, got {quality}"

    def test_quality_bounded_0_100(self):
        """Quality score is always clamped to [0, 100]."""
        t = datetime(2024, 6, 1)
        bars = []
        for i in range(3):
            p = 1.1000
            bars.append(_bar(t + timedelta(hours=i), p, p + 0.0003, p - 0.0003, p))
        for i in range(3):
            o = 1.1000 + i * 0.0070
            c = o + 0.0070
            bars.append(_bar(t + timedelta(hours=3 + i), o, c + 0.0002, o - 0.0002, c))
        quality, _, _, _ = compute_impulse_quality(bars, 2, 5)
        assert 0 <= quality <= 100


# ====================================================================
# 2. OTE zone detection
# ====================================================================

class TestOTEZone:
    def test_price_in_ote(self):
        """Bar at the 61.8-71% retracement → is_in_ote True."""
        bars = _make_impulse_bars(start_price=1.1000, end_price=1.1060, body_pct=0.75)
        graded = detect_graded_fibs(bars, min_impulse_quality=0, min_impulse_pips=0)
        ote_levels = [g for g in graded if g.is_in_ote]
        assert len(ote_levels) >= 1
        for g in ote_levels:
            assert 0.618 <= g.level_pct <= 0.710

    def test_382_not_in_ote(self):
        """38.2% level should NOT be in the OTE zone."""
        bars = _make_impulse_bars(start_price=1.1000, end_price=1.1060, body_pct=0.75)
        graded = detect_graded_fibs(bars, min_impulse_quality=0, min_impulse_pips=0)
        level_382 = [g for g in graded if abs(g.level_pct - 0.382) < 0.01]
        assert len(level_382) == 1
        assert not level_382[0].is_in_ote

    def test_fib_zone_built_from_quality_fib(self):
        """build_fib_zone extracts OTE band from a FibLevel with 618/705 levels."""
        bars = _make_impulse_bars(start_price=1.1000, end_price=1.1060, body_pct=0.75)
        fib = auto_fib(bars, levels=(0.382, 0.500, 0.618, 0.705))
        assert fib is not None
        zone = build_fib_zone(fib)
        assert zone is not None
        assert zone.direction in (Direction.LONG, Direction.SHORT)
        if fib.direction == Direction.LONG:
            assert zone.ote_top > zone.ote_bottom


# ====================================================================
# 3. Level weighting (OTE > 50% > 38.2% >> 78.6%)
# ====================================================================

class TestLevelWeighting:
    def test_ote_highest_weight(self):
        w_ote = compute_level_weight(0.618, 80)
        w_50 = compute_level_weight(0.500, 80)
        w_382 = compute_level_weight(0.382, 80)
        w_786 = compute_level_weight(0.786, 80)
        assert w_ote > w_50 > w_382 > w_786

    def test_786_near_zero_weight(self):
        w = compute_level_weight(0.786, 50)
        assert w < 0.15

    def test_quality_scales_weight(self):
        """Higher impulse quality → higher weight for the same level."""
        w_high = compute_level_weight(0.618, 90)
        w_low = compute_level_weight(0.618, 20)
        assert w_high > w_low

    def test_ote_range_all_high(self):
        """Every level in [0.618, 0.710] gets base=1.0."""
        for lvl in (0.618, 0.650, 0.700, 0.705, 0.710):
            w = compute_level_weight(lvl, 70)
            assert w > 0.6, f"Level {lvl} weight {w} unexpectedly low"


# ====================================================================
# 4. Fib invalidation (price past 78.6%)
# ====================================================================

class TestFibInvalidation:
    def test_bullish_fib_invalidated_by_deep_retrace(self):
        """If price drops below 78.6% of a bullish impulse → invalidated."""
        t = datetime(2024, 6, 1)
        fib = FibLevel(
            impulse_start=1.1000,
            impulse_end=1.1060,
            direction=Direction.LONG,
            levels={0.618: 1.1023, 0.786: 1.1013},
            created_at=t,
            impulse_quality=70,
        )
        deep_bar = _bar(t + timedelta(hours=1), 1.1010, 1.1015, 1.0995, 1.1000)
        result = invalidate_fib_level(fib, [deep_bar], 0)
        assert not result.is_active

    def test_bullish_fib_stays_active_above_786(self):
        """Price still above 78.6% → fib remains active."""
        t = datetime(2024, 6, 1)
        fib = FibLevel(
            impulse_start=1.1000,
            impulse_end=1.1060,
            direction=Direction.LONG,
            levels={0.618: 1.1023},
            created_at=t,
            impulse_quality=70,
        )
        bar = _bar(t + timedelta(hours=1), 1.1020, 1.1025, 1.1015, 1.1020)
        result = invalidate_fib_level(fib, [bar], 0)
        assert result.is_active

    def test_graded_fib_invalidation(self):
        """invalidate_fibs removes graded levels when price blows through."""
        t = datetime(2024, 6, 1)
        g = GradedFibLevel(
            level_pct=0.618, price=1.1023, direction=Direction.LONG,
            swing_start=1.1000, swing_end=1.1060, bar_index=10,
            impulse_quality=70,
        )
        deep_bar = _bar(t, 1.0990, 1.1000, 1.0985, 1.0990)
        remaining = invalidate_fibs([g], [deep_bar], 0)
        assert len(remaining) == 0


# ====================================================================
# 5. High quality impulse → fibs worth drawing
# ====================================================================

class TestFibsWorthDrawing:
    def test_quality_impulse_produces_fibs(self):
        """A strong impulse above thresholds returns graded fib levels."""
        bars = _make_impulse_bars(start_price=1.1000, end_price=1.1060, body_pct=0.80)
        graded = detect_graded_fibs(
            bars, min_impulse_quality=35, min_impulse_pips=20,
        )
        assert len(graded) > 0
        assert all(g.impulse_quality >= 35 for g in graded)

    def test_auto_fib_quality_fields_populated(self):
        """Legacy auto_fib now populates quality fields on FibLevel."""
        bars = _make_impulse_bars(start_price=1.1000, end_price=1.1060, body_pct=0.80)
        fib = auto_fib(bars)
        assert fib is not None
        assert fib.impulse_quality > 0
        assert fib.impulse_displacement_pips > 0
        assert len(fib.level_weights) > 0


# ====================================================================
# 6. Low quality impulse → fibs NOT drawn
# ====================================================================

class TestLowQualityFiltered:
    def test_tiny_drift_filtered_out(self):
        """A 5-pip drift → no fibs (below min thresholds)."""
        bars = _make_impulse_bars(start_price=1.1000, end_price=1.1005, body_pct=0.30)
        graded = detect_graded_fibs(
            bars, min_impulse_quality=35, min_impulse_pips=20,
        )
        assert len(graded) == 0

    def test_auto_fib_respects_quality_threshold(self):
        """auto_fib with min_impulse_quality returns None for weak impulses."""
        bars = _make_impulse_bars(start_price=1.1000, end_price=1.1005, body_pct=0.30)
        fib = auto_fib(bars, min_impulse_quality=35, min_impulse_pips=20)
        assert fib is None


# ====================================================================
# 7. Fib as confluence only (no standalone entry)
# ====================================================================

class TestConfluenceOnly:
    def test_fib_alone_returns_none(self):
        """FibRetracement strategy returns None when no other strategy fires."""
        bars = _make_impulse_bars(start_price=1.1000, end_price=1.1060, body_pct=0.80)
        fib = auto_fib(bars, levels=(0.382, 0.500, 0.618, 0.705))
        assert fib is not None

        retrace_price = fib.levels[0.500]
        retrace_bar = _bar(
            datetime(2024, 6, 2), retrace_price, retrace_price + 0.0005,
            retrace_price - 0.0005, retrace_price,
        )
        all_bars = bars + [retrace_bar]
        idx = len(all_bars) - 1

        ctx = FakeCtx(
            bars=all_bars,
            fib_by_index={0: fib},
            atr_by_index={idx: 0.003},
        )
        strat = FibRetracement()
        result = strat.evaluate(ctx, idx)
        assert result is None, "Fib alone should NOT produce a setup"

    def test_fib_with_zone_returns_setup(self):
        """FibRetracement fires when a zone also covers the price."""
        bars = _make_impulse_bars(start_price=1.1000, end_price=1.1060, body_pct=0.80)
        fib = auto_fib(bars, levels=(0.382, 0.500, 0.618, 0.705))
        assert fib is not None

        retrace_price = fib.levels[0.500]
        retrace_bar = _bar(
            datetime(2024, 6, 2), retrace_price, retrace_price + 0.0005,
            retrace_price - 0.0005, retrace_price,
        )
        all_bars = bars + [retrace_bar]
        idx = len(all_bars) - 1

        zone = Zone(
            direction=Direction.LONG,
            top=retrace_price + 0.0010,
            bottom=retrace_price - 0.0010,
            created_at=datetime(2024, 5, 30),
            created_bar_index=0,
            impulse_pips=40,
        )
        ctx = FakeCtx(
            bars=all_bars,
            fib_by_index={0: fib},
            atr_by_index={idx: 0.003},
            zones=[zone],
        )
        strat = FibRetracement()
        result = strat.evaluate(ctx, idx)
        assert result is not None, "Fib + zone should produce a setup"
        assert any("fib_" in c for c in result.confluences)


# ====================================================================
# 8. FVG left behind by impulse → bonus quality points
# ====================================================================

class TestFVGBonus:
    def test_impulse_with_fvg_gets_bonus(self):
        """An impulse that leaves an FVG gap scores higher."""
        t = datetime(2024, 6, 1)
        # Build bars with a clear bullish FVG: bar[2].low > bar[0].high
        bars_no_fvg = [
            _bar(t, 1.1000, 1.1010, 1.0990, 1.1005),
            _bar(t + timedelta(hours=1), 1.1005, 1.1015, 1.0995, 1.1010),
            _bar(t + timedelta(hours=2), 1.1010, 1.1020, 1.1005, 1.1015),
            _bar(t + timedelta(hours=3), 1.1015, 1.1025, 1.1010, 1.1020),
            _bar(t + timedelta(hours=4), 1.1020, 1.1030, 1.1015, 1.1025),
        ]
        q_no, _, _, fvg_no = compute_impulse_quality(bars_no_fvg, 0, 4)

        bars_with_fvg = [
            _bar(t, 1.1000, 1.1010, 1.0990, 1.1005),
            _bar(t + timedelta(hours=1), 1.1005, 1.1060, 1.1000, 1.1055),
            _bar(t + timedelta(hours=2), 1.1055, 1.1070, 1.1040, 1.1065),
            _bar(t + timedelta(hours=3), 1.1065, 1.1075, 1.1055, 1.1070),
            _bar(t + timedelta(hours=4), 1.1070, 1.1080, 1.1060, 1.1075),
        ]
        q_with, _, _, fvg_yes = compute_impulse_quality(bars_with_fvg, 0, 4)

        assert fvg_yes is True
        assert q_with > q_no, "Impulse with FVG should score higher"


# ====================================================================
# 9. Confluence tags generation
# ====================================================================

class TestConfluenceTags:
    def test_ote_tag_generated(self):
        """Bar touching the 61.8% level → 'fib_ote' tag."""
        fib = FibLevel(
            impulse_start=1.1000, impulse_end=1.1060, direction=Direction.LONG,
            levels={0.618: 1.1023, 0.500: 1.1030}, created_at=datetime(2024, 6, 1),
            impulse_quality=70,
        )
        bar = _bar(datetime(2024, 6, 2), 1.1022, 1.1025, 1.1020, 1.1023)
        tags = fib_confluence_tags(fib, bar, tol=0.0005)
        assert "fib_ote" in tags

    def test_high_quality_tag(self):
        """Impulse quality >= 60 → 'fib_high_quality' tag."""
        fib = FibLevel(
            impulse_start=1.1000, impulse_end=1.1060, direction=Direction.LONG,
            levels={0.618: 1.1023}, created_at=datetime(2024, 6, 1),
            impulse_quality=70,
        )
        bar = _bar(datetime(2024, 6, 2), 1.1022, 1.1025, 1.1020, 1.1023)
        tags = fib_confluence_tags(fib, bar, tol=0.0005)
        assert "fib_high_quality" in tags

    def test_low_quality_tag(self):
        """Impulse quality < 40 → 'fib_low_quality' tag."""
        fib = FibLevel(
            impulse_start=1.1000, impulse_end=1.1060, direction=Direction.LONG,
            levels={0.618: 1.1023}, created_at=datetime(2024, 6, 1),
            impulse_quality=30,
        )
        bar = _bar(datetime(2024, 6, 2), 1.1022, 1.1025, 1.1020, 1.1023)
        tags = fib_confluence_tags(fib, bar, tol=0.0005)
        assert "fib_low_quality" in tags

    def test_inactive_fib_no_tags(self):
        """Invalidated fib produces no tags."""
        fib = FibLevel(
            impulse_start=1.1000, impulse_end=1.1060, direction=Direction.LONG,
            levels={0.618: 1.1023}, created_at=datetime(2024, 6, 1),
            impulse_quality=70, is_active=False,
        )
        bar = _bar(datetime(2024, 6, 2), 1.1022, 1.1025, 1.1020, 1.1023)
        tags = fib_confluence_tags(fib, bar, tol=0.0005)
        assert len(tags) == 0


# ====================================================================
# 10. FibConfig integration
# ====================================================================

class TestFibConfig:
    def test_fib_config_defaults(self):
        from agent.config import FibConfig
        cfg = FibConfig()
        assert 0.618 in cfg.active_levels
        assert 0.705 in cfg.active_levels
        assert cfg.min_impulse_quality == 35.0
        assert cfg.min_impulse_pips == 20.0
        assert cfg.include_786_as_invalidation is True

    def test_fib_config_in_detectors(self):
        from agent.config import Config
        c = Config()
        assert hasattr(c.detectors, "fib")
        assert c.detectors.fib.ote_zone_start == 0.618
        assert c.detectors.fib.ote_zone_end == 0.710
