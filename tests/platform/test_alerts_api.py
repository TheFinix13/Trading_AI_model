"""F014 -- /api/alerts/* endpoint tests (spec asked 1; shipped 5)."""
from __future__ import annotations

import json
import secrets as _secrets
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import (  # noqa: E402
    alerts, alerts_telegram, auth, broker_connection, broker_health,
    credentials, kill_switches, rate_limiter, risk_budget,
)
from scripts.serve_platform import make_handler  # noqa: E402


def _request(url: str, method: str = "GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = dict(headers or {})
    if body is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode(errors="replace")
            code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        code = e.code
    try:
        parsed = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        parsed = None
    return code, raw, (parsed if isinstance(parsed, dict) else None)


def _make_server(tmp_path: Path, *, enforce_install_token: bool = False):
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    log_root = tmp_path / "logs"
    log_root.mkdir(exist_ok=True)
    handler = make_handler(
        log_root, tmp_path, reviews,
        live_dir=tmp_path / "sq",
        enforce_install_token=enforce_install_token,
        enforce_onboarding_gate=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    monkeypatch.setenv(kill_switches.KILL_DIR_ENV,
                       str(tmp_path / "cfg" / "kill"))
    broker_connection.reset_rate_limiter()
    broker_health.clear_cache()
    rate_limiter.reset()
    auth.set_session_expiry_seconds(7 * 24 * 3600)
    risk_budget.reset_state()
    alerts.reset()
    alerts_telegram.reset()
    yield
    credentials._reset_state_for_tests()
    broker_connection.reset_rate_limiter()
    broker_health.clear_cache()
    rate_limiter.reset()
    risk_budget.reset_state()
    alerts.reset()
    alerts_telegram.reset()


class TestGetConfig:
    def test_default_config_returned(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/alerts/config")
            assert code == 200
            assert body["enabled"] is False
            assert body["bot_token_configured"] is False
            assert "per_event" in body
        finally:
            srv.shutdown()


class TestPostConfig:
    def test_update_persists(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/alerts/config",
                method="POST",
                body={"enabled": True,
                      "per_event": {"stop_hit": False}})
            assert code == 200
            assert body["ok"] is True
            cfg = body["config"]
            assert cfg["per_event"]["stop_hit"] is False
        finally:
            srv.shutdown()

    def test_auth_gate_rejects_unauthenticated(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path, enforce_install_token=True)
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/api/alerts/config",
                method="POST",
                body={"enabled": True})
            assert code == 401
        finally:
            srv.shutdown()


class TestPostTest:
    def test_test_publishes_event(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/alerts/test",
                method="POST", body={})
            assert code == 200
            assert body["ok"] is True
            assert body["event"]["type"] == "trade_fill"
            # Ring buffer sees it too.
            assert alerts.recent(1)[0]["id"] == body["event"]["id"]
        finally:
            srv.shutdown()


class TestGetRecent:
    def test_recent_returns_ring_buffer(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        alerts.publish("trade_fill", {"n": 1})
        alerts.publish("stop_hit", {"n": 2})
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/alerts/recent")
            assert code == 200
            assert len(body["events"]) == 2
            # Newest first.
            assert body["events"][0]["type"] == "stop_hit"
        finally:
            srv.shutdown()


class TestAlertsPageServed:
    def test_page_html_route(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(f"http://{host}:{port}/alerts")
            assert code == 200
            assert "Alerts" in raw
            assert "/api/alerts/stream" in raw
        finally:
            srv.shutdown()
