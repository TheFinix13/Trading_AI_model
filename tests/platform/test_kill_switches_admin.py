"""F011 -- kill_switch_admin (WRITE path) tests.

Coverage:

- activate writes the flag file + audit line.
- activate_kill without reason still logs a placeholder reason.
- clear removes the flag + writes audit line.
- Idempotent activate (double-activate updates reason; still audits).
- Idempotent clear (clear when nothing there still audits as no-op).
- Unknown symbol raises ValueError before touching disk.
- Reason trimmed to 200 chars.
- Audit tail bounded by `limit`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.platform import credentials, kill_switch_admin, kill_switches


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(kill_switches.KILL_DIR_ENV, str(tmp_path / "kill"))
    credentials.set_config_dir(tmp_path)
    kill_switches.reset_cache_for_tests()
    yield tmp_path
    credentials.set_config_dir(None)
    kill_switches.reset_cache_for_tests()


def _load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestActivate:
    def test_activate_creates_flag_and_audit(self, _isolated_config: Path) -> None:
        kill_switch_admin.activate_kill(
            "EURUSD", reason="spread jumped", by="user")
        assert kill_switches.is_killed("EURUSD") is True
        events = _load_events(kill_switch_admin.events_log_path())
        assert len(events) == 1
        entry = events[0]
        assert entry["action"] == "activate"
        assert entry["scope"] == "EURUSD"
        assert entry["reason"] == "spread jumped"
        assert entry["by"] == "user"

    def test_activate_without_reason_logs_placeholder(
        self, _isolated_config: Path
    ) -> None:
        kill_switch_admin.activate_kill("EURUSD")
        events = _load_events(kill_switch_admin.events_log_path())
        assert events[0]["reason"] == "(no reason)"

    def test_activate_trims_reason_to_200_chars(
        self, _isolated_config: Path
    ) -> None:
        long_reason = "x" * 500
        kill_switch_admin.activate_kill("EURUSD", reason=long_reason)
        events = _load_events(kill_switch_admin.events_log_path())
        assert len(events[0]["reason"]) == 200

    def test_activate_unknown_symbol_raises(
        self, _isolated_config: Path
    ) -> None:
        with pytest.raises(ValueError, match="unknown symbol"):
            kill_switch_admin.activate_kill("XAUUSD")

    def test_activate_global_via_none_or_string(
        self, _isolated_config: Path
    ) -> None:
        kill_switch_admin.activate_kill(None, reason="A")
        assert kill_switches.is_killed() is True
        kill_switch_admin.clear_kill(None)
        kill_switch_admin.activate_kill("GLOBAL", reason="B")
        assert kill_switches.is_killed() is True


class TestClear:
    def test_clear_removes_flag_and_audits(self, _isolated_config: Path) -> None:
        kill_switch_admin.activate_kill("EURUSD", reason="x")
        kill_switch_admin.clear_kill("EURUSD")
        assert kill_switches.is_killed("EURUSD") is False
        events = _load_events(kill_switch_admin.events_log_path())
        actions = [e["action"] for e in events]
        assert actions == ["activate", "clear"]

    def test_clear_when_empty_is_noop_still_audited(
        self, _isolated_config: Path
    ) -> None:
        kill_switch_admin.clear_kill("EURUSD")
        events = _load_events(kill_switch_admin.events_log_path())
        assert len(events) == 1
        assert events[0]["action"] == "clear"
        assert events[0]["reason"] == "(no-op)"


class TestIdempotent:
    def test_double_activate_updates_reason(
        self, _isolated_config: Path
    ) -> None:
        kill_switch_admin.activate_kill("EURUSD", reason="first")
        kill_switch_admin.activate_kill("EURUSD", reason="second")
        rows = kill_switches.list_killed()
        assert rows[0]["reason"] == "second"
        events = _load_events(kill_switch_admin.events_log_path())
        assert [e["reason"] for e in events] == ["first", "second"]


class TestRecentEvents:
    def test_recent_events_bounded_by_limit(
        self, _isolated_config: Path
    ) -> None:
        for i in range(25):
            kill_switch_admin.activate_kill("EURUSD", reason=f"r{i}")
        assert len(kill_switch_admin.recent_events(20)) == 20
        assert len(kill_switch_admin.recent_events(5)) == 5

    def test_recent_events_returns_newest_last(
        self, _isolated_config: Path
    ) -> None:
        kill_switch_admin.activate_kill("EURUSD", reason="first")
        kill_switch_admin.clear_kill("EURUSD")
        kill_switch_admin.activate_kill("EURUSD", reason="second")
        events = kill_switch_admin.recent_events(3)
        assert events[-1]["reason"] == "second"

    def test_recent_events_missing_log_empty(
        self, _isolated_config: Path
    ) -> None:
        assert kill_switch_admin.recent_events() == []

    def test_recent_events_limit_zero(self, _isolated_config: Path) -> None:
        kill_switch_admin.activate_kill("EURUSD", reason="x")
        assert kill_switch_admin.recent_events(0) == []


class TestMalformedAuditLine:
    def test_malformed_line_skipped(self, _isolated_config: Path) -> None:
        kill_switch_admin.activate_kill("EURUSD", reason="ok")
        # Corrupt the audit tail so the reader must be resilient.
        with kill_switch_admin.events_log_path().open("a") as fh:
            fh.write("{not-json}\n")
        events = kill_switch_admin.recent_events(10)
        # Only the well-formed line survives.
        assert len(events) == 1
        assert events[0]["reason"] == "ok"
