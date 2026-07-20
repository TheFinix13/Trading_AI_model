"""``paper_loop.live_workspace(out_dir)`` — read the latest
``workspace_snapshot.json`` for the /v2 LIVE panel.

The engine writes the file on every H4 bar close; this loader fails
open (returns ``{"exists": False, "thoughts": []}``) on any read /
JSON error so a corrupted or missing snapshot never 500s the /v2 page.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.platform import paper_loop


def _write_snapshot(out_dir: Path, payload: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / paper_loop.WORKSPACE_SNAPSHOT_FILE
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_live_workspace_returns_expected_shape_on_populated_dir(
        tmp_path: Path):
    payload = {
        "as_of": "2026-07-21T00:04:00+00:00",
        "tick_id": 17,
        "thought_count": 3,
        "thoughts": [
            {"agent_id": "bachira_meguru", "symbol": "EURUSD",
             "narrative": "near demand", "confidence_in_thought": 0.72,
             "tags": ["zone_touch"], "tick_id": 17,
             "timestamp": "2026-07-21T00:04:00+00:00"},
            {"agent_id": "isagi_yoichi", "symbol": "GBPUSD",
             "narrative": "confluence pending", "confidence_in_thought": 0.55,
             "tags": [], "tick_id": 17,
             "timestamp": "2026-07-21T00:04:00+00:00"},
        ],
    }
    _write_snapshot(tmp_path, payload)
    got = paper_loop.live_workspace(tmp_path)
    assert got["exists"] is True
    assert got["tick_id"] == 17
    assert got["thought_count"] == 3
    assert isinstance(got["thoughts"], list)
    assert got["thoughts"][0]["agent_id"] == "bachira_meguru"
    assert got["as_of"] == "2026-07-21T00:04:00+00:00"


def test_live_workspace_missing_file_returns_exists_false(tmp_path: Path):
    got = paper_loop.live_workspace(tmp_path / "nope")
    assert got == {"exists": False, "thoughts": []}


def test_live_workspace_empty_dir_no_snapshot(tmp_path: Path):
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    got = paper_loop.live_workspace(tmp_path)
    assert got["exists"] is False
    assert got["thoughts"] == []


def test_live_workspace_malformed_json_fails_open(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / paper_loop.WORKSPACE_SNAPSHOT_FILE
    path.write_text("this is not JSON {", encoding="utf-8")
    got = paper_loop.live_workspace(tmp_path)
    # Fail open: no exception, no crash for the API layer above us.
    assert got["exists"] is False
    assert got["thoughts"] == []


def test_live_workspace_non_dict_top_level_fails_open(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / paper_loop.WORKSPACE_SNAPSHOT_FILE
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    got = paper_loop.live_workspace(tmp_path)
    assert got["exists"] is False
    assert got["thoughts"] == []


def test_live_workspace_defaults_when_fields_missing(tmp_path: Path):
    """A snapshot with only ``as_of`` (older schema) still loads, with
    zero defaults for the numeric fields and an empty thoughts list."""
    _write_snapshot(tmp_path, {"as_of": "2026-07-21T00:00:00+00:00"})
    got = paper_loop.live_workspace(tmp_path)
    assert got["exists"] is True
    assert got["tick_id"] == 0
    assert got["thought_count"] == 0
    assert got["thoughts"] == []
