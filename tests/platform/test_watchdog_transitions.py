"""F017 -- state-transition-only publishing + snapshot cache."""
from __future__ import annotations

import json
import secrets as _secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import alerts, credentials, watchdog  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    alerts.reset()
    watchdog.reset_cache_for_tests()
    yield
    credentials._reset_state_for_tests()
    alerts.reset()
    watchdog.reset_cache_for_tests()


def _r(check_id: str, status: str, detail: str = "d") -> dict:
    return {"id": check_id, "status": status, "detail": detail,
            "checked_at": "2026-07-24T00:00:00Z"}


@pytest.fixture()
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "watchdog_state.json"


class TestTransitionPublishing:
    def test_first_observation_of_warn_publishes(
            self, state_path: Path) -> None:
        seen: list[dict] = []
        out = watchdog.publish_transitions(
            [_r("calendar_feed", "warn")], state_path, seen.append)
        assert len(out) == 1 and len(seen) == 1
        assert seen[0]["check"] == "calendar_feed"
        assert seen[0]["status"] == "warn"
        assert seen[0]["previous"] is None
        assert seen[0]["recovered"] is False

    def test_steady_warn_does_not_republish(self, state_path: Path) -> None:
        seen: list[dict] = []
        watchdog.publish_transitions(
            [_r("calendar_feed", "warn")], state_path, seen.append)
        watchdog.publish_transitions(
            [_r("calendar_feed", "warn")], state_path, seen.append)
        watchdog.publish_transitions(
            [_r("calendar_feed", "warn")], state_path, seen.append)
        assert len(seen) == 1

    def test_escalation_warn_to_alarm_publishes(
            self, state_path: Path) -> None:
        seen: list[dict] = []
        watchdog.publish_transitions(
            [_r("risk_state", "warn")], state_path, seen.append)
        watchdog.publish_transitions(
            [_r("risk_state", "alarm")], state_path, seen.append)
        assert [p["status"] for p in seen] == ["warn", "alarm"]
        assert seen[1]["previous"] == "warn"

    def test_recovery_publishes_with_recovered_flag(
            self, state_path: Path) -> None:
        seen: list[dict] = []
        watchdog.publish_transitions(
            [_r("ledger_drift", "alarm")], state_path, seen.append)
        watchdog.publish_transitions(
            [_r("ledger_drift", "ok")], state_path, seen.append)
        assert len(seen) == 2
        assert seen[1]["recovered"] is True
        assert seen[1]["status"] == "ok"

    def test_ok_first_run_publishes_nothing(self, state_path: Path) -> None:
        seen: list[dict] = []
        watchdog.publish_transitions(
            [_r("intake_sla", "ok"), _r("sprint_pulse", "na")],
            state_path, seen.append)
        assert seen == []

    def test_ok_to_na_is_not_a_transition(self, state_path: Path) -> None:
        seen: list[dict] = []
        watchdog.publish_transitions(
            [_r("broker_health", "ok")], state_path, seen.append)
        watchdog.publish_transitions(
            [_r("broker_health", "na")], state_path, seen.append)
        assert seen == []

    def test_state_persists_across_calls(self, state_path: Path) -> None:
        watchdog.publish_transitions(
            [_r("calendar_feed", "alarm")], state_path, lambda p: None)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["states"]["calendar_feed"] == "alarm"

    def test_corrupt_state_file_treated_as_empty(
            self, state_path: Path) -> None:
        state_path.write_text("{nope", encoding="utf-8")
        seen: list[dict] = []
        out = watchdog.publish_transitions(
            [_r("calendar_feed", "warn")], state_path, seen.append)
        assert len(out) == 1  # degraded-from-unknown still publishes

    def test_broken_publisher_never_raises(self, state_path: Path) -> None:
        def _boom(payload: dict) -> None:
            raise RuntimeError("bus offline")
        out = watchdog.publish_transitions(
            [_r("calendar_feed", "warn")], state_path, _boom)
        assert out == []  # nothing published, nothing raised

    def test_default_publisher_lands_on_alerts_bus(
            self, state_path: Path) -> None:
        watchdog.publish_transitions(
            [_r("risk_state", "alarm")], state_path)
        events = alerts.recent(5)
        assert len(events) == 1
        assert events[0]["type"] == watchdog.ALERT_EVENT_TYPE
        assert events[0]["payload"]["check"] == "risk_state"

    def test_detail_carries_metadata_not_file_contents(
            self, state_path: Path) -> None:
        """Legal rolling constraint: payload detail is the check's
        detail string (ages/counts/ids), passed through verbatim."""
        seen: list[dict] = []
        watchdog.publish_transitions(
            [_r("intake_sla", "alarm", detail="I902 P0 untriaged 5.0h")],
            state_path, seen.append)
        assert seen[0]["detail"] == "I902 P0 untriaged 5.0h"


class TestSnapshotCache:
    def _kwargs(self, tmp_path: Path) -> dict:
        return dict(
            live_dir=None,
            calendar_cache_path=tmp_path / "none.json",
            risk_state_path=tmp_path / "none.jsonl",
            intake_dir=tmp_path / "none",
            ledger_json_path=tmp_path / "none.json",
            ledger_md_path=tmp_path / "none.md",
        )

    def test_snapshot_shape(self, tmp_path: Path) -> None:
        snap = watchdog.snapshot(publish=False, **self._kwargs(tmp_path))
        assert snap["cached"] is False
        assert snap["overall"] in watchdog.STATUSES
        assert len(snap["checks"]) == len(watchdog.CHECK_IDS)
        assert snap["generated_at"]

    def test_second_call_hits_cache(self, tmp_path: Path) -> None:
        first = watchdog.snapshot(publish=False, **self._kwargs(tmp_path))
        second = watchdog.snapshot(publish=False, **self._kwargs(tmp_path))
        assert first["cached"] is False
        assert second["cached"] is True
        assert second["generated_at"] == first["generated_at"]

    def test_force_bypasses_cache(self, tmp_path: Path) -> None:
        watchdog.snapshot(publish=False, **self._kwargs(tmp_path))
        snap = watchdog.snapshot(publish=False, force=True,
                                 **self._kwargs(tmp_path))
        assert snap["cached"] is False

    def test_zero_cache_seconds_recomputes(self, tmp_path: Path) -> None:
        watchdog.snapshot(publish=False, cache_seconds=0.0,
                          **self._kwargs(tmp_path))
        snap = watchdog.snapshot(publish=False, cache_seconds=0.0,
                                 **self._kwargs(tmp_path))
        assert snap["cached"] is False

    def test_snapshot_publishes_transitions_once(
            self, tmp_path: Path) -> None:
        kwargs = self._kwargs(tmp_path)
        # Corrupt risk-state file -> alarm -> one bus event on first
        # snapshot, none on the (forced, same-state) second.
        risk = tmp_path / "none.jsonl"
        risk.write_text("{broken\n", encoding="utf-8")
        watchdog.snapshot(**kwargs)
        assert len(alerts.recent(10)) == 1
        watchdog.snapshot(force=True, **kwargs)
        assert len(alerts.recent(10)) == 1

    def test_snapshot_publish_false_stays_silent(
            self, tmp_path: Path) -> None:
        kwargs = self._kwargs(tmp_path)
        risk = tmp_path / "none.jsonl"
        risk.write_text("{broken\n", encoding="utf-8")
        watchdog.snapshot(publish=False, **kwargs)
        assert alerts.recent(10) == []
