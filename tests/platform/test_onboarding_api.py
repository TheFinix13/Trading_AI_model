"""F008 -- onboarding API tests.

Exercises the routes wired in ``scripts/serve_platform.py``:

- ``GET /onboarding`` -> ONBOARDING_PAGE HTML.
- ``GET /settings/reset-install`` -> RESET_INSTALL_PAGE HTML.
- ``GET /api/onboarding/state`` -> full state dict.
- ``POST /api/onboarding/state?step=passphrase`` -> persists step.
- ``POST /api/onboarding/passphrase`` -> validates + accepts / rejects.
- ``POST /api/onboarding/pairs`` -> validates + stores default pairs.
- ``POST /api/onboarding/complete`` -> marks setup complete.
- ``POST /api/onboarding/reset`` -> wipes install state.
- First-visit gate: hitting `/hq` before setup redirects to `/onboarding`.
- After `mark_setup_complete`, `/hq` responds 200 again.
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

from agent.platform import (  # noqa: E402
    auth, broker_connection, credentials, onboarding,
)
from scripts.serve_platform import make_handler  # noqa: E402


def _request(url: str, method: str = "GET", body: dict | None = None,
             headers: dict | None = None, follow: bool = True,
             ) -> tuple[int, str, dict | None]:
    data = json.dumps(body).encode() if body is not None else None
    hdrs = dict(headers or {})
    if body is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # noqa: D401,A003
            return None

    if follow:
        opener = urllib.request.build_opener()
    else:
        opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req) as resp:
            raw = resp.read().decode(errors="replace")
            code = resp.status
            location = resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        code = e.code
        location = e.headers.get("Location", "") if e.headers else ""
    try:
        parsed = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        parsed = None
    result: dict | None = parsed if isinstance(parsed, dict) else None
    if location and not result:
        result = {"__location__": location}
    return code, raw, result


def _make_server(tmp_path: Path, enforce: bool = False,
                 auth_token: str | None = None,
                 onboarding_gate: bool = True):
    """Onboarding tests default to gate-on (that's what they're testing).
    Individual tests override to False when they need direct route
    access without the redirect."""
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    log_root = tmp_path / "logs"
    log_root.mkdir(exist_ok=True)
    handler = make_handler(log_root, tmp_path, reviews,
                           live_dir=tmp_path / "sq",
                           auth_token=auth_token,
                           enforce_install_token=enforce,
                           enforce_onboarding_gate=onboarding_gate)
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


# ---------------------------------------------------------------------------
# HTML routes
# ---------------------------------------------------------------------------

class TestOnboardingHtmlRoutes:

    def test_get_onboarding_html(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(
                f"http://{host}:{port}/onboarding")
            assert code == 200
            assert "Set up your Blue Lock install" in raw
            assert "Passphrase" in raw
        finally:
            srv.shutdown()

    def test_get_reset_install_html(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(
                f"http://{host}:{port}/settings/reset-install")
            assert code == 200
            assert "Reset your Blue Lock install" in raw
            assert "cannot be undone" in raw
        finally:
            srv.shutdown()


# ---------------------------------------------------------------------------
# First-visit gate
# ---------------------------------------------------------------------------

class TestFirstVisitRedirect:

    def test_hq_redirects_when_first_visit(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/hq", follow=False)
            assert code == 302
            assert body["__location__"] == "/onboarding"
        finally:
            srv.shutdown()

    def test_root_redirects_when_first_visit(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/", follow=False)
            assert code == 302
            assert body["__location__"] == "/onboarding"
        finally:
            srv.shutdown()

    def test_hq_reachable_after_setup_complete(self, tmp_path):
        onboarding.mark_setup_complete()
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(f"http://{host}:{port}/hq")
            assert code == 200
            assert "Blue Lock" in raw
        finally:
            srv.shutdown()

    def test_healthz_never_gated(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(f"http://{host}:{port}/healthz")
            assert code == 200
            assert body["status"] == "ok"
        finally:
            srv.shutdown()

    def test_onboarding_page_reachable_without_gate(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, _ = _request(f"http://{host}:{port}/onboarding")
            assert code == 200
        finally:
            srv.shutdown()

    def test_reset_install_reachable_without_gate(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/settings/reset-install")
            assert code == 200
        finally:
            srv.shutdown()

    def test_broker_wizard_reachable_first_visit(self, tmp_path):
        # Step 3 of onboarding links to /settings/broker; that page
        # must stay reachable even before setup completes.
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/settings/broker")
            assert code == 200
        finally:
            srv.shutdown()


# ---------------------------------------------------------------------------
# /api/onboarding/state
# ---------------------------------------------------------------------------

class TestStateEndpoint:

    def test_state_shape_before_setup(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/onboarding/state")
            assert code == 200
            assert set(body.keys()) == {
                "step", "completed", "install_fingerprint",
                "broker_connected", "keyring_available",
                "default_pairs",
            }
            assert body["completed"] is False
            assert body["broker_connected"] is False
        finally:
            srv.shutdown()

    def test_state_reflects_completion(self, tmp_path):
        onboarding.mark_setup_complete()
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/onboarding/state")
            assert code == 200
            assert body["completed"] is True
        finally:
            srv.shutdown()

    def test_state_post_persists_step(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            _request(
                f"http://{host}:{port}/api/onboarding/state?step=passphrase",
                method="POST")
            code, _, body = _request(
                f"http://{host}:{port}/api/onboarding/state")
            assert code == 200
            assert body["step"] == "passphrase"
        finally:
            srv.shutdown()


# ---------------------------------------------------------------------------
# /api/onboarding/passphrase
# ---------------------------------------------------------------------------

class TestPassphraseEndpoint:

    def test_empty_rejected_when_keychain_absent(self, tmp_path):
        # Fallback is forced, keychain reads as unavailable.
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/onboarding/passphrase",
                method="POST",
                body={"passphrase": "", "skipped": False})
            assert code == 200
            assert body["ok"] is False
            assert "at least" in body["message"].lower()
        finally:
            srv.shutdown()

    def test_long_enough_accepted(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/onboarding/passphrase",
                method="POST",
                body={"passphrase": "x" * 24,
                      "skipped": False})
            assert code == 200
            assert body["ok"] is True
        finally:
            srv.shutdown()

    def test_passphrase_never_returned_in_response(self, tmp_path):
        passphrase = _secrets.token_hex(8) + "-leak-check"
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(
                f"http://{host}:{port}/api/onboarding/passphrase",
                method="POST",
                body={"passphrase": passphrase,
                      "skipped": False})
            assert code == 200
            assert passphrase not in raw
        finally:
            srv.shutdown()


# ---------------------------------------------------------------------------
# /api/onboarding/pairs
# ---------------------------------------------------------------------------

class TestPairsEndpoint:

    def test_valid_pairs_saved(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/onboarding/pairs",
                method="POST",
                body={"pairs": ["EURUSD", "GBPUSD"]})
            assert code == 200
            assert body["ok"] is True
            assert body["pairs"] == ["EURUSD", "GBPUSD"]
        finally:
            srv.shutdown()

    def test_unknown_pair_rejected(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/onboarding/pairs",
                method="POST",
                body={"pairs": ["BTCUSD"]})
            assert code == 400
            assert body["ok"] is False
        finally:
            srv.shutdown()

    def test_empty_pairs_rejected(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/onboarding/pairs",
                method="POST",
                body={"pairs": []})
            assert code == 400
            assert body["ok"] is False
        finally:
            srv.shutdown()


# ---------------------------------------------------------------------------
# /api/onboarding/complete + reset
# ---------------------------------------------------------------------------

class TestCompleteAndReset:

    def test_complete_marks_setup_done(self, tmp_path):
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/onboarding/complete",
                method="POST", body={})
            assert code == 200
            assert body["ok"] is True
            assert onboarding.is_setup_complete()
        finally:
            srv.shutdown()

    def test_reset_wipes_setup(self, tmp_path):
        onboarding.mark_setup_complete()
        broker_connection.save_credentials(
            alias="primary", login="12345",
            password="x" * 12,
            server="Demo-Server1", account_type="demo")
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/onboarding/reset",
                method="POST", body={})
            assert code == 200
            assert body["ok"] is True
            assert not onboarding.is_setup_complete()
            assert broker_connection.list_aliases() == []
        finally:
            srv.shutdown()

    def test_onboarding_endpoints_open_when_gate_on(self, tmp_path):
        # These routes intentionally bypass the install-token gate
        # because they run before setup completes.
        srv = _make_server(tmp_path, enforce=True)
        try:
            host, port = srv.server_address
            for endpoint in (
                "/api/onboarding/state",
            ):
                code, _, _ = _request(
                    f"http://{host}:{port}{endpoint}")
                assert code == 200, endpoint
        finally:
            srv.shutdown()
