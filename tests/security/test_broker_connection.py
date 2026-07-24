"""F007 security tests -- `agent/platform/broker_connection.py`.

Per D048 for an auth/credentials/broker-connection feature:

(a) auth gate on /api/broker/* non-localhost requests (delegated to
    F006 install-token gate; covered by tests/platform/test_broker_api.py).
(b) password-in-logs regression -- never appears in a log line, response
    body, or return value.
(c) allow-list enforcement for server URLs.
(d) rate-limit enforcement -- 6th call within 60s trips 429.
(e) DELETE authorisation -- can only delete your own aliases (single-user
    invariant pinned for future multi-user).
"""
from __future__ import annotations

import logging
import re
import secrets as _secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import broker_connection, credentials  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    broker_connection.reset_rate_limiter()
    yield
    credentials._reset_state_for_tests()
    broker_connection.reset_rate_limiter()


# ---------------------------------------------------------------------------
# (b) password-in-logs regression
# ---------------------------------------------------------------------------

# Generated at runtime -- no secret-shaped literals for scanners to flag.
_PASSWORD_SENTINEL = "never-log-sentinel-" + _secrets.token_hex(6)

# Throwaway password for call-sites that only need a syntactically valid
# password (no leak assertion attached).
_DUMMY_PW = "x" * 12


class TestPasswordNeverLogged:

    def test_test_connection_does_not_log_password(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="agent.platform.broker_connection"):
            broker_connection.test_connection(
                login="12345", password=_PASSWORD_SENTINEL,
                server="Exness-MT5Demo")
        assert _PASSWORD_SENTINEL not in caplog.text

    def test_save_credentials_does_not_log_password(self, caplog):
        with caplog.at_level(logging.DEBUG,
                              logger="agent.platform.broker_connection"):
            broker_connection.save_credentials(
                alias="primary", login="12345",
                password=_PASSWORD_SENTINEL,
                server="Exness-MT5Demo", account_type="demo")
        assert _PASSWORD_SENTINEL not in caplog.text

    def test_test_connection_result_omits_password(self):
        result = broker_connection.test_connection(
            login="12345", password=_PASSWORD_SENTINEL,
            server="Exness-MT5Demo")
        # Every key + value in the response must not contain the sentinel.
        assert _PASSWORD_SENTINEL not in str(result)
        assert "password" not in result

    def test_list_aliases_never_returns_password(self):
        broker_connection.save_credentials(
            alias="one", login="111", password=_PASSWORD_SENTINEL,
            server="Exness-MT5Demo", account_type="demo")
        broker_connection.save_credentials(
            alias="two", login="222", password=_PASSWORD_SENTINEL + "2",
            server="Exness-MT5Demo", account_type="demo")
        rows = broker_connection.list_aliases()
        assert len(rows) == 2
        blob = str(rows)
        assert "password" not in blob
        assert _PASSWORD_SENTINEL not in blob


# ---------------------------------------------------------------------------
# (c) allow-list enforcement
# ---------------------------------------------------------------------------

class TestServerAllowList:

    @pytest.mark.parametrize("server", [
        "Exness-MT5Trial7",
        "MetaQuotes-Demo",
        "ICMarkets-Live12",
        "Demo-XY",
        "Sandbox-Playground",
    ])
    def test_allowed_prefixes_pass(self, server):
        result = broker_connection.test_connection(
            login="12345", password=_DUMMY_PW, server=server)
        # On macOS the MT5 branch short-circuits to mt5_unavailable;
        # what matters is the validator DID NOT reject the server.
        assert result["error_message"] != (
            f"server {server!r} not on allow-list")

    @pytest.mark.parametrize("server", [
        "evil-server.com",
        "http://evil",
        "127.0.0.1",
        "8.8.8.8",
        "some-random-name",
        "Exness_ (with space)",
        "../etc/passwd",
        "",
    ])
    def test_disallowed_servers_rejected(self, server):
        result = broker_connection.test_connection(
            login="12345", password=_DUMMY_PW, server=server)
        assert result["success"] is False
        # Some rejects come from regex (bad chars) rather than allowlist;
        # accept either failure path.
        assert result["error_code"] != 429  # not rate-limit
        assert result["error_message"], "must include an error message"

    def test_save_credentials_rejects_disallowed(self):
        with pytest.raises(ValueError):
            broker_connection.save_credentials(
                alias="x", login="12345", password=_DUMMY_PW,
                server="evil-server.com", account_type="demo")
        # Nothing persisted.
        assert broker_connection.list_aliases() == []


# ---------------------------------------------------------------------------
# (d) rate-limit enforcement
# ---------------------------------------------------------------------------

class TestRateLimit:

    def test_sixth_attempt_within_window_returns_429(self):
        for i in range(5):
            r = broker_connection.test_connection(
                login="12345", password=_DUMMY_PW,
                server="Exness-MT5Demo")
            assert r["error_code"] != 429, f"attempt {i} tripped early"
        # Sixth = rate-limited.
        r = broker_connection.test_connection(
            login="12345", password=_DUMMY_PW,
            server="Exness-MT5Demo")
        assert r["error_code"] == 429
        assert "wait a minute" in (r["error_message"] or "").lower()

    def test_reset_rate_limiter_clears_state(self):
        for _ in range(6):
            broker_connection.test_connection(
                login="12345", password=_DUMMY_PW,
                server="Exness-MT5Demo")
        broker_connection.reset_rate_limiter()
        r = broker_connection.test_connection(
            login="12345", password=_DUMMY_PW,
            server="Exness-MT5Demo")
        assert r["error_code"] != 429


# ---------------------------------------------------------------------------
# (e) DELETE authorisation invariant
# ---------------------------------------------------------------------------

class TestDeleteAuthorisation:
    """Single-user model per D052 -- 'authorisation' is trivially true
    for the process owner, but this test pins the invariant so a future
    multi-user landing can't silently regress.
    """

    def test_delete_removes_only_target_alias(self):
        broker_connection.save_credentials(
            "one", "111", _DUMMY_PW, "Exness-MT5Demo", "demo")
        broker_connection.save_credentials(
            "two", "222", _DUMMY_PW, "Exness-MT5Demo", "demo")
        assert broker_connection.delete_credentials("one") is True
        aliases = {r["alias"] for r in broker_connection.list_aliases()}
        assert aliases == {"two"}

    def test_delete_of_missing_alias_returns_false(self):
        assert broker_connection.delete_credentials("nonexistent") is False

    def test_delete_rejects_path_traversal_alias(self):
        with pytest.raises(ValueError):
            broker_connection.delete_credentials("../elsewhere")


# ---------------------------------------------------------------------------
# input-fuzz on the login / password / server fields
# ---------------------------------------------------------------------------

class TestInputFuzz:

    @pytest.mark.parametrize("bad_login", [
        "", " ", "12 34", "abc", "12.34", "-1", "1" * 21, None, [], {},
    ])
    def test_bad_login_rejected(self, bad_login):
        r = broker_connection.test_connection(
            login=bad_login, password=_DUMMY_PW, server="Exness-MT5Demo")
        assert r["success"] is False

    @pytest.mark.parametrize("bad_password", [
        "", None, 123, b"bytes",
    ])
    def test_bad_password_rejected(self, bad_password):
        r = broker_connection.test_connection(
            login="12345", password=bad_password, server="Exness-MT5Demo")
        assert r["success"] is False

    def test_oversized_password_rejected(self):
        r = broker_connection.test_connection(
            login="12345", password="x" * 1000, server="Exness-MT5Demo")
        assert r["success"] is False

    @pytest.mark.parametrize("bad_alias", [
        "", " ", "..", "a/b", "a\\b", "a\x00b", "a" * 65,
        None, 123,
    ])
    def test_bad_alias_rejected(self, bad_alias):
        with pytest.raises((ValueError, TypeError)):
            broker_connection.save_credentials(
                bad_alias, "12345", _DUMMY_PW, "Exness-MT5Demo", "demo")


# ---------------------------------------------------------------------------
# Round-trip: password stored + retrieved works, but password redacted in
# log stream when the RedactingFilter is mounted
# ---------------------------------------------------------------------------

class TestRoundTripWithRedactionFilter:

    def test_save_then_load_returns_password_intact(self):
        pw = "round-trip-pw-" + _secrets.token_hex(4)
        broker_connection.save_credentials(
            "primary", "12345", pw,
            "Exness-MT5Demo", "demo")
        loaded = broker_connection.load_credentials("primary")
        assert loaded is not None
        assert loaded["password"] == pw
        assert loaded["login"] == "12345"
        assert loaded["server"] == "Exness-MT5Demo"
        assert loaded["account_type"] == "demo"

    def test_password_pattern_never_leaks_in_log_text(self, caplog):
        pw = "extra-secret-long-" + _secrets.token_hex(5)
        with caplog.at_level(logging.INFO):
            broker_connection.save_credentials(
                "primary", "12345", pw,
                "Exness-MT5Demo", "demo")
        # Even without the RedactingFilter mounted for this test, the
        # module itself must not include the password in its log
        # arguments. The credentials.py filter is separately tested.
        assert pw not in caplog.text
        # Sanity: alias/login/server DO appear (they're not secret).
        assert "primary" in caplog.text
        assert re.search(r"login=12345", caplog.text)
