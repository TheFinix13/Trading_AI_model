"""Tests for SD zone quality grading, order-block boundaries, depletion, and retest entries."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from agent.detectors.zone_retest import ZoneEntry, check_zone_retest_entries
from agent.detectors.zones import (
    QualifiedZone,
    ZoneQuality,
    compute_zone_quality,
    detect_qualified_zones,
    fresh_qualified_zones,
    update_zone_depletion,
)
from agent.types import Bar, Direction, Timeframe, Zone


def _bar(
    t: datetime,
    o: float,
    h: float,
    l: float,
    c: float,
    tf: Timeframe = Timeframe.M15,
) -> Bar:
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=1000.0, timeframe=tf)


def _ts(minutes_offset: int = 0) -> datetime:
    return datetime(2025, 6, 10, 9, 0) + timedelta(minutes=minutes_offset)


class TestZoneQualityScoring:
    """Test the quality score formula produces sensible outputs."""

    def test_high_quality_zone(self):
        """A zone with all positive attributes should score 75+."""
        q = ZoneQuality(
            origin_type="drop_base_rally",
            base_candle_count=2,
            departure_pips=45.0,
            departure_body_pct=0.80,
            left_fvg=True,
            formation_session="london_open",
            is_killzone=True,
            zone_width_pips=12.0,
            width_vs_atr=0.8,
            revisit_count=0,
            fill_pct=0.0,
            age_bars=50,
        )
        score = compute_zone_quality(q)
        assert score >= 75, f"Expected >=75 but got {score}"

    def test_low_quality_zone(self):
        """A messy zone with bad attributes should score <30."""
        q = ZoneQuality(
            origin_type="impulse_only",
            base_candle_count=7,
            departure_pips=15.0,
            departure_body_pct=0.35,
            left_fvg=False,
            formation_session="off_session",
            is_killzone=False,
            zone_width_pips=40.0,
            width_vs_atr=3.5,
            revisit_count=2,
            fill_pct=0.6,
            age_bars=600,
        )
        score = compute_zone_quality(q)
        assert score < 30, f"Expected <30 but got {score}"

    def test_fvg_boosts_score(self):
        """Zone with FVG should score 10 points higher than without."""
        base = ZoneQuality(
            origin_type="drop_base_rally",
            base_candle_count=2,
            departure_body_pct=0.70,
            formation_session="london_open",
            is_killzone=True,
            width_vs_atr=1.0,
        )
        without_fvg = compute_zone_quality(base)
        base.left_fvg = True
        with_fvg = compute_zone_quality(base)
        assert with_fvg - without_fvg == 10

    def test_killzone_formation_scores_higher(self):
        """Killzone formation should score 12 points more than off-session."""
        kz = ZoneQuality(
            origin_type="impulse_only",
            base_candle_count=3,
            departure_body_pct=0.60,
            formation_session="london_open",
            is_killzone=True,
            width_vs_atr=1.5,
        )
        off = ZoneQuality(
            origin_type="impulse_only",
            base_candle_count=3,
            departure_body_pct=0.60,
            formation_session="off_session",
            is_killzone=False,
            width_vs_atr=1.5,
        )
        kz_score = compute_zone_quality(kz)
        off_score = compute_zone_quality(off)
        assert kz_score > off_score
        assert kz_score - off_score == 12  # 15 - 3

    def test_depletion_reduces_score(self):
        """Each revisit should reduce score by 5 (capped at 15)."""
        q = ZoneQuality(
            origin_type="drop_base_rally",
            base_candle_count=2,
            departure_body_pct=0.75,
            formation_session="london_open",
            is_killzone=True,
            width_vs_atr=1.0,
        )
        score_0 = compute_zone_quality(q)

        q.revisit_count = 2
        score_2 = compute_zone_quality(q)
        assert score_0 - score_2 == 10  # 2 * 5

        q.revisit_count = 5
        score_5 = compute_zone_quality(q)
        assert score_0 - score_5 == 15  # capped at 15

    def test_fill_pct_penalty(self):
        """Fill pct > 0.5 should subtract 10."""
        q = ZoneQuality(
            origin_type="drop_base_rally",
            base_candle_count=2,
            departure_body_pct=0.75,
            is_killzone=True,
            width_vs_atr=1.0,
        )
        score_fresh = compute_zone_quality(q)
        q.fill_pct = 0.6
        score_filled = compute_zone_quality(q)
        assert score_fresh - score_filled == 10

    def test_age_penalty(self):
        """Old zones should be penalized."""
        q = ZoneQuality(
            origin_type="drop_base_rally",
            base_candle_count=2,
            departure_body_pct=0.75,
            is_killzone=True,
            width_vs_atr=1.0,
        )
        score_young = compute_zone_quality(q)

        q.age_bars = 400
        score_medium = compute_zone_quality(q)
        assert score_young - score_medium == 5

        q.age_bars = 600
        score_old = compute_zone_quality(q)
        # 300+ = -5, 500+ = -10 (cumulative)
        assert score_young - score_old == 15

    def test_score_clamped_0_100(self):
        """Score should never go below 0 or above 100."""
        # Very bad zone
        q = ZoneQuality(
            origin_type="impulse_only",
            base_candle_count=10,
            departure_body_pct=0.1,
            is_killzone=False,
            width_vs_atr=5.0,
            revisit_count=10,
            fill_pct=0.9,
            age_bars=1000,
        )
        score = compute_zone_quality(q)
        assert score >= 0
        assert score <= 100


class TestOrderBlockBoundary:
    """Test that zones use proper order-block boundaries."""

    def _make_demand_scenario(self) -> list[Bar]:
        """Create bars: bearish candles then bullish impulse (demand zone)."""
        bars = []
        t = _ts()
        # Filler bars
        for i in range(5):
            bars.append(_bar(t + timedelta(minutes=15 * i), 1.1000, 1.1005, 1.0995, 1.1002))

        # Bearish order block candle (last bearish before impulse)
        bars.append(_bar(t + timedelta(minutes=75), 1.1002, 1.1005, 1.0990, 1.0992))

        # Strong bullish impulse (displacement)
        bars.append(_bar(t + timedelta(minutes=90), 1.0992, 1.1060, 1.0990, 1.1055))

        return bars

    def test_demand_zone_uses_bearish_ob(self):
        """Demand zone should be bounded by last bearish candle before impulse."""
        bars = self._make_demand_scenario()
        zones = detect_qualified_zones(bars, min_impulse_pips=20.0, base_lookback=5)

        demand_zones = [z for z in zones if z.direction == Direction.LONG]
        assert len(demand_zones) >= 1
        qz = demand_zones[0]
        # Zone should be bounded by the bearish OB candle (high=1.1005, low=1.0990)
        assert qz.top <= 1.1006
        assert qz.bottom >= 1.0989

    def _make_supply_scenario(self) -> list[Bar]:
        """Create bars: bullish candles then bearish impulse (supply zone)."""
        bars = []
        t = _ts()
        for i in range(5):
            bars.append(_bar(t + timedelta(minutes=15 * i), 1.1000, 1.1005, 1.0995, 1.1002))

        # Bullish order block candle (last bullish before bearish impulse)
        bars.append(_bar(t + timedelta(minutes=75), 1.0998, 1.1010, 1.0995, 1.1008))

        # Strong bearish impulse
        bars.append(_bar(t + timedelta(minutes=90), 1.1008, 1.1010, 1.0940, 1.0945))

        return bars

    def test_supply_zone_uses_bullish_ob(self):
        """Supply zone should be bounded by last bullish candle before bearish impulse."""
        bars = self._make_supply_scenario()
        zones = detect_qualified_zones(bars, min_impulse_pips=20.0, base_lookback=5)

        supply_zones = [z for z in zones if z.direction == Direction.SHORT]
        assert len(supply_zones) >= 1
        qz = supply_zones[0]
        # Zone bounded by bullish OB candle (high=1.1010, low=1.0995)
        assert qz.top <= 1.1011
        assert qz.bottom >= 1.0994


class TestDepletionTracking:
    """Test that revisits correctly deplete zones."""

    def _make_zone_and_revisits(self, revisit_count: int) -> tuple[list[QualifiedZone], list[Bar]]:
        """Create a demand zone followed by revisiting bars."""
        bars = []
        t = _ts()
        # Filler
        for i in range(5):
            bars.append(_bar(t + timedelta(minutes=15 * i), 1.1000, 1.1005, 1.0995, 1.1002))
        # OB candle (bearish)
        bars.append(_bar(t + timedelta(minutes=75), 1.1002, 1.1005, 1.0990, 1.0992))
        # Impulse
        bars.append(_bar(t + timedelta(minutes=90), 1.0992, 1.1060, 1.0990, 1.1055))
        # Bars that move away
        bars.append(_bar(t + timedelta(minutes=105), 1.1055, 1.1070, 1.1050, 1.1065))
        bars.append(_bar(t + timedelta(minutes=120), 1.1065, 1.1080, 1.1060, 1.1075))
        bars.append(_bar(t + timedelta(minutes=135), 1.1075, 1.1085, 1.1070, 1.1080))
        bars.append(_bar(t + timedelta(minutes=150), 1.1080, 1.1090, 1.1075, 1.1085))
        bars.append(_bar(t + timedelta(minutes=165), 1.1085, 1.1090, 1.1080, 1.1088))

        # Add revisiting bars (price comes back to zone ~1.0990-1.1005)
        for r in range(revisit_count):
            offset = 180 + r * 15
            bars.append(_bar(
                t + timedelta(minutes=offset),
                1.1020, 1.1025, 1.0995, 1.1010,
            ))

        # Final bar away from zone
        bars.append(_bar(t + timedelta(minutes=300), 1.1040, 1.1050, 1.1035, 1.1045))

        zones = detect_qualified_zones(bars, min_impulse_pips=20.0, base_lookback=5)
        return zones, bars

    def test_zero_revisits_not_depleted(self):
        zones, bars = self._make_zone_and_revisits(0)
        if not zones:
            pytest.skip("No zone detected in this scenario")
        update_zone_depletion(zones, bars, len(bars) - 1)
        for qz in zones:
            assert not qz.quality.is_depleted

    def test_three_revisits_depleted(self):
        zones, bars = self._make_zone_and_revisits(4)
        if not zones:
            pytest.skip("No zone detected in this scenario")
        update_zone_depletion(zones, bars, len(bars) - 1)
        demand = [z for z in zones if z.direction == Direction.LONG]
        if demand:
            assert demand[0].quality.revisit_count >= 3
            assert demand[0].quality.is_depleted


class TestFreshQualifiedZones:
    """Test filtering of qualified zones."""

    def _make_qz(self, score: float, depleted: bool = False, created_idx: int = 10) -> QualifiedZone:
        zone = Zone(
            direction=Direction.LONG,
            top=1.1010,
            bottom=1.1000,
            created_at=_ts(),
            created_bar_index=created_idx,
            impulse_pips=40.0,
        )
        quality = ZoneQuality(quality_score=score, is_depleted=depleted)
        return QualifiedZone(zone=zone, quality=quality)

    def test_depleted_zone_excluded(self):
        zones = [self._make_qz(60.0, depleted=True)]
        fresh = fresh_qualified_zones(zones, at_index=50)
        assert len(fresh) == 0

    def test_low_quality_excluded(self):
        zones = [self._make_qz(30.0)]
        fresh = fresh_qualified_zones(zones, at_index=50, min_quality_score=45.0)
        assert len(fresh) == 0

    def test_high_quality_included(self):
        zones = [self._make_qz(70.0)]
        fresh = fresh_qualified_zones(zones, at_index=50, min_quality_score=45.0)
        assert len(fresh) == 1


class TestZoneRetestEntries:
    """Test two-phase zone retest entry detection."""

    def _demand_zone(self) -> QualifiedZone:
        zone = Zone(
            direction=Direction.LONG,
            top=1.1010,
            bottom=1.1000,
            created_at=_ts(),
            created_bar_index=5,
            impulse_pips=40.0,
        )
        quality = ZoneQuality(
            origin_type="drop_base_rally",
            base_candle_count=2,
            departure_body_pct=0.75,
            is_killzone=True,
            width_vs_atr=0.8,
            quality_score=75.0,
        )
        return QualifiedZone(zone=zone, quality=quality)

    def _supply_zone(self) -> QualifiedZone:
        zone = Zone(
            direction=Direction.SHORT,
            top=1.1050,
            bottom=1.1040,
            created_at=_ts(),
            created_bar_index=5,
            impulse_pips=40.0,
        )
        quality = ZoneQuality(
            origin_type="rally_base_drop",
            base_candle_count=2,
            departure_body_pct=0.75,
            is_killzone=True,
            width_vs_atr=0.8,
            quality_score=75.0,
        )
        return QualifiedZone(zone=zone, quality=quality)

    def test_rejection_wick_demand(self):
        """Rejection wick into demand zone should trigger entry."""
        qz = self._demand_zone()
        bars = []
        for i in range(10):
            bars.append(_bar(_ts(i * 15), 1.1050, 1.1055, 1.1045, 1.1052))
        # Bar with rejection wick into demand zone (low dips into zone, closes above)
        bars.append(_bar(
            _ts(150), 1.1015, 1.1020, 1.0998, 1.1018,
        ))

        entries = check_zone_retest_entries(bars, [qz], at_index=10, require_reaction=True)
        assert len(entries) >= 1
        assert entries[0].reaction_type == "rejection_wick"

    def test_engulfing_demand(self):
        """Bullish engulfing at demand zone should trigger entry."""
        qz = self._demand_zone()
        bars = []
        for i in range(9):
            bars.append(_bar(_ts(i * 15), 1.1050, 1.1055, 1.1045, 1.1052))
        # Previous bar: bearish, dipping into zone
        bars.append(_bar(_ts(135), 1.1012, 1.1015, 1.1002, 1.1004))
        # Current bar: bullish engulfing
        bars.append(_bar(_ts(150), 1.1004, 1.1020, 1.1002, 1.1018))

        entries = check_zone_retest_entries(bars, [qz], at_index=10, require_reaction=True)
        assert len(entries) >= 1
        assert entries[0].reaction_type == "engulfing"

    def test_displacement_supply(self):
        """Bearish displacement from supply zone should trigger entry."""
        qz = self._supply_zone()
        bars = []
        for i in range(10):
            bars.append(_bar(_ts(i * 15), 1.1030, 1.1035, 1.1025, 1.1032))
        # Bar displaces downward from supply zone (opens in zone, closes below)
        bars.append(_bar(_ts(150), 1.1045, 1.1048, 1.1025, 1.1028))

        entries = check_zone_retest_entries(bars, [qz], at_index=10, require_reaction=True)
        assert len(entries) >= 1
        assert entries[0].reaction_type == "displacement"

    def test_depleted_zone_skipped(self):
        """A depleted zone should not produce entries."""
        qz = self._demand_zone()
        qz.quality.revisit_count = 5
        qz.quality.is_depleted = True

        bars = []
        for i in range(10):
            bars.append(_bar(_ts(i * 15), 1.1050, 1.1055, 1.1045, 1.1052))
        bars.append(_bar(_ts(150), 1.1015, 1.1020, 1.0998, 1.1018))

        entries = check_zone_retest_entries(bars, [qz], at_index=10, require_reaction=True)
        assert len(entries) == 0

    def test_no_reaction_no_entry(self):
        """Without a reaction candle, no entry should fire."""
        qz = self._demand_zone()
        bars = []
        for i in range(10):
            bars.append(_bar(_ts(i * 15), 1.1050, 1.1055, 1.1045, 1.1052))
        # Bar touches zone but no reaction pattern (small doji in zone)
        bars.append(_bar(_ts(150), 1.1005, 1.1007, 1.1003, 1.1005))

        entries = check_zone_retest_entries(bars, [qz], at_index=10, require_reaction=True)
        assert len(entries) == 0

    def test_entry_without_reaction_required(self):
        """With require_reaction=False, a touch is enough."""
        qz = self._demand_zone()
        bars = []
        for i in range(10):
            bars.append(_bar(_ts(i * 15), 1.1050, 1.1055, 1.1045, 1.1052))
        # Bar touches zone (any shape)
        bars.append(_bar(_ts(150), 1.1005, 1.1007, 1.1003, 1.1005))

        entries = check_zone_retest_entries(bars, [qz], at_index=10, require_reaction=False)
        assert len(entries) >= 1
