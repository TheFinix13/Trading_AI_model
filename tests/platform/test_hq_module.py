"""Unit tests for `agent.platform.hq`.

Three cases the /hq dashboard depends on:

1. **Happy path** — a valid `company_state.json` on disk yields a
   payload whose structural keys the frontend expects.
2. **Missing file** — the ledger isn't on this server; the module
   returns a skeleton payload with ``meta.unconfigured=True`` and a
   human-readable ``meta.unconfigured_reason`` so the dashboard
   renders a friendly banner instead of a 500.
3. **Malformed JSON** — the ledger exists but is corrupt; same
   graceful skeleton path, distinct reason so the operator can tell
   the two failures apart.

Derivations (``age_in_stage_days``, blockers surfacing, KPI back-
filling) get dedicated cases so future ledger schema changes don't
silently break the frontend contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import hq  # noqa: E402
from agent.platform.hq import hq_state  # noqa: E402


REQUIRED_TOP_LEVEL_KEYS = {
    "meta", "roles", "sprints", "features",
    "decisions", "kpis", "blockers",
    "intake", "experiments",
}


def _write_ledger(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestHappyPath:
    """A valid ledger yields a fully-populated payload."""

    def test_happy_path_returns_all_top_level_keys(self, tmp_path: Path):
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {"company_name": "Blue Lock Trading Co.",
                     "founded": "2026-07-21",
                     "current_sprint_id": "sprint-0"},
            "roles": [{"id": "ceo", "title": "CEO", "tier": "executive",
                       "active": True, "throughput_last_7d": 0}],
            "sprints": [{"id": "sprint-0", "name": "Trust Foundation",
                         "started_at": "2026-07-21",
                         "day_target": 14, "feature_ids": ["F001"]}],
            "features": [{"id": "F001", "title": "Public /performance",
                          "priority": "P0", "current_stage": "spec",
                          "current_owner_role": "cpo",
                          "history": [],
                          "blockers": [], "awaiting_ceo": False}],
            "decisions": [{"id": "D001", "date": "2026-07-21",
                           "role": "ceo",
                           "decision": "Founded Blue Lock Trading Co."}],
            "kpis": {"features_shipped_sprint_0": 0,
                     "features_total_sprint_0": 1,
                     "active_roles": 1, "total_roles": 1},
            "blockers": [],
        })
        state = hq_state(ledger_path=ledger)
        assert set(state.keys()) >= REQUIRED_TOP_LEVEL_KEYS
        assert state["meta"]["unconfigured"] is False
        assert state["meta"]["unconfigured_reason"] is None
        assert state["meta"]["company_name"] == "Blue Lock Trading Co."
        assert len(state["roles"]) == 1
        assert len(state["features"]) == 1
        assert state["kpis"]["total_roles"] == 1
        assert isinstance(state["blockers"], list)

    def test_generated_at_is_isoformat_utc(self, tmp_path: Path):
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {"meta": {}, "roles": [], "features": [],
                               "sprints": [], "decisions": [],
                               "kpis": {}, "blockers": []})
        state = hq_state(ledger_path=ledger)
        ts = state["meta"]["generated_at"]
        assert ts is not None
        assert ts.endswith("Z"), (
            f"generated_at should be Z-suffixed UTC, got {ts!r}")

    def test_decisions_capped_at_ten_with_total_preserved(self, tmp_path: Path):
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "roles": [], "features": [], "sprints": [],
            "decisions": [
                {"id": f"D{i:03d}", "date": "2026-07-21",
                 "role": "cpo", "decision": f"d{i}"}
                for i in range(1, 16)
            ],
            "kpis": {}, "blockers": [],
        })
        state = hq_state(ledger_path=ledger)
        assert len(state["decisions"]) == 10
        assert state["decisions_total"] == 15
        # The tail is preserved (D006 -> D015), so recent decisions win.
        assert state["decisions"][0]["id"] == "D006"
        assert state["decisions"][-1]["id"] == "D015"


class TestUnconfigured:
    """Missing / malformed ledger -> skeleton payload with reason."""

    def test_missing_file_returns_unconfigured_skeleton(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.json"
        state = hq_state(ledger_path=missing)
        assert set(state.keys()) >= REQUIRED_TOP_LEVEL_KEYS
        assert state["meta"]["unconfigured"] is True
        assert "not found" in state["meta"]["unconfigured_reason"]
        assert state["roles"] == []
        assert state["features"] == []
        assert state["decisions"] == []
        assert state["blockers"] == []
        # KPIs are still shape-correct so the frontend doesn't crash on
        # missing keys.
        assert set(state["kpis"].keys()) >= {
            "features_shipped_sprint_0", "features_total_sprint_0",
            "backlog_size", "bugs_open", "active_roles", "total_roles",
        }

    def test_malformed_json_returns_unconfigured_with_reason(self, tmp_path: Path):
        bad = tmp_path / "company_state.json"
        bad.write_text("{ not valid json ][", encoding="utf-8")
        state = hq_state(ledger_path=bad)
        assert state["meta"]["unconfigured"] is True
        assert "malformed" in state["meta"]["unconfigured_reason"].lower()

    def test_non_object_top_level_returns_unconfigured(self, tmp_path: Path):
        arr = tmp_path / "company_state.json"
        arr.write_text("[]", encoding="utf-8")
        state = hq_state(ledger_path=arr)
        assert state["meta"]["unconfigured"] is True

    def test_default_path_resolves_under_repo_root(self):
        assert hq.DEFAULT_LEDGER_PATH.name == "company_state.json"
        assert hq.DEFAULT_LEDGER_PATH.parent.name == "ledger"
        assert hq.DEFAULT_LEDGER_PATH.parent.parent.name == "company"


class TestDerivations:
    """Age, blockers, and KPI backfill logic."""

    def test_age_in_stage_days_derived_from_history(self, tmp_path: Path):
        # Feature entered `design` 3 days ago (from a fixed 'now'). The
        # derivation reads history and computes the delta.
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        three_days_ago = (now - timedelta(days=3)).isoformat()
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "roles": [], "sprints": [], "decisions": [],
            "kpis": {},
            "features": [{
                "id": "F001", "title": "test", "priority": "P0",
                "current_stage": "design",
                "current_owner_role": "ui_designer",
                "history": [
                    {"stage": "spec", "at": (now - timedelta(days=5))
                        .isoformat(), "role": "cpo"},
                    {"stage": "design", "at": three_days_ago,
                        "role": "ui_designer"},
                ],
                "blockers": [], "awaiting_ceo": False,
            }],
            "blockers": [],
        })
        state = hq_state(ledger_path=ledger)
        feature = state["features"][0]
        assert feature["age_in_stage_days"] == 3

    def test_explicit_age_wins_over_derived(self, tmp_path: Path):
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "roles": [], "sprints": [], "decisions": [],
            "kpis": {},
            "features": [{
                "id": "F001", "title": "test", "priority": "P0",
                "current_stage": "design",
                "current_owner_role": "ui_designer",
                "age_in_stage_days": 42,
                "history": [{"stage": "design",
                             "at": "2026-07-21T00:00:00Z",
                             "role": "ui_designer"}],
                "blockers": [], "awaiting_ceo": False,
            }],
            "blockers": [],
        })
        state = hq_state(ledger_path=ledger)
        assert state["features"][0]["age_in_stage_days"] == 42

    def test_ceo_blockers_surfaced_with_feature_annotations(self, tmp_path: Path):
        # A blocker with awaiting_ceo=True surfaces in the top-level list;
        # one without does NOT (that's an internal-role blocker).
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "roles": [], "sprints": [], "decisions": [],
            "kpis": {},
            "features": [{
                "id": "F002", "title": "player bios", "priority": "P0",
                "current_stage": "design",
                "current_owner_role": "ui_designer",
                "history": [],
                "blockers": [
                    {"raised_by": "ui_designer",
                     "raised_at": "2026-07-22T09:00:00Z",
                     "summary": "colour-blind palette conflict",
                     "recommendation": "swap to blue/orange",
                     "awaiting_ceo": True},
                    {"raised_by": "qa", "raised_at": "2026-07-22T10:00:00Z",
                     "summary": "waiting on backend fixture",
                     "awaiting_ceo": False},
                ],
                "awaiting_ceo": True,
            }],
            "blockers": [],
        })
        state = hq_state(ledger_path=ledger)
        assert len(state["blockers"]) == 1
        b = state["blockers"][0]
        assert b["feature_id"] == "F002"
        assert b["feature_title"] == "player bios"
        assert "colour-blind" in b["summary"]
        assert b["recommendation"] == "swap to blue/orange"

    def test_kpi_backfill_when_missing(self, tmp_path: Path):
        # If the ledger's kpis block omits active_roles / total_roles,
        # they're computed from the roles list. Same for backlog_size.
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "sprints": [], "decisions": [],
            "roles": [
                {"id": "a", "active": True}, {"id": "b", "active": False},
                {"id": "c", "active": True},
            ],
            "features": [
                {"id": "F1", "current_stage": "spec"},
                {"id": "F2", "current_stage": "build"},
                {"id": "F3", "current_stage": "ship"},
            ],
            "kpis": {},  # empty -- backfill everything
            "blockers": [],
        })
        state = hq_state(ledger_path=ledger)
        assert state["kpis"]["active_roles"] == 2
        assert state["kpis"]["total_roles"] == 3
        # Two open features (spec, build); "ship" excluded from backlog.
        assert state["kpis"]["backlog_size"] == 2


class TestRdPulse:
    """Charter-elevation additions (D081): top-level `intake` /
    `experiments` arrays are surfaced, and three R&D-pulse KPIs
    (`intake_items_open`, `experiments_in_flight`,
    `published_findings_last_30d`) either honour the ledger's recorded
    values or are derived from the arrays.
    """

    def test_intake_and_experiments_arrays_pass_through(self, tmp_path: Path):
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "roles": [], "sprints": [], "features": [],
            "decisions": [], "kpis": {}, "blockers": [],
            "intake": [
                {"id": "I001", "classification": "PROCESS",
                 "priority": "P2", "status": "triaged",
                 "summary": "flag"},
            ],
            "experiments": [
                {"id": "M001-PhaseAC", "status": "closed-negative"},
                {"id": "E-live", "status": "in-flight",
                 "hypothesis": "hyp"},
            ],
        })
        state = hq_state(ledger_path=ledger)
        assert "intake" in state and "experiments" in state
        assert len(state["intake"]) == 1
        assert state["intake"][0]["id"] == "I001"
        assert len(state["experiments"]) == 2
        assert {e["id"] for e in state["experiments"]} == {
            "M001-PhaseAC", "E-live"}

    def test_rd_kpis_default_to_zero_when_absent(self, tmp_path: Path):
        # Missing `intake` + `experiments` -> zero counters, matching
        # the skeleton contract so the frontend doesn't crash on
        # missing keys.
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "roles": [], "sprints": [], "features": [],
            "decisions": [], "kpis": {}, "blockers": [],
        })
        state = hq_state(ledger_path=ledger)
        assert state["intake"] == []
        assert state["experiments"] == []
        for key in ("intake_items_open", "experiments_in_flight",
                    "published_findings_last_30d"):
            assert state["kpis"][key] == 0, (
                f"expected {key}=0 on empty ledger")

    def test_intake_open_derived_when_kpi_not_recorded(self, tmp_path: Path):
        # Two intake items -- one open, one closed -- and no explicit
        # `intake_items_open` in kpis. Derivation counts the open one.
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "roles": [], "sprints": [], "features": [],
            "decisions": [], "kpis": {}, "blockers": [],
            "intake": [
                {"id": "I001", "status": "triaged"},
                {"id": "I002", "status": "closed"},
            ],
            "experiments": [],
        })
        state = hq_state(ledger_path=ledger)
        assert state["kpis"]["intake_items_open"] == 1

    def test_experiments_in_flight_excludes_closed_variants(
            self, tmp_path: Path):
        # `closed-negative`, `closed-positive`, `shipped`, `done` are all
        # terminal, and (I012/D113) queued states like `not-started`
        # are not in flight either. Only genuinely running experiments
        # count -- see test_experiments_kpi_semantics.py for the full
        # D113 pin.
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "roles": [], "sprints": [], "features": [],
            "decisions": [], "kpis": {}, "blockers": [],
            "intake": [],
            "experiments": [
                {"id": "e1", "status": "not-started"},
                {"id": "e2", "status": "in-flight"},
                {"id": "e3", "status": "closed-negative"},
                {"id": "e4", "status": "closed-positive"},
                {"id": "e5", "status": "shipped"},
                {"id": "e6", "status": "done"},
                {"id": "e7", "status": "closed"},
            ],
        })
        state = hq_state(ledger_path=ledger)
        # Only e2 counts (e1 is queued, not in flight).
        assert state["kpis"]["experiments_in_flight"] == 1

    def test_published_findings_30d_window(self, tmp_path: Path):
        # A published finding within 30d counts; older than 30d doesn't.
        # An experiment with `condensed_finding_status="published"` but no
        # explicit `condensed_finding_published_at` counts (best-effort:
        # assume recent).
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=5)).isoformat()
        stale = (now - timedelta(days=120)).isoformat()
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "roles": [], "sprints": [], "features": [],
            "decisions": [], "kpis": {}, "blockers": [],
            "intake": [],
            "experiments": [
                {"id": "e-recent",
                 "condensed_finding_status": "published",
                 "condensed_finding_published_at": recent},
                {"id": "e-stale",
                 "condensed_finding_status": "published",
                 "condensed_finding_published_at": stale},
                {"id": "e-undated",
                 "condensed_finding_status": "published"},
                {"id": "e-nyp",
                 "condensed_finding_status": "not-yet-published"},
            ],
        })
        state = hq_state(ledger_path=ledger)
        # `e-recent` + `e-undated` count; `e-stale` and `e-nyp` don't.
        assert state["kpis"]["published_findings_last_30d"] == 2

    def test_recorded_kpi_wins_over_derivation(self, tmp_path: Path):
        # If the ledger records explicit R&D counters, they take
        # precedence -- matches the `active_roles`/`total_roles`
        # pattern.
        ledger = tmp_path / "company_state.json"
        _write_ledger(ledger, {
            "meta": {}, "roles": [], "sprints": [], "features": [],
            "decisions": [],
            "kpis": {"intake_items_open": 42,
                     "experiments_in_flight": 7,
                     "published_findings_last_30d": 3},
            "blockers": [],
            "intake": [{"id": "I001", "status": "triaged"}],
            "experiments": [{"id": "e1", "status": "in-flight"}],
        })
        state = hq_state(ledger_path=ledger)
        assert state["kpis"]["intake_items_open"] == 42
        assert state["kpis"]["experiments_in_flight"] == 7
        assert state["kpis"]["published_findings_last_30d"] == 3

    def test_skeleton_includes_intake_and_experiments(
            self, tmp_path: Path):
        # Missing ledger -> skeleton payload with empty intake /
        # experiments arrays plus zeroed R&D KPI counters.
        missing = tmp_path / "does_not_exist.json"
        state = hq_state(ledger_path=missing)
        assert state["meta"]["unconfigured"] is True
        assert state["intake"] == []
        assert state["experiments"] == []
        for key in ("intake_items_open", "experiments_in_flight",
                    "published_findings_last_30d"):
            assert key in state["kpis"], (
                f"skeleton kpis missing {key!r}")
            assert state["kpis"][key] == 0
