"""Healthcheck (external dead-man's-switch) pinger tests.

Telegram's "Agent OFFLINE" message needs the process to still be alive to
send it -- a genuine VM freeze leaves nothing running to send anything.
`HealthcheckPinger` closes that gap by pinging an external watchdog (e.g.
healthchecks.io) that raises its own alarm on missed pings. These tests
cover config resolution (per-symbol override), the fail-open contract (a
broken network/missing URL must never raise), and the URL suffixes used
for success/fail pings.
"""
from __future__ import annotations

import pytest

from agent.notifications.healthcheck import HealthcheckConfig, HealthcheckPinger


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.calls: list[tuple[str, str, bytes | None]] = []

    def get(self, url, timeout=None):
        self.calls.append(("GET", url, None))
        return _FakeResponse(self.status_code)

    def post(self, url, content=None, timeout=None):
        self.calls.append(("POST", url, content))
        return _FakeResponse(self.status_code)


class _RaisingClient:
    def get(self, url, timeout=None):
        raise ConnectionError("network unreachable")

    def post(self, url, content=None, timeout=None):
        raise ConnectionError("network unreachable")


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def test_config_falls_back_to_shared_url(monkeypatch):
    monkeypatch.delenv("HEALTHCHECK_URL_EURUSD", raising=False)
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc-ping.com/shared-uuid")
    cfg = HealthcheckConfig.from_env(symbol="EURUSD")
    assert cfg.url == "https://hc-ping.com/shared-uuid"
    assert cfg.configured


def test_config_prefers_per_symbol_url(monkeypatch):
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc-ping.com/shared-uuid")
    monkeypatch.setenv("HEALTHCHECK_URL_EURUSD", "https://hc-ping.com/eurusd-uuid")
    cfg = HealthcheckConfig.from_env(symbol="EURUSD")
    assert cfg.url == "https://hc-ping.com/eurusd-uuid"


def test_config_unconfigured_when_no_url(monkeypatch):
    monkeypatch.delenv("HEALTHCHECK_URL", raising=False)
    monkeypatch.delenv("HEALTHCHECK_URL_EURUSD", raising=False)
    cfg = HealthcheckConfig.from_env(symbol="EURUSD")
    assert not cfg.configured


def test_dry_run_is_always_configured():
    cfg = HealthcheckConfig(url="", dry_run=True)
    assert cfg.configured


# ---------------------------------------------------------------------------
# Pinger behaviour
# ---------------------------------------------------------------------------


def test_ping_success_hits_base_url():
    client = _FakeClient(status_code=200)
    pinger = HealthcheckPinger(HealthcheckConfig(url="https://hc-ping.com/uuid"), client=client)
    assert pinger.ping() is True
    assert client.calls == [("GET", "https://hc-ping.com/uuid", None)]


def test_ping_fail_hits_fail_suffix_with_body():
    client = _FakeClient(status_code=200)
    pinger = HealthcheckPinger(HealthcheckConfig(url="https://hc-ping.com/uuid"), client=client)
    assert pinger.ping_fail("kill switch tripped") is True
    method, url, body = client.calls[0]
    assert method == "POST"
    assert url == "https://hc-ping.com/uuid/fail"
    assert body == b"kill switch tripped"


def test_ping_start_hits_start_suffix():
    client = _FakeClient(status_code=200)
    pinger = HealthcheckPinger(HealthcheckConfig(url="https://hc-ping.com/uuid"), client=client)
    assert pinger.ping_start() is True
    assert client.calls == [("GET", "https://hc-ping.com/uuid/start", None)]


def test_ping_returns_false_on_non_2xx():
    client = _FakeClient(status_code=500)
    pinger = HealthcheckPinger(HealthcheckConfig(url="https://hc-ping.com/uuid"), client=client)
    assert pinger.ping() is False


def test_unconfigured_ping_is_a_noop_not_an_error():
    pinger = HealthcheckPinger(HealthcheckConfig(url=""))
    assert pinger.ping() is False


def test_network_failure_fails_open_never_raises():
    pinger = HealthcheckPinger(HealthcheckConfig(url="https://hc-ping.com/uuid"), client=_RaisingClient())
    assert pinger.ping() is False
    assert pinger.ping_fail("boom") is False


def test_dry_run_prints_instead_of_network(capsys):
    pinger = HealthcheckPinger(HealthcheckConfig(url="", dry_run=True))
    assert pinger.ping() is True
    out = capsys.readouterr().out
    assert "[healthcheck] ping" in out


@pytest.mark.parametrize("suffix_call,expected_suffix", [
    ("ping", ""),
    ("ping_start", "start"),
])
def test_from_env_wires_symbol_through(monkeypatch, suffix_call, expected_suffix):
    monkeypatch.setenv("HEALTHCHECK_URL_GBPUSD", "https://hc-ping.com/gbpusd-uuid")
    client = _FakeClient(status_code=200)
    pinger = HealthcheckPinger.from_env(symbol="GBPUSD")
    pinger._client = client
    getattr(pinger, suffix_call)()
    expected_url = "https://hc-ping.com/gbpusd-uuid" + (f"/{expected_suffix}" if expected_suffix else "")
    assert client.calls[0][1] == expected_url
