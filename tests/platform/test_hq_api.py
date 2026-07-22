"""Contract tests for `/api/hq/state`.

The dashboard JS reads a set of top-level keys; a silent rename in
`hq.hq_state()` must trip these tests before it trips the UI. Also
verifies the "unconfigured" degradation path returns a 200 with a
shaped body (not a 500) so the dashboard's friendly-banner path
gets exercised.
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

from scripts.serve_platform import make_handler  # noqa: E402


REQUIRED_KEYS = {"meta", "roles", "sprints", "features",
                 "decisions", "kpis", "blockers",
                 "intake", "experiments"}


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _make_server(tmp_path: Path, ledger: Path | None):
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    log_root = tmp_path / "logs"
    log_root.mkdir()
    live_dir = tmp_path / "squad_live"
    handler = make_handler(log_root, tmp_path, reviews,
                           live_dir=live_dir,
                           company_ledger_path=ledger)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def configured_server(tmp_path: Path):
    ledger = tmp_path / "company_state.json"
    ledger.write_text(json.dumps({
        "meta": {"company_name": "Blue Lock Trading Co.",
                 "founded": "2026-07-21",
                 "current_sprint_id": "sprint-0"},
        "roles": [{"id": "ceo", "title": "CEO", "tier": "executive",
                   "active": True}],
        "sprints": [{"id": "sprint-0", "name": "Trust Foundation",
                     "started_at": "2026-07-21", "day_target": 14,
                     "feature_ids": ["F001"]}],
        "features": [{"id": "F001", "title": "Public /performance",
                      "priority": "P0", "current_stage": "spec",
                      "current_owner_role": "cpo",
                      "history": [], "blockers": [],
                      "awaiting_ceo": False}],
        "decisions": [{"id": "D001", "date": "2026-07-21",
                       "role": "ceo",
                       "decision": "Founded Blue Lock Trading Co."}],
        "kpis": {"features_shipped_sprint_0": 0,
                 "features_total_sprint_0": 1,
                 "active_roles": 1, "total_roles": 1},
        "blockers": [],
    }), encoding="utf-8")
    srv = _make_server(tmp_path, ledger)
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


@pytest.fixture()
def unconfigured_server(tmp_path: Path):
    # Point at a non-existent ledger path -- the /api/hq/state route
    # must still return 200 with an "unconfigured" skeleton.
    missing = tmp_path / "does_not_exist.json"
    srv = _make_server(tmp_path, missing)
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


class TestConfiguredContract:

    def test_returns_200_with_all_required_top_level_keys(
            self, configured_server):
        status, body = _get_json(configured_server + "/api/hq/state")
        assert status == 200
        assert set(body.keys()) >= REQUIRED_KEYS

    def test_meta_shape(self, configured_server):
        _, body = _get_json(configured_server + "/api/hq/state")
        meta = body["meta"]
        for key in ("company_name", "founded", "mission", "one_liner",
                    "current_sprint_id", "generated_at",
                    "unconfigured", "unconfigured_reason",
                    "schema_version"):
            assert key in meta, f"missing meta key: {key!r}"
        assert meta["unconfigured"] is False
        assert meta["unconfigured_reason"] is None

    def test_kpis_shape(self, configured_server):
        _, body = _get_json(configured_server + "/api/hq/state")
        kpis = body["kpis"]
        for key in ("features_shipped_sprint_0", "features_total_sprint_0",
                    "backlog_size", "bugs_open",
                    "cycle_time_days_p50", "test_coverage_pct",
                    "active_roles", "total_roles",
                    "intake_items_open", "experiments_in_flight",
                    "published_findings_last_30d"):
            assert key in kpis, f"missing kpi key: {key!r}"

    def test_features_carry_frontend_fields(self, configured_server):
        _, body = _get_json(configured_server + "/api/hq/state")
        f = body["features"][0]
        for key in ("id", "title", "priority", "current_stage",
                    "current_owner_role", "age_in_stage_days"):
            assert key in f, f"missing feature key: {key!r}"

    def test_roles_carry_frontend_fields(self, configured_server):
        _, body = _get_json(configured_server + "/api/hq/state")
        r = body["roles"][0]
        for key in ("id", "title", "tier", "active"):
            assert key in r, f"missing role key: {key!r}"

    def test_decisions_list_present(self, configured_server):
        _, body = _get_json(configured_server + "/api/hq/state")
        assert isinstance(body["decisions"], list)
        if body["decisions"]:
            d = body["decisions"][0]
            for key in ("id", "date", "role", "decision"):
                assert key in d, f"missing decision key: {key!r}"


class TestUnconfiguredContract:

    def test_returns_200_when_ledger_missing(self, unconfigured_server):
        # Critical: the endpoint MUST NOT 500 on a missing ledger.
        # The dashboard's friendly-banner path depends on 200 + shaped
        # body.
        status, body = _get_json(unconfigured_server + "/api/hq/state")
        assert status == 200
        assert body["meta"]["unconfigured"] is True
        assert body["meta"]["unconfigured_reason"] is not None
        assert set(body.keys()) >= REQUIRED_KEYS

    def test_unconfigured_body_is_still_shaped(self, unconfigured_server):
        # Empty arrays, not missing keys -- the dashboard iterates
        # every array unconditionally.
        _, body = _get_json(unconfigured_server + "/api/hq/state")
        assert body["roles"] == []
        assert body["features"] == []
        assert body["sprints"] == []
        assert body["decisions"] == []
        assert body["blockers"] == []
        assert body["intake"] == []
        assert body["experiments"] == []
        assert set(body["kpis"].keys()) >= {
            "features_shipped_sprint_0", "features_total_sprint_0",
            "backlog_size", "bugs_open", "active_roles", "total_roles",
            "intake_items_open", "experiments_in_flight",
            "published_findings_last_30d",
        }


class TestRdPulseContract:
    """The three R&D-pulse additions from D081: top-level `intake` and
    `experiments` arrays plus three new KPI counters. The dashboard JS
    reads all of these -- rename or drop = broken UI.
    """

    @pytest.fixture()
    def rd_server(self, tmp_path: Path):
        ledger = tmp_path / "company_state.json"
        ledger.write_text(json.dumps({
            "meta": {"company_name": "Blue Lock Trading Co.",
                     "founded": "2026-07-21",
                     "current_sprint_id": "sprint-2"},
            "roles": [], "sprints": [], "features": [], "decisions": [],
            "kpis": {"intake_items_open": 1,
                     "experiments_in_flight": 1,
                     "published_findings_last_30d": 0},
            "blockers": [],
            "intake": [
                {"id": "I001", "classification": "PROCESS",
                 "priority": "P2", "status": "triaged",
                 "summary": "flag"},
            ],
            "experiments": [
                {"id": "E-live", "status": "in-flight",
                 "hypothesis": "hyp"},
                {"id": "M001-PhaseAC", "status": "closed-negative"},
            ],
        }), encoding="utf-8")
        srv = _make_server(tmp_path, ledger)
        try:
            yield f"http://127.0.0.1:{srv.server_address[1]}"
        finally:
            srv.shutdown()

    def test_intake_array_reachable(self, rd_server):
        _, body = _get_json(rd_server + "/api/hq/state")
        assert isinstance(body["intake"], list)
        assert len(body["intake"]) == 1
        assert body["intake"][0]["id"] == "I001"
        assert body["intake"][0]["classification"] == "PROCESS"

    def test_experiments_array_reachable(self, rd_server):
        _, body = _get_json(rd_server + "/api/hq/state")
        assert isinstance(body["experiments"], list)
        assert len(body["experiments"]) == 2
        assert {e["id"] for e in body["experiments"]} == {
            "E-live", "M001-PhaseAC"}

    def test_rd_kpi_counters_pass_through(self, rd_server):
        _, body = _get_json(rd_server + "/api/hq/state")
        k = body["kpis"]
        assert k["intake_items_open"] == 1
        assert k["experiments_in_flight"] == 1
        assert k["published_findings_last_30d"] == 0
