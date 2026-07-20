"""``GET /api/v2/live/workspace`` — HTTP integration for the /v2 LIVE
workspace panel. Verifies:

1. 200 + expected shape when a populated ``workspace_snapshot.json``
   sits under the live dir.
2. 200 + ``exists=False`` when no snapshot has been written yet
   (fresh live dir; must never 500).
3. 401 without a token when auth is enabled on the handler (parity
   with every other /api/* route).
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

from agent.platform.paper_loop import WORKSPACE_SNAPSHOT_FILE  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


def _open_get(url: str, *, token: str | None = None):
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req)


@pytest.fixture()
def populated_live_dir(tmp_path: Path) -> Path:
    live = tmp_path / "squad_live"
    live.mkdir()
    (live / WORKSPACE_SNAPSHOT_FILE).write_text(json.dumps({
        "as_of": "2026-07-21T00:04:00+00:00",
        "tick_id": 42,
        "thought_count": 2,
        "thoughts": [
            {"agent_id": "bachira_meguru", "symbol": "EURUSD",
             "narrative": "near demand zone at 1.0850",
             "confidence_in_thought": 0.72, "tags": ["zone_touch"],
             "tick_id": 42, "timestamp": "2026-07-21T00:04:00+00:00"},
            {"agent_id": "isagi_yoichi", "symbol": "GBPUSD",
             "narrative": "confluence pending",
             "confidence_in_thought": 0.55, "tags": [],
             "tick_id": 42, "timestamp": "2026-07-21T00:04:00+00:00"},
        ],
    }), encoding="utf-8")
    return live


def _spin(tmp_path: Path, live_dir: Path, *, auth_token: str | None = None):
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    log_root = tmp_path / "logs"
    log_root.mkdir(exist_ok=True)
    handler = make_handler(log_root, tmp_path, reviews,
                           live_dir=live_dir, auth_token=auth_token)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_workspace_endpoint_returns_populated_snapshot(
        tmp_path: Path, populated_live_dir: Path):
    srv = _spin(tmp_path, populated_live_dir)
    try:
        with _open_get(
            f"http://127.0.0.1:{srv.server_address[1]}"
            f"/api/v2/live/workspace"
        ) as resp:
            body = resp.read()
            assert resp.status == 200
    finally:
        srv.shutdown()
    payload = json.loads(body)
    assert payload["exists"] is True
    assert payload["tick_id"] == 42
    assert payload["thought_count"] == 2
    assert len(payload["thoughts"]) == 2
    assert payload["thoughts"][0]["agent_id"] == "bachira_meguru"


def test_workspace_endpoint_empty_dir_returns_exists_false(tmp_path: Path):
    live = tmp_path / "squad_live"
    live.mkdir()
    srv = _spin(tmp_path, live)
    try:
        with _open_get(
            f"http://127.0.0.1:{srv.server_address[1]}"
            f"/api/v2/live/workspace"
        ) as resp:
            body = resp.read()
            assert resp.status == 200
    finally:
        srv.shutdown()
    payload = json.loads(body)
    assert payload["exists"] is False
    assert payload["thoughts"] == []


def test_workspace_endpoint_401_without_token_when_auth_enabled(
        tmp_path: Path, populated_live_dir: Path):
    srv = _spin(tmp_path, populated_live_dir, auth_token="secret")
    err = None
    try:
        try:
            _open_get(
                f"http://127.0.0.1:{srv.server_address[1]}"
                f"/api/v2/live/workspace"
            )
        except urllib.error.HTTPError as e:
            err = e
    finally:
        srv.shutdown()
    assert err is not None
    assert err.code == 401


def test_workspace_endpoint_200_with_bearer_token(
        tmp_path: Path, populated_live_dir: Path):
    srv = _spin(tmp_path, populated_live_dir, auth_token="secret")
    try:
        with _open_get(
            f"http://127.0.0.1:{srv.server_address[1]}"
            f"/api/v2/live/workspace",
            token="secret",
        ) as resp:
            body = resp.read()
            assert resp.status == 200
    finally:
        srv.shutdown()
    payload = json.loads(body)
    assert payload["exists"] is True
