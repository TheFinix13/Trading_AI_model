"""Tests for the pure logic of scripts/dogfood_personas.py (D092).

Server-dependent behaviour is exercised by running the script itself
(the dogfood run); these tests cover what must never regress silently:
front-matter parsing, persona loading + validation, journey assembly,
the no-live-mode safety invariant, and friction reporting.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import dogfood_personas as dog  # noqa: E402


# ---------------------------------------------------------------------------
# Front-matter parsing
# ---------------------------------------------------------------------------

class TestParseFrontMatter:
    def test_scalars_lists_and_nested_maps(self):
        text = "\n".join([
            "---",
            "id: P099",
            "name: \"Quoted Name\"",
            "goals:",
            "  - first goal",
            "  - second goal",
            "fake_profile:",
            "  alpha:",
            "    email: a@example.invalid",
            "    card_last4: \"0000\"",
            "---",
            "",
            "# body ignored",
        ])
        meta = dog.parse_front_matter(text)
        assert meta["id"] == "P099"
        assert meta["name"] == "Quoted Name"
        assert meta["goals"] == ["first goal", "second goal"]
        assert meta["fake_profile"]["alpha"]["email"] == \
            "a@example.invalid"
        assert meta["fake_profile"]["alpha"]["card_last4"] == "0000"

    def test_booleans_parse(self):
        meta = dog.parse_front_matter("---\nflag: true\nother: false\n---")
        assert meta["flag"] is True
        assert meta["other"] is False

    def test_missing_opening_fence_raises(self):
        with pytest.raises(ValueError):
            dog.parse_front_matter("id: P001\n---\n")

    def test_missing_closing_fence_raises(self):
        with pytest.raises(ValueError):
            dog.parse_front_matter("---\nid: P001\n")


# ---------------------------------------------------------------------------
# Persona loading — the shipped roster must always be loadable
# ---------------------------------------------------------------------------

class TestLoadPersonas:
    def test_shipped_roster_loads(self):
        personas = dog.load_personas()
        ids = [p.id for p in personas]
        assert ids == ["P001", "P002", "P003", "P004", "P005", "P006"]
        for p in personas:
            assert p.name and p.archetype and p.goals and p.devices
            assert p.risk_tolerance in ("none", "low", "medium", "high")
            assert p.tests, f"{p.id} declares no test surfaces"
            for surface in p.tests:
                assert surface in dog._KNOWN_SURFACES

    def test_ceo_persona_covers_every_surface(self):
        p001 = dog.load_personas()[0]
        assert set(p001.tests) == set(dog._KNOWN_SURFACES)

    def test_test_customers_carry_fake_profiles(self):
        p006 = [p for p in dog.load_personas() if p.id == "P006"][0]
        profile = p006.extra["fake_profile"]
        for person in profile.values():
            assert person["email"].endswith("@example.invalid")
            assert "DO_NOT_CHARGE" in person["card_token"]
            assert "NOT REAL" in person["full_name"]

    def test_missing_required_field_raises(self, tmp_path):
        (tmp_path / "P900-broken.md").write_text(
            "---\nid: P900\nname: Broken\n---\nbody\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing front-matter"):
            dog.load_personas(tmp_path)

    def test_duplicate_id_raises(self, tmp_path):
        body = ("---\nid: P901\nname: A\narchetype: x\ngoals:\n  - g\n"
                "risk_tolerance: low\ndevices:\n  - d\ntests:\n"
                "  - pages\n---\n")
        (tmp_path / "P901-a.md").write_text(body, encoding="utf-8")
        (tmp_path / "P901-b.md").write_text(body, encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate persona id"):
            dog.load_personas(tmp_path)

    def test_unknown_surface_raises(self, tmp_path):
        (tmp_path / "P902-x.md").write_text(
            "---\nid: P902\nname: A\narchetype: x\ngoals:\n  - g\n"
            "risk_tolerance: low\ndevices:\n  - d\ntests:\n"
            "  - warp_drive\n---\n", encoding="utf-8")
        with pytest.raises(ValueError, match="unknown test surfaces"):
            dog.load_personas(tmp_path)


# ---------------------------------------------------------------------------
# Journey assembly
# ---------------------------------------------------------------------------

def _persona(tests):
    return dog.Persona(
        id="P999", name="Test", archetype="unit-test dummy",
        goals=["g"], risk_tolerance="low", devices=["d"],
        tests=tests, path="(memory)")


class TestBuildJourneys:
    def test_journeys_follow_declared_surfaces_in_order(self):
        journeys = dog.build_journeys(
            _persona(["onboarding", "kill_switch", "pages"]))
        assert [j["name"] for j in journeys] == \
            ["onboarding", "kill_switch", "pages"]

    def test_every_surface_has_a_builder(self):
        journeys = dog.build_journeys(_persona(list(dog._KNOWN_SURFACES)))
        assert len(journeys) == len(dog._KNOWN_SURFACES)
        for journey in journeys:
            assert journey["steps"], f"{journey['name']} has no steps"

    def test_no_journey_ever_touches_live_mode_enable(self):
        # Safety invariant: the dogfood cast must never be able to
        # enable live mode, even against an isolated server.
        journeys = dog.build_journeys(_persona(list(dog._KNOWN_SURFACES)))
        for journey in journeys:
            for step in journey["steps"]:
                assert "/api/live-mode/enable" not in step["path"]

    def test_broker_journey_uses_obviously_fake_credentials(self):
        journeys = dog.build_journeys(_persona(["broker"]))
        payloads = [s["payload"] for s in journeys[0]["steps"]
                    if s["payload"]]
        assert payloads
        for payload in payloads:
            assert payload["password"] == dog.FAKE_PASSWORD
            assert "NOT-REAL" in payload["password"]

    def test_broker_journey_ends_with_rate_limit_check(self):
        journey = dog.build_journeys(_persona(["broker"]))[0]
        assert journey["pre"] == "reset_broker_rate_limiter"
        last = journey["steps"][-1]
        assert "Too many attempts" in last["contains"]

    def test_approvals_journey_checks_fail_closed_gate_first(self):
        journey = dog.build_journeys(_persona(["approvals"]))[0]
        first = journey["steps"][0]
        assert first["expect_status"] == (401,)
        assert not first["needs_internal_token"]
        tokened = [s for s in journey["steps"]
                   if s["needs_internal_token"]]
        assert len(tokened) == len(journey["steps"]) - 1

    def test_approval_entry_satisfies_queue_schema(self):
        from agent.platform import approval_queue
        entry = dog._approval_entry("P999", "unit test")
        for fld in approval_queue._REQUIRED_ENTRY_FIELDS:
            assert fld in entry
        assert entry["side"] in ("buy", "sell")
        assert entry["risk_snapshot"]["worst_case_loss"] > 0


# ---------------------------------------------------------------------------
# Friction reporting
# ---------------------------------------------------------------------------

def _result(ok=True, skipped=False, **over):
    base = {
        "persona": "P002", "persona_name": "Ada Nwosu",
        "journey": "onboarding", "label": "wizard state loads",
        "method": "GET", "path": "/api/onboarding/state",
        "status": 500, "expect_status": [200], "ok": ok,
        "skipped": skipped, "problem": "unexpected HTTP status 500",
        "body_excerpt": "boom",
    }
    base.update(over)
    return base


class TestFrictionReporting:
    def test_collect_frictions_ignores_passes_and_skips(self):
        results = [_result(ok=True), _result(ok=False),
                   _result(ok=False, skipped=True)]
        frictions = dog.collect_frictions(results)
        assert len(frictions) == 1
        assert frictions[0]["ok"] is False

    def test_candidate_intake_block_carries_the_evidence(self):
        block = dog.format_candidate_intake(_result(ok=False))
        assert block.startswith("CANDIDATE INTAKE")
        assert "P002 (Ada Nwosu)" in block
        assert "GET /api/onboarding/state" in block
        assert "unexpected HTTP status 500" in block
        assert "boom" in block

    def test_dotted_get_walks_nested_dicts(self):
        obj = {"a": {"b": {"c": 3}}}
        assert dog._dotted_get(obj, "a.b.c") == 3
        assert dog._dotted_get(obj, "a.x") is None
        assert dog._dotted_get(None, "a") is None
