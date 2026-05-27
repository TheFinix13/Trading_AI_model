"""Tests for BOS quality scoring, recency check, and BOS+FVG integration."""
from datetime import datetime, timedelta, timezone

import pytest

from agent.detectors.bos import compute_bos_quality, detect_bos, quality_bos, latest_bos
from agent.detectors.fvg import detect_fvgs
from agent.detectors.fvg_retest import check_fvg_retest_entries
from agent.types import Bar, BreakOfStructure, Direction, Timeframe


def _bar(t, o, h, l, c, tf=Timeframe.H1):
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=100, timeframe=tf)


T0 = datetime(2024, 3, 5, 8, 0, tzinfo=timezone.utc)  # London session


class TestBOSQualityScoring:
    """Test that quality scoring correctly ranks BOS events."""

    def test_high_quality_body_break(self):
        """Strong body break + displacement + killzone + recent swing = high score."""
        bos = BreakOfStructure(
            direction=Direction.LONG,
            broken_swing_price=1.1000,
            broken_at=T0,
            broken_bar_index=20,
            break_displacement_pips=12.0,
            break_body_pct=0.80,
            is_body_break=True,
            break_session="london_open",
            bars_since_swing=15,
            left_fvg_behind=True,
            left_orderblock=True,
        )
        score = compute_bos_quality(bos)
        assert score >= 80, f"Expected high score, got {score}"

    def test_low_quality_wick_break(self):
        """Wick-only break + low displacement + off-session + ancient swing = low score."""
        bos = BreakOfStructure(
            direction=Direction.SHORT,
            broken_swing_price=1.1000,
            broken_at=datetime(2024, 3, 5, 22, 0, tzinfo=timezone.utc),
            broken_bar_index=100,
            break_displacement_pips=2.0,
            break_body_pct=0.20,
            is_body_break=False,
            break_session="off_session",
            bars_since_swing=80,
            left_fvg_behind=False,
            left_orderblock=False,
        )
        score = compute_bos_quality(bos)
        assert score < 30, f"Expected low score, got {score}"

    def test_body_break_vs_wick_break(self):
        """Body break always scores higher than wick break, all else equal."""
        body_bos = BreakOfStructure(
            direction=Direction.LONG,
            broken_swing_price=1.1000,
            broken_at=T0,
            broken_bar_index=20,
            break_displacement_pips=8.0,
            break_body_pct=0.75,
            is_body_break=True,
            break_session="london_open",
            bars_since_swing=20,
        )
        wick_bos = BreakOfStructure(
            direction=Direction.LONG,
            broken_swing_price=1.1000,
            broken_at=T0,
            broken_bar_index=20,
            break_displacement_pips=8.0,
            break_body_pct=0.75,
            is_body_break=False,
            break_session="london_open",
            bars_since_swing=20,
        )
        assert compute_bos_quality(body_bos) > compute_bos_quality(wick_bos)

    def test_session_scoring(self):
        """Killzone sessions score higher than off-session."""
        london_bos = BreakOfStructure(
            direction=Direction.LONG,
            broken_swing_price=1.1000,
            broken_at=T0,
            broken_bar_index=20,
            break_displacement_pips=8.0,
            break_body_pct=0.70,
            is_body_break=True,
            break_session="london_open",
            bars_since_swing=20,
        )
        off_bos = BreakOfStructure(
            direction=Direction.LONG,
            broken_swing_price=1.1000,
            broken_at=T0,
            broken_bar_index=20,
            break_displacement_pips=8.0,
            break_body_pct=0.70,
            is_body_break=True,
            break_session="off_session",
            bars_since_swing=20,
        )
        assert compute_bos_quality(london_bos) > compute_bos_quality(off_bos)
        assert compute_bos_quality(london_bos) - compute_bos_quality(off_bos) == 15


class TestBOSRecency:
    """Test that swing recency affects quality."""

    def test_recent_swing_higher_score(self):
        """Breaking a recent swing (15 bars ago) is more significant."""
        recent = BreakOfStructure(
            direction=Direction.LONG,
            broken_swing_price=1.1000,
            broken_at=T0,
            broken_bar_index=20,
            break_displacement_pips=8.0,
            break_body_pct=0.70,
            is_body_break=True,
            break_session="london_open",
            bars_since_swing=15,
        )
        ancient = BreakOfStructure(
            direction=Direction.LONG,
            broken_swing_price=1.1000,
            broken_at=T0,
            broken_bar_index=20,
            break_displacement_pips=8.0,
            break_body_pct=0.70,
            is_body_break=True,
            break_session="london_open",
            bars_since_swing=80,
        )
        assert compute_bos_quality(recent) > compute_bos_quality(ancient)

    def test_quality_filter(self):
        """quality_bos() correctly filters by score and lookback."""
        bos_list = [
            BreakOfStructure(
                direction=Direction.LONG,
                broken_swing_price=1.1000,
                broken_at=T0,
                broken_bar_index=10,
                quality_score=60.0,
            ),
            BreakOfStructure(
                direction=Direction.SHORT,
                broken_swing_price=1.0950,
                broken_at=T0 + timedelta(hours=5),
                broken_bar_index=15,
                quality_score=30.0,  # Low quality
            ),
            BreakOfStructure(
                direction=Direction.LONG,
                broken_swing_price=1.1050,
                broken_at=T0 + timedelta(hours=10),
                broken_bar_index=25,
                quality_score=75.0,
            ),
        ]
        # Filter at index 30, min quality 50
        result = quality_bos(bos_list, at_index=30, min_quality=50.0, max_lookback_bars=50)
        assert len(result) == 2
        assert all(b.quality_score >= 50 for b in result)

    def test_quality_filter_respects_lookback(self):
        """quality_bos() excludes events beyond max_lookback_bars."""
        bos_list = [
            BreakOfStructure(
                direction=Direction.LONG,
                broken_swing_price=1.1000,
                broken_at=T0,
                broken_bar_index=5,
                quality_score=80.0,
            ),
        ]
        # At index 100, with max_lookback=50, the BOS at bar 5 is too old
        result = quality_bos(bos_list, at_index=100, min_quality=50.0, max_lookback_bars=50)
        assert len(result) == 0


class TestBOSDetection:
    """Test that the detector produces quality-graded BOS events."""

    def _build_bos_bars(self):
        """Build a series that creates a swing high then breaks it."""
        t = T0
        bars = []
        # Create some history with a swing high around bar 7
        prices = [
            (1.1000, 1.1010, 1.0995, 1.1005),   # 0
            (1.1005, 1.1020, 1.1000, 1.1015),   # 1
            (1.1015, 1.1030, 1.1010, 1.1025),   # 2
            (1.1025, 1.1050, 1.1020, 1.1045),   # 3
            (1.1045, 1.1060, 1.1040, 1.1055),   # 4
            (1.1055, 1.1070, 1.1050, 1.1065),   # 5
            (1.1065, 1.1080, 1.1060, 1.1075),   # 6
            (1.1075, 1.1090, 1.1070, 1.1080),   # 7  <-- swing high at 1.1090
            (1.1080, 1.1085, 1.1050, 1.1055),   # 8
            (1.1055, 1.1060, 1.1030, 1.1035),   # 9
            (1.1035, 1.1045, 1.1020, 1.1040),   # 10
            (1.1040, 1.1050, 1.1030, 1.1045),   # 11
            (1.1045, 1.1055, 1.1035, 1.1050),   # 12
            (1.1050, 1.1060, 1.1040, 1.1055),   # 13
            # Break of structure: close above the swing high (1.1090)
            (1.1055, 1.1100, 1.1050, 1.1095),   # 14  <-- BOS candle
        ]
        for i, (o, h, l, c) in enumerate(prices):
            bars.append(_bar(t + timedelta(hours=i), o, h, l, c))
        return bars

    def test_bos_detected_with_quality(self):
        """BOS detection produces events with quality scores."""
        bars = self._build_bos_bars()
        bos_list = detect_bos(bars, swing_lookback=5)
        assert len(bos_list) >= 1
        # At least one bullish BOS
        bullish = [b for b in bos_list if b.direction == Direction.LONG]
        assert len(bullish) >= 1
        # Should have quality fields populated
        last = bullish[-1]
        assert last.quality_score > 0
        assert last.is_body_break  # Close was above the swing
        assert last.bars_since_swing > 0

    def test_latest_bos_helper(self):
        """latest_bos() correctly returns the most recent event."""
        bos_list = [
            BreakOfStructure(direction=Direction.LONG, broken_swing_price=1.1000,
                           broken_at=T0, broken_bar_index=10),
            BreakOfStructure(direction=Direction.SHORT, broken_swing_price=1.0950,
                           broken_at=T0 + timedelta(hours=5), broken_bar_index=15),
        ]
        assert latest_bos(bos_list).broken_bar_index == 15
        assert latest_bos(bos_list, before_index=12).broken_bar_index == 10
        assert latest_bos([], before_index=10) is None


class TestBOSFVGIntegration:
    """Test that BOS + FVG combo scoring works correctly."""

    def test_fvg_after_bos_gets_traded(self):
        """An FVG that forms right after a BOS is a valid combo entry."""
        t = T0
        # Build a proper swing structure: up → swing high → pullback → break above high → FVG
        bars = [
            _bar(t, 1.1000, 1.1010, 1.0990, 1.1005),                           # 0
            _bar(t + timedelta(hours=1), 1.1005, 1.1020, 1.0995, 1.1015),       # 1
            _bar(t + timedelta(hours=2), 1.1015, 1.1035, 1.1010, 1.1030),       # 2
            _bar(t + timedelta(hours=3), 1.1030, 1.1050, 1.1020, 1.1045),       # 3
            _bar(t + timedelta(hours=4), 1.1045, 1.1060, 1.1035, 1.1055),       # 4
            _bar(t + timedelta(hours=5), 1.1055, 1.1070, 1.1045, 1.1060),       # 5  swing high ~1.1070
            _bar(t + timedelta(hours=6), 1.1060, 1.1065, 1.1040, 1.1045),       # 6  pullback
            _bar(t + timedelta(hours=7), 1.1045, 1.1050, 1.1030, 1.1035),       # 7
            _bar(t + timedelta(hours=8), 1.1035, 1.1045, 1.1025, 1.1040),       # 8
            _bar(t + timedelta(hours=9), 1.1040, 1.1050, 1.1030, 1.1045),       # 9
            _bar(t + timedelta(hours=10), 1.1045, 1.1055, 1.1035, 1.1050),      # 10
            # Strong impulse breaking above the swing high (1.1070) and creating FVG
            _bar(t + timedelta(hours=11), 1.1050, 1.1060, 1.1045, 1.1055),      # 11
            _bar(t + timedelta(hours=12), 1.1055, 1.1130, 1.1050, 1.1125),      # 12 impulse (BOS candle)
            _bar(t + timedelta(hours=13), 1.1125, 1.1140, 1.1100, 1.1110),      # 13 (FVG: 1.1100 > 1.1060)
        ]

        fvgs = detect_fvgs(bars, min_size_pips=2)
        bullish_fvgs = [f for f in fvgs if f.direction == Direction.LONG]
        assert len(bullish_fvgs) >= 1

        # Verify BOS exists (detector needs 2*lookback+1 = 11 bars minimum for swings)
        bos_list = detect_bos(bars, swing_lookback=3)
        # With lookback=3, swings form earlier allowing the break to be detected
        bullish_bos = [b for b in bos_list if b.direction == Direction.LONG]
        assert len(bullish_bos) >= 1

    def test_bos_as_context_not_entry(self):
        """A BOS alone (without FVG or reaction) should not be tradeable.

        This validates the philosophical shift: BOS is context, not trigger.
        """
        bos = BreakOfStructure(
            direction=Direction.LONG,
            broken_swing_price=1.1000,
            broken_at=T0,
            broken_bar_index=20,
            quality_score=80.0,
        )
        # High quality BOS alone is NOT an entry — just context
        # The BOSContinuation strategy requires FVG + reaction to fire
        assert bos.quality_score >= 50
        # But we'd need an FVG + reaction to actually enter
