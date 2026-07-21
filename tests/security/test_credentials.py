"""F006 security tests -- `agent/platform/credentials.py`.

Per D048, an auth/credentials-touching feature needs at minimum:

(a) auth-bypass negative tests -- the module rejects malformed / empty
    / control-char / oversized / path-traversal inputs before touching
    the backend.
(b) credential-storage-at-rest tests -- the encrypted-file fallback
    holds NO plaintext of the stored value, and the salt+passphrase
    round-trip is honest.
(c) input-fuzz tests on the credential fields.
(d) log-scrubber regression -- secrets never appear in log output.

Tests use throwaway passphrases inside a `tmp_path` config dir; the
real OS keychain is never touched thanks to `force_fallback(True)`.
"""
from __future__ import annotations

import logging
import string
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import credentials  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Every credentials test gets its own tmp_path + passphrase.

    Force-flips the fallback so real OS keychain calls never happen.
    """
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path)
    credentials.set_encrypted_file_passphrase("test-passphrase-" + "x" * 12)
    credentials.force_fallback(True)
    yield
    credentials._reset_state_for_tests()


# ---------------------------------------------------------------------------
# (a) auth-bypass -- rejecting malformed / empty / oversized inputs
# ---------------------------------------------------------------------------

class TestInputRejection:
    """The module refuses malformed inputs BEFORE any backend call.

    Attacker payloads simulated here: empty strings, whitespace-only,
    control chars, path-traversal (`..`, `/`, `\\`), oversized values,
    non-string types.
    """

    @pytest.mark.parametrize("bad_ns", [
        "", " ", "  ", "..", "../evil", "a/b", "a\\b",
        "a\x00b", "a\nb", "a\tb", "x" * 65,
        None, 123, [], {},
    ])
    def test_rejects_bad_namespace(self, bad_ns):
        with pytest.raises((ValueError, TypeError)):
            credentials.store_secret(bad_ns, "k", "v")  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_key", [
        "", " ", "  ", "..", "../evil", "a/b", "a\\b",
        "a\x00b", "a\nb", "a\tb", "x" * 65,
        None, 123, [], {},
    ])
    def test_rejects_bad_key(self, bad_key):
        with pytest.raises((ValueError, TypeError)):
            credentials.store_secret("ns", bad_key, "v")  # type: ignore[arg-type]

    def test_rejects_empty_value(self):
        with pytest.raises(ValueError):
            credentials.store_secret("ns", "k", "")

    def test_rejects_control_char_value(self):
        with pytest.raises(ValueError):
            credentials.store_secret("ns", "k", "abc\x00def")

    def test_rejects_oversized_value(self):
        with pytest.raises(ValueError):
            credentials.store_secret("ns", "k", "x" * 20000)

    def test_rejects_reserved_index_key(self):
        with pytest.raises(ValueError):
            credentials.store_secret("ns", "__index__", "v")


# ---------------------------------------------------------------------------
# (b) storage-at-rest -- encrypted-file fallback holds no plaintext
# ---------------------------------------------------------------------------

class TestEncryptedFallback:

    def test_round_trip_preserves_value(self):
        credentials.store_secret("mybroker", "alias-1", "hunter2-not-a-log")
        assert credentials.retrieve_secret("mybroker", "alias-1") \
            == "hunter2-not-a-log"

    def test_stored_bytes_do_not_contain_plaintext(self, tmp_path):
        sentinel = "ClearTextValue-must-not-hit-disk-8f7a"
        credentials.store_secret("ns", "k", sentinel)
        path = credentials.encrypted_file_path()
        assert path.is_file(), "encrypted file should exist after store"
        raw = path.read_bytes()
        assert sentinel.encode() not in raw, (
            "plaintext secret found in encrypted-file fallback")

    def test_wrong_passphrase_fails_safely(self):
        credentials.store_secret("ns", "k", "value")
        credentials.set_encrypted_file_passphrase("some-other-passphrase-y" * 3)
        assert credentials.retrieve_secret("ns", "k") is None

    def test_delete_removes_from_disk(self):
        credentials.store_secret("ns", "k", "value")
        assert credentials.delete_secret("ns", "k") is True
        assert credentials.retrieve_secret("ns", "k") is None

    def test_list_keys_omits_values(self):
        credentials.store_secret("brokers", "primary", "PW-secret-1")
        credentials.store_secret("brokers", "backup", "PW-secret-2")
        keys = credentials.list_keys("brokers")
        assert set(keys) == {"primary", "backup"}
        # Sanity: the values themselves should not be in the returned
        # list under any circumstance.
        for k in keys:
            assert "PW-secret" not in k

    def test_list_keys_hides_index_marker(self):
        credentials.store_secret("ns", "alpha", "v")
        keys = credentials.list_keys("ns")
        assert "__index__" not in keys


# ---------------------------------------------------------------------------
# (c) input-fuzz on the credential value field
# ---------------------------------------------------------------------------

class TestValueFuzz:
    """Round-trips over a variety of value shapes -- anything that
    survives sanitisation must decrypt back to itself byte-for-byte.
    """

    @pytest.mark.parametrize("value", [
        "simple",
        "with space",
        "with-dash",
        "with_underscore",
        "with.dots",
        "unicode-\u00e9\u00e0\u00fc-\u4e2d",
        "long-" + "x" * 4000,
        string.ascii_letters + string.digits + "!@#$%^&*()",
        "tab\tinside",
        "newline\ninside",
        "quotes\"and'apostrophes",
        "json{\"embedded\":\"value\"}",
        "sql'; DROP TABLE users; --",
        "<script>alert(1)</script>",
    ])
    def test_round_trip(self, value):
        assert credentials.store_secret("fuzz", "k", value)
        assert credentials.retrieve_secret("fuzz", "k") == value


# ---------------------------------------------------------------------------
# (d) log-scrubber regression -- secrets never appear in log output
# ---------------------------------------------------------------------------

class TestLogScrubbing:
    """The module's own log lines must NOT include the plaintext value.

    We attach a memory-handler to the credentials logger, exercise the
    public API with a distinctive sentinel, and assert the sentinel
    never appears in any log record.
    """

    def test_store_does_not_log_value(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="agent.platform.credentials"):
            credentials.store_secret("ns", "k",
                                     "SentinelPlaintext-do-not-log-8b3a")
        assert "SentinelPlaintext-do-not-log-8b3a" not in caplog.text

    def test_retrieve_does_not_log_value(self, caplog):
        credentials.store_secret("ns", "k",
                                 "SentinelPlaintext-do-not-log-9c4d")
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="agent.platform.credentials"):
            _ = credentials.retrieve_secret("ns", "k")
        assert "SentinelPlaintext-do-not-log-9c4d" not in caplog.text


# ---------------------------------------------------------------------------
# no-passphrase safe degradation
# ---------------------------------------------------------------------------

class TestDegradation:

    def test_store_without_passphrase_returns_false(self, monkeypatch):
        credentials.set_encrypted_file_passphrase(None)
        monkeypatch.delenv("BLUELOCK_PASSPHRASE", raising=False)
        assert credentials.store_secret("ns", "k", "v") is False

    def test_retrieve_without_passphrase_returns_none(self, monkeypatch):
        credentials.set_encrypted_file_passphrase(None)
        monkeypatch.delenv("BLUELOCK_PASSPHRASE", raising=False)
        assert credentials.retrieve_secret("ns", "k") is None

    def test_force_fallback_toggle(self):
        credentials.force_fallback(False)
        # We don't touch the real OS keychain in this suite; the toggle
        # is exercised for its own state-management, not for effect.
        assert credentials._FORCE_FALLBACK is False
        credentials.force_fallback(True)
        assert credentials._FORCE_FALLBACK is True
