"""F015 -- Org & Flow section on /hq.

Three layers, mirroring the test_hq_* patterns:

1. **Module** -- ``hq.org_state()``: tier grouping (incl. the
   ``executive-adjacent`` -> "R&D" label), report-line resolution
   (explicit ledger ``reports_to`` wins; tier default otherwise; CEO
   reports to nobody), the 11-stage review-chain payload, handoff
   parsing (newest-first, limit, malformed skipped), and the
   unconfigured degradation path.
2. **Page structure** -- the Org & Flow markup + JS renderers are
   pinned in the static ``HQ_PAGE`` string.
3. **API contract** -- ``/api/hq/org`` returns 200 + shaped body on
   both configured and unconfigured ledgers.
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

from agent.platform import hq  # noqa: E402
from agent.platform.pages import HQ_PAGE  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


def _write_ledger(path: Path, roles: list[dict]) -> Path:
    path.write_text(json.dumps({
        "meta": {"company_name": "Blue Lock Trading Co."},
        "roles": roles,
        "sprints": [], "features": [], "decisions": [],
        "kpis": {}, "blockers": [],
    }), encoding="utf-8")
    return path


_ROLES_FIXTURE = [
    {"id": "ceo", "title": "CEO", "tier": "executive",
     "persona_name": "The Ego", "active": True},
    {"id": "cto", "title": "CTO", "tier": "executive",
     "persona_name": "The Anri", "active": True},
    {"id": "cpo", "title": "Head of Product", "tier": "executive",
     "persona_name": "Noel Noa", "active": True},
    {"id": "ui_designer", "title": "UI Designer", "tier": "design",
     "persona_name": None, "active": True},
    {"id": "frontend", "title": "Frontend Engineer",
     "tier": "engineering", "persona_name": None, "active": True},
    {"id": "sales", "title": "Sales", "tier": "business",
     "persona_name": None, "active": False},
    {"id": "user_advocate", "title": "User Advocate", "tier": "business",
     "persona_name": None, "active": True, "reports_to": ["cpo"]},
    {"id": "research_lead", "title": "Research Lead",
     "tier": "executive-adjacent", "persona_name": "The Anri Junior",
     "active": True, "reports_to": ["cto", "cpo"]},
]


def _write_handoff(dir_: Path, name: str, payload) -> Path:
    p = dir_ / name
    p.write_text(json.dumps(payload) if not isinstance(payload, str)
                 else payload, encoding="utf-8")
    return p


class TestOrgStateModule:

    @pytest.fixture()
    def fixture_paths(self, tmp_path: Path):
        ledger = _write_ledger(tmp_path / "ledger.json", _ROLES_FIXTURE)
        handoffs = tmp_path / "handoffs"
        handoffs.mkdir()
        _write_handoff(handoffs, "F001-a.json", {
            "from_role": "cpo", "to_role": "ux_researcher",
            "feature_id": "F001", "timestamp": "2026-07-21T10:00:00Z"})
        _write_handoff(handoffs, "F002-b.json", {
            "from_role": "qa", "to_role": "legal",
            "feature_id": "F002", "timestamp": "2026-07-22T09:00:00Z"})
        _write_handoff(handoffs, "F003-c.json", {
            "from_role": "legal", "to_role": "ceo",
            "feature_id": "F003", "timestamp": "2026-07-21T18:00:00Z",
            "verdict": "green"})
        return ledger, handoffs

    def test_tiers_grouped_in_display_order_with_rd_label(
            self, fixture_paths):
        ledger, handoffs = fixture_paths
        out = hq.org_state(ledger_path=ledger, handoffs_dir=handoffs)
        assert out["unconfigured"] is False
        tier_ids = [t["id"] for t in out["tiers"]]
        assert tier_ids == ["executive", "design", "engineering",
                            "business", "executive-adjacent"]
        labels = {t["id"]: t["label"] for t in out["tiers"]}
        assert labels["executive-adjacent"] == "R&D"
        assert out["roles_total"] == len(_ROLES_FIXTURE)

    def test_report_lines_ceo_root_and_tier_defaults(self, fixture_paths):
        ledger, handoffs = fixture_paths
        out = hq.org_state(ledger_path=ledger, handoffs_dir=handoffs)
        by_id = {r["id"]: r for t in out["tiers"] for r in t["roles"]}
        assert by_id["ceo"]["reports_to"] == []          # root
        assert by_id["cto"]["reports_to"] == ["ceo"]     # exec default
        assert by_id["ui_designer"]["reports_to"] == ["cpo"]
        assert by_id["frontend"]["reports_to"] == ["cto"]
        assert by_id["sales"]["reports_to"] == ["ceo"]   # business default

    def test_explicit_reports_to_wins_over_tier_default(
            self, fixture_paths):
        ledger, handoffs = fixture_paths
        out = hq.org_state(ledger_path=ledger, handoffs_dir=handoffs)
        by_id = {r["id"]: r for t in out["tiers"] for r in t["roles"]}
        # user_advocate is business tier (default would be ceo) but the
        # ledger says cpo; research_lead dual-reports.
        assert by_id["user_advocate"]["reports_to"] == ["cpo"]
        assert by_id["research_lead"]["reports_to"] == ["cto", "cpo"]

    def test_roles_carry_active_and_persona(self, fixture_paths):
        ledger, handoffs = fixture_paths
        out = hq.org_state(ledger_path=ledger, handoffs_dir=handoffs)
        by_id = {r["id"]: r for t in out["tiers"] for r in t["roles"]}
        assert by_id["sales"]["active"] is False
        assert by_id["ceo"]["active"] is True
        assert by_id["ceo"]["persona_name"] == "The Ego"
        assert by_id["ui_designer"]["persona_name"] is None

    def test_review_chain_stages_and_conditionals(self, fixture_paths):
        ledger, handoffs = fixture_paths
        out = hq.org_state(ledger_path=ledger, handoffs_dir=handoffs)
        stages = [s["stage"] for s in out["review_chain"]]
        # The 11 stages of review-chain.md incl. the 7b research stage.
        assert stages == ["spec", "research", "design", "architecture",
                          "build", "qa", "security", "research (7b)",
                          "legal", "signoff", "ship"]
        cond = {s["stage"] for s in out["review_chain"]
                if s["conditional"]}
        assert cond == {"research", "architecture", "security",
                        "research (7b)", "legal"}
        owners = {s["stage"]: s["owner"] for s in out["review_chain"]}
        assert owners["research (7b)"] == "research_lead"
        assert owners["signoff"] == "ceo"

    def test_handoffs_newest_first_with_total(self, fixture_paths):
        ledger, handoffs = fixture_paths
        out = hq.org_state(ledger_path=ledger, handoffs_dir=handoffs)
        assert out["handoffs_total"] == 3
        ids = [h["feature_id"] for h in out["handoffs"]]
        assert ids == ["F002", "F003", "F001"]  # by timestamp desc
        assert out["handoffs"][1]["verdict"] == "green"

    def test_handoff_limit_applies(self, fixture_paths):
        ledger, handoffs = fixture_paths
        out = hq.org_state(ledger_path=ledger, handoffs_dir=handoffs,
                           handoff_limit=2)
        assert len(out["handoffs"]) == 2
        assert out["handoffs_total"] == 3

    def test_malformed_handoff_skipped_silently(self, fixture_paths):
        ledger, handoffs = fixture_paths
        _write_handoff(handoffs, "broken.json", "{not json")
        _write_handoff(handoffs, "list.json", ["not", "a", "dict"])
        out = hq.org_state(ledger_path=ledger, handoffs_dir=handoffs)
        assert out["handoffs_total"] == 3  # the two bad files dropped

    def test_missing_ledger_degrades_but_keeps_review_chain(
            self, tmp_path: Path):
        out = hq.org_state(ledger_path=tmp_path / "nope.json",
                           handoffs_dir=tmp_path / "no-handoffs")
        assert out["unconfigured"] is True
        assert out["unconfigured_reason"]
        assert out["tiers"] == []
        assert len(out["review_chain"]) == 11  # static, always renders
        assert out["handoffs"] == []
        assert out["handoffs_total"] == 0

    def test_malformed_ledger_degrades(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{oops", encoding="utf-8")
        out = hq.org_state(ledger_path=bad,
                           handoffs_dir=tmp_path / "no-handoffs")
        assert out["unconfigured"] is True
        assert out["tiers"] == []

    def test_unknown_tier_still_renders_after_canonical(self,
                                                        tmp_path: Path):
        ledger = _write_ledger(tmp_path / "l.json", [
            {"id": "ceo", "title": "CEO", "tier": "executive",
             "active": True},
            {"id": "mystery", "title": "Mystery", "tier": "future-tier",
             "active": True},
        ])
        out = hq.org_state(ledger_path=ledger,
                           handoffs_dir=tmp_path / "no-handoffs")
        tier_ids = [t["id"] for t in out["tiers"]]
        assert tier_ids == ["executive", "future-tier"]
        assert out["tiers"][1]["label"] == "future-tier"


class TestOrgFlowPageStructure:
    """Static markers pinned in HQ_PAGE, like TestRdPulseStructure."""

    def test_org_flow_section_present(self):
        assert 'id="org-flow"' in HQ_PAGE
        assert 'id="org-flow-heading"' in HQ_PAGE
        assert "Org &amp; Flow" in HQ_PAGE

    def test_three_blocks_present(self):
        for marker in ('id="org-chart"', 'id="org-pipeline"',
                       'id="org-handoffs"'):
            assert marker in HQ_PAGE, f"missing org block: {marker!r}"

    def test_renderers_defined_and_called(self):
        for fn in ("function renderOrgChart", "function renderOrgPipeline",
                   "function renderOrgHandoffs",
                   "async function renderOrgFlow"):
            assert fn in HQ_PAGE, f"missing JS renderer: {fn!r}"
        # Called on load AND on the 30s poll -- a definition without a
        # call leaves the section on `loading...` forever.
        assert "renderOrgFlow();" in HQ_PAGE
        assert "setInterval(renderOrgFlow, 30000);" in HQ_PAGE

    def test_fetches_the_org_endpoint(self):
        assert '/api/hq/org' in HQ_PAGE

    def test_mobile_collapse_rule_present(self):
        # The 700px collapse is the platform-wide mobile contract.
        assert ".org-tier-roles{grid-template-columns:1fr}" in HQ_PAGE


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _make_server(tmp_path: Path, ledger: Path | None,
                 handoffs: Path | None):
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    log_root = tmp_path / "logs"
    log_root.mkdir(exist_ok=True)
    handler = make_handler(log_root, tmp_path, reviews,
                           live_dir=tmp_path / "squad_live",
                           company_ledger_path=ledger,
                           company_handoffs_dir=handoffs)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


REQUIRED_ORG_KEYS = {"generated_at", "unconfigured",
                     "unconfigured_reason", "tiers", "roles_total",
                     "review_chain", "handoffs", "handoffs_total"}


class TestOrgApiContract:

    @pytest.fixture()
    def org_server(self, tmp_path: Path):
        ledger = _write_ledger(tmp_path / "ledger.json", _ROLES_FIXTURE)
        handoffs = tmp_path / "handoffs"
        handoffs.mkdir()
        _write_handoff(handoffs, "F001-a.json", {
            "from_role": "cpo", "to_role": "ux_researcher",
            "feature_id": "F001", "timestamp": "2026-07-21T10:00:00Z"})
        srv = _make_server(tmp_path, ledger, handoffs)
        try:
            yield f"http://127.0.0.1:{srv.server_address[1]}"
        finally:
            srv.shutdown()

    @pytest.fixture()
    def unconfigured_org_server(self, tmp_path: Path):
        srv = _make_server(tmp_path, tmp_path / "missing.json",
                           tmp_path / "missing-handoffs")
        try:
            yield f"http://127.0.0.1:{srv.server_address[1]}"
        finally:
            srv.shutdown()

    def test_returns_200_with_required_keys(self, org_server):
        status, body = _get_json(org_server + "/api/hq/org")
        assert status == 200
        assert set(body.keys()) >= REQUIRED_ORG_KEYS
        assert body["unconfigured"] is False
        assert body["roles_total"] == len(_ROLES_FIXTURE)
        assert len(body["review_chain"]) == 11
        assert body["handoffs_total"] == 1

    def test_unconfigured_returns_200_shaped(self,
                                             unconfigured_org_server):
        status, body = _get_json(
            unconfigured_org_server + "/api/hq/org")
        assert status == 200
        assert body["unconfigured"] is True
        assert body["tiers"] == []
        assert len(body["review_chain"]) == 11
