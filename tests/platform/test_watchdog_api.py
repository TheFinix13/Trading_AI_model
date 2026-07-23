"""F017 -- /api/watchdog/status endpoint + /hq strip smoke."""
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
    alerts, credentials, rate_limiter, watchdog,
)
from agent.platform.pages import HQ_PAGE  # noqa: E402
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
def _isolate(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase("watchdog-api-tests")
    credentials.force_fallback(True)
    rate_limiter.reset()
    alerts.reset()
    watchdog.reset_cache_for_tests()
    yield
    credentials._reset_state_for_tests()
    rate_limiter.reset()
    alerts.reset()
    watchdog.reset_cache_for_tests()


class TestWatchdogStatusApi:
    def test_returns_full_registry(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, _, body = _request(
                f"http://{host}:{port}/api/watchdog/status")
            assert code == 200
            assert body["overall"] in watchdog.STATUSES
            ids = [c["id"] for c in body["checks"]]
            assert ids == list(watchdog.CHECK_IDS)
        finally:
            srv.shutdown()

    def test_every_check_has_required_fields(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            _, _, body = _request(
                f"http://{host}:{port}/api/watchdog/status")
            for c in body["checks"]:
                assert set(c) >= {"id", "status", "detail", "checked_at"}
                assert c["status"] in watchdog.STATUSES
        finally:
            srv.shutdown()

    def test_second_hit_is_cached(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            url = f"http://{host}:{port}/api/watchdog/status"
            _, _, first = _request(url)
            _, _, second = _request(url)
            assert first["cached"] is False
            assert second["cached"] is True
        finally:
            srv.shutdown()

    def test_gated_when_token_enforced(self, tmp_path: Path) -> None:
        """Fail-closed like every other /api/* route: watchdog status
        is NOT on the pre-auth allow-list (same class as
        /api/hq/state -- ops detail strings stay behind the token on
        non-localhost binds)."""
        srv = _make_server(tmp_path, enforce_install_token=True)
        try:
            host, port = srv.server_address
            code, _, _ = _request(
                f"http://{host}:{port}/api/watchdog/status")
            assert code == 401
        finally:
            srv.shutdown()


class TestHqStripSmoke:
    def test_hq_page_carries_watchdog_strip(self, tmp_path: Path) -> None:
        srv = _make_server(tmp_path)
        try:
            host, port = srv.server_address
            code, raw, _ = _request(f"http://{host}:{port}/hq")
            assert code == 200
            assert "watchdog-strip" in raw
            assert "/api/watchdog/status" in raw
        finally:
            srv.shutdown()

    def test_template_has_render_and_refresh(self) -> None:
        assert "renderWatchdog" in HQ_PAGE
        assert "wd-chip" in HQ_PAGE
        assert "setInterval(renderWatchdog" in HQ_PAGE
