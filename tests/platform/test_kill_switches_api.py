"""F011 -- /api/kill-switches/* endpoint tests.

Coverage:
- GET /api/kill-switches/status returns killed_scopes + events + supported.
- POST /api/kill-switches/activate creates the flag and returns ok.
- POST /api/kill-switches/clear removes the flag and returns ok.
- Activate/clear roundtrip: activate -> status shows it, clear -> gone.
- Install-token gate: with `enforce_install_token=True` and no valid
  token, activate returns 401.
- Unknown symbol returns 400 with an error message.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import (  # noqa: E402
    auth, broker_connection, credentials, kill_switch_admin, kill_switches,
    rate_limiter,
)
from scripts.serve_platform import make_handler  # noqa: E402


def _request(url: str, method: str = "GET", body: dict | None = None,
             headers: dict | None = None
             ) -> tuple[int, str, dict | None]:
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
    result = parsed if isinstance(parsed, dict) else None
    return code, raw, result


def _make_server(tmp_path: Path, *,
                 enforce_install_token: bool = False,
                 auth_token: str | None = None):
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    log_root = tmp_path / "logs"
    log_root.mkdir(exist_ok=True)
    handler = make_handler(
        log_root, tmp_path, reviews,
        live_dir=tmp_path / "sq",
        auth_token=auth_token,
        enforce_install_token=enforce_install_token,
        enforce_onboarding_gate=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase("kill-tests-passphrase")
    credentials.force_fallback(True)
    monkeypatch.setenv(kill_switches.KILL_DIR_ENV,
                       str(tmp_path / "cfg" / "kill"))
    broker_connection.reset_rate_limiter()
    rate_limiter.reset()
    auth.set_session_expiry_seconds(7 * 24 * 3600)
    kill_switches.reset_cache_for_tests()
    yield
    credentials._reset_state_for_tests()
    broker_connection.reset_rate_limiter()
    rate_limiter.reset()
    kill_switches.reset_cache_for_tests()


class TestStatusEndpoint:
    def test_status_empty_state(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/kill-switches/status")
            assert code == 200
            assert body["killed_scopes"] == []
            assert body["events"] == []
            assert "EURUSD" in body["supported_symbols"]
        finally:
            srv.shutdown()

    def test_status_reflects_activate(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            kill_switch_admin.activate_kill("EURUSD", reason="spread")
            kill_switches.reset_cache_for_tests()
            code, _, body = _request(
                f"http://{host}:{port}/api/kill-switches/status")
            assert code == 200
            scopes = [s["scope"] for s in body["killed_scopes"]]
            assert "EURUSD" in scopes
            assert body["events"], "audit log must contain at least one event"
        finally:
            srv.shutdown()


class TestActivateEndpoint:
    def test_activate_creates_flag(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/kill-switches/activate",
                method="POST",
                body={"symbol": "EURUSD", "reason": "flash halt"})
            assert code == 200
            assert body == {"ok": True}
            assert kill_switches.is_killed("EURUSD") is True
        finally:
            srv.shutdown()

    def test_activate_global_via_null_symbol(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/kill-switches/activate",
                method="POST",
                body={"reason": "everything wobbly"})
            assert code == 200 and body == {"ok": True}
            assert kill_switches.is_killed() is True
        finally:
            srv.shutdown()

    def test_activate_unknown_symbol_returns_400(
        self, tmp_path: Path
    ) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/kill-switches/activate",
                method="POST",
                body={"symbol": "XAUUSD", "reason": "x"})
            assert code == 400
            assert body["ok"] is False
            assert "unknown symbol" in body["error"]
        finally:
            srv.shutdown()


class TestClearEndpoint:
    def test_clear_removes_flag(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            kill_switch_admin.activate_kill("EURUSD", reason="x")
            kill_switches.reset_cache_for_tests()
            code, _, body = _request(
                f"http://{host}:{port}/api/kill-switches/clear",
                method="POST",
                body={"symbol": "EURUSD"})
            assert code == 200 and body == {"ok": True}
            assert kill_switches.is_killed("EURUSD") is False
        finally:
            srv.shutdown()


class TestInstallTokenGate:
    def test_activate_requires_install_token_on_non_localhost_semantics(
        self, tmp_path: Path
    ) -> None:
        """The activate endpoint is behind the F006 install-token gate
        when `enforce_install_token=True`. With no token stored, a POST
        must be rejected with 401."""
        # Do NOT generate an install token first; the gate must refuse
        # the write.
        srv = _make_server(tmp_path, enforce_install_token=True)
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/api/kill-switches/activate",
                method="POST",
                body={"symbol": "EURUSD", "reason": "attempt"})
            assert code == 401, (
                "kill-switch activate must reject unauthenticated calls "
                "when the install-token gate is enforced")
            assert kill_switches.is_killed("EURUSD") is False
        finally:
            srv.shutdown()


class TestPageServed:
    def test_page_html_route(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(
                f"http://{host}:{port}/settings/kill-switches")
            assert code == 200
            assert "Kill switches" in raw
            assert "/api/kill-switches/status" in raw
        finally:
            srv.shutdown()
