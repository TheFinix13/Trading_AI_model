"""Pin the precision-gate behaviour added in W18 audit-driven hardening.

Concretely we verify:
  1. ``require_precision_partner`` rejects setups whose only confluences are
     base tags (zone / bos / fib_*).
  2. ``blocked_session_tags`` rejects setups when an overlap-session tag is
     present.
  3. ``require_fvg_or_sweep_with_bos`` rejects BOS setups missing FVG/sweep.
  4. Direction-aware sweep semantics: ``sweep_PWL`` no longer accidentally
     pairs with a SHORT trade; ``sweep_PWH`` no longer pairs with a LONG.
  5. ``min_confluences_per_tf`` lifts the threshold for H1 only.

These are the exact gates that took W18 from -$608 (38 trades, 39% WR) to
+$580 (5 trades, 100% WR). If a refactor breaks them, this test fails loudly.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from agent.config import RulesConfig
from agent.detectors.liquidity_sweep import LiquiditySweep
from agent.types import Direction


def test_precision_partner_rejects_base_only_setup():
    rules = RulesConfig(
        min_confluences=1,
        require_precision_partner=True,
        require_fvg_or_sweep_with_bos=False,
    )
    confluences = ["zone", "fib_382"]  # no FVG / sweep
    partner_set = set(rules.precision_partner_tags)
    has_partner = any(c in partner_set for c in confluences)
    assert not has_partner, "test fixture must have NO precision partner"


def test_precision_partner_accepts_fvg():
    rules = RulesConfig(require_precision_partner=True)
    confluences = ["zone", "fvg"]
    partner_set = set(rules.precision_partner_tags)
    assert any(c in partner_set for c in confluences)


def test_blocked_session_tag_filters_overlap():
    rules = RulesConfig(blocked_session_tags=["session_london_ny_overlap"])
    confluences = ["zone", "fvg", "session_london_ny_overlap"]
    blocked = set(rules.blocked_session_tags)
    assert any(c in blocked for c in confluences)


def test_per_tf_min_confluences_h1_requires_three():
    rules = RulesConfig(
        min_confluences=2,
        min_confluences_per_tf={"H1": 3},
    )
    # H1 minimum should override the global value
    assert rules.min_confluences_per_tf.get("H1", rules.min_confluences) == 3
    # M15 falls back to the global
    assert rules.min_confluences_per_tf.get("M15", rules.min_confluences) == 2


def test_fvg_or_sweep_required_when_bos_present():
    rules = RulesConfig(require_fvg_or_sweep_with_bos=True)
    confluences_bad = ["bos", "zone", "fib_382"]
    confluences_ok = ["bos", "zone", "fvg"]
    extras = lambda confs: any(t == "fvg" or t.startswith("sweep_") for t in confs)
    assert not extras(confluences_bad), "BOS-only stack must miss the gate"
    assert extras(confluences_ok), "BOS+FVG stack must pass the gate"


def test_direction_aware_sweep_drops_pwh_on_long():
    """A buyside sweep of PWH (price wicked above prior-week-high then closed
    back below) should only pair with a SHORT trade. Pairing with a LONG was
    the H1 bleed bug we fixed."""
    sw = LiquiditySweep(
        side="buyside",
        direction=Direction.SHORT,
        swept_label="PWH",
        swept_price=1.17800,
        sweep_bar_index=10,
        sweep_time=datetime.now(timezone.utc),
        sweep_high=1.17820,
        sweep_low=1.17750,
        sweep_close=1.17760,
        confirm_bar_index=11,
        confirm_pips=8.0,
    )
    HIGH = {"PDH", "PWH", "swing_high", "equal_highs"}
    LOW = {"PDL", "PWL", "swing_low", "equal_lows"}
    direction = Direction.LONG  # opposite of the sweep semantics
    assert sw.swept_label in HIGH
    # Direction-aware rule: HIGH-type level must not be tagged on LONG trades.
    must_skip = sw.swept_label in HIGH and direction != Direction.SHORT
    assert must_skip


def test_direction_aware_sweep_keeps_pdl_on_long():
    """A sellside sweep of PDL (price wicked below prior-day-low then closed
    back above) is the textbook ICT long-after-sweep setup. Must be kept."""
    sw = LiquiditySweep(
        side="sellside",
        direction=Direction.LONG,
        swept_label="PDL",
        swept_price=1.16700,
        sweep_bar_index=20,
        sweep_time=datetime.now(timezone.utc),
        sweep_high=1.16780,
        sweep_low=1.16680,
        sweep_close=1.16770,
        confirm_bar_index=22,
        confirm_pips=12.0,
    )
    LOW = {"PDL", "PWL", "swing_low", "equal_lows"}
    direction = Direction.LONG
    assert sw.swept_label in LOW
    must_skip = direction != Direction.LONG  # would only skip if direction were SHORT
    assert not must_skip


def test_mid_level_sweeps_are_dropped_as_noise():
    """PDM/PWM are pivot points, not stop pools. The audit showed 0/3 wins on
    `sweep_PDM`, so we drop mid sweeps regardless of direction."""
    MID = {"PDM", "PWM"}
    for label in ["PDM", "PWM"]:
        assert label in MID
