"""scripts/weekly_squad_report.py -- weekly v2 review bundle.

Synthetic two-day tape: an active day (proposal -> blocked -> open ->
close + tick_summary + system_status failure) and a quiet day (ticks
only). The window also spans a weekday with no tape at all, which must
be flagged.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.weekly_squad_report import (  # noqa: E402
    aggregate_week, issue_scan, render_report, window_days, write_bundle,
)
from agent.platform.highlights import _read_events  # noqa: E402

# 2026-07-20 (Mon), 2026-07-21 (Tue) on tape; 2026-07-22 (Wed) silent.
_DAYS = ["2026-07-20", "2026-07-21", "2026-07-22"]

_ROWS = [
    {"t": "2026-07-20T08:00:00+00:00", "type": "tick_summary",
     "symbol": "EURUSD", "tick_id": 1, "proposal_count": 1,
     "post_sentinel_count": 1, "workspace_thought_count": 9,
     "players_evaluated": ["isagi"], "players_who_proposed": ["isagi"]},
    {"t": "2026-07-20T08:00:01+00:00", "type": "proposal",
     "agent": "isagi", "symbol": "EURUSD", "dir": "long",
     "conviction": 0.8},
    {"t": "2026-07-20T08:00:02+00:00", "type": "blocked",
     "agent": "bachira", "symbol": "GBPUSD", "by": "sentinel",
     "rule": True, "reason": "R2 daily loss cap"},
    {"t": "2026-07-20T08:00:03+00:00", "type": "open",
     "agent": "isagi", "symbol": "EURUSD", "dir": "long"},
    {"t": "2026-07-20T16:00:00+00:00", "type": "close",
     "agent": "isagi", "symbol": "EURUSD", "goal": True,
     "pnl_pips": 25.0, "exit_reason": "tp", "r": 1.5, "tqs": 0.42},
    {"t": "2026-07-20T16:00:05+00:00", "type": "system_status",
     "component": "news_calendar", "status": "fetch_failed",
     "failure_streak": 2, "message": "timeout"},
    {"t": "2026-07-21T08:00:00+00:00", "type": "tick_summary",
     "symbol": "EURUSD", "tick_id": 2, "proposal_count": 0,
     "post_sentinel_count": 0, "workspace_thought_count": 9,
     "players_evaluated": ["isagi"], "players_who_proposed": []},
]


def _live_dir(tmp_path: Path) -> Path:
    live = tmp_path / "squad_live"
    live.mkdir()
    (live / "events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in _ROWS), encoding="utf-8")
    (live / "state.json").write_text('{"bars_seen": 200}', encoding="utf-8")
    return live


class TestWindowDays:
    def test_days_arg(self) -> None:
        days = window_days(3, None, None)
        assert len(days) == 3
        assert days == sorted(days)

    def test_start_end_inclusive(self) -> None:
        assert window_days(None, "2026-07-20", "2026-07-22") == _DAYS


class TestAggregation:
    def test_week_totals(self, tmp_path: Path) -> None:
        live = _live_dir(tmp_path)
        week = aggregate_week(_DAYS, live)
        t = week["totals"]
        assert t["shots"] == 1
        assert t["tackles"] == 1
        assert t["on_target"] == 1
        assert t["resolved"] == 1
        assert t["goals"] == 1
        assert t["net_pips"] == 25.0
        assert t["net_r"] == 1.5
        assert t["ticks_evaluated"] == 2

    def test_player_rollup(self, tmp_path: Path) -> None:
        week = aggregate_week(_DAYS, _live_dir(tmp_path))
        by_agent = {p["agent"]: p for p in week["players"]}
        assert by_agent["isagi"]["goals"] == 1
        assert by_agent["isagi"]["net_pips"] == 25.0
        assert by_agent["bachira"]["tackled"] == 1


class TestIssueScan:
    def test_flags_silent_weekday_and_system_rows(self, tmp_path: Path) -> None:
        live = _live_dir(tmp_path)
        issues = issue_scan(_read_events(live), _DAYS)
        assert issues["silent_weekdays"] == ["2026-07-22"]
        assert issues["system_status"][("news_calendar", "fetch_failed")] == 1
        assert issues["blocks"][("sentinel", "R2 daily loss cap")] == 1
        assert len(issues["closes"]) == 1


class TestReportAndBundle:
    def test_report_sections_and_flags(self, tmp_path: Path) -> None:
        live = _live_dir(tmp_path)
        rows = _read_events(live)
        report = render_report(_DAYS, aggregate_week(_DAYS, live),
                               issue_scan(rows, _DAYS), live)
        for needle in ("Executive summary", "Day by day", "Players",
                       "Resolved shadow trades", "Sentinel blocks",
                       "System health", "Review checklist",
                       "shadow-paper", "2026-07-22", "R2 daily loss cap",
                       "news_calendar", "+25.0"):
            assert needle in report, needle

    def test_zip_bundle_contents(self, tmp_path: Path) -> None:
        live = _live_dir(tmp_path)
        rows = _read_events(live)
        report = render_report(_DAYS, aggregate_week(_DAYS, live),
                               issue_scan(rows, _DAYS), live)
        out = tmp_path / "week.zip"
        write_bundle(out, report, rows, _DAYS, live)
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            assert {"REPORT.md", "events_window.jsonl",
                    "state.json"} <= names
            window = zf.read("events_window.jsonl").decode().splitlines()
            assert len(window) == len(_ROWS)

    def test_empty_tape_degrades_gracefully(self, tmp_path: Path) -> None:
        live = tmp_path / "empty"
        live.mkdir()
        report = render_report(_DAYS, aggregate_week(_DAYS, live),
                               issue_scan([], _DAYS), live)
        assert "no tape on record" in report
        # All three days are weekdays with no tape -> flagged.
        assert "runtime down" in report
