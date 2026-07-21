"""F008 -- security tests for the onboarding module.

Pins the security invariants:

1. Reset flow doesn't leak previous state -- after `reset_install`,
   `list_keys` in both namespaces returns [].
2. Passphrase strength gate is enforced when the keychain is absent.
3. First-visit gate returns True until `mark_setup_complete` fires.
4. `set_default_pairs` refuses anything outside the allow-list, empty
   inputs, and non-string inputs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import (  # noqa: E402
    auth, broker_connection, credentials, onboarding,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase("onboarding-tests-passphrase-33")
    credentials.force_fallback(True)
    broker_connection.reset_rate_limiter()
    yield
    credentials._reset_state_for_tests()
    broker_connection.reset_rate_limiter()


# ---------------------------------------------------------------------------
# Reset flow
# ---------------------------------------------------------------------------

class TestResetFlow:

    def test_reset_clears_onboarding_namespace(self):
        onboarding.mark_setup_complete()
        onboarding.set_current_step("passphrase")
        onboarding.set_default_pairs(["EURUSD", "GBPUSD"])
        assert onboarding.is_setup_complete()
        assert onboarding.reset_install()
        assert not onboarding.is_setup_complete()
        assert credentials.list_keys(onboarding.ONBOARDING_NAMESPACE) == []

    def test_reset_clears_broker_namespace(self):
        broker_connection.save_credentials(
            alias="primary", login="12345",
            password="s3cret-password-xyz",
            server="Demo-Server1", account_type="demo")
        assert broker_connection.list_aliases()
        assert onboarding.reset_install()
        assert broker_connection.list_aliases() == []

    def test_reset_clears_install_token(self):
        auth.generate_install_token()
        assert auth.is_install_configured()
        assert onboarding.reset_install()
        assert not auth.is_install_configured()
        assert auth.load_install_token() is None

    def test_reset_is_idempotent(self):
        assert onboarding.reset_install()
        assert onboarding.reset_install()

    def test_reset_does_not_leak_previous_secret_value(self, caplog):
        payload = "top-secret-marker-xyz-2026"
        credentials.store_secret(
            onboarding.ONBOARDING_NAMESPACE, "manual_test", payload)
        assert onboarding.reset_install()
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert payload not in joined, (
            "secret value leaked into log during reset")
        assert credentials.retrieve_secret(
            onboarding.ONBOARDING_NAMESPACE, "manual_test") is None


# ---------------------------------------------------------------------------
# Passphrase strength gate
# ---------------------------------------------------------------------------

class TestPassphraseGate:

    def test_empty_rejected_when_keychain_absent(self):
        ok, msg = onboarding.validate_passphrase(
            "", keyring_available=False)
        assert ok is False
        assert "at least" in msg.lower()

    def test_whitespace_only_rejected_when_keychain_absent(self):
        ok, _ = onboarding.validate_passphrase(
            "   ", keyring_available=False)
        assert ok is False

    def test_short_rejected_regardless_of_keychain(self):
        ok, _ = onboarding.validate_passphrase(
            "short", keyring_available=True)
        assert ok is False
        ok, _ = onboarding.validate_passphrase(
            "short", keyring_available=False)
        assert ok is False

    def test_long_enough_accepted(self):
        ok, msg = onboarding.validate_passphrase(
            "a-strong-passphrase-here", keyring_available=False)
        assert ok is True
        assert msg

    def test_empty_accepted_when_keychain_present(self):
        ok, msg = onboarding.validate_passphrase(
            "", keyring_available=True)
        assert ok is True
        assert "keychain" in msg.lower()

    def test_control_chars_rejected(self):
        ok, _ = onboarding.validate_passphrase(
            "long-enough\x00-with-null", keyring_available=True)
        assert ok is False

    def test_non_string_rejected(self):
        ok, _ = onboarding.validate_passphrase(
            12345, keyring_available=True)
        assert ok is False


# ---------------------------------------------------------------------------
# First-visit gate
# ---------------------------------------------------------------------------

class TestFirstVisitGate:

    def test_first_visit_true_before_setup(self):
        assert onboarding.is_first_visit() is True

    def test_first_visit_true_even_with_install_token(self):
        auth.generate_install_token()
        assert onboarding.is_first_visit() is True

    def test_first_visit_false_after_mark_complete(self):
        onboarding.mark_setup_complete()
        assert onboarding.is_first_visit() is False

    def test_first_visit_true_again_after_reset(self):
        onboarding.mark_setup_complete()
        onboarding.reset_install()
        assert onboarding.is_first_visit() is True


# ---------------------------------------------------------------------------
# set_default_pairs input safety
# ---------------------------------------------------------------------------

class TestDefaultPairsSafety:

    def test_accepts_allow_listed_pair(self):
        assert onboarding.set_default_pairs(["EURUSD"])
        assert onboarding.get_default_pairs() == ["EURUSD"]

    def test_deduplicates(self):
        onboarding.set_default_pairs(["EURUSD", "EURUSD", "GBPUSD"])
        assert onboarding.get_default_pairs() == ["EURUSD", "GBPUSD"]

    def test_rejects_unknown_pair(self):
        with pytest.raises(ValueError):
            onboarding.set_default_pairs(["EURUSD", "BTCUSD"])

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            onboarding.set_default_pairs([])

    def test_rejects_non_list(self):
        with pytest.raises(ValueError):
            onboarding.set_default_pairs("EURUSD")

    def test_rejects_non_string_element(self):
        with pytest.raises(ValueError):
            onboarding.set_default_pairs(["EURUSD", 42])

    def test_get_default_pairs_falls_back_when_missing(self):
        assert onboarding.get_default_pairs() == ["EURUSD"]


# ---------------------------------------------------------------------------
# set_current_step input safety
# ---------------------------------------------------------------------------

class TestSetCurrentStep:

    def test_accepts_known_step(self):
        assert onboarding.set_current_step("passphrase")

    def test_rejects_unknown_step(self):
        with pytest.raises(ValueError):
            onboarding.set_current_step("bogus")

    def test_rejects_non_string(self):
        with pytest.raises(ValueError):
            onboarding.set_current_step(3)


# ---------------------------------------------------------------------------
# get_onboarding_state shape
# ---------------------------------------------------------------------------

class TestOnboardingStateShape:

    def test_state_shape_and_fields(self):
        state = onboarding.get_onboarding_state()
        assert set(state.keys()) == {
            "step", "completed", "install_fingerprint",
            "broker_connected", "keyring_available", "default_pairs",
        }
        assert state["completed"] is False
        assert state["broker_connected"] is False
        assert state["step"] == "welcome"

    def test_state_reflects_broker_saved(self):
        broker_connection.save_credentials(
            alias="primary", login="12345", password="pw12345678",
            server="Demo-Server1", account_type="demo")
        state = onboarding.get_onboarding_state()
        assert state["broker_connected"] is True

    def test_state_reflects_install_fingerprint(self):
        auth.generate_install_token()
        state = onboarding.get_onboarding_state()
        assert state["install_fingerprint"]
        # Never leaks the full token via the state payload.
        token = auth.load_install_token()
        assert token not in state["install_fingerprint"]
