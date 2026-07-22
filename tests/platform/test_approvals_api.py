"""F013 -- /api/approvals/* + /api/live-mode/* endpoint tests."""
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
    approval_queue, auth, broker_connection, broker_health, credentials,
    kill_switches, rate_limiter, risk_budget,
)
from scripts.serve_platform import make_handler  # noqa: E402


def _request(url: str, method: str = "GET", body=None,
             headers=None):
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
    credentials.set_encrypted_file_passphrase("apr-api-tests-passphrase")
    credentials.force_fallback(True)
    monkeypatch.setenv(kill_switches.KILL_DIR_ENV,
                       str(tmp_path / "cfg" / "kill"))
    broker_connection.reset_rate_limiter()
    broker_health.clear_cache()
    rate_limiter.reset()
    auth.set_session_expiry_seconds(7 * 24 * 3600)
    risk_budget.reset_state()
    approval_queue.reset_state()
    yield
    credentials._reset_state_for_tests()
    broker_connection.reset_rate_limiter()
    broker_health.clear_cache()
    rate_limiter.reset()
    risk_budget.reset_state()
    approval_queue.reset_state()


def _payload() -> dict:
    return {
        "symbol": "EURUSD",
        "side": "buy",
        "size": 0.10,
        "entry": 1.0850,
        "stop": 1.0820,
        "take_profit": 1.0920,
        "rationale": "api test",
        "source_agent": "A1_baseline",
        "risk_snapshot": {"worst_case_loss": 20.0},
    }


class TestList:
    def test_list_all_starts_empty(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/approvals/list?status=all")
            assert code == 200
            assert body == {"entries": []}
        finally:
            srv.shutdown()

    def test_list_pending_reflects_state(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        aid = approval_queue.submit(_payload())
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/approvals/list?status=pending")
            assert code == 200
            assert len(body["entries"]) == 1
            assert body["entries"][0]["id"] == aid
        finally:
            srv.shutdown()

    def test_bad_status_returns_400(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/api/approvals/list?status=wat")
            assert code == 400
        finally:
            srv.shutdown()


class TestApproveReject:
    def test_approve_via_api(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        aid = approval_queue.submit(_payload())
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/approvals/{aid}/approve",
                method="POST", body={})
            assert code == 200
            assert body["ok"] is True
            assert approval_queue.get_entry(aid)["status"] == "approved"
        finally:
            srv.shutdown()

    def test_reject_via_api(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        aid = approval_queue.submit(_payload())
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/approvals/{aid}/reject",
                method="POST", body={"reason": "not for me"})
            assert code == 200
            assert body["ok"] is True
            entry = approval_queue.get_entry(aid)
            assert entry["status"] == "rejected"
            assert entry["resolution_reason"] == "not for me"
        finally:
            srv.shutdown()


class TestSubmitInternal:
    def test_submit_without_internal_token_rejected(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/approvals/submit",
                method="POST", body=_payload())
            assert code == 401
            assert "internal" in body.get("error", "").lower()
        finally:
            srv.shutdown()


class TestLiveModeStatus:
    def test_default_status_is_off(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/live-mode/status")
            assert code == 200
            assert body == {"enabled": False}
        finally:
            srv.shutdown()


class TestLiveModeEnable:
    def test_enable_rejects_without_ack(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/live-mode/enable",
                method="POST",
                body={"acknowledged": False,
                      "confirmation": "ENABLE LIVE MODE"})
            assert code == 400
            assert "acknowledgement" in body.get("error", "")
        finally:
            srv.shutdown()

    def test_enable_rejects_wrong_confirmation(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/live-mode/enable",
                method="POST",
                body={"acknowledged": True, "confirmation": "enable"})
            assert code == 400
            assert "confirmation" in body.get("error", "")
        finally:
            srv.shutdown()

    def test_enable_and_disable_roundtrip(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            # Enable.
            code, _, body = _request(
                f"http://{host}:{port}/api/live-mode/enable",
                method="POST",
                body={"acknowledged": True,
                      "confirmation": "ENABLE LIVE MODE"})
            assert code == 200
            assert body["enabled"] is True

            # Disable.
            code, _, body = _request(
                f"http://{host}:{port}/api/live-mode/disable",
                method="POST", body={})
            assert code == 200
            assert body["enabled"] is False
        finally:
            srv.shutdown()


class TestLiveModeWarning:
    def test_warning_readable_without_auth(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path, enforce_install_token=True)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/live-mode/warning")
            assert code == 200
            assert isinstance(body["body"], str)
            # Verbatim from company/legal/live-mode-warning.md if present.
            assert "live-mode" in body["body"].lower() or body["body"] == ""
        finally:
            srv.shutdown()


class TestApprovalsPageServed:
    def test_approvals_page_html_route(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(f"http://{host}:{port}/approvals")
            assert code == 200
            assert "Approvals queue" in raw or "Pending" in raw
        finally:
            srv.shutdown()

    def test_live_mode_page_html_route(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(f"http://{host}:{port}/settings/live-mode")
            assert code == 200
            assert "Live mode" in raw
            assert "ENABLE LIVE MODE" in raw
        finally:
            srv.shutdown()


class TestAuthGate:
    def test_approve_requires_install_token(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path, enforce_install_token=True)
        aid = approval_queue.submit(_payload())
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/api/approvals/{aid}/approve",
                method="POST", body={})
            assert code == 401
            assert approval_queue.get_entry(aid)["status"] == "pending"
        finally:
            srv.shutdown()
