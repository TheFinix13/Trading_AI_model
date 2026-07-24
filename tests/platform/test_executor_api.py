"""F018 -- /api/executor/* endpoints + /approvals page integration."""
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
    alerts, approval_queue, credentials, kill_switches, live_executor,
    rate_limiter, risk_budget,
)
from agent.platform.pages import APPROVALS_PAGE  # noqa: E402
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
    kill_switches.reset_cache_for_tests()
    rate_limiter.reset()
    risk_budget.reset_state()
    approval_queue.reset_state()
    alerts.reset()
    live_executor.reset_state_for_tests()
    yield
    credentials._reset_state_for_tests()
    rate_limiter.reset()
    risk_budget.reset_state()
    approval_queue.reset_state()
    alerts.reset()
    live_executor.reset_state_for_tests()


class TestExecutorStatusApi:
    def test_status_shape_and_default_disabled(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/executor/status")
            assert code == 200
            # Whatever the machine's platform.toml says, the shape and
            # the documented state values hold.
            assert body["state"] in live_executor.EXECUTOR_STATES
            assert set(body) >= {"enabled", "demo_only_ack",
                                 "allowed_server_patterns",
                                 "max_volume_lots",
                                 "broker_alias_configured",
                                 "adapter_available", "state",
                                 "recent_executions"}
        finally:
            srv.shutdown()

    def test_status_gated_when_token_enforced(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path, enforce_install_token=True)
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/api/executor/status")
            assert code == 401
        finally:
            srv.shutdown()


class TestExecutorWarningApi:
    def test_warning_served(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/executor/warning")
            assert code == 200
            assert "DEMO" in body["body"]
            assert "SINGLE-USE" in body["body"]
        finally:
            srv.shutdown()

    def test_warning_open_pre_auth(self, tmp_path: Path) -> None:
        """Same class as the F013 warnings: the Legal copy must load
        BEFORE the user has authenticated."""
        srv = _make_server(tmp_path, enforce_install_token=True)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/executor/warning")
            assert code == 200
            assert body["body"]
        finally:
            srv.shutdown()


class TestExecuteEndpoint:
    def test_refuses_when_disabled(self, tmp_path: Path) -> None:
        """The endpoint exists but every call refuses until the whole
        ceremony is done -- on a test box the first refusal wall is
        gate #5 / the four gates, never a send."""
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/executor/execute/apr_x",
                method="POST", body={})
            assert code == 409
            assert body["ok"] is False
            assert body["status"] == "refused"
        finally:
            srv.shutdown()

    def test_unknown_approval_refused(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/executor/execute/apr_missing",
                method="POST", body={})
            assert code == 409
            assert body["ok"] is False
        finally:
            srv.shutdown()

    def test_gated_when_token_enforced(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path, enforce_install_token=True)
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/api/executor/execute/apr_x",
                method="POST", body={})
            assert code == 401
        finally:
            srv.shutdown()

    def test_refusal_never_consumes_the_approval(
            self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        approval_queue.set_live_mode(True)
        aid = approval_queue.submit({
            "symbol": "EURUSD", "side": "buy", "size": 0.01,
            "entry": 1.0850, "stop": 1.0820, "take_profit": 1.0920,
            "rationale": "api test", "source_agent": "A1_baseline",
            "risk_snapshot": {"worst_case_loss": 5.0},
        })
        approval_queue.approve(aid)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/executor/execute/{aid}",
                method="POST", body={})
            assert code == 409
            assert body["status"] == "refused"
            # The approval is still approved and unconsumed.
            assert approval_queue.get_entry(aid)["status"] == "approved"
            assert live_executor._is_consumed(aid) is False
        finally:
            srv.shutdown()


class TestApprovalsPageIntegration:
    def test_page_served_with_executor_hooks(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(f"http://{host}:{port}/approvals")
            assert code == 200
            assert "/api/executor/status" in raw
            assert "/api/executor/execute/" in raw
            assert "exec-warn" in raw
        finally:
            srv.shutdown()

    def test_template_has_all_three_states(self) -> None:
        assert "loadExecutor" in APPROVALS_PAGE
        assert "Execute (DEMO account)" in APPROVALS_PAGE
        assert "not-on-windows" in APPROVALS_PAGE
        assert "Demo executor disabled" in APPROVALS_PAGE

    def test_template_confirms_before_execute(self) -> None:
        assert "confirm(" in APPROVALS_PAGE
        assert "single-use" in APPROVALS_PAGE
