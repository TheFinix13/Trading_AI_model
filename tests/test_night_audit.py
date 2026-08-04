"""Night Auditor (scripts/night_audit.py) — pinned behaviours.

The contract under test is the Tier-1 off-hours-shift promise:
a silent weekday alarms on day one, a timestamp_miss regression
alarms, a healthy day says "all nominal", and every warn/alarm
drafts an intake stub while NEVER touching anything outside
<live_dir>/audits/.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import night_audit as na  # noqa: E402

# 2026-08-03 is a Monday: full weekday floors apply.
MONDAY = datetime(2026, 8, 3, tzinfo=timezone.utc)
SATURDAY = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _tick(sym: str, hour: int, narrative: str = "quiet") -> dict:
    return {
        "type": "tick_summary",
        "timestamp": f"2026-08-03T{hour:02d}:00:00+00:00",
        "symbol": sym,
        "players_evaluated": ["a01_isagi"],
        "players_who_proposed": [],
        "proposal_count": 0,
        "thoughts_top5": [{"agent_id": "a01_isagi", "symbol": sym,
                           "narrative": narrative, "confidence": 0.1}],
    }


def _write_tape(live_dir: Path, events: list[dict],
                proposals: list[dict] | None = None,
                trades: list[dict] | None = None) -> None:
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in events) + "\n")
    for name, rows in (("proposals_all.jsonl", proposals or []),
                       ("trades.jsonl", trades or [])):
        (live_dir / name).write_text(
            "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""))
    (live_dir / "state.json").write_text(json.dumps(
        {"last_bar_times": {"EURUSD": "2026-08-03T23:00:00"}}))


def _healthy_events() -> list[dict]:
    return [_tick(sym, h) for sym in na.SYMBOLS_DEFAULT
            for h in na.EXPECTED_H4_CLOSES_UTC]


def test_healthy_weekday_is_all_nominal(tmp_path):
    _write_tape(tmp_path, _healthy_events(),
                proposals=[{"timestamp": "2026-08-03T07:00:00+00:00"}])
    result = na.audit_day(tmp_path, MONDAY)
    assert result["overall"] == "ok"
    by_id = {c["id"]: c for c in result["checks"]}
    assert by_id["tape_coverage_EURUSD"]["status"] == "ok"
    assert by_id["timestamp_miss"]["status"] == "ok"
    assert "1 proposals" in by_id["activity"]["detail"]


def test_silent_weekday_alarms_on_day_one(tmp_path):
    """The silent-week P0: zero rows on a weekday must alarm, per symbol."""
    _write_tape(tmp_path, [])
    result = na.audit_day(tmp_path, MONDAY)
    assert result["overall"] == "alarm"
    for sym in na.SYMBOLS_DEFAULT:
        assert {c["status"] for c in result["checks"]
                if c["id"] == f"tape_coverage_{sym}"} == {"alarm"}


def test_saturday_zero_rows_is_not_an_anomaly(tmp_path):
    _write_tape(tmp_path, [])
    result = na.audit_day(tmp_path, SATURDAY)
    assert result["overall"] == "ok"


def test_timestamp_miss_narrative_alarms(tmp_path):
    events = _healthy_events()
    events[0] = _tick("EURUSD", 3, narrative="abstain: timestamp_miss @03Z")
    _write_tape(tmp_path, events)
    result = na.audit_day(tmp_path, MONDAY)
    by_id = {c["id"]: c for c in result["checks"]}
    assert by_id["timestamp_miss"]["status"] == "alarm"
    assert result["overall"] == "alarm"


def test_stale_feed_row_alarms_and_refresh_streak_warns(tmp_path):
    stale = {"type": "system_status", "status": "stale",
             "timestamp": "2026-08-03T11:00:00+00:00"}
    _write_tape(tmp_path, _healthy_events() + [stale])
    by_id = {c["id"]: c for c in
             na.audit_day(tmp_path, MONDAY)["checks"]}
    assert by_id["feed_health"]["status"] == "alarm"

    streak = [{"type": "system_status", "status": "refresh_error",
               "failure_streak": n,
               "timestamp": f"2026-08-03T{10 + n:02d}:30:00+00:00"}
              for n in (1, 2, 3)]
    _write_tape(tmp_path, _healthy_events() + streak)
    by_id = {c["id"]: c for c in
             na.audit_day(tmp_path, MONDAY)["checks"]}
    assert by_id["feed_health"]["status"] == "warn"


def test_outputs_digest_and_stubs_only_under_audits(tmp_path):
    _write_tape(tmp_path, [])  # silent Monday -> alarms -> stubs
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    result = na.audit_day(tmp_path, MONDAY)
    digest = na.write_outputs(tmp_path, result)
    after = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    new_paths = after - before
    assert digest.exists() and digest.parent.name == "audits"
    assert new_paths, "auditor must write its outputs"
    assert all(str(p).startswith("audits") for p in new_paths), (
        "observe-and-draft rule: nothing outside <live_dir>/audits/")
    stubs = list((tmp_path / "audits" / "stubs").glob("*.md"))
    assert len(stubs) == len([c for c in result["checks"]
                              if c["status"] in ("warn", "alarm")])


def test_notify_publishes_single_watchdog_alert(tmp_path, monkeypatch):
    published: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        na.alerts, "publish",
        lambda ev_type, payload: published.append((ev_type, payload)))
    _write_tape(tmp_path, _healthy_events())
    na.notify(na.audit_day(tmp_path, MONDAY))
    assert len(published) == 1
    ev_type, payload = published[0]
    assert ev_type == "watchdog_alert"
    assert payload["check"] == "night_audit"
    assert "all nominal" in payload["detail"]
