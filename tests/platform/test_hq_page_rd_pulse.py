"""Tests for the /hq R&D pulse section.

Sprint 2 close-out was followed by the 2026-07-22 charter elevation
(D081) which added a top-level `intake` and `experiments` array to
``company/ledger/company_state.json`` and three new KPI counters
(`intake_items_open`, `experiments_in_flight`,
`published_findings_last_30d`). The dashboard now surfaces those on
`/hq` via a three-column "R&D pulse" section between the Sprint
Kanban and the Role grid.

These tests pin:

1. **Static structure** — the ``rd-pulse`` container + the three
   named columns exist in the shipped ``HQ_PAGE`` HTML, along with
   the client-side ``renderRdPulse`` function and the three new
   KPI-strip tiles.
2. **HTTP smoke — populated ledger** — the page renders 200 + the
   R&D pulse markers when the ledger has intake/experiments rows.
3. **HTTP smoke — empty state** — a ledger with no intake and no
   experiments still renders the section without crashing (the
   client-side render replaces the ``loading...`` placeholders with
   friendly empty-state copy).
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

from agent.platform.pages import HQ_PAGE  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


class TestRdPulseStructure:
    """The three R&D-pulse columns + the JS renderer are pinned in the
    static HQ_PAGE string. A silent rename here breaks the dashboard
    without a network round-trip, so we assert on markup + JS names.
    """

    def test_rd_pulse_section_present(self):
        assert 'id="rd-pulse"' in HQ_PAGE
        assert 'id="rd-pulse-heading"' in HQ_PAGE
        assert "R&amp;D pulse" in HQ_PAGE

    def test_three_named_columns_present(self):
        for column in ("intake", "experiments", "latest-finding"):
            assert f'data-rd-column="{column}"' in HQ_PAGE, (
                f"missing R&D pulse column: {column!r}")

    def test_column_headings_and_more_links_present(self):
        for heading in ("Intake queue", "Experiments in flight",
                        "Most recent published finding"):
            assert heading in HQ_PAGE, (
                f"missing R&D column heading: {heading!r}")
        for link in ('href="/rd/intake"', 'href="/rd/experiments"',
                     'href="/research"'):
            assert link in HQ_PAGE, (
                f"missing R&D column link: {link!r}")

    def test_render_rd_pulse_function_defined_and_called(self):
        # The renderer + its call from refresh() are both required --
        # a definition without a call would leave the section on
        # `loading...` forever.
        assert "function renderRdPulse" in HQ_PAGE
        assert "renderRdPulse(hq)" in HQ_PAGE
        assert "renderRdPulse({intake: [], experiments: []})" in HQ_PAGE

    def test_three_new_kpi_cells_labels_present(self):
        for label in ("Intake open", "Experiments in flight",
                      "Findings (30d)"):
            assert label in HQ_PAGE, f"missing KPI label: {label!r}"

    def test_kpi_over_bandwidth_warn_style_wired(self):
        # `intake_items_open > 20` renders the tile in warn tone --
        # confirm both the CSS class and the JS branch are wired.
        assert ".kpi-tile.warn" in HQ_PAGE
        assert "over triage bandwidth" in HQ_PAGE

    def test_role_grid_header_shows_19_seats(self):
        # Sanity: the role-grid caption line follows the 17->19 bump.
        assert "19 roles across 4 tiers" in HQ_PAGE
        assert "19 seats total" in HQ_PAGE

    def test_rd_pulse_css_tokens_added(self):
        for cls in (".rd-pulse", ".rd-column", ".rd-column-body",
                    ".rd-item", ".rd-more"):
            assert cls in HQ_PAGE, f"missing rd-pulse CSS token: {cls!r}"


# ---------------------------------------------------------------------------
# HTTP smoke tests
# ---------------------------------------------------------------------------

def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _make_server(tmp_path: Path, ledger: Path):
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
def populated_server(tmp_path: Path):
    ledger = tmp_path / "company_state.json"
    ledger.write_text(json.dumps({
        "meta": {"company_name": "Blue Lock Trading Co.",
                 "founded": "2026-07-21",
                 "current_sprint_id": "sprint-2"},
        "roles": [{"id": "ceo", "title": "CEO", "tier": "executive",
                   "active": True}],
        "sprints": [{"id": "sprint-2", "name": "Real-Trading",
                     "started_at": "2026-07-21", "day_target": 13,
                     "feature_ids": []}],
        "features": [],
        "decisions": [],
        "kpis": {"active_roles": 14, "total_roles": 19,
                 "intake_items_open": 1,
                 "experiments_in_flight": 0,
                 "published_findings_last_30d": 0},
        "blockers": [],
        "intake": [
            {"id": "I001", "classification": "PROCESS", "priority": "P2",
             "status": "triaged",
             "summary": "Sprint 1 honest-review flag."},
        ],
        "experiments": [
            {"id": "M001-PhaseAC", "status": "closed-negative",
             "verdict": "AC.2 A2 FAIL"},
            {"id": "F013-30d-approval-rate", "status": "not-started",
             "hypothesis": "At least 30% of proposed live orders "
                           "will be reviewed within timeout."},
        ],
    }), encoding="utf-8")
    srv = _make_server(tmp_path, ledger)
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


@pytest.fixture()
def empty_rd_server(tmp_path: Path):
    ledger = tmp_path / "company_state.json"
    ledger.write_text(json.dumps({
        "meta": {"company_name": "Blue Lock Trading Co.",
                 "founded": "2026-07-21",
                 "current_sprint_id": "sprint-2"},
        "roles": [],
        "sprints": [],
        "features": [],
        "decisions": [],
        "kpis": {},
        "blockers": [],
        "intake": [],
        "experiments": [],
    }), encoding="utf-8")
    srv = _make_server(tmp_path, ledger)
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


class TestRdPulseHttp:

    def test_rd_pulse_section_served_when_populated(self, populated_server):
        status, body = _get(populated_server + "/hq")
        assert status == 200
        for marker in (b'id="rd-pulse"', b'data-rd-column="intake"',
                       b'data-rd-column="experiments"',
                       b'data-rd-column="latest-finding"',
                       b"Intake queue", b"Experiments in flight",
                       b"Most recent published finding"):
            assert marker in body, f"missing rd-pulse marker: {marker!r}"

    def test_rd_pulse_section_present_on_empty_state(self, empty_rd_server):
        # Even with zero intake + zero experiments the HTML shell must
        # still ship the section; the client-side renderer swaps the
        # `loading...` placeholders for empty-state copy.
        status, body = _get(empty_rd_server + "/hq")
        assert status == 200
        assert b'id="rd-pulse"' in body
        assert b'data-rd-column="intake"' in body
        assert b'data-rd-column="experiments"' in body
        assert b'data-rd-column="latest-finding"' in body
