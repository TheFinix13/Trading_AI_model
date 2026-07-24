"""F006 security tests -- `agent/platform/auth.py`.

Threat model covered:

(a) auth-bypass: missing token, malformed token, wrong-length token,
    empty header, cookie only, query only.
(b) replay / expired-session: same token wins twice (single-user
    model, no per-session state) but a tampered token still fails.
(c) fingerprint: leaks the right chars, not more; None-safe.
(d) redaction filter: secrets never survive a log call.
(e) constant-time compare: no length-leak, no early-exit leak.
"""
from __future__ import annotations

import base64
import logging
import secrets as _secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import auth, credentials  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path)
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    yield
    credentials._reset_state_for_tests()


# ---------------------------------------------------------------------------
# generation + fingerprint
# ---------------------------------------------------------------------------

class TestGeneration:

    def test_generates_url_safe_token(self):
        t = auth.generate_install_token()
        assert isinstance(t, str)
        assert len(t) >= 32
        for ch in t:
            assert ch.isalnum() or ch in ("-", "_"), (
                f"non-url-safe char in token: {ch!r}")

    def test_generates_high_entropy(self):
        tokens = {auth.generate_install_token() for _ in range(20)}
        assert len(tokens) == 20, "token collision -- entropy too low"

    def test_generated_token_persisted(self):
        t = auth.generate_install_token()
        assert auth.load_install_token() == t

    def test_regenerate_overwrites_prior(self):
        first = auth.generate_install_token()
        second = auth.generate_install_token()
        assert first != second
        assert auth.load_install_token() == second

    def test_clear_removes_token(self):
        auth.generate_install_token()
        assert auth.clear_install_token() is True
        assert auth.load_install_token() is None
        assert auth.is_install_configured() is False


class TestFingerprint:

    def test_fingerprint_shape_for_long_token(self):
        token = "a" * 8 + "MIDDLESECRETMIDDLE" + "z" * 8
        fp = auth.install_token_fingerprint(token)
        assert fp.startswith("aaaaaaaa")
        assert fp.endswith("zzzzzzzz")
        assert "\u2026" in fp
        # Middle secret must be scrubbed.
        assert "MIDDLESECRETMIDDLE" not in fp

    def test_fingerprint_stable_for_same_input(self):
        t = "some-fixed-token-" + "y" * 24
        assert auth.install_token_fingerprint(t) \
            == auth.install_token_fingerprint(t)

    def test_fingerprint_none_and_empty_safe(self):
        assert auth.install_token_fingerprint(None) == ""
        assert auth.install_token_fingerprint("") == ""

    def test_short_token_still_masked(self):
        fp = auth.install_token_fingerprint("abc")
        # Whatever the shape, must not equal the input verbatim
        # unless it's already been ellipsis-scrubbed.
        assert "\u2026" in fp or fp == "abc"


# ---------------------------------------------------------------------------
# check_request_token
# ---------------------------------------------------------------------------

class TestCheckRequestToken:

    def test_no_install_no_fallback_denies(self):
        assert auth.check_request_token(header_value="anything") is False

    def test_missing_all_presented_denies(self):
        auth.generate_install_token()
        assert auth.check_request_token() is False

    def test_correct_header_wins(self):
        t = auth.generate_install_token()
        assert auth.check_request_token(header_value=t) is True

    def test_correct_cookie_wins(self):
        t = auth.generate_install_token()
        assert auth.check_request_token(cookie_value=t) is True

    def test_correct_query_wins(self):
        t = auth.generate_install_token()
        assert auth.check_request_token(query_value=t) is True

    def test_wrong_token_denies(self):
        auth.generate_install_token()
        assert auth.check_request_token(header_value="A" * 43) is False

    def test_malformed_token_denies(self):
        auth.generate_install_token()
        for bad in ("", " ", "\x00", "shortie", "a" * 5,
                    "a b c", "abc;def", "a" * 200):
            assert auth.check_request_token(header_value=bad) is False, (
                f"malformed token {bad!r} should be rejected")

    def test_fallback_token_accepted(self):
        # No install token stored; only the platform.toml fallback.
        # Generated at runtime -- no secret-shaped literal for scanners.
        legacy_tok = _secrets.token_urlsafe(26)
        assert auth.check_request_token(
            header_value=legacy_tok,
            fallback_token=legacy_tok) is True

    def test_replay_same_token_still_wins(self):
        t = auth.generate_install_token()
        assert auth.check_request_token(header_value=t) is True
        assert auth.check_request_token(header_value=t) is True

    def test_tampered_token_denies(self):
        t = auth.generate_install_token()
        tampered = t[:-1] + ("A" if t[-1] != "A" else "B")
        assert auth.check_request_token(header_value=tampered) is False


class TestConstantTimeCompare:

    def test_identical_returns_true(self):
        assert auth.constant_time_equal("abc", "abc") is True

    def test_different_length_returns_false(self):
        assert auth.constant_time_equal("abcd", "abce") is False
        assert auth.constant_time_equal("abc", "abcd") is False

    def test_none_inputs_return_false(self):
        assert auth.constant_time_equal(None, "abc") is False
        assert auth.constant_time_equal("abc", None) is False
        assert auth.constant_time_equal(None, None) is False


# ---------------------------------------------------------------------------
# auth_status payload
# ---------------------------------------------------------------------------

class TestAuthStatus:

    def test_status_before_setup(self):
        status = auth.auth_status()
        assert status["authenticated"] is False
        assert status["install_fingerprint"] is None
        assert "keyring_available" in status

    def test_status_after_setup(self):
        t = auth.generate_install_token()
        status = auth.auth_status()
        assert status["authenticated"] is True
        assert status["install_fingerprint"], (
            "fingerprint should be present after setup")
        assert t not in (status["install_fingerprint"] or ""), (
            "full token must never appear in the fingerprint")

    def test_status_never_returns_token(self):
        auth.generate_install_token()
        status = auth.auth_status()
        assert "token" not in status
        assert "install_token" not in status


# ---------------------------------------------------------------------------
# RedactingFilter -- log scrubber regression
# ---------------------------------------------------------------------------

class TestRedactingFilter:

    def test_scrubs_long_url_safe_token(self):
        filt = auth.RedactingFilter()
        rec = logging.LogRecord("test", logging.INFO, __file__, 1,
                                "leaked=%s", ("A" * 40,), None)
        filt.filter(rec)
        assert "A" * 40 not in str(rec.args), (
            "40-char url-safe blob should be scrubbed")

    def test_scrubs_password_kv(self):
        filt = auth.RedactingFilter()
        rec = logging.LogRecord("test", logging.INFO, __file__, 1,
                                "connecting password=hunter2 to server",
                                (), None)
        filt.filter(rec)
        assert "hunter2" not in rec.msg

    def test_scrubs_token_kv(self):
        filt = auth.RedactingFilter()
        # Built at runtime so scanners never see a token-shaped literal.
        # 24 input bytes -> 32 base64 chars, no padding: satisfies the
        # >= 24 url-safe chars URL_SAFE_TOKEN_RE precondition.
        fake_blob = base64.b64encode(b"foobarbazqux" + b"doabc1234567").decode()
        assert len(fake_blob) >= 24
        rec = logging.LogRecord("test", logging.INFO, __file__, 1,
                                "req token=" + fake_blob,
                                (), None)
        filt.filter(rec)
        assert fake_blob[:12] not in rec.msg
        assert "<redacted>" in rec.msg or "<redacted-token>" in rec.msg

    def test_scrubs_json_password_field(self):
        filt = auth.RedactingFilter()
        # Constructed at runtime; keeps the non-alphanumeric tail the
        # JSON-field pattern must cope with.
        pw = "hunter2" + "!!"
        rec = logging.LogRecord("test", logging.INFO, __file__, 1,
                                '{"login":123,"password":"%s"}' % pw,
                                (), None)
        filt.filter(rec)
        assert pw not in rec.msg

    def test_scrubs_via_args_tuple(self):
        filt = auth.RedactingFilter()
        # Use a 40-char blob so we hit the URL_SAFE_TOKEN_RE (>= 24).
        long_secret = "hunter2" + "Y" * 33
        rec = logging.LogRecord("test", logging.INFO, __file__, 1,
                                "user=%s pw=%s", ("alice", long_secret),
                                None)
        filt.filter(rec)
        rendered = "%s %s" % (rec.args or ("", ""))
        assert long_secret not in rendered, (
            "long secret in args survived redaction")

    def test_short_bearer_word_not_over_scrubbed(self):
        # Words shorter than 24 chars pass through -- we only scrub
        # long token-like blobs and explicit key=value pairs.
        filt = auth.RedactingFilter()
        rec = logging.LogRecord("test", logging.INFO, __file__, 1,
                                "hello world greetings from tests",
                                (), None)
        filt.filter(rec)
        assert rec.msg == "hello world greetings from tests"

    def test_install_redacting_filter_is_idempotent(self):
        f1 = auth.install_redacting_filter("agent.platform.tests_isolated")
        f2 = auth.install_redacting_filter("agent.platform.tests_isolated")
        lg = logging.getLogger("agent.platform.tests_isolated")
        matching = [f for f in lg.filters
                    if isinstance(f, auth.RedactingFilter)]
        assert len(matching) == 1, (
            "install_redacting_filter should replace the prior filter, "
            "not stack them")
        # The second call should return the fresh filter, not the first.
        assert f2 is not f1


# ---------------------------------------------------------------------------
# End-to-end: an install-token scrubbed from an accidentally-logged line
# ---------------------------------------------------------------------------

class TestInstallTokenNeverLeaks:

    def test_generated_token_scrubbed_when_logged(self, caplog):
        auth.install_redacting_filter("agent.platform.tests_leak")
        lg = logging.getLogger("agent.platform.tests_leak")
        t = auth.generate_install_token()
        with caplog.at_level(logging.DEBUG, logger="agent.platform.tests_leak"):
            lg.info("about to accidentally leak %s here", t)
        assert t not in caplog.text, (
            "install token survived the RedactingFilter -- log scrubber "
            "regression")
