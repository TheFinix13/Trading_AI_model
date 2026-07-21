"""HTTP integration + contract tests for /players routes and
/api/players/* endpoints (F002).

- GET /players               -> 200 HTML with the squad index.
- GET /players/<id>          -> 200 HTML for each of the ten valid ids.
- GET /players/unknown       -> 404 HTML shell listing the ten ids.
- GET /api/players/list      -> 200 JSON with the ten-row roster.
- GET /api/players/<id>      -> 200 JSON for each valid id.
- GET /api/players/unknown   -> 404 JSON with `valid_ids` list.
- Cold-start: empty live dir -> API still returns shape, never 500.
- Read-only: no files are created under live_dir by any request.
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

from agent.platform import players  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


def _make_server(tmp_path: Path, live_dir: Path | None = None):
    log_root = tmp_path / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    handler = make_handler(log_root, tmp_path, reviews, live_dir=live_dir)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _get(url: str) -> tuple[int, dict, bytes]:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _get_json(url: str) -> tuple[int, dict]:
    status, _, body = _get(url)
    return status, json.loads(body)


def _fs_snapshot(root: Path) -> dict[str, int]:
    snap: dict[str, int] = {}
    for p in root.rglob("*"):
        if p.is_file():
            snap[str(p.relative_to(root))] = p.stat().st_size
    return snap


@pytest.fixture()
def cold_server(tmp_path: Path):
    live = tmp_path / "squad_live"
    live.mkdir()
    srv = _make_server(tmp_path, live_dir=live)
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", live
    finally:
        srv.shutdown()


@pytest.fixture()
def seeded_server(tmp_path: Path):
    live = tmp_path / "squad_live"
    live.mkdir()
    (live / "events.jsonl").write_text(
        json.dumps({"t": "2026-07-15T09:00:00Z", "type": "propose",
                    "agent": "isagi_yoichi"}) + "\n" +
        json.dumps({"t": "2026-07-15T13:00:00Z", "type": "close",
                    "agent": "isagi_yoichi", "symbol": "EURUSD",
                    "pnl_pips": 12.5, "dir": "long"}) + "\n"
    )
    srv = _make_server(tmp_path, live_dir=live)
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", live
    finally:
        srv.shutdown()


# --------------------------------------------------------------------
# /players (HTML)
# --------------------------------------------------------------------

def test_get_players_index_html(cold_server):
    base, _ = cold_server
    status, _, body = _get(base + "/players")
    assert status == 200
    text = body.decode()
    assert "The squad" in text
    assert '/api/players/list' in text
    assert "Blue Lock is a manga" in text


def test_get_players_all_ten_detail_ok(cold_server):
    base, _ = cold_server
    for id_ in players.valid_ids():
        status, _, body = _get(base + f"/players/{id_}")
        assert status == 200, f"{id_} returned {status}"
        text = body.decode()
        assert f'var PLAYER_ID = "{id_}";' in text


def test_get_players_case_insensitive_route(cold_server):
    base, _ = cold_server
    status, _, body = _get(base + "/players/Isagi")
    assert status == 200
    assert 'var PLAYER_ID = "isagi";' in body.decode()


def test_get_players_unknown_returns_404_with_index_links(cold_server):
    base, _ = cold_server
    status, _, body = _get(base + "/players/obiwan")
    assert status == 404
    text = body.decode()
    assert "Striker not found" in text
    for id_ in players.valid_ids():
        assert f'/players/{id_}' in text


# --------------------------------------------------------------------
# /api/players/list
# --------------------------------------------------------------------

def test_api_players_list_cold_start_shape(cold_server):
    base, _ = cold_server
    status, payload = _get_json(base + "/api/players/list")
    assert status == 200
    assert payload["total"] == 10
    assert len(payload["players"]) == 10
    for row in payload["players"]:
        for k in ("id", "name", "playstyle_tag", "status", "tier",
                  "symbols", "signature_blurb",
                  "proposals", "wins", "net_pips"):
            assert k in row


def test_api_players_list_ordered(cold_server):
    base, _ = cold_server
    _, payload = _get_json(base + "/api/players/list")
    ids = [row["id"] for row in payload["players"]]
    assert ids == list(players.valid_ids())


def test_api_players_list_alias_endpoint(cold_server):
    """/api/players (no /list) should map to the same payload as a
    convenience alias -- callers pasting either URL get a response."""
    base, _ = cold_server
    a_status, a_payload = _get_json(base + "/api/players")
    b_status, b_payload = _get_json(base + "/api/players/list")
    assert a_status == 200 and b_status == 200
    assert a_payload["total"] == b_payload["total"] == 10


# --------------------------------------------------------------------
# /api/players/<id>
# --------------------------------------------------------------------

def test_api_player_detail_shape(cold_server):
    base, _ = cold_server
    status, payload = _get_json(base + "/api/players/isagi")
    assert status == 200
    for k in ("id", "name", "canon_player", "playstyle_tag", "status",
              "tier", "weapon", "symbols", "home_tf",
              "signature_blurb", "playstyle_prose",
              "signature_setup", "evolution",
              "stats", "recent_activity", "source_hint",
              "generated_at"):
        assert k in payload, f"missing {k}"


def test_api_player_detail_stats_zero_on_cold(cold_server):
    base, _ = cold_server
    _, payload = _get_json(base + "/api/players/isagi")
    assert payload["stats"]["proposals"] == 0
    assert payload["stats"]["trades"] == 0
    assert payload["stats"]["net_pips"] == 0.0


def test_api_player_detail_seeded_reflects_events(seeded_server):
    base, _ = seeded_server
    _, payload = _get_json(base + "/api/players/isagi")
    assert payload["stats"]["proposals"] == 1
    assert payload["stats"]["trades"] == 1
    assert payload["stats"]["net_pips"] == 12.5
    assert payload["recent_activity"], "expected non-empty recent_activity"


def test_api_player_detail_canon_variant(cold_server):
    base, _ = cold_server
    status, payload = _get_json(base + "/api/players/isagi_yoichi")
    assert status == 200
    assert payload["id"] == "isagi"


def test_api_player_detail_unknown_returns_404_shape(cold_server):
    base, _ = cold_server
    status, payload = _get_json(base + "/api/players/obiwan")
    assert status == 404
    assert "valid_ids" in payload
    assert set(payload["valid_ids"]) == set(players.valid_ids())


def test_api_player_endpoints_never_500(cold_server):
    base, _ = cold_server
    for path in ("/api/players/list", "/api/players/isagi",
                 "/api/players/kunigami", "/api/players/sae"):
        status, _, _ = _get(base + path)
        assert status < 500, f"{path} returned {status}"


# --------------------------------------------------------------------
# Read-only invariant
# --------------------------------------------------------------------

def test_read_only_invariant_on_live_dir(cold_server):
    base, live = cold_server
    before = _fs_snapshot(live)
    for path in ("/players", "/players/isagi", "/api/players/list",
                 "/api/players/isagi", "/api/players/unknown",
                 "/players/unknown"):
        _get(base + path)
    assert _fs_snapshot(live) == before


# --------------------------------------------------------------------
# Bios shipped in-tree round-trip through the API
# --------------------------------------------------------------------

def test_api_player_detail_returns_playstyle_prose_from_shipped_bio(cold_server):
    base, _ = cold_server
    _, payload = _get_json(base + "/api/players/rin")
    # shipped bio has non-empty playstyle_prose + at least one evolution row.
    assert payload["playstyle_prose"]
    assert payload["evolution"]
