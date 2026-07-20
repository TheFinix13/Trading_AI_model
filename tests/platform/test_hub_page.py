"""Tests for the redesigned platform hub (``HUB_PAGE``).

Three layers, matching the redesign spec:

1. **Structure** — string-level assertions on the static HUB_PAGE
   HTML: every user-visible section is present, every API endpoint
   the JS calls is wired in, no stale copy leaks through.
2. **HTTP integration** — spin up the real ``scripts/serve_platform``
   handler on an ephemeral port over a synthetic reviews/log tree and
   confirm ``GET /`` renders the redesigned hub with the right content
   type + explainer heading.
3. **API contract** — the hub JS fires four fetches on load
   (``/api/v1/status``, ``/api/v2/live/status``,
   ``/api/v2/live/events``, ``/healthz``). Assert the JSON shape from
   each endpoint on a fresh test server matches what the hub expects,
   so a silent field rename in one of the collectors trips these tests
   before it trips the UI.
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

from agent.platform.pages import HUB_PAGE  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


# ---------------------------------------------------------------------------
# 1) Static-string structure tests
# ---------------------------------------------------------------------------

class TestHubStructure:
    """The rendered HTML is a plain string — assert its shape directly."""

    def test_title_and_top_headline_present(self):
        assert "Multi-pair trading platform" in HUB_PAGE
        assert "<title>Trading platform</title>" in HUB_PAGE

    def test_every_major_section_heading_present(self):
        # Section names from the redesign spec (top to bottom).
        for marker in (
            "v1", "v2", "Squad", "Zones agent",
            "What am I looking at?",
            "Glossary",
            "Recent activity",
        ):
            assert marker in HUB_PAGE, f"missing section marker: {marker!r}"

    def test_all_four_api_endpoints_wired_into_js(self):
        # The hub JS Promise.all's these four endpoints on load. If one
        # is renamed / removed, the KPI cards silently break, so we pin
        # the strings here.
        for endpoint in (
            "/api/v1/status",
            "/api/v2/live/status",
            "/api/v2/live/events",
            "/healthz",
        ):
            assert endpoint in HUB_PAGE, f"missing endpoint: {endpoint!r}"

    def test_no_stale_v2_copy(self):
        # v2 has gained live shadow-paper mode via run_squad_live.py; the
        # "sim-only" badge and "until graduated" subtitle are misleading.
        for stale in ("sim-only", "until graduated"):
            assert stale not in HUB_PAGE, (
                f"stale marker still present: {stale!r}")

    def test_glossary_lists_all_seven_squad_names(self):
        for name in ("Isagi", "Bachira", "Rin",
                     "Chigiri", "Reo", "Nagi", "Barou"):
            assert name in HUB_PAGE, f"missing squad name: {name!r}"

    def test_explainer_has_three_paragraph_leads(self):
        for lead in ("Two agents, one demo account",
                     "Why two agents?",
                     "How to read the /v2 page"):
            assert lead in HUB_PAGE, (
                f"missing explainer paragraph lead: {lead!r}")

    def test_glossary_uses_native_details_disclosure(self):
        # <details class="glossary"> keeps the section collapsible with
        # zero JS, so the KPI strip stays uncluttered by default.
        assert "<details class=\"glossary\">" in HUB_PAGE
        assert "<summary>Glossary" in HUB_PAGE

    def test_footer_pins_branch_and_deploy_context(self):
        # Newcomers land here first — the footer tells them which branch
        # is deployed and where the logs live, so links back to the code
        # aren't guesswork.
        assert "next-gen" in HUB_PAGE
        assert "Exness VM" in HUB_PAGE

    def test_v2_tile_advertises_live_shadow_paper(self):
        # Redesign brief: the v2 tile paragraph must state the current
        # runtime mode, not just "walk-forward replay".
        assert "live shadow-paper" in HUB_PAGE


# ---------------------------------------------------------------------------
# 2) HTTP integration + 3) API contract
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


@pytest.fixture()
def hub_server(tmp_path: Path):
    """A cold-start platform server: empty reviews dir, empty log root,
    no live dir on disk yet — the state a newcomer would hit right
    after a fresh clone. The hub must render sensibly against this."""
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    log_root = tmp_path / "logs"
    log_root.mkdir()
    live_dir = tmp_path / "squad_live"  # deliberately not created
    handler = make_handler(log_root, tmp_path, reviews, live_dir=live_dir)
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


class TestHubHttpSurface:

    def test_hub_serves_html_with_explainer_heading(self, hub_server):
        status, headers, body = _get(hub_server + "/")
        assert status == 200
        assert headers.get("Content-Type", "").startswith("text/html")
        assert b"Multi-pair trading platform" in body
        assert b"What am I looking at?" in body
        assert b"Recent activity" in body

    def test_hub_survives_cold_start(self, hub_server):
        # Same cold-start server: /v1 status returns empty symbols, live
        # dir doesn't exist. The hub HTML must still ship intact so its
        # JS can render the "no data yet" affordances.
        status, _, body = _get(hub_server + "/")
        assert status == 200
        assert b"loading" in body  # initial placeholder text still in DOM


class TestHubApiContract:
    """Each endpoint's payload must contain the fields the hub JS reads."""

    def test_v1_status_shape(self, hub_server):
        status, _, body = _get(hub_server + "/api/v1/status")
        assert status == 200
        payload = json.loads(body)
        # Fields the KPI card + tile summary + system-card kill badge
        # all pull from.
        assert isinstance(payload.get("symbols"), list)
        assert "global_kill" in payload
        assert "log_root" in payload

    def test_v2_live_status_shape(self, hub_server):
        status, _, body = _get(hub_server + "/api/v2/live/status")
        assert status == 200
        payload = json.loads(body)
        # The v2 KPI card's badge logic branches on running/source; the
        # rows read last_event_time and poll_heartbeat_age_seconds. All
        # four must be present in the payload even on a fresh reset.
        for key in ("exists", "running", "source",
                    "last_event_time", "poll_heartbeat_age_seconds",
                    "kill"):
            assert key in payload, f"missing key: {key!r}"

    def test_healthz_shape(self, hub_server):
        status, _, body = _get(hub_server + "/healthz")
        assert status == 200
        payload = json.loads(body)
        assert payload.get("status") == "ok"
        assert payload.get("version")
        assert isinstance(payload.get("uptime_seconds"), (int, float))

    def test_live_events_endpoint_reachable(self, hub_server):
        # Cold start: live dir doesn't exist yet, so the endpoint
        # returns 404. That's fine — the hub JS treats 404 as "no events
        # yet" and shows the waiting message. We only need to confirm
        # the endpoint answers (isn't a 500 or a routing hole).
        status, _, _ = _get(hub_server + "/api/v2/live/events?cursor=0&limit=5")
        assert status in (200, 404)
