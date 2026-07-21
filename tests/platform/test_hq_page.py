"""Tests for the /hq dashboard page (`HQ_PAGE`).

Two layers:

1. **Static structure** — string-level assertions on the constant HTML
   confirming every section named in the /hq spec is present.
2. **HTTP smoke** — spin up the platform server, GET /hq, confirm 200
   + content-type + expected structural markers in the body.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.pages import HQ_PAGE, HUB_PAGE  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


# --------------------------------------------------------------------------
# 1) Static structure
# --------------------------------------------------------------------------

class TestHqStructure:
    """Every section named in the /hq spec must be present in the HTML."""

    def test_title_and_company_name(self):
        assert "<title>Blue Lock Trading Co. -- HQ</title>" in HQ_PAGE
        assert "Blue Lock Trading Co." in HQ_PAGE

    def test_header_shows_sprint_badge_and_day_counter(self):
        assert 'id="hq-sprint-badge"' in HQ_PAGE
        assert 'id="hq-day-counter"' in HQ_PAGE

    def test_kpi_strip_container_present(self):
        assert 'id="kpi-strip"' in HQ_PAGE

    def test_kanban_columns_named_in_js(self):
        for col in ("Backlog", "Design", "Build", "Review", "Ship"):
            assert col in HQ_PAGE, f"missing kanban column: {col!r}"
        assert 'id="kanban"' in HQ_PAGE

    def test_role_grid_and_tier_labels(self):
        assert 'id="role-grid"' in HQ_PAGE
        for tier in ("Executive", "Design", "Engineering", "Business"):
            assert tier in HQ_PAGE, f"missing tier label: {tier!r}"

    def test_decisions_log_container(self):
        assert 'id="decisions-log"' in HQ_PAGE
        assert "Decisions log" in HQ_PAGE

    def test_blockers_panel_present(self):
        assert 'id="blockers"' in HQ_PAGE
        assert "Blockers" in HQ_PAGE
        # Empty-state message is required so an empty blockers panel
        # doesn't look broken.
        assert "No blockers. Company is executing." in HQ_PAGE

    def test_footer_references_ledger_path(self):
        assert "company/ledger/company_state.json" in HQ_PAGE
        assert 'id="hq-footer"' in HQ_PAGE

    def test_fetches_hq_state_endpoint_and_polls_30s(self):
        # The dashboard fetches /api/hq/state on load and every 30 s.
        # A rename of either the endpoint or the interval breaks the
        # dashboard silently, so we pin them here.
        assert '/api/hq/state' in HQ_PAGE
        assert 'setInterval(refresh, 30000)' in HQ_PAGE

    def test_nav_active_class_on_hq(self):
        # `nav('hq')` marks the HQ tab active on this page (see the
        # _NAV template in pages.py).
        assert 'href="/hq" class="here"' in HQ_PAGE

    def test_no_cursor_attribution_leak(self):
        # Non-negotiable: no Cursor attribution in any shipped string.
        for banned in ("Made-with: Cursor", "Made with Cursor",
                       "cursor.com", "cursoragent"):
            assert banned.lower() not in HQ_PAGE.lower(), (
                f"attribution leak: {banned!r}")

    def test_dark_theme_tokens_referenced(self):
        # The dashboard reuses the platform's dark-theme tokens; no new
        # colours should be introduced by the /hq styles.
        for token in ("var(--bg)", "var(--panel)", "var(--border)",
                      "var(--fg)", "var(--dim)", "var(--accent)"):
            assert token in HQ_PAGE, f"missing token: {token!r}"


class TestHubTileLinksToHq:
    """The hub's fourth tile links to /hq."""

    def test_hub_tile_exists(self):
        assert 'href="/hq"' in HUB_PAGE
        assert "HQ &middot; Blue Lock Trading Co." in HUB_PAGE

    def test_hub_tile_summary_wired(self):
        # The hub JS calls renderHqTile(hq); confirm the tile summary
        # element + the render function are present.
        assert 'id="tile-hq-summary"' in HUB_PAGE
        assert 'renderHqTile' in HUB_PAGE

    def test_hub_fetches_hq_state(self):
        # The hub's refresh loop pulls /api/hq/state alongside the
        # existing three endpoints.
        assert '/api/hq/state' in HUB_PAGE


# --------------------------------------------------------------------------
# 2) HTTP smoke
# --------------------------------------------------------------------------

@pytest.fixture()
def hq_server(tmp_path: Path):
    """A cold-start platform server pointing at a fixture ledger.

    Same shape as the shipped `company_state.json`, minimal contents so
    the frontend can smoke-render every section.
    """
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    log_root = tmp_path / "logs"
    log_root.mkdir()
    live_dir = tmp_path / "squad_live"  # deliberately not created
    ledger = tmp_path / "company_state.json"
    ledger.write_text(json.dumps({
        "meta": {"company_name": "Blue Lock Trading Co.",
                 "founded": "2026-07-21",
                 "current_sprint_id": "sprint-0"},
        "roles": [
            {"id": "ceo", "title": "CEO", "tier": "executive",
             "persona_name": "The Ego", "active": True,
             "current_task": "signoff", "throughput_last_7d": 0},
        ],
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
    handler = make_handler(log_root, tmp_path, reviews,
                           live_dir=live_dir,
                           company_ledger_path=ledger)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def _get(url: str) -> tuple[int, dict, bytes]:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class TestHqPageHttp:

    def test_hq_route_returns_200(self, hq_server):
        status, headers, body = _get(hq_server + "/hq")
        assert status == 200
        assert headers.get("Content-Type", "").startswith("text/html")

    def test_hq_body_contains_structural_markers(self, hq_server):
        _, _, body = _get(hq_server + "/hq")
        for marker in (b"Blue Lock Trading Co.", b"kpi-strip",
                       b"kanban", b"role-grid", b"decisions-log",
                       b"Blockers"):
            assert marker in body, f"missing marker in body: {marker!r}"

    def test_hq_nav_still_shows_other_tabs(self, hq_server):
        _, _, body = _get(hq_server + "/hq")
        # HQ page's nav includes links to the other three routes.
        for target in (b"/v1", b"/v2", b'href="/"'):
            assert target in body, f"missing nav link: {target!r}"
