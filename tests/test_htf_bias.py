"""HTF bias helper — causality, direction, and dead-band."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.alphas.concepts._htf import HTFBias, _resample_factor, htf_bias_at
from agent.types import Bar, Direction, Timeframe


def _bars(n: int, slope_pips_per_bar: float, tf: Timeframe = Timeframe.H4) -> list[Bar]:
    """Synthetic series with a constant pip slope per bar so we can compute the
    expected bias analytically."""
    out = []
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = 1.1000
    for i in range(n):
        c = price + slope_pips_per_bar * 0.0001
        o = price
        h = max(o, c) + 0.0001
        l = min(o, c) - 0.0001
        out.append(Bar(time=t0 + timedelta(hours=tf.minutes // 60 or 1, minutes=tf.minutes) * 0,
                       open=o, high=h, low=l, close=c, volume=100.0, timeframe=tf))
        # bar.time isn't actually used by htf_bias_at, but be tidy:
        out[-1].time = t0 + timedelta(minutes=tf.minutes * i)
        price = c
    return out


class TestResampleFactor:
    def test_h4_to_d1_is_6(self):
        assert _resample_factor("H4", "D1") == 6

    def test_h1_to_h4_is_4(self):
        assert _resample_factor("H1", "H4") == 4

    def test_same_tf_is_1(self):
        assert _resample_factor("H4", "H4") == 1

    def test_higher_to_lower_raises(self):
        with pytest.raises(ValueError):
            _resample_factor("D1", "H1")

    def test_non_divisible_raises(self):
        with pytest.raises(ValueError):
            _resample_factor("H1", "M30")  # would be 0.5


class TestHTFBias:
    def test_up_when_recent_move_clears_threshold(self):
        # H4 series rising 10 pips/bar; D1 = 6 H4 bars, lookback=5 ⇒ 30 H4 bars back.
        # Move pips between now and -30 H4 bars = 300 pips, well > 30 threshold.
        bars = _bars(60, slope_pips_per_bar=10.0, tf=Timeframe.H4)
        bias = htf_bias_at(bars, len(bars) - 1, htf="D1", htf_lookback=5)
        assert bias is HTFBias.UP

    def test_down_when_recent_move_clears_threshold(self):
        bars = _bars(60, slope_pips_per_bar=-10.0, tf=Timeframe.H4)
        bias = htf_bias_at(bars, len(bars) - 1, htf="D1", htf_lookback=5)
        assert bias is HTFBias.DOWN

    def test_neutral_inside_dead_band(self):
        # Flat series — 0 pips of movement, threshold is 30 pips ⇒ NEUTRAL.
        bars = _bars(60, slope_pips_per_bar=0.0, tf=Timeframe.H4)
        bias = htf_bias_at(bars, len(bars) - 1, htf="D1", htf_lookback=5)
        assert bias is HTFBias.NEUTRAL

    def test_neutral_when_history_too_short(self):
        # Need >= 6*5 + 6 = 36 H4 bars for D1/5 lookback; give it 20 ⇒ NEUTRAL.
        bars = _bars(20, slope_pips_per_bar=10.0, tf=Timeframe.H4)
        bias = htf_bias_at(bars, len(bars) - 1, htf="D1", htf_lookback=5)
        assert bias is HTFBias.NEUTRAL

    def test_neutral_for_unknown_htf(self):
        bars = _bars(60, slope_pips_per_bar=10.0, tf=Timeframe.H4)
        bias = htf_bias_at(bars, len(bars) - 1, htf="W1", htf_lookback=5)
        assert bias is HTFBias.NEUTRAL

    def test_neutral_when_target_tf_lower_than_source(self):
        # D1 source → H4 target would be downgrading, not upgrading.
        bars = _bars(60, slope_pips_per_bar=10.0, tf=Timeframe.D1)
        bias = htf_bias_at(bars, len(bars) - 1, htf="H4", htf_lookback=5)
        assert bias is HTFBias.NEUTRAL

    def test_bias_is_strictly_causal(self):
        """Add ONE giant up-bar at the END of a down-sloping series and confirm
        the bias at an earlier index does NOT flip up. If the helper peeked
        forward this test would fail."""
        bars = _bars(60, slope_pips_per_bar=-10.0, tf=Timeframe.H4)
        # Bar at the end carries a 1000-pip up close.
        bars[-1].close = bars[-1].open + 0.1000
        bars[-1].high = bars[-1].close + 0.0010
        # Bias evaluated at an earlier bar must STILL be DOWN.
        bias = htf_bias_at(bars, len(bars) - 5, htf="D1", htf_lookback=5)
        assert bias is HTFBias.DOWN


class TestHTFBiasMatches:
    def test_up_matches_long_only(self):
        assert HTFBias.UP.matches(Direction.LONG)
        assert not HTFBias.UP.matches(Direction.SHORT)

    def test_down_matches_short_only(self):
        assert HTFBias.DOWN.matches(Direction.SHORT)
        assert not HTFBias.DOWN.matches(Direction.LONG)

    def test_neutral_matches_neither(self):
        assert not HTFBias.NEUTRAL.matches(Direction.LONG)
        assert not HTFBias.NEUTRAL.matches(Direction.SHORT)
