"""Unit tests for the four new ICT-style detectors.

Note on times: all UTC. NY local = UTC-4 in April (EDT). The NY trading "day"
in our daily-level bucketer is calendar NY date, so a UTC-Apr-28 bar at hour
03:00 belongs to NY-Apr-27 (23:00 EDT prev). Tests use bars within a single
NY day to keep assertions clean."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.detectors.daily_levels import compute_daily_levels, nearest_level
from agent.detectors.liquidity_sweep import detect_liquidity_sweeps
from agent.detectors.range_phase import label_range_phases
from agent.detectors.sessions import is_kill_zone, label_bars, label_session
from agent.types import Bar, Timeframe


def _b(day: int, hour: int, h: float, l: float, c: float, o: float | None = None) -> Bar:
    o = o if o is not None else (h + l) / 2
    return Bar(
        time=datetime(2026, 4, day, hour, 0, tzinfo=timezone.utc),
        open=o, high=h, low=l, close=c, volume=100, timeframe=Timeframe.M15,
    )


# --- sessions ----------------------------------------------------------------

class TestSessions:
    def test_ny_morning_is_overlap(self):
        # 13:30 UTC = 09:30 EDT (DST in April)
        assert label_session(datetime(2026, 4, 28, 13, 30, tzinfo=timezone.utc)) == "london_ny_overlap"

    def test_ny_afternoon_is_ny(self):
        # 18:00 UTC = 14:00 EDT
        assert label_session(datetime(2026, 4, 28, 18, 0, tzinfo=timezone.utc)) == "ny"

    def test_late_night_is_asia(self):
        # 01:00 UTC = 21:00 EDT prev day
        assert label_session(datetime(2026, 4, 29, 1, 0, tzinfo=timezone.utc)) == "asia"

    def test_dead_zone_is_off(self):
        # 21:30 UTC = 17:30 EDT (between NY close and Asia open)
        assert label_session(datetime(2026, 4, 28, 21, 30, tzinfo=timezone.utc)) == "off"

    def test_label_bars_matches_label_session(self):
        bars = [_b(28, h, 1.17, 1.16, 1.165) for h in range(0, 24, 4)]
        labels = label_bars(bars)
        assert len(labels) == len(bars)
        for b, lbl in zip(bars, labels):
            assert lbl == label_session(b.time)

    def test_kill_zone_set(self):
        assert is_kill_zone("london")
        assert is_kill_zone("london_ny_overlap")
        assert is_kill_zone("ny")
        assert not is_kill_zone("asia")
        assert not is_kill_zone("off")


# --- daily levels ------------------------------------------------------------

class TestDailyLevels:
    def test_first_bar_of_dataset_has_no_prior(self):
        # The very first bar of any dataset cannot reference yesterday — it's day 0.
        bars = [_b(28, h, 1.1745, 1.1705, 1.1730) for h in range(8, 18)]
        out = compute_daily_levels(bars)
        assert out[0].pdh is None and out[0].pdl is None

    def test_second_day_uses_first_day_range(self):
        # Day 1: 09:00–17:00 UTC = 05:00–13:00 EDT, all on NY-Apr-28.
        d1 = [_b(28, h, 1.1745, 1.1705, 1.1730) for h in range(9, 18)]
        # Day 2: 13:00 UTC Apr-29 = 09:00 EDT Apr-29 (clearly NY-Apr-29).
        d2 = [_b(29, 13, 1.1738, 1.1712, 1.1725)]
        out = compute_daily_levels(d1 + d2)
        L = out[-1]
        assert L.pdh == pytest.approx(1.1745)
        assert L.pdl == pytest.approx(1.1705)
        assert L.pdm == pytest.approx(1.1725)

    def test_nearest_level_within_tolerance(self):
        d1 = [_b(28, h, 1.1745, 1.1705, 1.1730) for h in range(9, 18)]
        d2 = [_b(29, 13, 1.1738, 1.1712, 1.1725)]
        out = compute_daily_levels(d1 + d2)
        nl = nearest_level(out[-1], 1.17452, max_pips=10.0)
        assert nl is not None and nl[0] == "PDH"

    def test_nearest_level_returns_none_when_far(self):
        d1 = [_b(28, h, 1.1745, 1.1705, 1.1730) for h in range(9, 18)]
        d2 = [_b(29, 13, 1.1738, 1.1712, 1.1725)]
        out = compute_daily_levels(d1 + d2)
        assert nearest_level(out[-1], 1.20000, max_pips=15.0) is None


# --- liquidity sweep ---------------------------------------------------------

class TestLiquiditySweep:
    def _two_day_series(self):
        # Day 1: tight range so PDH = 1.1745, all bars on NY-Apr-28.
        bars = [_b(28, h, 1.1745, 1.1705, 1.1730) for h in range(9, 18)]
        # Day 2: morning sweep above PDH then immediate reversal lower.
        # Open is set explicitly BELOW PDH so the bar's body is below the level
        # (otherwise the level falls below ref=max(o,c) and is treated as a
        # *lower* target instead of an upper one).
        bars += [
            _b(29, 13, 1.1748, 1.1735, 1.1740, o=1.1738),  # near PDH
            _b(29, 14, 1.1772, 1.1738, 1.1710, o=1.1740),  # spike above PDH, close below
            _b(29, 15, 1.1715, 1.1690, 1.1695, o=1.1710),  # confirmation lower
        ]
        return bars

    def test_buyside_sweep_detected(self):
        sweeps = detect_liquidity_sweeps(self._two_day_series(), confirm_pips=10.0)
        buyside = [s for s in sweeps if s.side == "buyside"]
        assert any(s.swept_label == "PDH" for s in buyside)

    def test_no_sweeps_on_flat_data(self):
        bars = [_b(28, h, 1.1730, 1.1730, 1.1730) for h in range(24)]
        sweeps = detect_liquidity_sweeps(bars)
        assert sweeps == []


# --- range phase -------------------------------------------------------------

class TestRangePhase:
    def test_off_session_tagged_off(self):
        # 21:30 UTC = 17:30 EDT = "off" session
        bars = [_b(28, 21, 1.1745, 1.1705, 1.1730)]
        out = label_range_phases(bars)
        assert out[0].phase == "off"

    def test_asia_with_no_sweep_is_accumulation(self):
        # 02:00 UTC = 22:00 EDT = asia
        bars = [_b(28, 2, 1.1745, 1.1705, 1.1730)]
        out = label_range_phases(bars)
        assert out[0].phase == "accumulation"
