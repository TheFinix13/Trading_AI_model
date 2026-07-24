"""F006 API tests -- `/api/auth/status` + install-token gate on /api/*.

Two lanes exercised:

- Localhost-open behaviour: `enforce_install_token=False` means all
  Sprint 0 routes stay reachable. `/api/auth/status` still emits a
  well-shaped payload.
- Non-localhost gate: `enforce_install_token=True` blocks /api/*
  routes without a token. Presenting the stored install token via
  header / cookie / query all pass.
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

from agent.platform import auth, credentials  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


def _get(url: str, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except json.JSONDecodeError:
            body = {}
        return e.code, body


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
    yield
    credentials._reset_state_for_tests()


# ---------------------------------------------------------------------------
# /api/auth/status
# ---------------------------------------------------------------------------

class TestAuthStatusEndpoint:

    def test_status_unauthenticated_shape(self, tmp_path):
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, body = _get(f"http://{host}:{port}/api/auth/status")
            assert code == 200
            assert set(body.keys()) == {
                "authenticated", "install_fingerprint", "keyring_available"}
            assert body["authenticated"] is False
            assert body["install_fingerprint"] is None
        finally:
            srv.shutdown()

    def test_status_after_generation(self, tmp_path):
        auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, body = _get(f"http://{host}:{port}/api/auth/status")
            assert code == 200
            assert body["authenticated"] is True
            assert body["install_fingerprint"]
            # Never leaks the full token.
            token = auth.load_install_token()
            assert token not in json.dumps(body)
        finally:
            srv.shutdown()

    def test_status_reachable_without_token_when_gate_on(self, tmp_path):
        auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, body = _get(f"http://{host}:{port}/api/auth/status")
            # The gate exempts /api/auth/status so unauth-ed clients
            # can probe whether the install is set up.
            assert code == 200
            assert body["authenticated"] is True
        finally:
            srv.shutdown()


# ---------------------------------------------------------------------------
# Install-token gate
# ---------------------------------------------------------------------------

class TestInstallTokenGate:

    def test_no_token_blocks_protected_route(self, tmp_path):
        auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, body = _get(f"http://{host}:{port}/api/performance/state")
            assert code == 401
            assert body.get("error"), body
        finally:
            srv.shutdown()

    def test_correct_header_unlocks(self, tmp_path):
        t = auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, body = _get(f"http://{host}:{port}/api/performance/state",
                              headers={"X-Bluelock-Token": t})
            assert code == 200, body
        finally:
            srv.shutdown()

    def test_bearer_header_unlocks(self, tmp_path):
        t = auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, body = _get(f"http://{host}:{port}/api/performance/state",
                              headers={"Authorization": f"Bearer {t}"})
            assert code == 200, body
        finally:
            srv.shutdown()

    def test_cookie_unlocks(self, tmp_path):
        t = auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, body = _get(f"http://{host}:{port}/api/performance/state",
                              headers={"Cookie": f"platform_token={t}"})
            assert code == 200, body
        finally:
            srv.shutdown()

    def test_query_token_unlocks(self, tmp_path):
        t = auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, body = _get(
                f"http://{host}:{port}/api/performance/state?token={t}")
            assert code == 200, body
        finally:
            srv.shutdown()

    def test_wrong_token_blocks(self, tmp_path):
        auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, _ = _get(f"http://{host}:{port}/api/performance/state",
                           headers={"X-Bluelock-Token": "A" * 43})
            assert code == 401
        finally:
            srv.shutdown()

    def test_platform_toml_fallback_accepted(self, tmp_path):
        # No install token stored; only the legacy platform.toml token.
        # Generated at runtime -- no token-shaped literal for scanners.
        legacy_tok = _secrets.token_urlsafe(27)
        srv = _make_server(tmp_path, enforce=True, auth_token=legacy_tok)
        try:
            host, port = srv.server_address
            # The old auth_token path lives on the _authorized() layer
            # (Bearer / cookie / query) and also the new install-gate
            # layer (as `fallback_token`). Either wins.
            code, _ = _get(
                f"http://{host}:{port}/api/performance/state",
                headers={"Authorization": f"Bearer {legacy_tok}"})
            assert code == 200
        finally:
            srv.shutdown()

    def test_gate_off_for_localhost_mode(self, tmp_path):
        """enforce=False keeps single-user dev loop open on 127.0.0.1."""
        srv = _make_server(tmp_path, enforce=False)
        try:
            host, port = srv.server_address
            code, _ = _get(f"http://{host}:{port}/api/performance/state")
            assert code == 200
        finally:
            srv.shutdown()

    def test_healthz_stays_open(self, tmp_path):
        auth.generate_install_token()
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            code, body = _get(f"http://{host}:{port}/healthz")
            assert code == 200
            assert body["status"] == "ok"
        finally:
            srv.shutdown()


# ---------------------------------------------------------------------------
# Regression: install-token never appears in any log the server emits
# ---------------------------------------------------------------------------

def test_install_token_not_leaked_in_error_body(tmp_path):
    t = auth.generate_install_token()
    srv = _make_server(tmp_path, enforce=True)
    try:
        host, port = srv.server_address
        code, body = _get(f"http://{host}:{port}/api/performance/state")
        assert code == 401
        assert t not in json.dumps(body), (
            "install token leaked into 401 body")
    finally:
        srv.shutdown()
