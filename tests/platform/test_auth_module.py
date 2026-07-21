"""F006 module smoke -- `agent/platform/auth.py`.

Complements tests/security/test_auth.py with contract-level checks.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import auth, credentials  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path)
    credentials.set_encrypted_file_passphrase("module-smoke-passphrase")
    credentials.force_fallback(True)
    yield
    credentials._reset_state_for_tests()


def test_public_names():
    for name in ("generate_install_token", "load_install_token",
                 "clear_install_token", "install_token_fingerprint",
                 "auth_status", "check_request_token",
                 "is_install_configured", "RedactingFilter",
                 "install_redacting_filter"):
        assert hasattr(auth, name), f"missing public name: {name!r}"


def test_check_request_token_signature():
    sig = inspect.signature(auth.check_request_token)
    assert set(sig.parameters.keys()) == {
        "header_value", "cookie_value", "query_value", "fallback_token"}


def test_auth_status_returns_expected_keys():
    payload = auth.auth_status()
    assert set(payload.keys()) == {
        "authenticated", "install_fingerprint", "keyring_available"}


def test_fingerprint_never_reveals_middle():
    t = auth.generate_install_token()
    fp = auth.install_token_fingerprint(t)
    assert t not in fp  # full token never in fingerprint
    # Middle third of the token must not appear verbatim.
    mid = t[len(t) // 3: 2 * len(t) // 3]
    if len(mid) > 8:
        assert mid not in fp


def test_check_request_token_is_bool():
    result = auth.check_request_token(header_value=None)
    assert isinstance(result, bool)


def test_is_install_configured_reflects_store():
    assert auth.is_install_configured() is False
    auth.generate_install_token()
    assert auth.is_install_configured() is True
    auth.clear_install_token()
    assert auth.is_install_configured() is False
