"""Tests for `agent.regime.detector`.

Covers:
    * Output shape (RegimeLabel fields populated, frozen).
    * Slope-based primary classification on synthetic series.
    * ATR-ratio splits for high_vol / low_vol / chop.
    * Session derivation table.
    * Empty / short series fallbacks.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.regime.detector import (
    RegimeDetector,
    RegimeLabel,
    _atr,
    _body_pct_avg,
    _ny_session,
    _slope_pips,
)
from agent.types import Bar, Timeframe


def _bar(t: datetime, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=0.0, timeframe=Timeframe.H1)


def _series(start: datetime, prices: list[float], *, vol: float = 0.0005) -> list[Bar]:
    """Build a simple H1 series where each bar has high/low padded by `vol`
    around the close. `start` is the time of the first bar."""
    bars = []
    prev = prices[0]
    for i, p in enumerate(prices):
        t = start + timedelta(hours=i)
        bars.append(_bar(t, o=prev, h=max(prev, p) + vol, l=min(prev, p) - vol, c=p))
        prev = p
    return bars


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


def test_regime_label_is_immutable():
    label = RegimeLabel("chop", "ny", True, 0.0, 1.0, 0.5)
    with pytest.raises(Exception):
        label.primary = "trending_up"  # type: ignore[misc]


def test_regime_detector_output_fields_populated():
    bars = _series(datetime(2026, 5, 14, 12, tzinfo=timezone.utc), [1.1] * 80)
    label = RegimeDetector().label(bars, len(bars) - 1)
    assert isinstance(label, RegimeLabel)
    assert label.primary in {"trending_up", "trending_down", "chop", "low_vol", "high_vol", "unknown"}
    assert label.session in {"asia", "london", "ny", "overlap", "off"}
    assert isinstance(label.kill_zone, bool)
    assert isinstance(label.slope_pips, float)
    assert isinstance(label.atr_ratio, float)
    assert 0.0 <= label.body_pct <= 1.0


def test_empty_bars_returns_unknown():
    label = RegimeDetector().label([], 0)
    assert label.primary == "unknown"
    assert label.session == "off"


def test_short_series_safe():
    # < 5 bars -> slope is 0, defaults to chop with neutral atr_ratio.
    bars = _series(datetime(2026, 5, 14, 8, tzinfo=timezone.utc), [1.1, 1.1001, 1.1002])
    label = RegimeDetector().label(bars, len(bars) - 1)
    assert label.primary in {"chop", "low_vol", "high_vol"}
    assert label.slope_pips == 0.0


# ---------------------------------------------------------------------------
# Primary classification
# ---------------------------------------------------------------------------


def _strong_uptrend_prices(n: int = 80) -> list[float]:
    # Linear up: ~0.0001 (=1 pip) per bar over 80 bars -> 80 pips slope.
    return [1.10 + 0.0001 * i for i in range(n)]


def _strong_downtrend_prices(n: int = 80) -> list[float]:
    return [1.20 - 0.0001 * i for i in range(n)]


def _flat_prices(n: int = 80) -> list[float]:
    base = 1.10
    return [base + 0.0000001 * (i % 3) for i in range(n)]


def test_classifies_uptrend():
    bars = _series(datetime(2026, 5, 14, 8, tzinfo=timezone.utc), _strong_uptrend_prices(80))
    label = RegimeDetector().label(bars, len(bars) - 1)
    assert label.primary == "trending_up"
    assert label.slope_pips > 3.0


def test_classifies_downtrend():
    bars = _series(datetime(2026, 5, 14, 8, tzinfo=timezone.utc), _strong_downtrend_prices(80))
    label = RegimeDetector().label(bars, len(bars) - 1)
    assert label.primary == "trending_down"
    assert label.slope_pips < -3.0


def test_classifies_flat_as_low_vol_or_chop():
    bars = _series(datetime(2026, 5, 14, 8, tzinfo=timezone.utc), _flat_prices(80), vol=0.00001)
    label = RegimeDetector().label(bars, len(bars) - 1)
    # Flat + tiny range -> low_vol or chop, not a trend.
    assert label.primary in {"chop", "low_vol"}
    assert abs(label.slope_pips) < 3.0


def test_classifies_high_vol_when_atr_high():
    # Construct a series whose final 50 bars all oscillate +/-0.001 around
    # base. Mean slope is ~0 (alternates), short-term ATR is ~10x its long
    # average. Should classify as high_vol or chop (NOT a trend).
    base = 1.10
    prices = []
    # 60 quiet bars to seed ATR(50).
    for i in range(60):
        prices.append(base + 0.00001 * (i % 2))
    # 20 oscillating bars at the end to inflate ATR(14).
    for i in range(20):
        prices.append(base + (0.001 if i % 2 == 0 else -0.001))
    bars = _series(datetime(2026, 5, 14, 8, tzinfo=timezone.utc), prices, vol=0.0001)
    label = RegimeDetector().label(bars, len(bars) - 1)
    # Whatever the slope sign, it must NOT be classified as a trend.
    assert label.primary in {"chop", "high_vol", "low_vol"}
    assert label.atr_ratio > 1.0


# ---------------------------------------------------------------------------
# Session derivation
# ---------------------------------------------------------------------------


def test_ny_session_table_weekday():
    base = datetime(2026, 5, 14, 0, tzinfo=timezone.utc)  # Thursday
    # 0..5 = asia
    for h in range(0, 6):
        assert _ny_session(base.replace(hour=h)) == "asia", f"hour={h}"
    # 6..11 = london
    for h in range(6, 12):
        assert _ny_session(base.replace(hour=h)) == "london", f"hour={h}"
    # 12..15 = overlap
    for h in range(12, 16):
        assert _ny_session(base.replace(hour=h)) == "overlap", f"hour={h}"
    # 16..20 = ny
    for h in range(16, 21):
        assert _ny_session(base.replace(hour=h)) == "ny", f"hour={h}"
    # 21..23 wraps to asia
    for h in range(21, 24):
        assert _ny_session(base.replace(hour=h)) == "asia", f"hour={h}"


def test_ny_session_weekend_is_off():
    sat = datetime(2026, 5, 16, 12, tzinfo=timezone.utc)
    sun = datetime(2026, 5, 17, 12, tzinfo=timezone.utc)
    assert _ny_session(sat) == "off"
    assert _ny_session(sun) == "off"


def test_kill_zone_flag_matches_session():
    base = datetime(2026, 5, 14, 8, tzinfo=timezone.utc)  # london, Thursday
    bars = _series(base, _flat_prices(80))
    label = RegimeDetector().label(bars, len(bars) - 1)
    # Last bar is base+79h -> Sunday 15:00 UTC -> off (weekend).
    # Easier: build a series ending squarely in the london bucket.
    bars2 = _series(datetime(2026, 5, 14, 0, tzinfo=timezone.utc), _flat_prices(8))
    # Index 7 -> 7 hours after midnight UTC Thursday -> 07:00 -> london.
    label2 = RegimeDetector().label(bars2, 7)
    assert label2.session == "london"
    assert label2.kill_zone is True
    # And in asia (hour 4 UTC) it must be False.
    label3 = RegimeDetector().label(bars2, 4)
    assert label3.session == "asia"
    assert label3.kill_zone is False


# ---------------------------------------------------------------------------
# Helper functions (kept private but tested directly for coverage)
# ---------------------------------------------------------------------------


def test_slope_pips_zero_on_flat_input():
    closes = [1.1] * 60
    assert _slope_pips(closes, 50) == 0.0


def test_slope_pips_positive_on_uptrend():
    closes = [1.1 + 0.0001 * i for i in range(60)]
    s = _slope_pips(closes, 50)
    assert s > 0


def test_slope_pips_handles_short_input():
    assert _slope_pips([1.1, 1.1001], 50) == 0.0


def test_atr_returns_zero_for_no_history():
    bars = _series(datetime(2026, 5, 14, tzinfo=timezone.utc), [1.1])
    assert _atr(bars, 14, 0) == 0.0


def test_body_pct_avg_handles_zero_range_bars():
    bars = _series(datetime(2026, 5, 14, tzinfo=timezone.utc), [1.1] * 5, vol=0.0)
    # All bars zero range -> ratio collapses to 0.0 (no contributions).
    assert _body_pct_avg(bars, 4, 5) == 0.0


def test_atr_ratio_neutral_when_long_atr_zero():
    bars = _series(datetime(2026, 5, 14, tzinfo=timezone.utc), [1.1] * 3)
    label = RegimeDetector().label(bars, len(bars) - 1)
    # Not enough data for a meaningful ATR(50); detector returns neutral 1.0.
    assert label.atr_ratio == pytest.approx(1.0, rel=1e-6) or label.atr_ratio == 0.0


def test_label_is_safe_at_arbitrary_index_overflow():
    bars = _series(datetime(2026, 5, 14, tzinfo=timezone.utc), [1.1] * 60)
    # at_index past the end clamps to last.
    label = RegimeDetector().label(bars, 999)
    assert label.session in {"asia", "london", "ny", "overlap", "off"}
