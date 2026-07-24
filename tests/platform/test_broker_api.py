"""F007 broker API tests -- /settings/broker + /api/broker/*.

Exercises the routes wired in ``scripts/serve_platform.py``:

- ``GET /settings/broker`` -> HTML shell of the wizard.
- ``GET /api/broker/list`` -> list of saved aliases (no passwords).
- ``POST /api/broker/save`` -> stores a credential under an alias.
- ``DELETE /api/broker/<alias>`` -> removes it.
- ``POST /api/broker/test-connection`` -> returns a friendly
  short-circuit payload on macOS/Linux where MT5 is unavailable.
- ``GET /api/broker/live-warning`` -> Legal warning text (auth-open).
- Install-token gate on non-localhost binds still gates broker routes.
"""
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

# Runtime-generated fixture password; the no-leak assertions below use the
# same value, so no secret-shaped literal ever appears in this file.
_FIXTURE_PW = "fixture-pw-" + _secrets.token_hex(6)

from agent.platform import auth, broker_connection, credentials  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


def _request(url: str, method: str = "GET", body: dict | None = None,
             headers: dict | None = None) -> tuple[int, str, dict | None]:
    data = json.dumps(body).encode() if body is not None else None
    hdrs = dict(headers or {})
    if body is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        code = e.code
    else:
        code = resp.status
    try:
        parsed = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        parsed = None
    return code, raw, parsed


def _make_server(tmp_path: Path, enforce: bool, auth_token: str | None = None):
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    log_root = tmp_path / "logs"
    log_root.mkdir(exist_ok=True)
    handler = make_handler(log_root, tmp_path, reviews,
                           live_dir=tmp_path / "sq",
                           auth_token=auth_token,
                           enforce_install_token=enforce)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


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


class TestWizardHtml:

    def test_wizard_html_served(self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(f"http://{host}:{port}/settings/broker")
            assert code == 200
            assert "Connect your broker" in raw
            assert "in-pw" in raw  # password field id
            assert 'type="password"' in raw
            assert 'autocomplete="off"' in raw
        finally:
            srv.shutdown()

    def test_wizard_html_trailing_slash(self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, _, _ = _request(f"http://{host}:{port}/settings/broker/")
            assert code == 200
        finally:
            srv.shutdown()


class TestListEndpoint:

    def test_list_empty_when_nothing_stored(self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, _, body = _request(f"http://{host}:{port}/api/broker/list")
            assert code == 200
            assert body == {"aliases": []}
        finally:
            srv.shutdown()

    def test_list_shows_stored_alias_but_no_password(self, tmp_path):
        broker_connection.save_credentials(
            alias="primary", login="12345",
            password=_FIXTURE_PW,
            server="Demo-Server1", account_type="demo")
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, raw, body = _request(
                f"http://{host}:{port}/api/broker/list")
            assert code == 200
            assert len(body["aliases"]) == 1
            row = body["aliases"][0]
            assert row["alias"] == "primary"
            assert row["account_type"] == "demo"
            assert row["server"] == "Demo-Server1"
            assert row["login"] == "12345"
            assert "password" not in row
            assert _FIXTURE_PW not in raw
        finally:
            srv.shutdown()


class TestSaveEndpoint:

    def test_save_round_trips(self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/save",
                method="POST",
                body={"alias": "primary", "login": "12345",
                      "password": _FIXTURE_PW, "server": "Demo-Server1",
                      "account_type": "demo"})
            assert code == 200
            assert body == {"success": True}
            code, _, listing = _request(
                f"http://{host}:{port}/api/broker/list")
            assert code == 200
            assert len(listing["aliases"]) == 1
        finally:
            srv.shutdown()

    def test_save_rejects_disallowed_server(self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/save",
                method="POST",
                body={"alias": "hacker", "login": "12345",
                      "password": _FIXTURE_PW,
                      "server": "evil.example.com",
                      "account_type": "demo"})
            assert code == 400
            assert body["success"] is False
            assert "allow-list" in body["error"]
        finally:
            srv.shutdown()

    def test_save_rejects_bad_alias(self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/save",
                method="POST",
                body={"alias": "../etc/passwd", "login": "12345",
                      "password": _FIXTURE_PW,
                      "server": "Demo-Server1",
                      "account_type": "demo"})
            assert code == 400
            assert body["success"] is False
        finally:
            srv.shutdown()

    def test_save_ignores_junk_body(self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/save",
                method="POST",
                body={})
            assert code == 400
            assert body["success"] is False
        finally:
            srv.shutdown()


class TestDeleteEndpoint:

    def test_delete_removes_alias(self, tmp_path):
        broker_connection.save_credentials(
            alias="to-remove", login="12345", password=_FIXTURE_PW,
            server="Demo-Server1", account_type="demo")
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/to-remove",
                method="DELETE")
            assert code == 200
            assert body == {"success": True}
            assert broker_connection.list_aliases() == []
        finally:
            srv.shutdown()

    def test_delete_unknown_alias_returns_false(self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/nonexistent",
                method="DELETE")
            assert code == 200
            assert body == {"success": False}
        finally:
            srv.shutdown()


class TestTestConnectionEndpoint:

    def test_test_connection_short_circuits_when_mt5_unavailable(
            self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, raw, body = _request(
                f"http://{host}:{port}/api/broker/test-connection",
                method="POST",
                body={"login": "12345", "password": _FIXTURE_PW,
                      "server": "Demo-Server1"})
            assert code == 200
            assert body["success"] is False
            assert body["account_type"] == "unknown"
            # Password must never appear in response payload.
            assert _FIXTURE_PW not in raw
        finally:
            srv.shutdown()

    def test_test_connection_rejects_disallowed_server(self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/test-connection",
                method="POST",
                body={"login": "12345", "password": _FIXTURE_PW,
                      "server": "evil.example.com"})
            assert code == 200
            assert body["success"] is False
            # broker_connection wraps to a friendly error payload rather
            # than raising, so the response body still reads well.
        finally:
            srv.shutdown()


class TestLiveWarningEndpoint:

    def test_live_warning_served_plain_text(self, tmp_path):
        # Ensure the on-disk warning file exists via the repo -- if not,
        # the server falls back to a safe minimal string.
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(
                f"http://{host}:{port}/api/broker/live-warning")
            assert code == 200
            assert "real money" in raw.lower()
        finally:
            srv.shutdown()

    def test_live_warning_reachable_without_token_when_gate_on(self,
                                                                tmp_path):
        auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/api/broker/live-warning")
            assert code == 200
        finally:
            srv.shutdown()


class TestBrokerGate:

    def test_broker_list_blocked_without_token_when_gate_on(self, tmp_path):
        auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/list")
            assert code == 401
            assert body["error"]
        finally:
            srv.shutdown()

    def test_broker_list_unlocks_with_token(self, tmp_path):
        t = auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/list",
                headers={"X-Bluelock-Token": t})
            assert code == 200
            assert "aliases" in body
        finally:
            srv.shutdown()

    def test_broker_save_blocked_without_token_when_gate_on(self, tmp_path):
        auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/save",
                method="POST",
                body={"alias": "primary", "login": "12345",
                      "password": _FIXTURE_PW,
                      "server": "Demo-Server1",
                      "account_type": "demo"})
            assert code == 401
            assert body["error"]
        finally:
            srv.shutdown()

    def test_broker_delete_blocked_without_token_when_gate_on(self, tmp_path):
        auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/broker/anything",
                method="DELETE")
            assert code == 401
            assert body["error"]
        finally:
            srv.shutdown()
