"""F008 -- module smoke tests for onboarding.py.

Public API presence + basic contract. Fine-grained security is
pinned by tests/security/test_onboarding.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import broker_connection, credentials, onboarding  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase("smoke-tests-passphrase-33-chars")
    credentials.force_fallback(True)
    broker_connection.reset_rate_limiter()
    yield
    credentials._reset_state_for_tests()
    broker_connection.reset_rate_limiter()


def test_public_api_present():
    for name in ("is_first_visit", "is_setup_complete",
                 "mark_setup_complete", "reset_install",
                 "get_onboarding_state", "set_current_step",
                 "set_default_pairs", "get_default_pairs",
                 "validate_passphrase", "ONBOARDING_NAMESPACE"):
        assert hasattr(onboarding, name), f"missing public API: {name}"


def test_onboarding_namespace_constant():
    assert onboarding.ONBOARDING_NAMESPACE == "bluelock"


def test_mark_setup_complete_flips_is_first_visit():
    assert onboarding.is_first_visit() is True
    assert onboarding.mark_setup_complete()
    assert onboarding.is_first_visit() is False
    assert onboarding.is_setup_complete() is True


def test_round_trip_default_pairs():
    onboarding.set_default_pairs(["EURUSD", "USDCAD"])
    assert onboarding.get_default_pairs() == ["EURUSD", "USDCAD"]


def test_state_defaults_before_any_setup():
    state = onboarding.get_onboarding_state()
    assert state["step"] == "welcome"
    assert state["completed"] is False
    assert state["broker_connected"] is False
    assert state["default_pairs"] == ["EURUSD"]


def test_reset_returns_true_when_nothing_to_delete():
    assert onboarding.reset_install() is True


def test_set_current_step_persists():
    onboarding.set_current_step("passphrase")
    state = onboarding.get_onboarding_state()
    assert state["step"] == "passphrase"
