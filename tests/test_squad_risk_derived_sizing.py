"""F025 blocker B3 -- risk-derived fill sizing.

The bug this pins: Sentinel R1 asks "even at the broker minimum lot,
does this stop risk more than 5 % of equity?" and refuses if so. That is
a FLOOR check and correct as one. What never existed is the step that
sizes a position DOWN to the budget, so the engine filled ``FIXED_LOT``
(0.1) regardless -- ten times the lot R1 measured. On the $100 shadow
book nothing settled in real money so it was harmless bookkeeping. On a
funded $500 account the advertised 5 %-per-trade cap understates true
risk by 10x, and R1 happily allows a 250-pip stop that costs 50 % of the
account at the lot actually filled.

Two properties matter more than the arithmetic:

1. **Default OFF is byte-identical.** Every banked replay and the whole
   shadow tape must be unaffected, so `risk_derived_sizing=False` has to
   fill exactly what it filled before.
2. **ON can only shrink.** Enabling it must never size a position UP,
   which makes the flag safe to turn on without re-validating the book.
"""
from __future__ import annotations

import pytest

from agent.squad.lot_intent import FIXED_LOT, MIN_LOT, risk_budget_lot

# EURUSD-shaped sandbox constants: $0.10/pip at 0.01 lot => $10/pip at 1.0.
EURUSD_PIP_VALUE_PER_MIN_LOT = 0.10
CAP = 0.05


# ---------------------------------------------------------------------------
# The arithmetic in the docstring
# ---------------------------------------------------------------------------

def test_typical_stop_on_500_sizes_to_the_budget():
    # $500 x 5 % = $25 budget. A 30-pip stop at $10/pip/lot costs $300
    # per lot, so 25/300 = 0.0833 lots, rounded down to 0.08.
    lot = risk_budget_lot(
        sl_pips=30.0, equity=500.0,
        pip_value_per_min_lot=EURUSD_PIP_VALUE_PER_MIN_LOT,
        per_trade_risk_frac=CAP,
    )
    assert lot == pytest.approx(0.08)
    realised_risk = 30.0 * lot * (EURUSD_PIP_VALUE_PER_MIN_LOT * 100.0)
    assert realised_risk == pytest.approx(24.0)
    assert realised_risk <= CAP * 500.0


def test_fixed_lot_on_the_same_trade_breaches_the_cap():
    # The behaviour being replaced: 30 pips at 0.1 lot = $30 = 6 % of a
    # $500 account, over the cap R1 advertises.
    risk_at_fixed_lot = 30.0 * FIXED_LOT * (EURUSD_PIP_VALUE_PER_MIN_LOT * 100.0)
    assert risk_at_fixed_lot == pytest.approx(30.0)
    assert risk_at_fixed_lot > CAP * 500.0


def test_the_250_pip_stop_r1_allows_is_half_the_account_at_fixed_lot():
    # R1's own boundary: at min-lot a 250-pip EURUSD stop costs exactly
    # the $25 cap, so R1 ALLOWS it. Filled at FIXED_LOT it costs $250.
    r1_implied = 250.0 * EURUSD_PIP_VALUE_PER_MIN_LOT
    assert r1_implied == pytest.approx(25.0)          # R1 says fine
    at_fixed = 250.0 * FIXED_LOT * (EURUSD_PIP_VALUE_PER_MIN_LOT * 100.0)
    assert at_fixed == pytest.approx(250.0)           # reality: 50 %
    # Risk-derived sizing brings it back to the cap.
    lot = risk_budget_lot(
        sl_pips=250.0, equity=500.0,
        pip_value_per_min_lot=EURUSD_PIP_VALUE_PER_MIN_LOT,
        per_trade_risk_frac=CAP,
    )
    assert lot == pytest.approx(MIN_LOT)
    assert 250.0 * lot * (EURUSD_PIP_VALUE_PER_MIN_LOT * 100.0) == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# Safety properties
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sl_pips", [1.0, 5.0, 10.0, 20.0, 30.0, 50.0, 120.0, 300.0])
@pytest.mark.parametrize("equity", [100.0, 500.0, 1000.0, 10_000.0])
def test_never_sizes_above_the_desired_lot(sl_pips, equity):
    # The property that makes the flag safe to enable: it can only
    # shrink. A tiny stop on a fat account would otherwise ask for a
    # position far above the book the roster was validated on.
    lot = risk_budget_lot(
        sl_pips=sl_pips, equity=equity,
        pip_value_per_min_lot=EURUSD_PIP_VALUE_PER_MIN_LOT,
        desired_lot=FIXED_LOT, per_trade_risk_frac=CAP,
    )
    assert lot <= FIXED_LOT + 1e-9


@pytest.mark.parametrize("sl_pips", [10.0, 30.0, 80.0, 250.0])
@pytest.mark.parametrize("equity", [100.0, 500.0, 1000.0])
def test_realised_risk_never_exceeds_the_cap(sl_pips, equity):
    lot = risk_budget_lot(
        sl_pips=sl_pips, equity=equity,
        pip_value_per_min_lot=EURUSD_PIP_VALUE_PER_MIN_LOT,
        per_trade_risk_frac=CAP,
    )
    if lot == 0.0:
        return       # unfundable -> caller skips the trade
    risk = sl_pips * lot * (EURUSD_PIP_VALUE_PER_MIN_LOT * 100.0)
    assert risk <= CAP * equity + 1e-9


def test_rounds_down_to_lot_increments_never_up():
    # Rounding UP is the exact bug class being fixed, so a budget that
    # affords 0.0833 must fill 0.08 and not 0.09.
    lot = risk_budget_lot(
        sl_pips=30.0, equity=500.0,
        pip_value_per_min_lot=EURUSD_PIP_VALUE_PER_MIN_LOT,
        per_trade_risk_frac=CAP,
    )
    assert lot == pytest.approx(0.08)
    n_increments = round(lot / MIN_LOT, 6)
    assert n_increments == int(n_increments)


def test_unfundable_budget_returns_zero_not_min_lot():
    # $100 book, 400-pip stop: even one min-lot costs $40 = 40 % > 5 %.
    # Returning MIN_LOT here would reintroduce the overshoot.
    lot = risk_budget_lot(
        sl_pips=400.0, equity=100.0,
        pip_value_per_min_lot=EURUSD_PIP_VALUE_PER_MIN_LOT,
        per_trade_risk_frac=CAP,
    )
    assert lot == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sl_pips": 0.0, "equity": 500.0, "pip_value_per_min_lot": 0.10},
        {"sl_pips": -30.0, "equity": 500.0, "pip_value_per_min_lot": 0.10},
        {"sl_pips": 30.0, "equity": 0.0, "pip_value_per_min_lot": 0.10},
        {"sl_pips": 30.0, "equity": -500.0, "pip_value_per_min_lot": 0.10},
        {"sl_pips": 30.0, "equity": 500.0, "pip_value_per_min_lot": 0.0},
    ],
)
def test_degenerate_inputs_refuse_rather_than_guess(kwargs):
    assert risk_budget_lot(**kwargs, per_trade_risk_frac=CAP) == 0.0


def test_symbol_pip_value_is_honoured_not_the_major_constant():
    # I030 lesson: hardcoding the 0.10 major-pair value made JPY and
    # metals size wrongly. A 10x pip value must give a 10x smaller lot.
    # desired_lot lifted well clear of the answer so the FIXED_LOT
    # ceiling doesn't clamp both sides and hide the ratio.
    major = risk_budget_lot(
        sl_pips=30.0, equity=5000.0, pip_value_per_min_lot=0.10,
        desired_lot=10.0, per_trade_risk_frac=CAP,
    )
    heavy = risk_budget_lot(
        sl_pips=30.0, equity=5000.0, pip_value_per_min_lot=1.00,
        desired_lot=10.0, per_trade_risk_frac=CAP,
    )
    assert heavy < major
    assert heavy == pytest.approx(major / 10.0, rel=0.2)
