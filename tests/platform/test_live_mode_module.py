"""F013 -- live-mode toggle module unit tests.

Coverage (5+):
1. Default is OFF on a fresh install.
2. set_live_mode(True) persists across is_live_mode_enabled() calls.
3. set_live_mode(False) persists across calls.
4. disable() is an alias for set_live_mode(False).
5. enable_ceremony refuses without acknowledgement.
6. enable_ceremony refuses with wrong confirmation string.
7. enable_ceremony accepts both -> live-mode flips ON.
8. Keyring round-trip: writing "true" and reading back gives True.
"""
from __future__ import annotations

import secrets as _secrets

from pathlib import Path

import pytest

from agent.platform import approval_queue, credentials


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    approval_queue.reset_state()
    yield
    credentials._reset_state_for_tests()
    approval_queue.reset_state()


class TestDefault:
    def test_default_is_off(self) -> None:
        assert approval_queue.is_live_mode_enabled() is False


class TestSetLiveMode:
    def test_enable_persists(self) -> None:
        assert approval_queue.set_live_mode(True) is True
        assert approval_queue.is_live_mode_enabled() is True

    def test_disable_persists(self) -> None:
        approval_queue.set_live_mode(True)
        assert approval_queue.disable() is True
        assert approval_queue.is_live_mode_enabled() is False


class TestCeremony:
    def test_refuses_without_acknowledgement(self) -> None:
        ok, reason = approval_queue.enable_ceremony(
            acknowledged=False,
            confirmation=approval_queue.CONFIRMATION_PHRASE)
        assert ok is False
        assert "acknowledgement" in reason
        assert approval_queue.is_live_mode_enabled() is False

    def test_refuses_wrong_confirmation(self) -> None:
        ok, reason = approval_queue.enable_ceremony(
            acknowledged=True, confirmation="enable live mode")
        assert ok is False
        assert "confirmation" in reason
        assert approval_queue.is_live_mode_enabled() is False

    def test_accepts_both(self) -> None:
        ok, reason = approval_queue.enable_ceremony(
            acknowledged=True,
            confirmation=approval_queue.CONFIRMATION_PHRASE)
        assert ok is True
        assert reason == "ok"
        assert approval_queue.is_live_mode_enabled() is True


class TestRoundTrip:
    def test_round_trip_via_keyring(self) -> None:
        approval_queue.set_live_mode(True)
        # Bypass the module and read the raw secret to prove it's
        # actually persisted, not just an in-memory cache.
        val = credentials.retrieve_secret(
            approval_queue.LIVE_MODE_NAMESPACE,
            approval_queue.LIVE_MODE_KEY)
        assert val == "true"
