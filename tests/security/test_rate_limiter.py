"""F009 security tests -- agent/platform/rate_limiter.py.

Threat model covered:

(a) Bucket-drain: overburst hits the 429 wall at the right count.
(b) Bucket refill: honest token replenishment over time.
(c) Per-token isolation: two install tokens never share a bucket.
(d) Monotonic retry-after: never exceeds the configured refill window.
(e) Config-round-trip: set / get preserves invariants.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import rate_limiter  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_buckets():
    rate_limiter.reset()
    rate_limiter.set_config(requests_per_minute=60)  # default
    yield
    rate_limiter.reset()


class TestBucketDrain:

    def test_capacity_60_allows_60_bursts(self):
        rate_limiter.set_config(requests_per_minute=60)
        for _ in range(60):
            allowed, retry = rate_limiter.check("finger-A")
            assert allowed is True
            assert retry == 0.0

    def test_61st_burst_is_rate_limited(self):
        rate_limiter.set_config(requests_per_minute=60)
        for _ in range(60):
            rate_limiter.check("finger-A")
        allowed, retry = rate_limiter.check("finger-A")
        assert allowed is False
        assert retry > 0.0

    def test_retry_after_never_exceeds_refill_window(self):
        rate_limiter.set_config(requests_per_minute=60)
        for _ in range(60):
            rate_limiter.check("finger-A")
        allowed, retry = rate_limiter.check("finger-A")
        assert allowed is False
        assert retry <= 60.0

    def test_none_or_empty_key_refused(self):
        assert rate_limiter.check(None) == (False, 0.0)
        assert rate_limiter.check("") == (False, 0.0)


class TestBucketRefill:

    def test_bucket_refills_over_time(self):
        rate_limiter.set_config(capacity=10, refill_per_sec=1.0)
        for _ in range(10):
            rate_limiter.check("finger-A", now=0.0)
        allowed, _ = rate_limiter.check("finger-A", now=0.5)
        assert allowed is False  # only 0.5 tokens dripped in
        allowed, _ = rate_limiter.check("finger-A", now=1.5)
        assert allowed is True  # 1.5 tokens available, one consumed

    def test_bucket_caps_at_capacity(self):
        rate_limiter.set_config(capacity=5, refill_per_sec=1.0)
        # Drain fully then wait "10 seconds" of virtual time -- should
        # only refill up to capacity (5), not overflow.
        for _ in range(5):
            rate_limiter.check("finger-A", now=0.0)
        for _ in range(5):
            allowed, _ = rate_limiter.check("finger-A", now=100.0)
            assert allowed is True
        allowed, _ = rate_limiter.check("finger-A", now=100.0)
        assert allowed is False


class TestPerTokenIsolation:

    def test_two_tokens_have_independent_budgets(self):
        rate_limiter.set_config(capacity=3, refill_per_sec=0.001)
        for _ in range(3):
            assert rate_limiter.check("finger-A", now=0.0)[0] is True
        # A is now dry, but B should have a full budget.
        for _ in range(3):
            assert rate_limiter.check("finger-B", now=0.0)[0] is True
        # And A is still rate-limited.
        assert rate_limiter.check("finger-A", now=0.0)[0] is False

    def test_bucket_count_grows_with_new_tokens(self):
        rate_limiter.reset()
        rate_limiter.check("finger-1")
        rate_limiter.check("finger-2")
        rate_limiter.check("finger-3")
        assert rate_limiter.bucket_count() == 3


class TestReset:

    def test_reset_clears_all_buckets(self):
        rate_limiter.set_config(capacity=2, refill_per_sec=0.001)
        for _ in range(2):
            rate_limiter.check("finger-A", now=0.0)
        assert rate_limiter.check("finger-A", now=0.0)[0] is False
        rate_limiter.reset()
        assert rate_limiter.check("finger-A", now=0.0)[0] is True

    def test_reset_single_key(self):
        rate_limiter.set_config(capacity=2, refill_per_sec=0.001)
        for _ in range(2):
            rate_limiter.check("finger-A", now=0.0)
            rate_limiter.check("finger-B", now=0.0)
        rate_limiter.reset("finger-A")
        assert rate_limiter.check("finger-A", now=0.0)[0] is True
        assert rate_limiter.check("finger-B", now=0.0)[0] is False


class TestConfig:

    def test_get_config_after_set(self):
        rate_limiter.set_config(requests_per_minute=120)
        cfg = rate_limiter.get_config()
        assert cfg["capacity"] == 120
        assert cfg["requests_per_minute"] == pytest.approx(120.0)

    def test_capacity_and_refill_can_be_set_directly(self):
        rate_limiter.set_config(capacity=200, refill_per_sec=5.0)
        cfg = rate_limiter.get_config()
        assert cfg["capacity"] == 200
        assert cfg["refill_per_sec"] == pytest.approx(5.0)

    def test_invalid_capacity_raises(self):
        with pytest.raises(ValueError):
            rate_limiter.set_config(capacity=0)
        with pytest.raises(ValueError):
            rate_limiter.set_config(capacity=100_000)

    def test_invalid_refill_raises(self):
        with pytest.raises(ValueError):
            rate_limiter.set_config(refill_per_sec=0.0)
