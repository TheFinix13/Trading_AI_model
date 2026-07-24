"""F009 security tests -- session expiry.

Threat model covered:

(a) A stale session (older than the expiry window) is refused.
(b) A fresh session is refreshed on every authenticated hit.
(c) Missing activity == expired (belt-and-braces).
(d) `clear_session_activity` resets state.
(e) Expiry window is configurable and honest.
"""
from __future__ import annotations

import secrets as _secrets
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import auth, credentials  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path)
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    auth.set_session_expiry_seconds(auth.DEFAULT_SESSION_EXPIRY_SECONDS)
    yield
    credentials._reset_state_for_tests()
    auth.set_session_expiry_seconds(auth.DEFAULT_SESSION_EXPIRY_SECONDS)


class TestExpiryDefault:

    def test_default_seconds_matches_seven_days(self):
        assert auth.get_session_expiry_seconds() == 7 * 24 * 3600


class TestMissingActivity:

    def test_missing_activity_counts_as_expired(self):
        assert auth.session_last_activity() is None
        assert auth.is_session_expired() is True


class TestRecordAndCheck:

    def test_record_activity_makes_session_fresh(self):
        auth.record_session_activity()
        assert auth.is_session_expired() is False

    def test_old_activity_expires(self):
        auth.set_session_expiry_seconds(10)
        auth.record_session_activity(now=1_000_000.0)
        # 20 seconds later -- past the 10s window.
        assert auth.is_session_expired(now=1_000_020.0) is True

    def test_recent_activity_is_fresh(self):
        auth.set_session_expiry_seconds(10)
        auth.record_session_activity(now=1_000_000.0)
        assert auth.is_session_expired(now=1_000_005.0) is False


class TestClear:

    def test_clear_resets_activity(self):
        auth.record_session_activity()
        assert auth.session_last_activity() is not None
        ok = auth.clear_session_activity()
        assert ok is True
        assert auth.session_last_activity() is None
        assert auth.is_session_expired() is True


class TestConfig:

    def test_invalid_expiry_raises(self):
        with pytest.raises(ValueError):
            auth.set_session_expiry_seconds(0)
        with pytest.raises(ValueError):
            auth.set_session_expiry_seconds(-1)

    def test_expiry_round_trip(self):
        auth.set_session_expiry_seconds(3600)
        assert auth.get_session_expiry_seconds() == 3600
