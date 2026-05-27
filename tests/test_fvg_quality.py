"""Tests for FVG quality scoring, fill tracking, and reaction detection."""
from datetime import datetime, timedelta, timezone

import pytest

from agent.detectors.fvg import compute_fvg_quality, detect_fvgs, quality_fvgs, unfilled_fvgs
from agent.detectors.fvg_retest import (
    check_fvg_retest_entries,
    collect_structural_targets,
)
from agent.types import Bar, Direction, FVG, Swing, Timeframe


def _bar(t, o, h, l, c, tf=Timeframe.H1):
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=100, timeframe=tf)


T0 = datetime(2024, 3, 5, 8, 0, tzinfo=timezone.utc)  # London session (kill zone)


class TestFVGQualityScoring:
    """Test that quality scoring correctly ranks FVGs."""

    def test_high_quality_fvg(self):
        """Large FVG + aggressive candle + kill zone = high score."""
        fvg = FVG(
            direction=Direction.LONG,
            top=1.1020,
            bottom=1.1000,
            created_at=T0,
            created_bar_index=5,
            size_pips=20.0,
            creation_displacement_pips=25.0,
            creation_body_pct=0.85,
            formation_session="london_open",
            is_killzone=True,
            fill_pct=0.0,
            revisit_count=0,
        )
        score = compute_fvg_quality(fvg)
        assert score >= 75, f"Expected high score, got {score}"

    def test_low_quality_fvg(self):
        """Small FVG + weak candle + off-session + partially filled = low score."""
        fvg = FVG(
            direction=Direction.SHORT,
            top=1.1005,
            bottom=1.1000,
            created_at=datetime(2024, 3, 5, 22, 0, tzinfo=timezone.utc),  # Off-session
            created_bar_index=10,
            size_pips=5.0,
            creation_displacement_pips=5.0,
            creation_body_pct=0.30,
            formation_session="off_session",
            is_killzone=False,
            fill_pct=0.7,
            revisit_count=2,
        )
        score = compute_fvg_quality(fvg)
        assert score < 30, f"Expected low score, got {score}"

    def test_medium_quality_fvg(self):
        """Medium size + decent aggressiveness + London body = medium score."""
        fvg = FVG(
            direction=Direction.LONG,
            top=1.1012,
            bottom=1.1000,
            created_at=datetime(2024, 3, 5, 10, 0, tzinfo=timezone.utc),
            created_bar_index=8,
            size_pips=12.0,
            creation_displacement_pips=15.0,
            creation_body_pct=0.65,
            formation_session="london_body",
            is_killzone=False,
            fill_pct=0.3,
            revisit_count=1,
        )
        score = compute_fvg_quality(fvg)
        assert 35 <= score <= 65, f"Expected medium score, got {score}"

    def test_revisit_penalty(self):
        """Each revisit reduces quality score."""
        base = FVG(
            direction=Direction.LONG,
            top=1.1015,
            bottom=1.1000,
            created_at=T0,
            created_bar_index=5,
            size_pips=15.0,
            creation_displacement_pips=20.0,
            creation_body_pct=0.80,
            formation_session="london_open",
            is_killzone=True,
            fill_pct=0.0,
            revisit_count=0,
        )
        score_0 = compute_fvg_quality(base)

        base.revisit_count = 2
        score_2 = compute_fvg_quality(base)

        assert score_0 > score_2
        assert score_0 - score_2 == 10  # 2 * 5 = 10 pip penalty

    def test_fill_reduces_quality(self):
        """Partially filled FVG has lower quality than fresh one."""
        fvg_fresh = FVG(
            direction=Direction.LONG,
            top=1.1015,
            bottom=1.1000,
            created_at=T0,
            created_bar_index=5,
            size_pips=15.0,
            creation_body_pct=0.75,
            formation_session="london_open",
            is_killzone=True,
            fill_pct=0.0,
        )
        fvg_partial = FVG(
            direction=Direction.LONG,
            top=1.1015,
            bottom=1.1000,
            created_at=T0,
            created_bar_index=5,
            size_pips=15.0,
            creation_body_pct=0.75,
            formation_session="london_open",
            is_killzone=True,
            fill_pct=0.6,
        )
        assert compute_fvg_quality(fvg_fresh) > compute_fvg_quality(fvg_partial)


class TestFVGFillTracking:
    """Test that fill tracking correctly monitors penetration."""

    def test_partial_fill_tracked(self):
        """When price enters FVG but doesn't fully cross it, fill_pct updates."""
        t = T0
        bars = [
            _bar(t, 1.1000, 1.1010, 1.0990, 1.1005),
            _bar(t + timedelta(hours=1), 1.1005, 1.1100, 1.1000, 1.1095),  # Impulse
            _bar(t + timedelta(hours=2), 1.1100, 1.1110, 1.1050, 1.1080),  # FVG: [1.1010, 1.1050]
            # Price returns and dips into FVG partially
            _bar(t + timedelta(hours=3), 1.1080, 1.1085, 1.1035, 1.1070),
        ]
        fvgs = detect_fvgs(bars, min_size_pips=2)
        assert len(fvgs) >= 1
        fvg = fvgs[0]
        assert fvg.fill_pct > 0
        assert not fvg.is_fully_filled

    def test_full_fill_marks_done(self):
        """When price completely crosses FVG, it's marked fully filled."""
        t = T0
        bars = [
            _bar(t, 1.1000, 1.1010, 1.0990, 1.1005),
            _bar(t + timedelta(hours=1), 1.1005, 1.1100, 1.1000, 1.1095),
            _bar(t + timedelta(hours=2), 1.1100, 1.1110, 1.1050, 1.1080),
            # Price drops all the way through the FVG
            _bar(t + timedelta(hours=3), 1.1080, 1.1080, 1.0980, 1.0990),
        ]
        fvgs = detect_fvgs(bars, min_size_pips=2)
        assert len(fvgs) >= 1
        fvg = fvgs[0]
        assert fvg.is_fully_filled
        assert fvg.fill_pct == 1.0
        assert fvg.filled is True

    def test_unfilled_filter_excludes_full(self):
        """unfilled_fvgs() excludes fully filled FVGs."""
        t = T0
        bars = [
            _bar(t, 1.1000, 1.1010, 1.0990, 1.1005),
            _bar(t + timedelta(hours=1), 1.1005, 1.1100, 1.1000, 1.1095),
            _bar(t + timedelta(hours=2), 1.1100, 1.1110, 1.1050, 1.1080),
            _bar(t + timedelta(hours=3), 1.1080, 1.1080, 1.0980, 1.0990),
        ]
        fvgs = detect_fvgs(bars, min_size_pips=2)
        active = unfilled_fvgs(fvgs, at_index=3)
        assert len(active) == 0


class TestFVGReactionDetection:
    """Test that reaction patterns are correctly identified."""

    def _build_bullish_fvg_and_retest_bars(self, reaction_style: str):
        """Build bars that form a bullish FVG and then show a specific reaction."""
        t = T0
        # Create FVG
        bars = [
            _bar(t, 1.1000, 1.1010, 1.0990, 1.1005),                          # idx 0
            _bar(t + timedelta(hours=1), 1.1005, 1.1100, 1.1000, 1.1095),      # idx 1 (impulse)
            _bar(t + timedelta(hours=2), 1.1095, 1.1110, 1.1050, 1.1080),      # idx 2 (gap low=1.1050 > bar0.high=1.1010)
            _bar(t + timedelta(hours=3), 1.1080, 1.1090, 1.1060, 1.1085),      # idx 3 (consolidation)
        ]
        # FVG zone: bottom=1.1010, top=1.1050

        if reaction_style == "rejection_wick":
            # Bar dips into FVG zone with long lower wick, closes above
            bars.append(_bar(t + timedelta(hours=4), 1.1060, 1.1065, 1.1015, 1.1055))  # idx 4
        elif reaction_style == "engulfing":
            # Previous bar enters FVG, then current bar engulfs bullishly
            bars.append(_bar(t + timedelta(hours=4), 1.1060, 1.1065, 1.1020, 1.1025))  # idx 4 enters FVG
            bars.append(_bar(t + timedelta(hours=5), 1.1025, 1.1070, 1.1020, 1.1068))  # idx 5 engulfs
        elif reaction_style == "displacement":
            # Previous bar enters FVG, then current bar displaces up strongly
            # (open above prev.close so engulfing doesn't match)
            bars.append(_bar(t + timedelta(hours=4), 1.1060, 1.1065, 1.1020, 1.1025))  # idx 4 enters FVG
            bars.append(_bar(t + timedelta(hours=5), 1.1030, 1.1090, 1.1028, 1.1085))  # idx 5 displacement (open > prev.close)

        return bars

    def test_rejection_wick_detected(self):
        """Rejection wick pattern triggers entry."""
        bars = self._build_bullish_fvg_and_retest_bars("rejection_wick")
        fvgs = detect_fvgs(bars, min_size_pips=2)
        assert len(fvgs) >= 1

        entries = check_fvg_retest_entries(
            bars, fvgs, at_index=4,
            min_quality_score=0,  # Accept any quality for test
            require_reaction=True,
            max_fill_pct=1.0,  # Don't filter by fill (bar itself causes fill)
        )
        assert len(entries) == 1
        assert entries[0].reaction_type == "rejection_wick"

    def test_engulfing_detected(self):
        """Engulfing pattern triggers entry."""
        bars = self._build_bullish_fvg_and_retest_bars("engulfing")
        fvgs = detect_fvgs(bars, min_size_pips=2)
        assert len(fvgs) >= 1

        entries = check_fvg_retest_entries(
            bars, fvgs, at_index=5,
            min_quality_score=0,
            require_reaction=True,
            max_fill_pct=1.0,
        )
        assert len(entries) == 1
        assert entries[0].reaction_type == "engulfing"

    def test_displacement_detected(self):
        """Displacement pattern triggers entry."""
        bars = self._build_bullish_fvg_and_retest_bars("displacement")
        fvgs = detect_fvgs(bars, min_size_pips=2)
        assert len(fvgs) >= 1

        entries = check_fvg_retest_entries(
            bars, fvgs, at_index=5,
            min_quality_score=0,
            require_reaction=True,
            max_fill_pct=1.0,
        )
        assert len(entries) == 1
        assert entries[0].reaction_type == "displacement"

    def test_touch_without_reaction_rejected(self):
        """A simple touch without reaction is rejected when require_reaction=True."""
        t = T0
        bars = [
            _bar(t, 1.1000, 1.1010, 1.0990, 1.1005),
            _bar(t + timedelta(hours=1), 1.1005, 1.1100, 1.1000, 1.1095),
            _bar(t + timedelta(hours=2), 1.1095, 1.1110, 1.1050, 1.1080),
            # Price barely touches FVG top, no wick, no reaction
            _bar(t + timedelta(hours=3), 1.1060, 1.1065, 1.1048, 1.1052),
        ]
        fvgs = detect_fvgs(bars, min_size_pips=2)
        entries = check_fvg_retest_entries(
            bars, fvgs, at_index=3,
            min_quality_score=0,
            require_reaction=True,
        )
        assert len(entries) == 0

    def test_quality_filter_blocks_low_score(self):
        """FVGs below quality threshold don't produce entries even with reaction."""
        t = datetime(2024, 3, 5, 23, 0, tzinfo=timezone.utc)  # Off-session
        bars = [
            _bar(t, 1.1000, 1.1005, 1.0995, 1.1003),                          # Small candle
            _bar(t + timedelta(hours=1), 1.1003, 1.1060, 1.1000, 1.1055),      # Small impulse
            _bar(t + timedelta(hours=2), 1.1055, 1.1060, 1.1020, 1.1025),      # Gap
            _bar(t + timedelta(hours=3), 1.1025, 1.1030, 1.1005, 1.1010),      # Returns
            # Rejection wick
            _bar(t + timedelta(hours=4), 1.1010, 1.1050, 1.1005, 1.1045),
        ]
        fvgs = detect_fvgs(bars, min_size_pips=2)
        entries = check_fvg_retest_entries(
            bars, fvgs, at_index=4,
            min_quality_score=80,  # Very high threshold
            require_reaction=True,
        )
        assert len(entries) == 0


class TestFVGDetectionBackwardCompat:
    """Ensure the rebuilt detector maintains backward compatibility."""

    def test_basic_bullish_detection(self):
        """Same test as legacy test_fvg.py — must still pass."""
        t = datetime(2024, 1, 1)
        bars = [
            _bar(t, 1.1000, 1.1010, 1.0990, 1.1005),
            _bar(t + timedelta(hours=1), 1.1005, 1.1100, 1.1000, 1.1095),
            _bar(t + timedelta(hours=2), 1.1100, 1.1110, 1.1050, 1.1080),
        ]
        fvgs = detect_fvgs(bars, min_size_pips=2)
        assert len(fvgs) == 1
        assert fvgs[0].direction == Direction.LONG

    def test_basic_bearish_detection(self):
        """Same test as legacy test_fvg.py — must still pass."""
        t = datetime(2024, 1, 1)
        bars = [
            _bar(t, 1.1100, 1.1110, 1.1090, 1.1095),
            _bar(t + timedelta(hours=1), 1.1095, 1.1100, 1.1000, 1.1005),
            _bar(t + timedelta(hours=2), 1.1000, 1.1080, 1.0990, 1.0995),
        ]
        fvgs = detect_fvgs(bars, min_size_pips=2)
        assert len(fvgs) == 1
        assert fvgs[0].direction == Direction.SHORT

    def test_fvg_has_quality_fields(self):
        """New quality fields are populated on detected FVGs."""
        t = T0
        bars = [
            _bar(t, 1.1000, 1.1010, 1.0990, 1.1005),
            _bar(t + timedelta(hours=1), 1.1005, 1.1100, 1.1000, 1.1095),
            _bar(t + timedelta(hours=2), 1.1100, 1.1110, 1.1050, 1.1080),
        ]
        fvgs = detect_fvgs(bars, min_size_pips=2)
        fvg = fvgs[0]
        assert fvg.quality_score > 0
        assert fvg.creation_body_pct > 0
        assert fvg.formation_session != ""


class TestStructuralTargets:
    """Test TP target collection from swings and daily levels."""

    def test_long_targets_above_price(self):
        t = T0
        bars = [_bar(t + timedelta(hours=i), 1.1000, 1.1010, 1.0990, 1.1000) for i in range(10)]
        swings = [
            Swing(time=t, price=1.0980, is_high=False, bar_index=2),
            Swing(time=t + timedelta(hours=3), price=1.1050, is_high=True, bar_index=3),
            Swing(time=t + timedelta(hours=5), price=1.1080, is_high=True, bar_index=5),
        ]
        targets = collect_structural_targets(bars, 8, Direction.LONG, swings=swings)
        assert all(t > 1.1000 for t in targets)
        assert 1.1050 in targets
        assert 1.1080 in targets

    def test_short_targets_below_price(self):
        t = T0
        bars = [_bar(t + timedelta(hours=i), 1.1000, 1.1010, 1.0990, 1.1000) for i in range(10)]
        swings = [
            Swing(time=t, price=1.0950, is_high=False, bar_index=2),
            Swing(time=t + timedelta(hours=3), price=1.0970, is_high=False, bar_index=3),
            Swing(time=t + timedelta(hours=5), price=1.1080, is_high=True, bar_index=5),
        ]
        targets = collect_structural_targets(bars, 8, Direction.SHORT, swings=swings)
        assert all(t < 1.1000 for t in targets)
        assert 1.0950 in targets
        assert 1.0970 in targets
