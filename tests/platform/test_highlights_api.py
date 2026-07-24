"""F020 -- HTTP tests for /highlights and /api/highlights/*.

- GET /highlights                     -> 200 HTML page.
- GET /api/highlights/reports?n=      -> 200 JSON index (n clamped,
                                         bad n falls back).
- GET /api/highlights/report/<day>    -> 200 JSON report; unknown day
                                         -> empty-state payload;
                                         malformed day -> 404 (regex).
- Install-token gate: the API routes are NOT in the unauthenticated
  allow-list; with enforcement on, a tokenless call gets 401.
- Cold start / missing live dir never 500s.
- Read-only over live_dir.
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

from tests.platform.test_highlights_module import (  # noqa: E402
    ACTIVE_DAY, ACTIVE_ROWS, QUIET_DAY, QUIET_ROWS, _write_tape,
)
import scripts.serve_platform as sp  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


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
    _write_tape(live, ACTIVE_ROWS + QUIET_ROWS)
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


def test_highlights_page_route(seeded_server):
    base, _ = seeded_server
    status, body = _get(base + "/highlights")
    assert status == 200
    assert "Match highlights" in body.decode()


def test_reports_index_shape(seeded_server):
    base, _ = seeded_server
    status, payload = _get_json(base + "/api/highlights/reports?n=14")
    assert status == 200
    assert [r["day"] for r in payload["reports"]] == [QUIET_DAY, ACTIVE_DAY]
    assert "NOT profit performance" in payload["provenance"]
    for row in payload["reports"]:
        for k in ("day", "quiet", "headline", "shots", "goals",
                  "resolved", "net_pips"):
            assert k in row


def test_reports_n_param_and_bad_n_fallback(seeded_server):
    base, _ = seeded_server
    _, one = _get_json(base + "/api/highlights/reports?n=1")
    assert len(one["reports"]) == 1
    status, bad = _get_json(base + "/api/highlights/reports?n=banana")
    assert status == 200
    assert len(bad["reports"]) == 2  # fell back to the default window


def test_report_day_endpoint_matches_module(seeded_server):
    base, live = seeded_server
    from agent.platform import highlights
    status, payload = _get_json(
        base + f"/api/highlights/report/{ACTIVE_DAY}")
    assert status == 200
    direct = highlights.match_report(ACTIVE_DAY, live_dir=live)
    assert payload["full_time"] == direct["full_time"]
    assert payload["headline"] == direct["headline"]


def test_report_unknown_day_empty_payload(seeded_server):
    base, _ = seeded_server
    status, payload = _get_json(base + "/api/highlights/report/2001-01-01")
    assert status == 200
    assert payload["empty"] is True


def test_report_malformed_day_404(seeded_server):
    base, _ = seeded_server
    status, _ = _get(base + "/api/highlights/report/garbage")
    assert status == 404


def test_missing_live_dir_never_500(bare_server):
    for path in ("/highlights", "/api/highlights/reports?n=5",
                 f"/api/highlights/report/{ACTIVE_DAY}"):
        status, _ = _get(bare_server + path)
        assert status < 500, f"{path} returned {status}"


def test_api_routes_not_in_unauthenticated_allowlist():
    for path in ("/api/highlights/reports",
                 f"/api/highlights/report/{ACTIVE_DAY}"):
        assert path not in sp._UNAUTHENTICATED_API_PATHS


def test_install_gate_fires_when_enforced(tmp_path):
    live = tmp_path / "squad_live"
    _write_tape(live, ACTIVE_ROWS)
    srv = _make_server(tmp_path, live_dir=live,
                       enforce_install_token=True)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        status, payload = _get_json(base + "/api/highlights/reports?n=1")
        assert status == 401
        assert "install-token" in payload["error"]
    finally:
        srv.shutdown()


def test_read_only_over_live_dir(seeded_server):
    base, live = seeded_server
    before = {str(p): p.stat().st_size for p in live.rglob("*")}
    for path in ("/highlights", "/api/highlights/reports?n=14",
                 f"/api/highlights/report/{ACTIVE_DAY}",
                 f"/api/highlights/report/{QUIET_DAY}",
                 "/api/highlights/report/2001-01-01"):
        _get(base + path)
    assert {str(p): p.stat().st_size for p in live.rglob("*")} == before
