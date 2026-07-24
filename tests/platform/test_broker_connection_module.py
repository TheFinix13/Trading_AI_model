"""F007 module smoke -- `agent/platform/broker_connection.py`.

Complements tests/security/test_broker_connection.py with contract +
signature checks.
"""
from __future__ import annotations

import inspect
import secrets as _secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Throwaway fixture password -- obviously non-secret shape for scanners.
_FIXTURE_PW = "x" * 12

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


def test_public_api_present():
    for name in ("is_mt5_available", "test_connection",
                 "save_credentials", "load_credentials",
                 "list_aliases", "delete_credentials",
                 "reset_rate_limiter", "ALLOWED_SERVERS",
                 "BROKER_NAMESPACE"):
        assert hasattr(broker_connection, name), f"missing: {name!r}"


def test_test_connection_signature():
    sig = inspect.signature(broker_connection.test_connection)
    assert list(sig.parameters.keys()) == [
        "login", "password", "server", "timeout"]


def test_test_connection_result_shape():
    r = broker_connection.test_connection(
        login="12345", password=_FIXTURE_PW, server="Exness-MT5Demo")
    assert set(r.keys()) == {
        "success", "error_code", "error_message", "account_type",
        "account_number", "balance_currency", "server"}


def test_is_mt5_available_returns_bool():
    v = broker_connection.is_mt5_available()
    assert isinstance(v, bool)


def test_allowed_servers_non_empty_tuple():
    assert isinstance(broker_connection.ALLOWED_SERVERS, tuple)
    assert len(broker_connection.ALLOWED_SERVERS) >= 5
    for prefix in broker_connection.ALLOWED_SERVERS:
        assert isinstance(prefix, str)
        assert prefix, "prefix must be non-empty"


def test_save_and_load_round_trip():
    ok = broker_connection.save_credentials(
        "primary", "12345", _FIXTURE_PW, "Exness-MT5Demo", "demo")
    assert ok is True
    loaded = broker_connection.load_credentials("primary")
    assert loaded is not None
    assert loaded["login"] == "12345"
    assert loaded["password"] == _FIXTURE_PW
    assert loaded["server"] == "Exness-MT5Demo"
    assert loaded["account_type"] == "demo"


def test_list_aliases_returns_metadata_only():
    broker_connection.save_credentials(
        "primary", "12345", _FIXTURE_PW, "Exness-MT5Demo", "demo")
    rows = broker_connection.list_aliases()
    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) == {"alias", "account_type", "server", "login"}
    assert "password" not in row


def test_delete_reduces_list():
    broker_connection.save_credentials(
        "one", "111", "pwabcdef", "Exness-MT5Demo", "demo")
    broker_connection.save_credentials(
        "two", "222", "pwghijkl", "Exness-MT5Demo", "live")
    assert len(broker_connection.list_aliases()) == 2
    assert broker_connection.delete_credentials("one") is True
    aliases = {r["alias"] for r in broker_connection.list_aliases()}
    assert aliases == {"two"}


def test_load_nonexistent_returns_none():
    assert broker_connection.load_credentials("no-such-alias") is None


def test_broker_namespace_constant():
    assert broker_connection.BROKER_NAMESPACE == "broker_mt5"
