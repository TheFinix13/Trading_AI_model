"""F017 -- watchdog check registry: ok / warn / alarm / na per check."""
from __future__ import annotations

import json
import os
import secrets as _secrets
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import credentials, watchdog  # noqa: E402


NOW = 1_800_000_000.0  # fixed epoch for deterministic ages


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    watchdog.reset_cache_for_tests()
    yield
    credentials._reset_state_for_tests()
    watchdog.reset_cache_for_tests()


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


# ---------------------------------------------------------------------
# runtime_heartbeat
# ---------------------------------------------------------------------

class TestRuntimeHeartbeat:
    def test_na_when_not_configured(self) -> None:
        r = watchdog.check_runtime_heartbeat(None)
        assert r["status"] == "na"
        assert r["id"] == "runtime_heartbeat"

    def test_na_when_dir_never_created(self, tmp_path: Path) -> None:
        r = watchdog.check_runtime_heartbeat(tmp_path / "nope")
        assert r["status"] == "na"

    def test_na_when_dir_empty(self, tmp_path: Path) -> None:
        live = tmp_path / "live"
        live.mkdir()
        r = watchdog.check_runtime_heartbeat(live)
        assert r["status"] == "na"
        assert "artefact" in r["detail"]

    def _live_with_heartbeat(self, tmp_path: Path, age_s: float) -> Path:
        live = tmp_path / "live"
        live.mkdir(exist_ok=True)
        hb = live / "poll_heartbeat.txt"
        hb.write_text("beat", encoding="utf-8")
        stamp = time.time() - age_s
        os.utime(hb, (stamp, stamp))
        return live

    def test_ok_when_fresh(self, tmp_path: Path) -> None:
        live = self._live_with_heartbeat(tmp_path, age_s=10)
        r = watchdog.check_runtime_heartbeat(live)
        assert r["status"] == "ok"

    def test_warn_when_older_than_5_minutes(self, tmp_path: Path) -> None:
        live = self._live_with_heartbeat(tmp_path, age_s=6 * 60)
        r = watchdog.check_runtime_heartbeat(live)
        assert r["status"] == "warn"

    def test_alarm_when_older_than_30_minutes(self, tmp_path: Path) -> None:
        live = self._live_with_heartbeat(tmp_path, age_s=31 * 60)
        r = watchdog.check_runtime_heartbeat(live)
        assert r["status"] == "alarm"

    def test_warn_when_kill_file_present(self, tmp_path: Path) -> None:
        live = self._live_with_heartbeat(tmp_path, age_s=10)
        (live / "kill.txt").write_text("manual stop", encoding="utf-8")
        r = watchdog.check_runtime_heartbeat(live)
        assert r["status"] == "warn"
        assert "kill" in r["detail"].lower()


# ---------------------------------------------------------------------
# calendar_feed
# ---------------------------------------------------------------------

class TestCalendarFeed:
    def _cache(self, tmp_path: Path, fetched_age_s: float) -> Path:
        path = tmp_path / "news_calendar.json"
        path.write_text(json.dumps({
            "fetched_at": _iso(NOW - fetched_age_s),
            "events": [],
        }), encoding="utf-8")
        return path

    def test_na_when_absent(self, tmp_path: Path) -> None:
        r = watchdog.check_calendar_feed(tmp_path / "missing.json", now=NOW)
        assert r["status"] == "na"

    def test_ok_when_fresh(self, tmp_path: Path) -> None:
        r = watchdog.check_calendar_feed(
            self._cache(tmp_path, 3600), now=NOW)
        assert r["status"] == "ok"

    def test_warn_after_12_hours(self, tmp_path: Path) -> None:
        r = watchdog.check_calendar_feed(
            self._cache(tmp_path, 13 * 3600), now=NOW)
        assert r["status"] == "warn"

    def test_alarm_after_48_hours(self, tmp_path: Path) -> None:
        r = watchdog.check_calendar_feed(
            self._cache(tmp_path, 49 * 3600), now=NOW)
        assert r["status"] == "alarm"

    def test_alarm_on_corrupt_json(self, tmp_path: Path) -> None:
        path = tmp_path / "news_calendar.json"
        path.write_text("{nope", encoding="utf-8")
        r = watchdog.check_calendar_feed(path, now=NOW)
        assert r["status"] == "alarm"

    def test_alarm_when_fetched_at_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "news_calendar.json"
        path.write_text(json.dumps({"events": []}), encoding="utf-8")
        r = watchdog.check_calendar_feed(path, now=NOW)
        assert r["status"] == "alarm"


# ---------------------------------------------------------------------
# broker_health
# ---------------------------------------------------------------------

class TestBrokerHealth:
    def test_na_when_no_aliases(self) -> None:
        r = watchdog.check_broker_health()
        assert r["status"] == "na"

    def test_warn_when_probed_alias_down(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            watchdog.broker_health, "list_health_states",
            lambda: [{"alias": "demo1", "alive": False,
                      "reason": "MT5 init failed",
                      "checked_at": "2026-07-24T00:00:00+00:00"}])
        r = watchdog.check_broker_health()
        assert r["status"] == "warn"
        assert "demo1" in r["detail"]

    def test_ok_when_alias_saved_but_never_probed(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            watchdog.broker_health, "list_health_states",
            lambda: [{"alias": "demo1", "alive": False,
                      "reason": "not yet probed", "checked_at": None}])
        r = watchdog.check_broker_health()
        assert r["status"] == "ok"
        assert "none probed yet" in r["detail"]

    def test_ok_when_all_alive(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            watchdog.broker_health, "list_health_states",
            lambda: [{"alias": "demo1", "alive": True, "reason": "ok",
                      "checked_at": "2026-07-24T00:00:00+00:00"}])
        r = watchdog.check_broker_health()
        assert r["status"] == "ok"

    def test_alarm_when_probe_machinery_raises(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom():
            raise RuntimeError("keychain exploded")
        monkeypatch.setattr(
            watchdog.broker_health, "list_health_states", _boom)
        r = watchdog.check_broker_health()
        assert r["status"] == "alarm"


# ---------------------------------------------------------------------
# risk_state
# ---------------------------------------------------------------------

class TestRiskState:
    def test_na_when_absent(self, tmp_path: Path) -> None:
        r = watchdog.check_risk_state(tmp_path / "risk_state.jsonl",
                                      now=NOW)
        assert r["status"] == "na"

    def test_ok_with_valid_rows(self, tmp_path: Path) -> None:
        path = tmp_path / "risk_state.jsonl"
        path.write_text(
            json.dumps({"ts": _iso(NOW - 60), "symbol": "EURUSD",
                        "strategy": "A1", "pnl": -3.0}) + "\n",
            encoding="utf-8")
        r = watchdog.check_risk_state(path, now=NOW)
        assert r["status"] == "ok"
        assert "1 fill row" in r["detail"]

    def test_alarm_on_corrupt_line(self, tmp_path: Path) -> None:
        path = tmp_path / "risk_state.jsonl"
        path.write_text('{"ts": "2026-01-01T00:00:00Z"}\n{broken\n',
                        encoding="utf-8")
        r = watchdog.check_risk_state(path, now=NOW)
        assert r["status"] == "alarm"
        assert "line 2" in r["detail"]

    def test_alarm_on_future_dated_row(self, tmp_path: Path) -> None:
        path = tmp_path / "risk_state.jsonl"
        path.write_text(
            json.dumps({"ts": _iso(NOW + 3600), "pnl": -1.0}) + "\n",
            encoding="utf-8")
        r = watchdog.check_risk_state(path, now=NOW)
        assert r["status"] == "alarm"
        assert "future-dated" in r["detail"]

    def test_small_clock_skew_tolerated(self, tmp_path: Path) -> None:
        path = tmp_path / "risk_state.jsonl"
        path.write_text(
            json.dumps({"ts": _iso(NOW + 30), "pnl": -1.0}) + "\n",
            encoding="utf-8")
        r = watchdog.check_risk_state(path, now=NOW)
        assert r["status"] == "ok"


# ---------------------------------------------------------------------
# intake_sla
# ---------------------------------------------------------------------

def _intake_item(directory: Path, item_id: str, *, priority: str,
                 status: str, age_s: float) -> None:
    (directory / f"{item_id}-fixture.md").write_text(
        "---\n"
        f"id: {item_id}\n"
        "source: dogfood\n"
        f"submitted_at: {_iso(NOW - age_s)}\n"
        f"priority: {priority}\n"
        f"status: {status}\n"
        "---\n\n# fixture\n", encoding="utf-8")


class TestIntakeSla:
    def test_na_when_no_dir(self, tmp_path: Path) -> None:
        r = watchdog.check_intake_sla(tmp_path / "nope", now=NOW)
        assert r["status"] == "na"

    def test_ok_inside_sla(self, tmp_path: Path) -> None:
        _intake_item(tmp_path, "I900", priority="P0", status="filed",
                     age_s=1800)
        _intake_item(tmp_path, "I901", priority="P1", status="routed",
                     age_s=86400)
        r = watchdog.check_intake_sla(tmp_path, now=NOW)
        assert r["status"] == "ok"

    def test_alarm_p0_untriaged_past_4_hours(self, tmp_path: Path) -> None:
        _intake_item(tmp_path, "I902", priority="P0", status="filed",
                     age_s=5 * 3600)
        r = watchdog.check_intake_sla(tmp_path, now=NOW)
        assert r["status"] == "alarm"
        assert "I902" in r["detail"]

    def test_warn_p1_untriaged_past_7_days(self, tmp_path: Path) -> None:
        _intake_item(tmp_path, "I903", priority="P1", status="new",
                     age_s=8 * 86400)
        r = watchdog.check_intake_sla(tmp_path, now=NOW)
        assert r["status"] == "warn"
        assert "I903" in r["detail"]

    def test_warn_any_open_item_past_30_days(self, tmp_path: Path) -> None:
        _intake_item(tmp_path, "I904", priority="P2", status="routed",
                     age_s=31 * 86400)
        r = watchdog.check_intake_sla(tmp_path, now=NOW)
        assert r["status"] == "warn"
        assert "30d" in r["detail"]

    def test_closed_items_never_flag(self, tmp_path: Path) -> None:
        _intake_item(tmp_path, "I905", priority="P0", status="resolved",
                     age_s=90 * 86400)
        r = watchdog.check_intake_sla(tmp_path, now=NOW)
        assert r["status"] == "ok"

    def test_alarm_beats_warn(self, tmp_path: Path) -> None:
        _intake_item(tmp_path, "I906", priority="P0", status="filed",
                     age_s=5 * 3600)
        _intake_item(tmp_path, "I907", priority="P1", status="filed",
                     age_s=8 * 86400)
        r = watchdog.check_intake_sla(tmp_path, now=NOW)
        assert r["status"] == "alarm"


# ---------------------------------------------------------------------
# sprint_pulse + ledger_drift
# ---------------------------------------------------------------------

def _ledger(tmp_path: Path, *, verdict: str = "in_progress",
            decision_dates: list[str] | None = None) -> Path:
    path = tmp_path / "company_state.json"
    path.write_text(json.dumps({
        "sprints": [{"id": "sprint-x", "verdict": verdict}],
        "decisions": [{"id": f"D{i:03d}", "date": d}
                      for i, d in enumerate(decision_dates or [], 1)],
    }), encoding="utf-8")
    return path


class TestSprintPulse:
    def test_na_when_no_ledger(self, tmp_path: Path) -> None:
        r = watchdog.check_sprint_pulse(tmp_path / "nope.json", now=NOW)
        assert r["status"] == "na"

    def test_na_when_no_in_progress_sprint(self, tmp_path: Path) -> None:
        path = _ledger(tmp_path, verdict="COMPLETE",
                       decision_dates=["2026-01-01"])
        r = watchdog.check_sprint_pulse(path, now=NOW)
        assert r["status"] == "na"

    def test_ok_with_recent_decision(self, tmp_path: Path) -> None:
        fresh = time.strftime("%Y-%m-%d", time.gmtime(NOW - 86400))
        path = _ledger(tmp_path, decision_dates=[fresh])
        r = watchdog.check_sprint_pulse(path, now=NOW)
        assert r["status"] == "ok"

    def test_warn_when_quiet_past_7_days(self, tmp_path: Path) -> None:
        stale = time.strftime("%Y-%m-%d", time.gmtime(NOW - 9 * 86400))
        path = _ledger(tmp_path, decision_dates=[stale])
        r = watchdog.check_sprint_pulse(path, now=NOW)
        assert r["status"] == "warn"
        assert "sprint-x" in r["detail"]

    def test_warn_when_no_decisions_at_all(self, tmp_path: Path) -> None:
        path = _ledger(tmp_path, decision_dates=[])
        r = watchdog.check_sprint_pulse(path, now=NOW)
        assert r["status"] == "warn"


class TestLedgerDrift:
    def _pair(self, tmp_path: Path, json_n: int, md_n: int) -> tuple[Path, Path]:
        jp = tmp_path / "company_state.json"
        jp.write_text(json.dumps({
            "decisions": [{"id": f"D{i:03d}"} for i in range(1, json_n + 1)],
        }), encoding="utf-8")
        mp = tmp_path / "decisions_log.md"
        mp.write_text("\n".join(
            f"## D{i:03d} · 2026-07-24 · ceo · [TEST]\n\nbody\n"
            for i in range(1, md_n + 1)), encoding="utf-8")
        return jp, mp

    def test_ok_when_counts_match(self, tmp_path: Path) -> None:
        jp, mp = self._pair(tmp_path, 3, 3)
        r = watchdog.check_ledger_drift(jp, mp)
        assert r["status"] == "ok"

    def test_alarm_on_mismatch(self, tmp_path: Path) -> None:
        jp, mp = self._pair(tmp_path, 3, 2)
        r = watchdog.check_ledger_drift(jp, mp)
        assert r["status"] == "alarm"
        assert "JSON=3" in r["detail"] and "MD=2" in r["detail"]

    def test_alarm_when_one_file_missing(self, tmp_path: Path) -> None:
        jp, _ = self._pair(tmp_path, 1, 1)
        r = watchdog.check_ledger_drift(jp, tmp_path / "nope.md")
        assert r["status"] == "alarm"

    def test_na_when_both_missing(self, tmp_path: Path) -> None:
        r = watchdog.check_ledger_drift(tmp_path / "a.json",
                                        tmp_path / "b.md")
        assert r["status"] == "na"

    def test_alarm_on_malformed_json(self, tmp_path: Path) -> None:
        jp = tmp_path / "company_state.json"
        jp.write_text("{broken", encoding="utf-8")
        mp = tmp_path / "decisions_log.md"
        mp.write_text("## D001 · x · y · [Z]\n", encoding="utf-8")
        r = watchdog.check_ledger_drift(jp, mp)
        assert r["status"] == "alarm"

    def test_real_repo_ledger_is_in_sync(self) -> None:
        """The shipped ledger must never drift -- this is the check's
        own dogfood."""
        r = watchdog.check_ledger_drift()
        assert r["status"] == "ok", r["detail"]


# ---------------------------------------------------------------------
# registry runners
# ---------------------------------------------------------------------

class TestRegistry:
    def test_run_checks_covers_all_ids_in_order(self, tmp_path: Path) -> None:
        results = watchdog.run_checks(
            live_dir=None,
            calendar_cache_path=tmp_path / "none.json",
            risk_state_path=tmp_path / "none.jsonl",
            intake_dir=tmp_path / "none",
            ledger_json_path=tmp_path / "none.json",
            ledger_md_path=tmp_path / "none.md",
            now=NOW)
        assert [r["id"] for r in results] == list(watchdog.CHECK_IDS)
        for r in results:
            assert r["status"] in watchdog.STATUSES
            assert r["checked_at"]

    def test_run_check_unknown_id_raises(self) -> None:
        with pytest.raises(ValueError):
            watchdog.run_check("nope")

    def test_overall_status_ranking(self) -> None:
        ok = {"status": "ok"}
        na = {"status": "na"}
        warn = {"status": "warn"}
        alarm = {"status": "alarm"}
        assert watchdog.overall_status([ok, na]) == "ok"
        assert watchdog.overall_status([ok, warn]) == "warn"
        assert watchdog.overall_status([warn, alarm]) == "alarm"
        assert watchdog.overall_status([]) == "ok"
