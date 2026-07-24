"""Tests for the platform web server (hub + /v1 live + /v2 squad pitch).

Covers the v2 data plane (`agent/platform/squad_events.py`) against a
synthetic replay cache, the v1 collectors against a synthetic log root,
and the HTTP surface end-to-end on an ephemeral port. The hard rule
under test throughout: everything is READ-ONLY and the /v2 API can
never read outside the configured reviews directory.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.platform import live_status, squad_events  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


@pytest.fixture()
def replay_cache(tmp_path: Path) -> Path:
    """A minimal but schema-faithful g7_replay_cache_* directory."""
    reviews = tmp_path / "reviews"
    cache = reviews / "g7_replay_cache_test-match"
    cache.mkdir(parents=True)
    _write_jsonl(cache / "proposals_all.jsonl", [
        {"agent_id": "isagi_yoichi", "timestamp": "2024-01-01T00:00:00+00:00",
         "symbol": "EURUSD", "direction": "long", "conviction": 0.75,
         "rationale": {"signal_reason": "zone_demand",
                       "doctrine_ref": "06-blue-lock-doctrine.md sec 3.1",
                       "empirical_prior": "E001/E006",
                       "base_conviction": 0.65, "final_conviction": 0.75,
                       "peer_confluence_isagi": False,
                       "peer_confluence_lift": 0.0}},
        {"agent_id": "barou_shoei", "timestamp": "2024-01-01T04:00:00+00:00",
         "symbol": "USDCAD", "direction": "short", "conviction": 0.7},
        {"agent_id": "bachira_meguru", "timestamp": "2024-01-01T04:00:00+00:00",
         "symbol": "USDCAD", "direction": "short", "conviction": 0.8},
    ])
    _write_jsonl(cache / "proposals_rejected.jsonl", [
        # A peer tackle: Bachira out-competes Barou.
        {"tick_id": 1, "symbol": "USDCAD", "timestamp": "2024-01-01T04:00:00+00:00",
         "winner_agent_id": "bachira_meguru", "loser_agent_id": "barou_shoei",
         "loser_direction": "short", "winner_direction": "short",
         "rejection_reason": "lower_conviction_same_symbol"},
        # A Sentinel wall block.
        {"tick_id": 2, "symbol": "EURUSD", "timestamp": "2024-01-01T08:00:00+00:00",
         "winner_agent_id": "isagi_yoichi", "loser_agent_id": "isagi_yoichi",
         "loser_direction": "long", "winner_direction": "long",
         "rejection_reason": "r6_per_symbol_risk_cap"},
    ])
    _write_jsonl(cache / "trades.jsonl", [
        {"agent_id": "isagi_yoichi", "symbol": "EURUSD",
         "entry_time": "2024-01-01 00:00:00+00:00",
         "exit_time": "2024-01-01 12:00:00+00:00",
         "direction": "long", "exit_reason": "tp", "pnl_pips": 42.5,
         "mae_pips": 5.0, "mfe_pips": 50.0, "bars_held": 3,
         "r_multiple": 1.5, "tqs_components": {"tqs": 0.61}},
        {"agent_id": "bachira_meguru", "symbol": "USDCAD",
         "entry_time": "2024-01-01 04:00:00+00:00",
         "exit_time": "2024-01-01 16:00:00+00:00",
         "direction": "short", "exit_reason": "sl", "pnl_pips": -20.0,
         "r_multiple": -1.0, "tqs_components": {"tqs": 0.1}},
    ])
    (cache / "workspace_counts.json").write_text(
        json.dumps({"publish": {"isagi_yoichi": 3}}), encoding="utf-8")
    # A decoy dir without the full artifact set must NOT be listed.
    (reviews / "g7_replay_cache_incomplete").mkdir()
    return reviews


@pytest.fixture()
def log_root(tmp_path: Path) -> Path:
    """A minimal live log root with one symbol dir."""
    root = tmp_path / "logs"
    sym = root / "EURUSD"
    sym.mkdir(parents=True)
    (sym / "state.json").write_text(json.dumps({
        "saved_at": "2026-07-13T00:00:00+00:00",
        "position_monitor": {"entry_ctx": {}, "excursion": {}},
        "risk_manager": {"day_pnl": 1.25, "halted_today": False},
        "post_loss_guard": {"consecutive_losses": 0},
    }), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# squad_events (v2 data plane)
# ---------------------------------------------------------------------------

class TestSquadEvents:

    def test_list_matches_requires_full_artifact_set(self, replay_cache):
        matches = squad_events.list_matches(replay_cache)
        assert [m["id"] for m in matches] == ["g7_replay_cache_test-match"]
        assert matches[0]["label"] == "test-match"

    def test_list_matches_missing_dir_is_empty(self, tmp_path):
        assert squad_events.list_matches(tmp_path / "nope") == []

    def test_timeline_is_time_ordered_and_typed(self, replay_cache):
        events, summary = squad_events.build_timeline(
            replay_cache / "g7_replay_cache_test-match")
        # 3 proposals + 2 blocks + 2 opens + 2 closes = 9 events.
        assert len(events) == 9
        # Timestamps mix "T" (proposals) and space (trades) separators, so
        # order must be checked on the parsed datetimes, not the strings.
        from datetime import datetime
        times = [datetime.fromisoformat(e["t"]) for e in events]
        assert times == sorted(times)
        assert {e["type"] for e in events} == {
            "proposal", "blocked", "open", "close"}

    def test_tackle_vs_sentinel_wall(self, replay_cache):
        events, _ = squad_events.build_timeline(
            replay_cache / "g7_replay_cache_test-match")
        blocked = [e for e in events if e["type"] == "blocked"]
        tackle = next(e for e in blocked if not e["rule"])
        wall = next(e for e in blocked if e["rule"])
        assert tackle["agent"] == "barou_shoei"
        assert tackle["by"] == "bachira_meguru"
        assert wall["by"] == "SENTINEL"
        assert wall["reason"] == "r6_per_symbol_risk_cap"

    def test_close_goal_semantics(self, replay_cache):
        events, _ = squad_events.build_timeline(
            replay_cache / "g7_replay_cache_test-match")
        closes = {e["agent"]: e for e in events if e["type"] == "close"}
        assert closes["isagi_yoichi"]["goal"] is True
        assert closes["isagi_yoichi"]["tqs"] == 0.61
        assert closes["bachira_meguru"]["goal"] is False

    def test_summary_per_agent(self, replay_cache):
        _, summary = squad_events.build_timeline(
            replay_cache / "g7_replay_cache_test-match")
        pa = summary["per_agent"]
        assert pa["isagi_yoichi"]["goals"] == 1
        assert pa["isagi_yoichi"]["pips"] == 42.5
        assert pa["barou_shoei"]["blocked"] == 1
        assert pa["barou_shoei"]["trades"] == 0
        assert summary["workspace"]["publish"]["isagi_yoichi"] == 3
        # Roster ships with the summary so the UI can draw the pitch.
        assert "isagi_yoichi" in summary["roster"]

    def test_event_cursor_paging(self, replay_cache):
        cache = replay_cache / "g7_replay_cache_test-match"
        first = squad_events.get_events(cache, cursor=0, limit=4)
        assert len(first["events"]) == 4
        assert first["next_cursor"] == 4
        rest = squad_events.get_events(cache, cursor=4, limit=100)
        assert len(rest["events"]) == first["total"] - 4
        assert rest["next_cursor"] == first["total"]

    def test_proposal_detail_carries_rationale(self, replay_cache):
        events, _ = squad_events.build_timeline(
            replay_cache / "g7_replay_cache_test-match")
        prop = next(e for e in events
                    if e["type"] == "proposal" and e["agent"] == "isagi_yoichi")
        d = prop["detail"]
        assert d["signal_reason"] == "zone_demand"
        assert d["doctrine_ref"].startswith("06-blue-lock-doctrine")
        assert d["base_conviction"] == 0.65
        assert d["final_conviction"] == 0.75

    def test_close_detail_carries_trade_forensics(self, replay_cache):
        events, _ = squad_events.build_timeline(
            replay_cache / "g7_replay_cache_test-match")
        close = next(e for e in events
                     if e["type"] == "close" and e["agent"] == "isagi_yoichi")
        d = close["detail"]
        assert d["r_multiple"] == 1.5
        assert d["mae_pips"] == 5.0
        assert d["mfe_pips"] == 50.0
        assert d["tqs_components"]["tqs"] == 0.61

    def test_paged_events_strip_detail(self, replay_cache):
        cache = replay_cache / "g7_replay_cache_test-match"
        page = squad_events.get_events(cache, cursor=0, limit=100)
        assert page["events"], "expected events"
        assert all("detail" not in e for e in page["events"])

    def test_event_detail_lookup(self, replay_cache):
        cache = replay_cache / "g7_replay_cache_test-match"
        events, _ = squad_events.build_timeline(cache)
        idx = next(i for i, e in enumerate(events) if e["type"] == "close")
        detail = squad_events.get_event_detail(cache, idx)
        assert detail["type"] == "close"
        assert "detail" in detail
        assert squad_events.get_event_detail(cache, 10_000) is None

    def test_summary_win_rate(self, replay_cache):
        _, summary = squad_events.build_timeline(
            replay_cache / "g7_replay_cache_test-match")
        pa = summary["per_agent"]
        assert pa["isagi_yoichi"]["win_rate"] == 1.0
        assert pa["bachira_meguru"]["win_rate"] == 0.0
        assert pa["barou_shoei"]["win_rate"] is None  # no trades

    def test_optional_thoughts_stream(self, replay_cache):
        cache = replay_cache / "g7_replay_cache_test-match"
        # Absent thoughts.jsonl -> no thought events (graceful).
        events, _ = squad_events.build_timeline(cache)
        assert not [e for e in events if e["type"] == "thought"]
        _write_jsonl(cache / "thoughts.jsonl", [
            {"agent_id": "isagi_yoichi",
             "timestamp": "2024-01-01T02:00:00+00:00",
             "symbol": "EURUSD", "text": "the field is opening up"},
        ])
        events, _ = squad_events.build_timeline(cache)
        thoughts = [e for e in events if e["type"] == "thought"]
        assert len(thoughts) == 1
        assert thoughts[0]["text"] == "the field is opening up"
        # And they sort into the timeline by timestamp.
        from datetime import datetime
        times = [datetime.fromisoformat(e["t"]) for e in events]
        assert times == sorted(times)

    def test_cache_invalidates_on_file_change(self, replay_cache):
        cache = replay_cache / "g7_replay_cache_test-match"
        events1, _ = squad_events.build_timeline(cache)
        n1 = len(events1)
        # Append one more proposal — a live paper stream would do exactly
        # this, so the cache must pick it up.
        with (cache / "proposals_all.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "agent_id": "itoshi_rin", "timestamp": "2024-01-02T00:00:00+00:00",
                "symbol": "GBPUSD", "direction": "long", "conviction": 0.9,
            }) + "\n")
        events2, _ = squad_events.build_timeline(cache)
        assert len(events2) == n1 + 1


# ---------------------------------------------------------------------------
# live_status (v1 data plane)
# ---------------------------------------------------------------------------

class TestLiveStatus:

    def test_collect_status_shape(self, log_root, tmp_path):
        payload = live_status.collect_status(log_root, tmp_path)
        assert payload["global_kill"] is None
        assert [s["symbol"] for s in payload["symbols"]] == ["EURUSD"]
        sym = payload["symbols"][0]
        # No daily log file -> no-data (state.json alone is not aliveness).
        assert sym["status"] == "no-data"
        assert sym["risk"]["day_pnl"] == 1.25

    def test_global_kill_surfaces(self, log_root, tmp_path):
        (tmp_path / "kill_switch").write_text("manual halt: test",
                                              encoding="utf-8")
        payload = live_status.collect_status(log_root, tmp_path)
        assert payload["global_kill"] == "manual halt: test"


# ---------------------------------------------------------------------------
# platform.toml config
# ---------------------------------------------------------------------------

class TestConfig:

    def test_defaults_without_file(self, tmp_path):
        from agent.platform.config import load_config
        cfg = load_config(tmp_path)
        assert cfg["host"] == "127.0.0.1"
        assert cfg["port"] == 8787
        assert cfg["auth_token"] is None
        assert cfg["live_dir"] == Path(cfg["log_root"]) / "squad_live"

    def test_toml_overrides_and_derived_live_dir(self, tmp_path):
        from agent.platform.config import load_config
        # Token built at runtime so no secret-shaped literal lands here.
        tok = "tok-" + "z" * 8
        (tmp_path / "platform.toml").write_text(
            'log_root = "/tmp/logs"\nport = 9999\nauth_token = "%s"\n' % tok,
            encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg["log_root"] == Path("/tmp/logs")
        assert cfg["port"] == 9999
        assert cfg["auth_token"] == tok
        assert cfg["live_dir"] == Path("/tmp/logs") / "squad_live"

    def test_broken_toml_falls_back(self, tmp_path):
        from agent.platform.config import load_config
        (tmp_path / "platform.toml").write_text("not [ valid toml",
                                                encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg["port"] == 8787

    def test_paper_loop_defaults_are_empty(self, tmp_path):
        from agent.platform.config import load_config
        cfg = load_config(tmp_path)
        # Empty strings so callers can just check truthiness (see
        # scripts/run_squad_paper.py) -- the actual auto-pick happens
        # in paper_loop.select_source_cache when both are empty.
        assert cfg["paper_loop"] == {"cache": "", "aggregator": ""}

    def test_paper_loop_toml_overrides(self, tmp_path):
        from agent.platform.config import load_config
        (tmp_path / "platform.toml").write_text(
            "[paper_loop]\n"
            'aggregator = "phi41"\n'
            'cache = "g7_replay_cache_g7retry1-arm4"\n',
            encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg["paper_loop"]["aggregator"] == "phi41"
        assert cfg["paper_loop"]["cache"] == "g7_replay_cache_g7retry1-arm4"


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

@pytest.fixture()
def live_dir(replay_cache, tmp_path) -> Path:
    """A live output dir produced by the paper loop from the fixture cache."""
    from agent.platform.paper_loop import PaperLoop
    out = tmp_path / "squad_live"
    PaperLoop(replay_cache / "g7_replay_cache_test-match", out,
              tick_seconds=0).run(sleep=lambda s: None,
                                  log=lambda *a, **k: None)
    return out


@pytest.fixture()
def server(replay_cache, log_root, tmp_path, live_dir):
    handler = make_handler(log_root, tmp_path, replay_cache,
                           live_dir=live_dir)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:  # noqa: PERF203
        return e.code, e.read()


class TestHttpSurface:

    def test_pages_render(self, server):
        for path, marker in [("/", b"Multi-pair trading platform"),
                             ("/v1", b"Zones agent"),
                             ("/v2", b"Blue Lock squad")]:
            status, body = _get(server + path)
            assert status == 200
            assert marker in body

    def test_v1_status_api(self, server):
        status, body = _get(server + "/api/v1/status")
        assert status == 200
        assert json.loads(body)["symbols"][0]["symbol"] == "EURUSD"

    def test_v2_matches_and_playback(self, server):
        status, body = _get(server + "/api/v2/matches")
        assert status == 200
        matches = json.loads(body)["matches"]
        assert matches[0]["id"] == "g7_replay_cache_test-match"

        mid = matches[0]["id"]
        status, body = _get(server + f"/api/v2/match/{mid}/summary")
        assert status == 200
        assert json.loads(body)["n_events"] == 9

        status, body = _get(server + f"/api/v2/match/{mid}/events?cursor=0&limit=5")
        assert status == 200
        page = json.loads(body)
        assert len(page["events"]) == 5
        assert page["next_cursor"] == 5

    def test_event_detail_endpoint(self, server):
        mid = "g7_replay_cache_test-match"
        status, body = _get(server + f"/api/v2/match/{mid}/event/0")
        assert status == 200
        ev = json.loads(body)
        assert ev["type"] and ev["t"]
        status, _ = _get(server + f"/api/v2/match/{mid}/event/9999")
        assert status == 404

    def test_unknown_match_404(self, server):
        status, _ = _get(server + "/api/v2/match/g7_replay_cache_nope/summary")
        assert status == 404

    def test_traversal_is_rejected(self, server):
        # Dots and slashes never match the route regex -> 404, and the
        # resolve() containment check backstops it.
        status, _ = _get(server + "/api/v2/match/..%2F..%2Fetc/summary")
        assert status == 404

    def test_unknown_path_404(self, server):
        status, _ = _get(server + "/definitely-not-a-page")
        assert status == 404

    def test_healthz(self, server):
        status, body = _get(server + "/healthz")
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "ok"
        assert payload["uptime_seconds"] >= 0
        assert payload["version"]

    def test_live_status_endpoint(self, server):
        status, body = _get(server + "/api/v2/live/status")
        assert status == 200
        st = json.loads(body)
        assert st["exists"] is True
        assert st["running"] is True

    def test_live_tail_matches_replay_parse(self, server):
        # The live dir was produced by the paper loop from the same
        # fixture cache, so the tail must serve the same events.
        status, body = _get(server + "/api/v2/live/events?cursor=0&limit=100")
        assert status == 200
        live_page = json.loads(body)
        status, body = _get(
            server + "/api/v2/match/g7_replay_cache_test-match/events"
            "?cursor=0&limit=100")
        replay_page = json.loads(body)
        assert live_page["events"] == replay_page["events"]
        assert live_page["total"] == replay_page["total"]

    def test_live_summary_and_event_detail(self, server):
        status, body = _get(server + "/api/v2/live/summary")
        assert status == 200
        assert "per_agent" in json.loads(body)
        status, body = _get(server + "/api/v2/live/event/0")
        assert status == 200
        assert json.loads(body)["t"]

    def test_auth_token_enforced(self, replay_cache, log_root, tmp_path,
                                 live_dir):
        handler = make_handler(log_root, tmp_path, replay_cache,
                               live_dir=live_dir, auth_token="hunter2")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            # No token -> 401 everywhere except /healthz.
            status, _ = _get(base + "/v2")
            assert status == 401
            status, _ = _get(base + "/api/v1/status")
            assert status == 401
            status, _ = _get(base + "/healthz")
            assert status == 200
            # Wrong token -> 401.
            status, _ = _get(base + "/v2?token=wrong")
            assert status == 401
            # Query token works and plants a session cookie.
            req = urllib.request.Request(base + "/v2?token=hunter2")
            with urllib.request.urlopen(req) as resp:
                assert resp.status == 200
                cookie = resp.headers.get("Set-Cookie", "")
                assert "platform_token=hunter2" in cookie
            # Bearer header works.
            req = urllib.request.Request(
                base + "/api/v2/matches",
                headers={"Authorization": "Bearer hunter2"})
            with urllib.request.urlopen(req) as resp:
                assert resp.status == 200
            # Cookie alone works (what page-issued fetches rely on).
            req = urllib.request.Request(
                base + "/api/v2/matches",
                headers={"Cookie": "platform_token=hunter2"})
            with urllib.request.urlopen(req) as resp:
                assert resp.status == 200
        finally:
            srv.shutdown()

    def test_live_appends_are_visible_without_restart(self, server, live_dir):
        status, body = _get(server + "/api/v2/live/events?cursor=0&limit=1000")
        before = json.loads(body)["total"]
        with (live_dir / "proposals_all.jsonl").open("a",
                                                     encoding="utf-8") as fh:
            fh.write(json.dumps({
                "agent_id": "nagi_seishiro",
                "timestamp": "2024-01-02T00:00:00+00:00",
                "symbol": "AUDUSD", "direction": "long",
                "conviction": 0.8}) + "\n")
        status, body = _get(
            server + f"/api/v2/live/events?cursor={before}&limit=10")
        page = json.loads(body)
        assert page["total"] == before + 1
        assert page["events"][0]["agent"] == "nagi_seishiro"
