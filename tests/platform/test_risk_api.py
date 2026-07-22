"""F012 -- /api/risk/* endpoint tests.

Coverage:
- GET /api/risk/state returns budget + brokers + exposure + as_of.
- GET /api/risk/budgets returns the config.
- POST /api/risk/budgets updates + returns the updated budgets.
- Auth gate: POST rejected without install-token when enforced.
- Scenario: two losing fills drain daily budget; can_send_order refuses
  third; clear (reset_state) restores headroom.
- /risk HTML route serves the page.
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
    auth, broker_connection, broker_health, credentials, kill_switches,
    rate_limiter, risk_budget,
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
                 enforce_install_token: bool = False):
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
    credentials.set_encrypted_file_passphrase("risk-api-tests-passphrase")
    credentials.force_fallback(True)
    monkeypatch.setenv(kill_switches.KILL_DIR_ENV,
                       str(tmp_path / "cfg" / "kill"))
    broker_connection.reset_rate_limiter()
    broker_health.clear_cache()
    rate_limiter.reset()
    auth.set_session_expiry_seconds(7 * 24 * 3600)
    risk_budget.reset_state()
    yield
    credentials._reset_state_for_tests()
    broker_connection.reset_rate_limiter()
    broker_health.clear_cache()
    rate_limiter.reset()
    risk_budget.reset_state()


class TestGetState:
    def test_state_shape(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/risk/state")
            assert code == 200
            assert set(body.keys()) >= {"budget", "brokers", "exposure", "as_of"}
            assert "per_day" in body["budget"]
            assert body["exposure"]["open_positions"] == 0
        finally:
            srv.shutdown()


class TestGetBudgets:
    def test_defaults_returned(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/risk/budgets")
            assert code == 200
            assert body["per_day"]["max_loss"] == (
                risk_budget.DEFAULT_PER_DAY_MAX_LOSS)
        finally:
            srv.shutdown()


class TestPostBudgets:
    def test_update_roundtrip(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/risk/budgets",
                method="POST",
                body={"per_day": {"max_loss": 300.0}})
            assert code == 200
            assert body["ok"] is True
            assert body["budgets"]["per_day"]["max_loss"] == 300.0
        finally:
            srv.shutdown()

    def test_auth_gate_rejects_unauthenticated_when_enforced(
        self, tmp_path: Path
    ) -> None:
        srv = _make_server(tmp_path, enforce_install_token=True)
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/api/risk/budgets",
                method="POST",
                body={"per_day": {"max_loss": 999.0}})
            assert code == 401
            # And the config must not have been mutated.
            cfg = risk_budget.load_config()
            assert cfg["per_day"]["max_loss"] == (
                risk_budget.DEFAULT_PER_DAY_MAX_LOSS)
        finally:
            srv.shutdown()


class TestScenarioBudgetDrain:
    """Two orders drain daily budget -> third blocked -> reset restores."""

    def test_drain_block_reset(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            # Set a small per-day cap for a deterministic scenario.
            risk_budget.save_config({"per_day": {"max_loss": 20.0}})

            risk_budget.record_fill("EURUSD", "A1", -8.0)
            risk_budget.record_fill("GBPUSD", "A2", -8.0)
            # Third order asking for $8 more would push total to $24 > $20 cap.
            ok, reason = risk_budget.can_send_order("USDCAD", "A3", 8.0)
            assert ok is False
            assert "per-day cap" in reason

            # Reset the audit trail -> cap is fully restored.
            risk_budget.reset_state()
            ok2, reason2 = risk_budget.can_send_order("USDCAD", "A3", 8.0)
            assert ok2 is True
            assert reason2 == "ok"
        finally:
            srv.shutdown()


class TestRiskPageServed:
    def test_page_html_route(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(f"http://{host}:{port}/risk")
            assert code == 200
            assert "Risk" in raw
            assert "/api/risk/state" in raw
        finally:
            srv.shutdown()
