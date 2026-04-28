"""Unit tests for calibration diagnostics."""
from __future__ import annotations

import numpy as np

from agent.analysis.calibration import calibration_report


def test_perfect_calibration():
    """Probs that exactly match outcome rate per bin → ECE near zero, no overconfidence."""
    rng = np.random.default_rng(42)
    n = 5000
    probs = rng.uniform(0, 1, n)
    outcomes = (rng.uniform(0, 1, n) < probs).astype(int)
    rep = calibration_report(probs, outcomes, n_bins=10)
    assert rep.n == n
    assert rep.brier < 0.20
    assert rep.ece < 0.04
    assert rep.is_overconfident_high_bins is False


def test_overconfident_model():
    """Model says 0.85 but actual win rate is 0.4. Should flag overconfidence."""
    n = 500
    probs = np.full(n, 0.85)
    outcomes = np.zeros(n, dtype=int)
    outcomes[: int(0.4 * n)] = 1  # only 40% win, despite p=0.85
    rep = calibration_report(probs, outcomes, n_bins=10)
    assert rep.is_overconfident_high_bins is True
    # ECE should reflect the 0.45 gap weighted by the bin's mass
    assert rep.ece > 0.40


def test_useless_model():
    """Model predicts 0.5 always → Brier ~0.25 (random performance)."""
    n = 1000
    rng = np.random.default_rng(1)
    probs = np.full(n, 0.5)
    outcomes = (rng.uniform(0, 1, n) < 0.5).astype(int)
    rep = calibration_report(probs, outcomes, n_bins=10)
    assert 0.20 < rep.brier < 0.30


def test_empty_input():
    rep = calibration_report(np.array([]), np.array([], dtype=int))
    assert rep.n == 0
    assert "No predictions" in rep.summary
