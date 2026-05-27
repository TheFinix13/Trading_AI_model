"""Tests for the per-strategy GateProfile system.

Verifies that:
  1. Default profile applies all gates.
  2. LZI profile bypasses precision_partner, structural_anchor, close_confirmation.
  3. ML score override works.
  4. Blocked hours override works.
  5. validate_setup_gates respects profile flags.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.config import (
    GATE_PROFILE_DEFAULT,
    GATE_PROFILE_LZI,
    GATE_PROFILES,
    GateProfile,
    load_config,
)
from agent.rules.engine import RuleEngine
from agent.types import Bar, Direction, Setup, Timeframe


def _bar(t, o, h, l, c, tf=Timeframe.H1):
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=1000.0, timeframe=tf)


def _make_setup(
    *,
    direction=Direction.LONG,
    confluences=None,
    strategy_name=None,
    entry=1.1000,
    stop=1.0970,
    tp=1.1050,
    tf=Timeframe.H1,
):
    return Setup(
        direction=direction,
        timeframe=tf,
        detected_at=datetime(2025, 5, 15, 14, 0, tzinfo=timezone.utc),
        detected_bar_index=100,
        entry=entry,
        stop=stop,
        take_profit=tp,
        confluences=confluences or ["zone", "fvg", "fib_382", "session_ny"],
        strategy_name=strategy_name,
    )


def _make_bars(n=200, tf=Timeframe.H1):
    """Generate a sequence of bars around 1.1000 for testing."""
    base_time = datetime(2025, 5, 15, 0, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        t = base_time.replace(hour=i % 24, day=15 + i // 24)
        bars.append(_bar(t, 1.0990, 1.1010, 1.0980, 1.1000, tf=tf))
    return bars


class TestDefaultProfileAppliesAllGates:
    """Default profile must have all gates active."""

    def test_all_flags_true(self):
        p = GATE_PROFILE_DEFAULT
        assert p.check_rr_minimum is True
        assert p.check_daily_dd_halt is True
        assert p.check_max_positions is True
        assert p.check_stop_bounds is True
        assert p.require_precision_partner is True
        assert p.require_structural_anchor is True
        assert p.require_close_confirmation is True
        assert p.reject_false_breakouts is True
        assert p.require_fvg_or_sweep_with_bos is True
        assert p.check_blocked_sessions is True
        assert p.check_blocked_hours is True
        assert p.check_min_confluences is True
        assert p.apply_caution_days_boost is True
        assert p.apply_ml_scorer is True

    def test_no_overrides(self):
        p = GATE_PROFILE_DEFAULT
        assert p.ml_score_override is None
        assert p.blocked_hours_override is None

    def test_default_rejects_setup_missing_precision_partner(self):
        cfg = load_config()
        engine = RuleEngine(cfg)
        # 3 confluences to pass H1 min_confluences, but no precision partner
        setup = _make_setup(confluences=["zone", "bos", "session_ny"])
        bars = _make_bars()
        passed, reason = engine.validate_setup_gates(setup, bars, 100, GATE_PROFILE_DEFAULT)
        assert not passed
        assert reason == "precision_partner"

    def test_default_rejects_setup_missing_structural_anchor(self):
        cfg = load_config()
        engine = RuleEngine(cfg)
        # Has precision partner (fvg) but no structural anchor
        setup = _make_setup(confluences=["zone", "fvg", "near_PDH"])
        bars = _make_bars()
        passed, reason = engine.validate_setup_gates(setup, bars, 100, GATE_PROFILE_DEFAULT)
        assert not passed
        assert reason == "structural_anchor"


class TestLZIProfileBypassesRedundantGates:
    """LZI profile must bypass precision_partner, structural_anchor,
    close_confirmation, false_breakouts, fvg_or_sweep_with_bos,
    min_confluences."""

    def test_lzi_flags(self):
        p = GATE_PROFILE_LZI
        assert p.require_precision_partner is False
        assert p.require_structural_anchor is False
        assert p.require_close_confirmation is False
        assert p.reject_false_breakouts is False
        assert p.require_fvg_or_sweep_with_bos is False
        assert p.check_min_confluences is False
        assert p.apply_caution_days_boost is False
        # Safety gates stay on
        assert p.check_rr_minimum is True
        assert p.check_stop_bounds is True
        assert p.apply_ml_scorer is True

    def test_lzi_passes_setup_without_precision_partner(self):
        cfg = load_config()
        engine = RuleEngine(cfg)
        setup = _make_setup(
            confluences=["lzi_retest", "displacement"],
            strategy_name="LiquidityGrabReversal",
        )
        bars = _make_bars()
        passed, reason = engine.validate_setup_gates(setup, bars, 100, GATE_PROFILE_LZI)
        assert passed, f"Expected pass but got: {reason}"

    def test_lzi_still_checks_rr(self):
        cfg = load_config()
        engine = RuleEngine(cfg)
        setup = _make_setup(
            confluences=["lzi_retest"],
            strategy_name="LiquidityGrabReversal",
            entry=1.1000,
            stop=1.0995,
            tp=1.1002,
        )
        bars = _make_bars()
        passed, reason = engine.validate_setup_gates(setup, bars, 100, GATE_PROFILE_LZI)
        assert not passed
        assert reason == "rr_minimum"

    def test_profile_lookup_by_strategy_name(self):
        assert GATE_PROFILES.get("LiquidityGrabReversal") is GATE_PROFILE_LZI
        assert GATE_PROFILES.get("lzi_retest") is GATE_PROFILE_LZI
        assert GATE_PROFILES.get("default") is GATE_PROFILE_DEFAULT
        assert GATE_PROFILES.get("UnknownStrategy") is None


class TestMLScoreOverride:
    """Profile's ml_score_override must be used instead of global threshold."""

    def test_lzi_has_lower_ml_threshold(self):
        p = GATE_PROFILE_LZI
        assert p.ml_score_override == 0.40

    def test_default_has_no_override(self):
        p = GATE_PROFILE_DEFAULT
        assert p.ml_score_override is None


class TestBlockedHoursOverride:
    """Profile's blocked_hours_override restricts the blocked-hour set."""

    def test_lzi_only_blocks_hour_13(self):
        p = GATE_PROFILE_LZI
        assert p.blocked_hours_override == [13]

    def test_default_uses_global_blocked_hours(self):
        p = GATE_PROFILE_DEFAULT
        assert p.blocked_hours_override is None

    def test_lzi_passes_at_hour_3_ny(self):
        """LZI should pass at NY hour 3 (London open chop) which is
        blocked for default strategies."""
        cfg = load_config()
        engine = RuleEngine(cfg)
        # NY hour 3 = UTC hour 8 (EDT). Use Wednesday to avoid Thu no_trade_day.
        t = datetime(2025, 5, 14, 8, 0, tzinfo=timezone.utc)
        bars = _make_bars()
        bars[100] = _bar(t, 1.0990, 1.1010, 1.0980, 1.1000)
        setup = _make_setup(
            confluences=["lzi_retest", "displacement"],
            strategy_name="LiquidityGrabReversal",
        )
        setup.detected_at = t
        passed, reason = engine.validate_setup_gates(setup, bars, 100, GATE_PROFILE_LZI)
        assert passed, f"LZI should pass at NY hour 3, but failed: {reason}"

    def test_lzi_blocked_at_hour_13_ny(self):
        """LZI should still be blocked at NY hour 13 (pre-close chop)."""
        cfg = load_config()
        engine = RuleEngine(cfg)
        # NY hour 13 = UTC hour 17 (during EDT). Use Wednesday to avoid Thu no_trade_day.
        t = datetime(2025, 5, 14, 17, 0, tzinfo=timezone.utc)
        bars = _make_bars()
        bars[100] = _bar(t, 1.0990, 1.1010, 1.0980, 1.1000)
        setup = _make_setup(
            confluences=["lzi_retest"],
            strategy_name="LiquidityGrabReversal",
        )
        setup.detected_at = t
        passed, reason = engine.validate_setup_gates(setup, bars, 100, GATE_PROFILE_LZI)
        assert not passed
        assert reason == "blocked_hour"


class TestGateProfileCustom:
    """Verify that custom profiles can be constructed and used."""

    def test_custom_profile_partial_relaxation(self):
        p = GateProfile(
            name="custom",
            require_precision_partner=False,
            require_structural_anchor=True,
        )
        assert p.require_precision_partner is False
        assert p.require_structural_anchor is True
        assert p.check_rr_minimum is True
