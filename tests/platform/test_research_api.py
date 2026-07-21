"""HTTP integration + contract tests for /research and
/api/research/verdicts (F003).

- GET /research returns 200 + HTML with the timeline scaffold.
- GET /api/research/verdicts returns 200 JSON with the shipped
  manifest's entries when the sibling research repo is on this
  machine.
- Missing research_root -> 200 JSON with `source_exists=False`.
- Missing manifest -> 200 JSON with `unconfigured=True`.
- Read-only: no files created under research_root by any request.
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


REQUIRED_KEYS = {
    "generated_at", "source_repo_path", "source_exists",
    "cpo_signoff_by", "cpo_signoff_at",
    "entries", "all_candidates", "published_total", "unconfigured",
}


def _make_server(tmp_path: Path,
                 research_root: Path | None = None,
                 research_manifest_path: Path | None = None):
    log_root = tmp_path / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    handler = make_handler(
        log_root, tmp_path, reviews,
        research_root=research_root,
        research_manifest_path=research_manifest_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _get(url: str) -> tuple[int, dict, bytes]:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _get_json(url: str) -> tuple[int, dict]:
    status, _, body = _get(url)
    return status, json.loads(body)


def _fs_snapshot(root: Path) -> dict[str, int]:
    snap: dict[str, int] = {}
    for p in root.rglob("*"):
        if p.is_file():
            snap[str(p.relative_to(root))] = p.stat().st_size
    return snap


@pytest.fixture()
def fixture_research_root(tmp_path: Path) -> Path:
    root = tmp_path / "research"
    (root / "experiments" / "E001_concept_ablation").mkdir(parents=True)
    (root / "experiments" / "E001_concept_ablation" / "REPORT.md").write_text(
        "# E001 -- Report\n\n"
        "**Date:** 2026-06-09 · **Status:** complete · survivor.\n\n"
        "## Abstract\n\n"
        "Six of seven concepts died. One survived. Details follow.\n\n"
        + ("padding line\n" * 30),
        encoding="utf-8",
    )
    (root / "programs").mkdir()
    return root


@pytest.fixture()
def fixture_manifest(tmp_path: Path) -> Path:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({
        "cpo_signoff_by": "cpo",
        "cpo_signoff_at": "2026-07-21T00:00:00Z",
        "entries": [
            {"campaign_id": "E001_concept_ablation", "publish": True,
             "verdict_kind": "alive_survivor",
             "verdict_label": "Alive -- sole survivor",
             "brand_summary": "Brand-approved summary text.",
             "headline_stat": "1 of 7 concepts passed."},
        ],
    }), encoding="utf-8")
    return p


@pytest.fixture()
def cold_server(tmp_path: Path):
    """No research_root, no manifest."""
    srv = _make_server(tmp_path)
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


@pytest.fixture()
def configured_server(tmp_path: Path, fixture_research_root: Path,
                      fixture_manifest: Path):
    srv = _make_server(tmp_path, research_root=fixture_research_root,
                       research_manifest_path=fixture_manifest)
    try:
        yield (f"http://127.0.0.1:{srv.server_address[1]}",
               fixture_research_root, fixture_manifest)
    finally:
        srv.shutdown()


# --------------------------------------------------------------------
# /research HTML
# --------------------------------------------------------------------

def test_get_research_page_200(cold_server):
    status, _, body = _get(cold_server + "/research")
    assert status == 200
    text = body.decode()
    assert "Research verdicts" in text
    assert '/api/research/verdicts' in text
    assert "How pre-registration and BH-FDR keep us honest" in text


# --------------------------------------------------------------------
# /api/research/verdicts contract
# --------------------------------------------------------------------

def test_api_verdicts_cold_start_shape(cold_server):
    status, payload = _get_json(cold_server + "/api/research/verdicts")
    assert status == 200
    assert set(payload) == REQUIRED_KEYS
    assert payload["source_exists"] is False
    assert payload["entries"] == []


def test_api_verdicts_configured_publishes_manifest_row(configured_server):
    base, root, _ = configured_server
    status, payload = _get_json(base + "/api/research/verdicts")
    assert status == 200
    assert payload["source_exists"] is True
    assert payload["cpo_signoff_by"] == "cpo"
    assert payload["published_total"] == 1
    assert payload["all_candidates"] >= 1
    assert payload["entries"][0]["campaign_id"] == "E001_concept_ablation"
    assert payload["entries"][0]["verdict_kind"] == "alive_survivor"
    assert payload["entries"][0]["summary"] == "Brand-approved summary text."


def test_api_verdicts_missing_manifest_flags_unconfigured(tmp_path: Path,
                                                         fixture_research_root: Path):
    srv = _make_server(tmp_path, research_root=fixture_research_root,
                       research_manifest_path=tmp_path / "missing.json")
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        status, payload = _get_json(base + "/api/research/verdicts")
        assert status == 200
        assert payload["unconfigured"] is True
        assert payload["entries"] == []
    finally:
        srv.shutdown()


def test_api_verdicts_never_500(cold_server, configured_server):
    for base in (cold_server, configured_server[0]):
        status, _, _ = _get(base + "/api/research/verdicts")
        assert status < 500


# --------------------------------------------------------------------
# Read-only invariant
# --------------------------------------------------------------------

def test_read_only_invariant_on_research_root(configured_server):
    base, root, _ = configured_server
    before = _fs_snapshot(root)
    for path in ("/research", "/api/research/verdicts",
                 "/api/research/verdicts", "/api/research/verdicts"):
        _get(base + path)
    assert _fs_snapshot(root) == before


# --------------------------------------------------------------------
# Shipped manifest smoke test
# --------------------------------------------------------------------

def test_api_verdicts_shipped_manifest_publishes_expected(tmp_path: Path):
    """When the sibling repo is on this machine, hitting /api/research
    /verdicts with the shipped (default) manifest publishes the six
    Sprint 0 approved campaigns. Skips when the sibling repo is not
    checked out."""
    sibling = Path("/Users/the1finix/Documents/GitHub/finance-research-experiments")
    if not sibling.is_dir():
        pytest.skip("finance-research-experiments not on this machine")
    srv = _make_server(tmp_path, research_root=sibling)
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        _, payload = _get_json(base + "/api/research/verdicts")
        ids = {e["campaign_id"] for e in payload["entries"]}
        expected = {
            "E001_concept_ablation", "E004_walk_forward",
            "E007_impulse_origin_bounce", "E022_structure_aware_tp_snap",
            "E024_near_tp_stall_exit", "phase_ac_pitch_assignment",
        }
        assert expected.issubset(ids)
        assert payload["published_total"] == 6
    finally:
        srv.shutdown()
