"""I012 (D113) -- pinned semantics for the `experiments_in_flight` KPI.

The cycle-2 triage made the semantic call: **in flight = an OPEN
evaluation panel or scheduled compute only.** Queued states
(`not-started`, `awaiting-panel`) are not in flight -- nothing is
running, so counting them would overstate R&D activity. Terminal
states (`closed*` incl. `closed-negative`, `shipped`, `done`) are not
in flight either. Under this rule the truthful value for the REAL
ledger (M001-PhaseAC closed-negative + F013-30d not-started) is 0,
and the last test pins exactly that against the live file.

Sprint-3 housekeeping rider from the chartering session (D116).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.hq import hq_state  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_LEDGER = REPO_ROOT / "company" / "ledger" / "company_state.json"


def _ledger_with_experiments(tmp_path: Path, experiments: list[dict],
                             kpis: dict | None = None) -> Path:
    ledger = tmp_path / "company_state.json"
    ledger.write_text(json.dumps({
        "meta": {}, "roles": [], "sprints": [], "features": [],
        "decisions": [], "kpis": kpis or {}, "blockers": [],
        "intake": [], "experiments": experiments,
    }), encoding="utf-8")
    return ledger


def _in_flight(tmp_path: Path, experiments: list[dict]) -> int:
    ledger = _ledger_with_experiments(tmp_path, experiments)
    return hq_state(ledger_path=ledger)["kpis"]["experiments_in_flight"]


class TestD113Semantics:
    def test_open_panel_and_scheduled_compute_count(self, tmp_path):
        assert _in_flight(tmp_path, [
            {"id": "e1", "status": "open-panel"},
            {"id": "e2", "status": "scheduled-compute"},
            {"id": "e3", "status": "in-flight"},
        ]) == 3

    def test_queued_states_are_not_in_flight(self, tmp_path):
        # THE I012 call: nothing is running for these, so they are
        # queued -- not in flight.
        assert _in_flight(tmp_path, [
            {"id": "e1", "status": "not-started"},
            {"id": "e2", "status": "awaiting-panel"},
            {"id": "e3", "status": "queued"},
            {"id": "e4", "status": "parked"},
        ]) == 0

    def test_terminal_states_are_not_in_flight(self, tmp_path):
        # closed-negative is terminal too: the campaign landed, even
        # if the answer was unwelcome.
        assert _in_flight(tmp_path, [
            {"id": "e1", "status": "closed-negative"},
            {"id": "e2", "status": "closed-positive"},
            {"id": "e3", "status": "closed"},
            {"id": "e4", "status": "shipped"},
            {"id": "e5", "status": "done"},
        ]) == 0

    def test_mixed_ledger_counts_only_running(self, tmp_path):
        assert _in_flight(tmp_path, [
            {"id": "e1", "status": "not-started"},
            {"id": "e2", "status": "open-panel"},
            {"id": "e3", "status": "closed-negative"},
            {"id": "e4", "status": "awaiting-panel"},
        ]) == 1

    def test_statusless_rows_do_not_count(self, tmp_path):
        assert _in_flight(tmp_path, [
            {"id": "e1"}, {"id": "e2", "status": ""},
        ]) == 0

    def test_recorded_nonzero_kpi_still_wins(self, tmp_path):
        # The active_roles/total_roles precedence pattern is unchanged:
        # an explicit non-zero recorded value takes precedence.
        ledger = _ledger_with_experiments(
            tmp_path, [{"id": "e1", "status": "not-started"}],
            kpis={"experiments_in_flight": 7})
        assert hq_state(
            ledger_path=ledger)["kpis"]["experiments_in_flight"] == 7


class TestTruthfulValueOnRealLedger:
    def test_real_ledger_reports_zero_in_flight(self):
        """The D113 truthful value: the real ledger's experiments array
        holds one closed-negative campaign and one not-started
        experiment -- nothing has an open panel or scheduled compute,
        so /hq must report exactly 0, not 1."""
        assert REAL_LEDGER.is_file()
        state = hq_state(ledger_path=REAL_LEDGER)
        statuses = {str(e.get("status") or "").lower()
                    for e in state["experiments"]}
        # Guard: if a genuinely running experiment ever lands in the
        # ledger, this pin must be revisited rather than deleted.
        assert statuses <= {"closed-negative", "not-started",
                            "awaiting-panel", "closed-positive",
                            "closed", "shipped", "done", "queued",
                            "parked"}, (
            "a running experiment appeared -- update this pin "
            "deliberately, per I012 audit-cadence rules")
        assert state["kpis"]["experiments_in_flight"] == 0
