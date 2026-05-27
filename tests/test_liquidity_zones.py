"""Tests for the two-phase liquidity zone (LZI) detector and PD Array targeting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.detectors.liquidity_zones import (
    LiquidityEntry,
    LiquidityZone,
    check_retest_entries,
    detect_liquidity_zones,
)
from agent.detectors.pd_array import (
    PDArrayTarget,
    collect_opposite_liquidity_levels,
    find_draw_on_liquidity,
)
from agent.types import Bar, Direction, Timeframe

BASE = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
PIP = 0.0001


def _bar(i: int, o: float, h: float, l: float, c: float, tf=Timeframe.H1) -> Bar:
    return Bar(
        time=BASE + timedelta(hours=i),
        open=o, high=h, low=l, close=c,
        volume=100.0, timeframe=tf,
    )


def _flat_bars(n: int, price: float = 1.1000, tf=Timeframe.H1) -> list[Bar]:
    """Generate n flat bars at a stable price (for warm-up / padding)."""
    bars = []
    for i in range(n):
        bars.append(_bar(i, price, price + 5 * PIP, price - 5 * PIP, price, tf))
    return bars


# ============================================================================
# Phase 1: LZI creation
# ============================================================================

class TestLZICreation:
    """Tests for detect_liquidity_zones (Phase 1)."""

    def _build_sweep_scenario(self, side: str) -> list[Bar]:
        """Build a bar series with a clear sweep of a swing high or low.

        For buyside: builds a run-up creating a swing high, then a bar that
        sweeps above it and closes back below (failed breakout above highs).

        For sellside: builds a run-down creating a swing low, then a bar that
        sweeps below it and closes back above (failed breakout below lows).
        """
        bars = _flat_bars(20)  # warm-up

        if side == "buyside":
            # Build a swing high at 1.1100 around bar 25
            for i in range(20, 23):
                bars.append(_bar(i, 1.1050, 1.1060, 1.1040, 1.1050))
            bars.append(_bar(23, 1.1070, 1.1100, 1.1060, 1.1080))  # swing high at 1.1100
            bars.append(_bar(24, 1.1080, 1.1100, 1.1070, 1.1080))
            for i in range(25, 28):
                bars.append(_bar(i, 1.1070, 1.1080, 1.1050, 1.1060))
            # Gap down to confirm swing high
            for i in range(28, 33):
                bars.append(_bar(i, 1.1040, 1.1050, 1.1030, 1.1040))
            # Sweep bar: wicks above the swing high (1.1100) but closes back below
            bars.append(_bar(33, 1.1060, 1.1120, 1.1050, 1.1060))
        else:
            # Build a swing low at 1.0900 around bar 25
            for i in range(20, 23):
                bars.append(_bar(i, 1.0950, 1.0960, 1.0940, 1.0950))
            bars.append(_bar(23, 1.0930, 1.0940, 1.0900, 1.0920))  # swing low at 1.0900
            bars.append(_bar(24, 1.0920, 1.0930, 1.0900, 1.0920))
            for i in range(25, 28):
                bars.append(_bar(i, 1.0930, 1.0950, 1.0920, 1.0940))
            # Gap up to confirm swing low
            for i in range(28, 33):
                bars.append(_bar(i, 1.0960, 1.0970, 1.0950, 1.0960))
            # Sweep bar: wicks below the swing low (1.0900) but closes back above
            bars.append(_bar(33, 1.0940, 1.0950, 1.0880, 1.0940))

        return bars

    def test_buyside_sweep_creates_lzi(self):
        bars = self._build_sweep_scenario("buyside")
        zones = detect_liquidity_zones(
            bars, swing_lookback=2, min_wick_size_pips=5.0,
        )
        buyside_zones = [z for z in zones if z.side == "buyside"]
        assert len(buyside_zones) >= 1
        z = buyside_zones[-1]
        assert z.trade_direction == Direction.SHORT
        assert z.zone_top > z.zone_bottom
        assert z.wick_size_pips >= 5.0

    def test_sellside_sweep_creates_lzi(self):
        bars = self._build_sweep_scenario("sellside")
        zones = detect_liquidity_zones(
            bars, swing_lookback=2, min_wick_size_pips=5.0,
        )
        sellside_zones = [z for z in zones if z.side == "sellside"]
        assert len(sellside_zones) >= 1
        z = sellside_zones[-1]
        assert z.trade_direction == Direction.LONG
        assert z.zone_top > z.zone_bottom
        assert z.wick_size_pips >= 5.0

    def test_small_wick_filtered_out(self):
        """Wicks below min_wick_size_pips should not create zones."""
        bars = _flat_bars(20)
        # Add bars creating a swing high at 1.1060
        for i in range(20, 25):
            bars.append(_bar(i, 1.1050, 1.1060, 1.1040, 1.1050))
        # Bar with a small upper wick: high=1.1063 close=1.1058 → wick = 0.5 pips
        bars.append(_bar(25, 1.1055, 1.1063, 1.1040, 1.1058))
        zones = detect_liquidity_zones(
            bars, swing_lookback=2, min_wick_size_pips=10.0,
        )
        recent = [z for z in zones if z.formation_bar_index == 25]
        assert len(recent) == 0

    def test_direction_correctness_sellside_long(self):
        """Sellside sweep → trade_direction must be LONG."""
        bars = self._build_sweep_scenario("sellside")
        zones = detect_liquidity_zones(bars, swing_lookback=2, min_wick_size_pips=5.0)
        for z in zones:
            if z.side == "sellside":
                assert z.trade_direction == Direction.LONG

    def test_direction_correctness_buyside_short(self):
        """Buyside sweep → trade_direction must be SHORT."""
        bars = self._build_sweep_scenario("buyside")
        zones = detect_liquidity_zones(bars, swing_lookback=2, min_wick_size_pips=5.0)
        for z in zones:
            if z.side == "buyside":
                assert z.trade_direction == Direction.SHORT


# ============================================================================
# Phase 2: Retest → Consumption → Displacement
# ============================================================================

class TestRetestEntries:
    """Tests for check_retest_entries (Phase 2)."""

    def _make_zone(self, **overrides) -> LiquidityZone:
        defaults = dict(
            side="sellside",
            trade_direction=Direction.LONG,
            swept_label="PDL",
            swept_price=1.0900,
            zone_top=1.0920,
            zone_bottom=1.0880,
            formation_bar_index=10,
            formation_time=BASE + timedelta(hours=10),
            wick_size_pips=40.0,
            status="waiting",
        )
        defaults.update(overrides)
        return LiquidityZone(**defaults)

    def test_retest_detected(self):
        """Price returning to the zone should transition status to retesting."""
        zone = self._make_zone()
        bars = _flat_bars(15, price=1.0960)
        # Bar 15 touches the zone
        bars.append(_bar(15, 1.0930, 1.0935, 1.0910, 1.0920))

        check_retest_entries(
            bars, [zone], at_index=15,
            retest_proximity_pips=5.0,
            consumption_min_bars=2,
        )
        assert zone.status == "retesting"
        assert zone.retest_bar_index == 15

    def test_consumption_counted(self):
        """Bars spending time inside the zone should increment consumption_bars."""
        zone = self._make_zone(status="retesting", retest_bar_index=14, consumption_bars=1)
        bars = _flat_bars(15, price=1.0960)
        # Bar 15 is inside the zone
        bars.append(_bar(15, 1.0910, 1.0925, 1.0900, 1.0915))

        check_retest_entries(
            bars, [zone], at_index=15,
            retest_proximity_pips=5.0,
            consumption_min_bars=3,
        )
        assert zone.consumption_bars == 2

    def test_displacement_generates_entry(self):
        """A strong candle closing away from consumed zone should trigger entry."""
        zone = self._make_zone(
            status="consumed",
            retest_bar_index=13,
            consumption_bars=3,
        )
        bars = _flat_bars(15, price=1.0960)
        # Bar 15: strong bullish candle displacing above zone
        # Body = 20 pips, range = 25 pips -> body_pct = 80% > 60%
        bars.append(_bar(15, 1.0920, 1.0950, 1.0918, 1.0940))

        entries = check_retest_entries(
            bars, [zone], at_index=15,
            displacement_min_body_pct=0.60,
            displacement_min_pips=8.0,
            stop_buffer_pips=3.0,
        )
        assert len(entries) == 1
        e = entries[0]
        assert e.direction == Direction.LONG
        assert e.entry_price == 1.0940
        assert e.stop_price < zone.zone_bottom
        assert zone.status == "triggered"

    def test_full_sequence_sweep_to_entry(self):
        """Full lifecycle: waiting → retesting → consumed → triggered."""
        zone = self._make_zone(formation_bar_index=5)
        bars = _flat_bars(10, price=1.0960)

        # Bars 10-11: price away from zone (still waiting)
        bars.append(_bar(10, 1.0960, 1.0970, 1.0950, 1.0960))
        bars.append(_bar(11, 1.0955, 1.0965, 1.0945, 1.0955))

        for i in [10, 11]:
            check_retest_entries(bars, [zone], at_index=i, consumption_min_bars=2)
        assert zone.status == "waiting"

        # Bars 12-13: price returns to zone (retest + consumption)
        bars.append(_bar(12, 1.0920, 1.0930, 1.0900, 1.0910))
        check_retest_entries(bars, [zone], at_index=12, consumption_min_bars=2)
        assert zone.status == "retesting"

        bars.append(_bar(13, 1.0910, 1.0925, 1.0895, 1.0915))
        check_retest_entries(bars, [zone], at_index=13, consumption_min_bars=2)
        assert zone.status == "consumed"

        # Bar 14: displacement candle (strong bullish)
        bars.append(_bar(14, 1.0915, 1.0960, 1.0910, 1.0955))
        entries = check_retest_entries(
            bars, [zone], at_index=14,
            consumption_min_bars=2,
            displacement_min_body_pct=0.60,
            displacement_min_pips=8.0,
        )
        assert len(entries) == 1
        assert zone.status == "triggered"
        assert entries[0].direction == Direction.LONG

    def test_zone_expiry(self):
        """Zone expires if no retest within zone_expiry_bars."""
        zone = self._make_zone(formation_bar_index=5)
        n = 120
        bars = _flat_bars(n, price=1.1050)

        check_retest_entries(
            bars, [zone], at_index=n - 1,
            zone_expiry_bars=100,
        )
        assert zone.status == "expired"

    def test_retest_max_bars_expiry(self):
        """Zone waiting status expires if no retest within retest_max_bars."""
        zone = self._make_zone(formation_bar_index=5)
        bars = _flat_bars(70, price=1.1050)

        check_retest_entries(
            bars, [zone], at_index=69,
            retest_max_bars=50,
            zone_expiry_bars=200,
        )
        assert zone.status == "expired"

    def test_already_triggered_zone_skipped(self):
        """A zone that already triggered should not generate another entry."""
        zone = self._make_zone(status="triggered")
        bars = _flat_bars(15, price=1.0910)
        bars.append(_bar(15, 1.0920, 1.0960, 1.0910, 1.0955))

        entries = check_retest_entries(bars, [zone], at_index=15)
        assert len(entries) == 0

    def test_weak_candle_no_displacement(self):
        """A doji or small-body candle should NOT trigger displacement."""
        zone = self._make_zone(
            status="consumed",
            retest_bar_index=13,
            consumption_bars=3,
        )
        bars = _flat_bars(15, price=1.0960)
        # Doji: body < 60% of range
        bars.append(_bar(15, 1.0915, 1.0930, 1.0900, 1.0916))

        entries = check_retest_entries(
            bars, [zone], at_index=15,
            displacement_min_body_pct=0.60,
        )
        assert len(entries) == 0


# ============================================================================
# PD Array Targeting
# ============================================================================

class TestPDArray:
    """Tests for PD Array / draw on liquidity targeting."""

    def test_find_nearest_unswept_buyside(self):
        """LONG direction should find nearest unswept high above."""
        from agent.detectors.daily_levels import DailyLevels
        from agent.types import Swing

        bars = _flat_bars(30, price=1.1000)
        dl = DailyLevels(pdh=1.1050, pdl=1.0950, pwh=1.1100, pwl=1.0850)

        target = find_draw_on_liquidity(
            bars, at_index=29, direction=Direction.LONG,
            daily_levels=dl,
        )
        assert target is not None
        assert target.price == 1.1050  # PDH is closest above
        assert target.side == "buyside"
        assert not target.already_swept

    def test_find_nearest_unswept_sellside(self):
        """SHORT direction should find nearest unswept low below."""
        from agent.detectors.daily_levels import DailyLevels

        bars = _flat_bars(30, price=1.1000)
        dl = DailyLevels(pdh=1.1050, pdl=1.0950, pwh=1.1100, pwl=1.0850)

        target = find_draw_on_liquidity(
            bars, at_index=29, direction=Direction.SHORT,
            daily_levels=dl,
        )
        assert target is not None
        assert target.price == 1.0950  # PDL is closest below
        assert target.side == "sellside"

    def test_swept_level_excluded(self):
        """A level that price already wicked through should be excluded."""
        from agent.detectors.daily_levels import DailyLevels

        bars = _flat_bars(25, price=1.1000)
        # Bar 25 sweeps through PDH at 1.1050
        bars.append(_bar(25, 1.1040, 1.1060, 1.1030, 1.1035))
        # Bars 26-29 below
        for i in range(26, 30):
            bars.append(_bar(i, 1.1000, 1.1010, 1.0990, 1.1000))

        dl = DailyLevels(pdh=1.1050, pdl=1.0950, pwh=1.1100, pwl=1.0850)

        target = find_draw_on_liquidity(
            bars, at_index=29, direction=Direction.LONG,
            daily_levels=dl, swept_lookback_bars=10,
        )
        # PDH was swept, so next target should be PWH
        assert target is not None
        assert target.label == "PWH"
        assert target.price == 1.1100

    def test_no_target_returns_none(self):
        """If no unswept levels exist, return None."""
        bars = _flat_bars(30, price=1.5000)  # way above any reasonable levels

        target = find_draw_on_liquidity(
            bars, at_index=29, direction=Direction.LONG,
            daily_levels=None, swings=None,
        )
        assert target is None

    def test_collect_opposite_levels(self):
        """collect_opposite_liquidity_levels returns all valid targets."""
        from agent.detectors.daily_levels import DailyLevels

        bars = _flat_bars(30, price=1.1000)
        dl = DailyLevels(pdh=1.1050, pdl=1.0950, pwh=1.1100, pwl=1.0850)

        levels = collect_opposite_liquidity_levels(
            bars, at_index=29, direction=Direction.LONG,
            daily_levels=dl,
        )
        labels = [lbl for lbl, _ in levels]
        assert "PDH" in labels
        assert "PWH" in labels


# ============================================================================
# Strategy integration
# ============================================================================

class TestStrategyIntegration:
    """Test the LiquidityGrabReversal strategy with LZI context."""

    def test_strategy_returns_setup_on_triggered_entry(self):
        """Strategy should return a Setup when a zone completes the full sequence."""
        from types import SimpleNamespace
        from agent.strategy.strategies.liquidity_grab_reversal import LiquidityGrabReversal
        from agent.detectors.daily_levels import DailyLevels

        # Pre-build a consumed zone ready for displacement
        zone = LiquidityZone(
            side="sellside",
            trade_direction=Direction.LONG,
            swept_label="PDL",
            swept_price=1.0900,
            zone_top=1.0920,
            zone_bottom=1.0880,
            formation_bar_index=5,
            formation_time=BASE + timedelta(hours=5),
            wick_size_pips=40.0,
            status="consumed",
            retest_bar_index=13,
            consumption_bars=3,
        )

        bars = _flat_bars(15, price=1.0960)
        # Displacement candle
        bars.append(_bar(15, 1.0920, 1.0960, 1.0915, 1.0955))

        dl = DailyLevels(pdh=1.1050, pdl=1.0900)

        ctx = SimpleNamespace(
            bars=bars,
            liquidity_zones=[zone],
            daily_levels=[dl] * len(bars),
            swings=[],
            atr_by_index={15: 0.0030},
            liquidity_config=None,
        )

        strategy = LiquidityGrabReversal()
        setup = strategy.evaluate(ctx, at_index=15)
        assert setup is not None
        assert setup.direction == Direction.LONG
        assert setup.strategy_name == "LiquidityGrabReversal"
        assert "lzi_displacement" in setup.confluences

    def test_strategy_returns_none_when_no_zones(self):
        """Strategy should return None if there are no LZI zones."""
        from types import SimpleNamespace
        from agent.strategy.strategies.liquidity_grab_reversal import LiquidityGrabReversal

        bars = _flat_bars(20)
        ctx = SimpleNamespace(
            bars=bars,
            liquidity_zones=[],
            daily_levels=[],
            swings=[],
            atr_by_index={},
            liquidity_config=None,
        )

        strategy = LiquidityGrabReversal()
        setup = strategy.evaluate(ctx, at_index=19)
        assert setup is None


# ============================================================================
# Edge cases
# ============================================================================

class TestEdgeCases:
    """Edge cases and robustness tests."""

    def test_empty_bars(self):
        zones = detect_liquidity_zones([], min_wick_size_pips=10.0)
        assert zones == []

    def test_very_short_series(self):
        bars = _flat_bars(5)
        zones = detect_liquidity_zones(bars, swing_lookback=5, min_wick_size_pips=10.0)
        assert zones == []

    def test_check_retest_empty_zones(self):
        bars = _flat_bars(20)
        entries = check_retest_entries(bars, [], at_index=19)
        assert entries == []

    def test_pd_array_out_of_bounds(self):
        bars = _flat_bars(10)
        target = find_draw_on_liquidity(bars, at_index=100, direction=Direction.LONG)
        assert target is None
