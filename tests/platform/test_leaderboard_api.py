"""F022 -- HTTP tests for /leaderboard and /api/leaderboard.

- GET /leaderboard                  -> 200 HTML page.
- GET /api/leaderboard?by=&window=  -> 200 JSON standings; bad params
                                       fold to defaults, never 500.
- Endpoint payloads equal the module's own computation.
- Install-token gate: /api/leaderboard is NOT in the unauthenticated
  allow-list; with enforcement on, a tokenless call gets 401.
- Cold start / missing live dir never 500s. Read-only over live_dir.
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

from tests.platform.test_leaderboard_module import (  # noqa: E402
    ROWS, _write_tape,
)
import scripts.serve_platform as sp  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402
from agent.platform import leaderboard  # noqa: E402


def _make_server(tmp_path: Path, live_dir: Path | None = None, **kw):
    log_root = tmp_path / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    handler = make_handler(log_root, tmp_path, reviews,
                           live_dir=live_dir, **kw)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _get_json(url: str) -> tuple[int, dict]:
    status, body = _get(url)
    return status, json.loads(body)


@pytest.fixture()
def seeded_server(tmp_path: Path):
    live = tmp_path / "squad_live"
    _write_tape(live, ROWS)
    srv = _make_server(tmp_path, live_dir=live)
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", live
    finally:
        srv.shutdown()


@pytest.fixture()
def bare_server(tmp_path: Path):
    srv = _make_server(tmp_path, live_dir=None)
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def test_leaderboard_page_route(seeded_server):
    base, _ = seeded_server
    status, body = _get(base + "/leaderboard")
    assert status == 200
    page = body.decode()
    assert "Standings" in page
    assert "NOT investment performance" in page


def test_api_default_shape_matches_module(seeded_server):
    base, live = seeded_server
    status, payload = _get_json(base + "/api/leaderboard")
    assert status == 200
    direct = leaderboard.standings("agent", live_dir=live)
    assert payload["by"] == "agent"
    assert payload["window_days"] is None
    assert payload["rows"] == direct["rows"]
    assert payload["provenance"] == leaderboard.PROVENANCE_NOTE


def test_api_pair_grouping(seeded_server):
    base, live = seeded_server
    status, payload = _get_json(base + "/api/leaderboard?by=pair")
    assert status == 200
    assert payload["by"] == "pair"
    assert payload["rows"] == leaderboard.standings(
        "pair", live_dir=live)["rows"]


def test_api_window_param(seeded_server):
    base, _ = seeded_server
    status, payload = _get_json(base + "/api/leaderboard?by=agent&window=30")
    assert status == 200
    assert payload["window_days"] == 30
    assert payload["window_label"] == "last 30 days"


def test_api_bad_params_fold_to_defaults(seeded_server):
    base, _ = seeded_server
    status, payload = _get_json(
        base + "/api/leaderboard?by=banana&window=garbage")
    assert status == 200
    assert payload["by"] == "agent"
    assert payload["window_days"] is None


def test_missing_live_dir_never_500(bare_server):
    for path in ("/leaderboard", "/api/leaderboard",
                 "/api/leaderboard?by=pair&window=7"):
        status, _ = _get(bare_server + path)
        assert status < 500, f"{path} returned {status}"
    status, payload = _get_json(bare_server + "/api/leaderboard")
    assert payload["rows"] == []


def test_api_route_not_in_unauthenticated_allowlist():
    assert "/api/leaderboard" not in sp._UNAUTHENTICATED_API_PATHS


def test_install_gate_fires_when_enforced(tmp_path):
    live = tmp_path / "squad_live"
    _write_tape(live, ROWS)
    srv = _make_server(tmp_path, live_dir=live,
                       enforce_install_token=True)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        status, payload = _get_json(base + "/api/leaderboard")
        assert status == 401
        assert "install-token" in payload["error"]
    finally:
        srv.shutdown()


def test_read_only_over_live_dir(seeded_server):
    base, live = seeded_server
    before = {str(p): p.stat().st_size for p in live.rglob("*")}
    for path in ("/leaderboard", "/api/leaderboard",
                 "/api/leaderboard?by=pair",
                 "/api/leaderboard?by=agent&window=7"):
        _get(base + path)
    assert {str(p): p.stat().st_size for p in live.rglob("*")} == before
