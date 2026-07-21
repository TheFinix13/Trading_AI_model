"""Unit tests for agent/platform/research.py -- F003 data plane.

Four surfaces are covered:

* Publication manifest loader: happy path, missing file, malformed
  JSON, empty entries list, list vs dict entries shape.
* REPORT.md parser: canonical `**Verdict:**`, `**Status:**`, and
  `**Outcome:**` header lines; abstract extraction; short-file
  reject; unreadable file; verdict-kind classification (dead / fail
  / pass / stopped / parked / complete / stage-1-complete).
* Filesystem walker: skips `_TEMPLATE`, skips `REPORT 2.md` drift
  copies, aggregates across `experiments/` and `programs/`.
* `get_state`: manifest gate honoured (only allow-listed entries
  reach the payload), missing research_root yields shaped-empty
  payload with `unconfigured=True` when the manifest is also
  missing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.platform import research


# --------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------

REPORT_ALIVE = """# E001 -- Report

**Date:** 2026-06-09 · **Status:** complete · sole survivor handed to E002.

## Abstract

This is the abstract paragraph.

More detail here.

## Method

Not relevant to the parser.
""" + ("more content padding line\n" * 30)

REPORT_DEAD = """# E024 -- Near-TP stall exit

**Verdict:** `dead` · **Stage 2:** cancelled · **Date:** 2026-07-20

## Abstract

Stage 1 measured expectancy across three symbols. It did not meet
the promotion criterion. Stage 2 was cancelled.
""" + ("more content padding line\n" * 30)

REPORT_PASS_THIN = """# Phase AC campaign

**Written:** 2026-07-21 (UTC). **Status:** PASS (thin)

## Abstract

We asked whether pair-character predicts agent success.
""" + ("more content padding line\n" * 30)

REPORT_SHORT = "# Tiny\n**Verdict:** whatever\n"

REPORT_TEMPLATE = """# _TEMPLATE

**Status:** complete / stopped at stage N / parked.
""" + ("padding\n" * 40)


def _mk_report(root: Path, rel: str, body: str) -> Path:
    """Create a REPORT.md at ``root / rel / REPORT.md``."""
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    p = d / "REPORT.md"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture()
def research_root(tmp_path: Path) -> Path:
    root = tmp_path / "research"
    root.mkdir()
    _mk_report(root, "experiments/E001_concept_ablation", REPORT_ALIVE)
    _mk_report(root, "experiments/E024_near_tp_stall_exit", REPORT_DEAD)
    _mk_report(root, "experiments/_TEMPLATE", REPORT_TEMPLATE)
    # drift copy that should be skipped:
    (root / "experiments" / "E013_safety_layer_contribution").mkdir()
    (root / "experiments" / "E013_safety_layer_contribution" / "REPORT 2.md").write_text(
        REPORT_ALIVE, encoding="utf-8")
    _mk_report(
        root,
        "programs/M001_multi_agent_ensemble/experiments/phase_ac_pitch_assignment",
        REPORT_PASS_THIN,
    )
    return root


def _fs_snapshot(root: Path) -> dict[str, int]:
    snap: dict[str, int] = {}
    for p in root.rglob("*"):
        if p.is_file():
            snap[str(p.relative_to(root))] = p.stat().st_size
    return snap


# --------------------------------------------------------------------
# Publication manifest loader
# --------------------------------------------------------------------

def test_load_manifest_missing_file(tmp_path: Path):
    m = research.load_manifest(tmp_path / "nope.json")
    assert m["unconfigured"] is True
    assert m["entries"] == {}


def test_load_manifest_malformed_json(tmp_path: Path):
    p = tmp_path / "manifest.json"
    p.write_text("{not-json", encoding="utf-8")
    m = research.load_manifest(p)
    assert m["unconfigured"] is True
    assert m["entries"] == {}


def test_load_manifest_happy_path(tmp_path: Path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({
        "cpo_signoff_by": "cpo",
        "cpo_signoff_at": "2026-07-21T00:00:00Z",
        "entries": [
            {"campaign_id": "E001", "publish": True,
             "verdict_kind": "alive", "brand_summary": "Yes"},
            {"campaign_id": "E002", "publish": False,
             "verdict_kind": "dead"},
        ],
    }), encoding="utf-8")
    m = research.load_manifest(p)
    assert m["unconfigured"] is False
    assert m["cpo_signoff_by"] == "cpo"
    assert set(m["entries"].keys()) == {"E001", "E002"}
    assert m["entries"]["E001"]["publish"] is True


def test_load_manifest_dict_entries_shape(tmp_path: Path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({
        "entries": {"E001": {"publish": True, "verdict_kind": "alive"}}
    }), encoding="utf-8")
    m = research.load_manifest(p)
    assert m["entries"]["E001"]["publish"] is True


def test_load_manifest_default_path_reads_shipped():
    m = research.load_manifest()
    assert m["unconfigured"] is False
    assert m["cpo_signoff_by"] == "cpo"
    assert isinstance(m["entries"], dict)


# --------------------------------------------------------------------
# REPORT parser
# --------------------------------------------------------------------

def test_parse_report_alive(tmp_path: Path):
    p = _mk_report(tmp_path, "E001_concept_ablation", REPORT_ALIVE)
    parsed = research.parse_report(p)
    assert parsed is not None
    assert parsed["campaign_id"] == "E001_concept_ablation"
    assert "Report" in parsed["title"]
    assert parsed["verdict_kind"] == "complete"
    assert parsed["status_raw"].startswith("complete")
    assert "abstract paragraph" in parsed["abstract"]


def test_parse_report_dead_verdict(tmp_path: Path):
    p = _mk_report(tmp_path, "E024_near_tp_stall_exit", REPORT_DEAD)
    parsed = research.parse_report(p)
    assert parsed["verdict_kind"] == "dead"
    assert "dead" in parsed["status_raw"].lower()


def test_parse_report_pass_thin_verdict(tmp_path: Path):
    p = _mk_report(tmp_path, "phase_ac_pitch_assignment", REPORT_PASS_THIN)
    parsed = research.parse_report(p)
    assert parsed["verdict_kind"] == "pass_thin"


def test_parse_report_short_file_rejected(tmp_path: Path):
    p = _mk_report(tmp_path, "E999_tiny", REPORT_SHORT)
    assert research.parse_report(p) is None


def test_parse_report_missing_file(tmp_path: Path):
    assert research.parse_report(tmp_path / "nope.md") is None


def test_classify_verdict_variants():
    cases = [
        ("dead", "dead"),
        ("`dead`", "dead"),
        ("FAIL", "fail"),
        ("PASS", "pass"),
        ("Pass (thin)", "pass_thin"),
        ("stopped at stage 1", "stopped_at_stage_1"),
        ("stopped", "stopped"),
        ("parked_low_yield", "parked_low_yield"),
        ("complete · foo", "complete"),
        ("in_progress", "in_progress"),
        ("", "unknown"),
        ("some other verdict", "unknown"),
    ]
    for txt, expected in cases:
        assert research._classify_verdict(txt) == expected, txt


def test_parse_report_extracts_iso_date(tmp_path: Path):
    p = _mk_report(tmp_path, "E024_near_tp_stall_exit", REPORT_DEAD)
    parsed = research.parse_report(p)
    assert "2026-07-20" in parsed["date"]


# --------------------------------------------------------------------
# Filesystem walker
# --------------------------------------------------------------------

def test_list_all_finds_experiments_and_programs(research_root: Path):
    entries = research.list_all(research_root)
    ids = [e["campaign_id"] for e in entries]
    assert "E001_concept_ablation" in ids
    assert "E024_near_tp_stall_exit" in ids
    assert "phase_ac_pitch_assignment" in ids


def test_list_all_skips_template(research_root: Path):
    ids = [e["campaign_id"] for e in research.list_all(research_root)]
    assert "_TEMPLATE" not in ids


def test_list_all_skips_report_2_drift(research_root: Path):
    ids = [e["campaign_id"] for e in research.list_all(research_root)]
    assert "E013_safety_layer_contribution" not in ids


def test_list_all_sorts_newest_first(research_root: Path):
    entries = research.list_all(research_root)
    # 2026-07-20 (E024) comes before 2026-07-21 (phase_ac); phase_ac before E001 (2026-06-09).
    assert entries[0]["campaign_id"] == "phase_ac_pitch_assignment"


def test_list_all_missing_root_returns_empty():
    assert research.list_all(None) == []
    assert research.list_all(Path("/does/not/exist")) == []


# --------------------------------------------------------------------
# get_state
# --------------------------------------------------------------------

def test_get_state_manifest_gate_honoured(research_root: Path, tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "cpo_signoff_by": "cpo",
        "cpo_signoff_at": "2026-07-21T00:00:00Z",
        "entries": [
            {"campaign_id": "E024_near_tp_stall_exit", "publish": True,
             "verdict_kind": "dead", "verdict_label": "Dead",
             "brand_summary": "The brand summary override wins."},
            {"campaign_id": "E001_concept_ablation", "publish": False},
        ],
    }), encoding="utf-8")
    st = research.get_state(research_root=research_root,
                            manifest_path=manifest)
    ids = [e["campaign_id"] for e in st["entries"]]
    assert ids == ["E024_near_tp_stall_exit"]
    assert st["entries"][0]["summary"] == "The brand summary override wins."
    assert st["all_candidates"] >= 3
    assert st["published_total"] == 1
    assert st["source_exists"] is True
    assert st["cpo_signoff_by"] == "cpo"
    assert st["unconfigured"] is False


def test_get_state_missing_root_returns_shape(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"entries": []}), encoding="utf-8")
    st = research.get_state(research_root=None, manifest_path=manifest)
    assert st["source_exists"] is False
    assert st["entries"] == []
    assert st["all_candidates"] == 0
    assert st["unconfigured"] is False


def test_get_state_missing_manifest_flags_unconfigured(research_root: Path,
                                                       tmp_path: Path):
    st = research.get_state(research_root=research_root,
                            manifest_path=tmp_path / "missing.json")
    assert st["unconfigured"] is True
    assert st["entries"] == []


def test_get_state_never_publishes_without_publish_flag(research_root: Path,
                                                       tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "entries": [
            {"campaign_id": "E024_near_tp_stall_exit"},  # no publish flag
        ],
    }), encoding="utf-8")
    st = research.get_state(research_root=research_root,
                            manifest_path=manifest)
    assert st["entries"] == []


def test_get_state_shipped_manifest_publishes_expected_ids():
    """Regression lock -- the shipped manifest publishes 6 entries
    against the shipped research_root when it's on this machine.
    Skips gracefully when the sibling repo isn't checked out."""
    root = Path("/Users/the1finix/Documents/GitHub/finance-research-experiments")
    if not root.is_dir():
        pytest.skip("finance-research-experiments not on this machine")
    st = research.get_state(research_root=root)
    ids = {e["campaign_id"] for e in st["entries"]}
    expected = {
        "E001_concept_ablation", "E004_walk_forward",
        "E007_impulse_origin_bounce", "E022_structure_aware_tp_snap",
        "E024_near_tp_stall_exit", "phase_ac_pitch_assignment",
    }
    assert expected.issubset(ids)


# --------------------------------------------------------------------
# Read-only invariant
# --------------------------------------------------------------------

def test_read_only_invariant(research_root: Path, tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "entries": [{"campaign_id": "E024_near_tp_stall_exit",
                     "publish": True}]
    }), encoding="utf-8")
    before = _fs_snapshot(research_root)
    for _ in range(3):
        research.get_state(research_root=research_root,
                           manifest_path=manifest)
        research.list_all(research_root)
    assert _fs_snapshot(research_root) == before
