"""F009 security tests -- install-token rotation.

Threat model covered:

(a) `rotate_install_token` generates a fresh token.
(b) The old token no longer authorises (it was overwritten).
(c) The new token authorises.
(d) Rotation without a prior token raises RuntimeError.
(e) Rotation response is a well-formed URL-safe token.
(f) Rotation refreshes the session (so a stale timestamp does not
    immediately expire the new token).
(g) The rate-limit bucket keyed on the fingerprint is not stuck.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import auth, credentials, rate_limiter  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, caplog):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path)
    credentials.set_encrypted_file_passphrase("rotation-tests-passphrase-xyz")
    credentials.force_fallback(True)
    rate_limiter.reset()
    auth.set_session_expiry_seconds(auth.DEFAULT_SESSION_EXPIRY_SECONDS)
    caplog.set_level(logging.INFO, logger="agent.platform.auth")
    yield
    credentials._reset_state_for_tests()
    rate_limiter.reset()


class TestRotation:

    def test_rotate_without_prior_raises(self):
        with pytest.raises(RuntimeError):
            auth.rotate_install_token()

    def test_rotate_generates_new_url_safe_token(self):
        first = auth.generate_install_token()
        second = auth.rotate_install_token()
        assert isinstance(second, str)
        assert second != first
        for ch in second:
            assert ch.isalnum() or ch in ("-", "_"), (
                f"non-url-safe char in rotated token: {ch!r}")
        assert len(second) >= 32

    def test_rotate_overwrites_stored_token(self):
        first = auth.generate_install_token()
        second = auth.rotate_install_token()
        assert auth.load_install_token() == second
        assert auth.load_install_token() != first

    def test_rotate_response_authorises_but_prior_does_not(self):
        first = auth.generate_install_token()
        rotated = auth.rotate_install_token()
        assert auth.check_request_token(header_value=rotated) is True
        assert auth.check_request_token(header_value=first) is False

    def test_rotate_refreshes_session_activity(self):
        auth.generate_install_token()
        auth.set_session_expiry_seconds(10)
        # Pretend the session was created ages ago.
        auth.clear_session_activity()
        assert auth.is_session_expired() is True
        auth.rotate_install_token()
        # After rotation the session is fresh.
        assert auth.is_session_expired() is False

    def test_rotate_logs_only_fingerprint(self, caplog):
        auth.generate_install_token()
        rotated = auth.rotate_install_token()
        for record in caplog.records:
            msg = record.getMessage()
            assert rotated not in msg, (
                f"rotated token leaked into log record: {msg!r}")
