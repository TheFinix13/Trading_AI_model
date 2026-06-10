"""Benjamini-Hochberg + bootstrap p-value tests."""
from __future__ import annotations

import numpy as np

from agent.backtest.metrics import benjamini_hochberg, bootstrap_p_value


class TestBootstrapPValue:
    def test_clear_positive_edge_has_low_p(self):
        rng = np.random.default_rng(0)
        pnls = list(rng.normal(2.0, 1.0, size=200))
        p = bootstrap_p_value(pnls, n_resamples=400)
        assert p < 0.01

    def test_no_edge_has_high_p(self):
        rng = np.random.default_rng(1)
        pnls = list(rng.normal(0.0, 1.0, size=200))
        p = bootstrap_p_value(pnls, n_resamples=400)
        assert p > 0.05

    def test_clear_negative_edge_returns_high_greater_p(self):
        rng = np.random.default_rng(2)
        pnls = list(rng.normal(-1.5, 0.5, size=100))
        # "alternative=greater" tests for a positive mean — a negative mean
        # must produce a p-value close to 1.
        p = bootstrap_p_value(pnls, n_resamples=400, alternative="greater")
        assert p > 0.9

    def test_empty_or_tiny_returns_one(self):
        assert bootstrap_p_value([], n_resamples=10) == 1.0
        assert bootstrap_p_value([3.0], n_resamples=10) == 1.0

    def test_p_value_is_strictly_in_open_unit_interval(self):
        """Add-one smoothing must never let p hit exactly 0 or > 1."""
        pnls = [10.0] * 100  # would naively give p=0
        p = bootstrap_p_value(pnls, n_resamples=200)
        assert 0.0 < p <= 1.0


class TestBenjaminiHochberg:
    def test_all_null_rejects_few(self):
        # 50 uniform-ish p-values: expect roughly zero rejections at FDR=0.05.
        rng = np.random.default_rng(0)
        ps = list(rng.uniform(0.0, 1.0, size=50))
        rejects, q = benjamini_hochberg(ps, fdr=0.05)
        assert sum(rejects) <= 2  # very loose; usually 0

    def test_all_strong_signals_all_rejected(self):
        ps = [1e-6] * 20
        rejects, _ = benjamini_hochberg(ps, fdr=0.05)
        assert all(rejects)

    def test_mixed_rejects_the_strong_ones(self):
        # 5 strong + 15 null. BH should reject the 5 strong, mostly miss the rest.
        ps = [0.001, 0.002, 0.003, 0.004, 0.005] + [0.40, 0.55, 0.60, 0.70,
                                                     0.80, 0.85, 0.90, 0.95,
                                                     0.96, 0.97, 0.98, 0.99,
                                                     0.995, 0.999, 1.0]
        rejects, q = benjamini_hochberg(ps, fdr=0.05)
        assert all(rejects[:5])
        assert not any(rejects[5:])
        for qv in q:
            assert 0.0 <= qv <= 1.0

    def test_q_values_are_monotone_in_sorted_p(self):
        ps = [0.01, 0.04, 0.03, 0.20, 0.50, 0.001]
        _, q = benjamini_hochberg(ps, fdr=0.05)
        sorted_pairs = sorted(zip(ps, q))
        last = -1.0
        for _, qv in sorted_pairs:
            assert qv >= last
            last = qv

    def test_empty_input(self):
        r, q = benjamini_hochberg([], fdr=0.05)
        assert r == []
        assert q == []
