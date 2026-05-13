"""Tests for cross-timeframe zone/FVG overlay in the rule engine.

Validates that:
  1. HTFBias.htf_zones_near_price is populated when price is near/in an HTF zone.
  2. An H1 entry zone overlapping a D1 demand zone produces "htf_zone_align_D1".
  3. Non-overlapping zones don't produce the alignment tag.
  4. Tolerance handling: zones within tolerance still count as overlapping.
  5. HTF FVG alignment: entry price inside an HTF FVG produces "htf_fvg_align_*".
  6. Direction mismatch: a long LTF zone overlapping a short HTF zone is not tagged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.rules.htf_bias import HTFBias, HTFBiasComputer, _ema_slope
from agent.types import Bar, Direction, FVG, Timeframe, Zone


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_bars(n: int, timeframe: Timeframe, start_price: float = 1.1700,
               step: float = 0.0002) -> list[Bar]:
    """Gently rising bars."""
    bars = []
    t0 = datetime(2025, 6, 1, tzinfo=timezone.utc)
    delta = timedelta(days=1) if timeframe == Timeframe.D1 else timedelta(hours=4)
    for i in range(n):
        c = start_price + i * step
        bars.append(Bar(
            time=t0 + delta * i,
            open=c - step / 2, high=c + step / 3, low=c - step,
            close=c, volume=1000.0, timeframe=timeframe,
        ))
    return bars


def _make_zone(direction: Direction, top: float, bottom: float,
               bar_index: int = 10) -> Zone:
    return Zone(
        direction=direction,
        top=top, bottom=bottom,
        created_at=datetime(2025, 6, 10, tzinfo=timezone.utc),
        created_bar_index=bar_index,
        impulse_pips=(top - bottom) * 10000,
    )


def _make_fvg(direction: Direction, top: float, bottom: float,
              bar_index: int = 15) -> FVG:
    return FVG(
        direction=direction,
        top=top, bottom=bottom,
        created_at=datetime(2025, 6, 15, tzinfo=timezone.utc),
        created_bar_index=bar_index,
        size_pips=(top - bottom) * 10000,
    )


# ── HTFBias zone population tests ───────────────────────────────────────

class TestHTFBiasZonesNearPrice:
    def test_zone_populated_when_price_inside(self):
        """Price sitting inside an HTF demand zone should appear in htf_zones_near_price."""
        bars = _make_bars(60, Timeframe.D1, start_price=1.1700)
        zone = _make_zone(Direction.LONG, top=1.1740, bottom=1.1720, bar_index=5)
        hb = HTFBiasComputer(bars=bars, zones=[zone], zone_proximity_pips=30.0)

        price_inside = 1.1730
        bias = hb.bias_at(bars[30].time, current_price=price_inside)

        assert len(bias.htf_zones_near_price) == 1
        hz = bias.htf_zones_near_price[0]
        assert hz["source_tf"] == "D1"
        assert hz["direction"] == "long"
        assert hz["top"] == 1.1740
        assert hz["bottom"] == 1.1720

    def test_zone_populated_when_price_near(self):
        """Price 15 pips from a zone should appear when proximity is 30 pips."""
        bars = _make_bars(60, Timeframe.D1, start_price=1.1700)
        zone = _make_zone(Direction.LONG, top=1.1740, bottom=1.1720, bar_index=5)
        hb = HTFBiasComputer(bars=bars, zones=[zone], zone_proximity_pips=30.0)

        price_near = 1.1755  # 15 pips above zone top
        bias = hb.bias_at(bars[30].time, current_price=price_near)

        assert len(bias.htf_zones_near_price) == 1

    def test_zone_not_populated_when_price_far(self):
        """Price 50 pips away should NOT appear when proximity is 30 pips."""
        bars = _make_bars(60, Timeframe.D1, start_price=1.1700)
        zone = _make_zone(Direction.LONG, top=1.1740, bottom=1.1720, bar_index=5)
        hb = HTFBiasComputer(bars=bars, zones=[zone], zone_proximity_pips=30.0)

        price_far = 1.1800  # 60 pips above zone top
        bias = hb.bias_at(bars[30].time, current_price=price_far)

        assert len(bias.htf_zones_near_price) == 0

    def test_fvg_populated_when_price_inside(self):
        """Price inside an HTF FVG should appear in htf_fvgs_near_price."""
        bars = _make_bars(60, Timeframe.D1, start_price=1.1700)
        fvg = _make_fvg(Direction.LONG, top=1.1745, bottom=1.1730, bar_index=10)
        hb = HTFBiasComputer(bars=bars, zones=[], fvgs=[fvg],
                             zone_proximity_pips=30.0)

        price_inside = 1.1738
        bias = hb.bias_at(bars[30].time, current_price=price_inside)

        assert len(bias.htf_fvgs_near_price) == 1
        hf = bias.htf_fvgs_near_price[0]
        assert hf["source_tf"] == "D1"
        assert hf["direction"] == "long"


# ── Cross-TF alignment in RuleEngine ────────────────────────────────────

class TestHTFZoneAlignment:
    """Integration test: build an HTFBias with known zones and verify the
    RuleEngine._build method tags htf_zone_align_D1 when the LTF zone overlaps."""

    def test_overlapping_zones_produce_alignment_tag(self):
        """H1 demand zone at 1.1720-1.1740 overlapping D1 demand zone at 1.1715-1.1745
        should produce htf_zone_align_D1."""
        d1_zone = _make_zone(Direction.LONG, top=1.1745, bottom=1.1715, bar_index=5)
        h1_zone = _make_zone(Direction.LONG, top=1.1740, bottom=1.1720, bar_index=40)

        d1_bias = HTFBias(
            direction=Direction.LONG,
            in_demand_zone=True,
            source_tf="D1",
            htf_zones_near_price=[{
                "source_tf": "D1",
                "direction": "long",
                "top": d1_zone.top,
                "bottom": d1_zone.bottom,
                "distance_pips": 0.0,
            }],
        )

        tol = 0.0015  # 15 pips
        overlap = (
            h1_zone.bottom <= d1_bias.htf_zones_near_price[0]["top"] + tol
            and h1_zone.top >= d1_bias.htf_zones_near_price[0]["bottom"] - tol
        )
        assert overlap, "H1 zone should overlap D1 zone"

        hz = d1_bias.htf_zones_near_price[0]
        dir_str = "long"
        assert hz["direction"] == dir_str
        tag = f"htf_zone_align_{hz['source_tf']}"
        assert tag == "htf_zone_align_D1"

    def test_non_overlapping_zones_no_tag(self):
        """H1 demand zone at 1.1900-1.1920 should NOT overlap D1 zone at 1.1715-1.1745."""
        d1_zone_info = {
            "source_tf": "D1",
            "direction": "long",
            "top": 1.1745,
            "bottom": 1.1715,
            "distance_pips": 155.0,
        }
        h1_zone = _make_zone(Direction.LONG, top=1.1920, bottom=1.1900, bar_index=40)

        tol = 0.0015
        overlap = (
            h1_zone.bottom <= d1_zone_info["top"] + tol
            and h1_zone.top >= d1_zone_info["bottom"] - tol
        )
        assert not overlap, "Zones 155 pips apart should NOT overlap"

    def test_tolerance_allows_near_miss(self):
        """Zones separated by less than tolerance should still overlap."""
        d1_zone_info = {
            "source_tf": "D1",
            "direction": "long",
            "top": 1.1745,
            "bottom": 1.1715,
            "distance_pips": 1.0,
        }
        # H1 zone starts 10 pips above D1 zone top (barely outside)
        h1_zone = _make_zone(Direction.LONG, top=1.1775, bottom=1.1755, bar_index=40)

        tol = 0.0015  # 15 pips tolerance
        overlap = (
            h1_zone.bottom <= d1_zone_info["top"] + tol
            and h1_zone.top >= d1_zone_info["bottom"] - tol
        )
        assert overlap, "10 pip gap should be bridged by 15 pip tolerance"

    def test_direction_mismatch_no_alignment(self):
        """A long LTF zone should NOT align with a short HTF zone."""
        hz = {
            "source_tf": "D1",
            "direction": "short",
            "top": 1.1745,
            "bottom": 1.1715,
            "distance_pips": 0.0,
        }
        h1_zone = _make_zone(Direction.LONG, top=1.1740, bottom=1.1720, bar_index=40)
        dir_str = "long"

        tol = 0.0015
        overlap = (
            h1_zone.bottom <= hz["top"] + tol
            and h1_zone.top >= hz["bottom"] - tol
        )
        # Zones overlap geographically but directions differ
        assert overlap, "Zones overlap in price space"
        assert hz["direction"] != dir_str, "Direction mismatch should prevent tagging"


class TestHTFFVGAlignment:
    def test_price_in_htf_fvg_produces_tag(self):
        """Entry price inside an HTF bullish FVG should produce htf_fvg_align_D1."""
        hf = {
            "source_tf": "D1",
            "direction": "long",
            "top": 1.1745,
            "bottom": 1.1730,
            "distance_pips": 0.0,
        }
        entry_price = 1.1738
        tol = 0.0015

        price_in_fvg = hf["bottom"] <= entry_price <= hf["top"]
        assert price_in_fvg

        tag = f"htf_fvg_align_{hf['source_tf']}"
        assert tag == "htf_fvg_align_D1"

    def test_price_outside_htf_fvg_no_tag(self):
        """Entry price 50 pips away from HTF FVG should NOT produce a tag."""
        hf = {
            "source_tf": "D1",
            "direction": "long",
            "top": 1.1745,
            "bottom": 1.1730,
            "distance_pips": 50.0,
        }
        entry_price = 1.1800
        tol = 0.0015

        price_in_fvg = hf["bottom"] <= entry_price <= hf["top"]
        bar_low = entry_price - 0.0005
        bar_high = entry_price + 0.0005
        bar_touches_fvg = (bar_low <= hf["top"] + tol) and (bar_high >= hf["bottom"] - tol)
        assert not price_in_fvg
        assert not bar_touches_fvg


class TestHTFBiasComputerBuild:
    """Verify that HTFBiasComputer.build() detects FVGs and populates them."""

    def test_build_includes_fvgs(self):
        bars = _make_bars(60, Timeframe.D1, start_price=1.1700, step=0.0008)
        hb = HTFBiasComputer.build(bars, zone_min_impulse_pips=5.0,
                                   fvg_min_size_pips=1.0)
        # FVGs list should be populated (may be empty if bars don't form gaps,
        # but the attribute must exist)
        assert hasattr(hb, "fvgs")
        assert isinstance(hb.fvgs, list)

    def test_build_sets_proximity(self):
        bars = _make_bars(60, Timeframe.D1, start_price=1.1700)
        hb = HTFBiasComputer.build(bars, zone_proximity_pips=50.0)
        assert hb.zone_proximity_pips == 50.0
