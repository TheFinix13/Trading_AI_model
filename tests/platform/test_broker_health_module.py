"""F012 -- broker_health module tests.

Coverage (5+):
1. 30-s cache round-trip -- second call within TTL doesn't hit backend.
2. No credentials -> friendly "no credentials" payload, no probe call.
3. Password NEVER surfaces in the return payload.
4. list_health_states matches list_aliases + reflects cache.
5. clear_cache invalidates -- subsequent call re-probes.
6. Custom cache_ttl kwarg respected.
7. is_broker_alive returns bool derived from `alive`.
"""
from __future__ import annotations

import secrets as _secrets

from pathlib import Path
from unittest.mock import patch

import pytest

from agent.platform import (
    broker_connection, broker_health, credentials,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    broker_connection.reset_rate_limiter()
    broker_health.clear_cache()
    yield
    credentials._reset_state_for_tests()
    broker_connection.reset_rate_limiter()
    broker_health.clear_cache()


def _fake_test_connection_success(*, login: str, password: str,
                                  server: str, timeout: float = 4.0) -> dict:
    """Stand-in for broker_connection.test_connection -- always green,
    NEVER echoes password."""
    return {
        "success": True,
        "error_code": None,
        "error_message": None,
        "account_type": "demo",
        "account_number": login,
        "balance_currency": "USD",
        "server": server,
    }


def _fake_test_connection_fail(*, login: str, password: str,
                               server: str, timeout: float = 4.0) -> dict:
    return {
        "success": False,
        "error_code": 6,
        "error_message": "connection refused",
        "account_type": "unknown",
        "account_number": login,
        "balance_currency": None,
        "server": server,
    }


class TestNoCredentials:
    def test_missing_alias_short_circuits(self) -> None:
        result = broker_health.check_broker_health("nonexistent")
        assert result["alive"] is False
        assert result["reason"] == "no credentials"
        assert result["account_type"] is None
        assert "password" not in result


class TestCache:
    def test_second_call_hits_cache(self) -> None:
        broker_connection.save_credentials(
            alias="live-1", login=12345, password="x" * 12,
            server="MetaQuotes-Demo", account_type="demo")
        with patch("agent.platform.broker_health.broker_connection."
                   "test_connection",
                   side_effect=_fake_test_connection_success) as m:
            first = broker_health.check_broker_health("live-1")
            second = broker_health.check_broker_health("live-1")
        assert first["alive"] is True
        assert first["cached"] is False
        assert second["cached"] is True
        assert m.call_count == 1

    def test_custom_ttl_forces_refetch(self) -> None:
        broker_connection.save_credentials(
            alias="live-1", login=12345, password="x" * 12,
            server="MetaQuotes-Demo", account_type="demo")
        with patch("agent.platform.broker_health.broker_connection."
                   "test_connection",
                   side_effect=_fake_test_connection_success) as m:
            broker_health.check_broker_health("live-1")
            # cache_ttl=0 forces a fresh probe on next call.
            broker_health.check_broker_health("live-1", cache_ttl=0)
        assert m.call_count == 2

    def test_clear_cache_invalidates(self) -> None:
        broker_connection.save_credentials(
            alias="live-1", login=12345, password="x" * 12,
            server="MetaQuotes-Demo", account_type="demo")
        with patch("agent.platform.broker_health.broker_connection."
                   "test_connection",
                   side_effect=_fake_test_connection_success) as m:
            broker_health.check_broker_health("live-1")
            broker_health.clear_cache()
            broker_health.check_broker_health("live-1")
        assert m.call_count == 2


class TestPasswordNeverInReturn:
    def test_password_scrubbed(self) -> None:
        pw = "scrub-check-pw-" + _secrets.token_hex(4)
        broker_connection.save_credentials(
            alias="live-1", login=12345, password=pw,
            server="MetaQuotes-Demo", account_type="demo")
        with patch("agent.platform.broker_health.broker_connection."
                   "test_connection",
                   side_effect=_fake_test_connection_success):
            result = broker_health.check_broker_health("live-1")
        for k, v in result.items():
            assert pw not in str(v), (
                f"password leaked into field {k!r}: {v!r}")


class TestFailurePath:
    def test_failure_returns_alive_false(self) -> None:
        broker_connection.save_credentials(
            alias="dead-1", login=99, password="p",
            server="MetaQuotes-Demo", account_type="demo")
        with patch("agent.platform.broker_health.broker_connection."
                   "test_connection",
                   side_effect=_fake_test_connection_fail):
            result = broker_health.check_broker_health("dead-1")
        assert result["alive"] is False
        assert result["reason"] == "connection refused"


class TestListHealthStates:
    def test_list_reflects_aliases(self) -> None:
        broker_connection.save_credentials(
            alias="a", login=1, password="p", server="MetaQuotes-Demo",
            account_type="demo")
        broker_connection.save_credentials(
            alias="b", login=2, password="p", server="MetaQuotes-Demo",
            account_type="demo")
        rows = broker_health.list_health_states()
        aliases = {r["alias"] for r in rows}
        assert aliases == {"a", "b"}
        # Neither has been probed yet.
        for r in rows:
            assert r["alive"] is False
            assert r["reason"] == "not yet probed"


class TestIsBrokerAlive:
    def test_wrapper_returns_bool(self) -> None:
        broker_connection.save_credentials(
            alias="live-1", login=1, password="p",
            server="MetaQuotes-Demo", account_type="demo")
        with patch("agent.platform.broker_health.broker_connection."
                   "test_connection",
                   side_effect=_fake_test_connection_success):
            assert broker_health.is_broker_alive("live-1") is True
