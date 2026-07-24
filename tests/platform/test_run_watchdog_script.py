"""F017 -- scripts/run_watchdog.py: exit codes, output, loop mode."""
from __future__ import annotations

import json
import secrets as _secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import alerts, credentials, watchdog  # noqa: E402
from scripts import run_watchdog  # noqa: E402


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


def _fake_results(*statuses: str) -> list[dict]:
    return [{"id": cid, "status": st, "detail": f"{cid} fixture",
             "checked_at": "2026-07-24T00:00:00Z"}
            for cid, st in zip(watchdog.CHECK_IDS, statuses)]


@pytest.fixture()
def pin_checks(monkeypatch: pytest.MonkeyPatch):
    """Pin watchdog.run_checks to a fixed registry result so the
    script's exit code is deterministic regardless of repo state."""
    def _pin(*statuses: str) -> None:
        results = _fake_results(*statuses)
        monkeypatch.setattr(watchdog, "run_checks",
                            lambda **kwargs: results)
    return _pin


class TestExitCodes:
    def test_all_ok_exits_zero(self, pin_checks) -> None:
        pin_checks("ok", "ok", "na", "ok", "ok", "na", "ok")
        assert run_watchdog.run_once(None, log=lambda *_: None) == 0

    def test_warn_exits_one(self, pin_checks) -> None:
        pin_checks("ok", "warn", "na", "ok", "ok", "na", "ok")
        assert run_watchdog.run_once(None, log=lambda *_: None) == 1

    def test_alarm_exits_two(self, pin_checks) -> None:
        pin_checks("ok", "warn", "na", "alarm", "ok", "na", "ok")
        assert run_watchdog.run_once(None, log=lambda *_: None) == 2

    def test_all_na_exits_zero(self, pin_checks) -> None:
        pin_checks("na", "na", "na", "na", "na", "na", "na")
        assert run_watchdog.run_once(None, log=lambda *_: None) == 0


class TestOutput:
    def test_plain_output_one_line_per_check(self, pin_checks) -> None:
        pin_checks("ok", "ok", "na", "ok", "ok", "na", "ok")
        lines: list[str] = []
        run_watchdog.run_once(None, log=lines.append)
        check_lines = [ln for ln in lines if ln.startswith("[")]
        assert len(check_lines) == len(watchdog.CHECK_IDS)
        assert any(ln.startswith("overall:") for ln in lines)

    def test_json_output_parses(self, pin_checks) -> None:
        pin_checks("ok", "warn", "na", "ok", "ok", "na", "ok")
        lines: list[str] = []
        run_watchdog.run_once(None, as_json=True, log=lines.append)
        payload = json.loads("\n".join(lines))
        assert payload["overall"] == "warn"
        assert len(payload["checks"]) == len(watchdog.CHECK_IDS)
        assert "published_transitions" in payload

    def test_transitions_published_to_bus(self, pin_checks) -> None:
        pin_checks("ok", "ok", "na", "alarm", "ok", "na", "ok")
        run_watchdog.run_once(None, log=lambda *_: None)
        events = alerts.recent(5)
        assert len(events) == 1
        assert events[0]["type"] == "watchdog_alert"
        assert events[0]["payload"]["check"] == "risk_state"

    def test_repeat_run_publishes_nothing_new(self, pin_checks) -> None:
        pin_checks("ok", "ok", "na", "alarm", "ok", "na", "ok")
        run_watchdog.run_once(None, log=lambda *_: None)
        run_watchdog.run_once(None, log=lambda *_: None)
        assert len(alerts.recent(5)) == 1


class TestMain:
    @pytest.fixture(autouse=True)
    def _pin_config(self, monkeypatch: pytest.MonkeyPatch,
                    tmp_path: Path):
        monkeypatch.setattr(
            run_watchdog, "load_config",
            lambda root: {"live_dir": tmp_path / "sq",
                          "alerts": {"telegram": {"enabled": False}},
                          "telegram": {}})

    def test_one_shot_returns_worst_code(
            self, pin_checks, capsys: pytest.CaptureFixture) -> None:
        pin_checks("ok", "ok", "na", "ok", "ok", "na", "ok")
        assert run_watchdog.main([]) == 0
        assert "overall: ok" in capsys.readouterr().out

    def test_loop_bounded_by_max_iterations(
            self, pin_checks, monkeypatch: pytest.MonkeyPatch,
            capsys: pytest.CaptureFixture) -> None:
        pin_checks("ok", "ok", "na", "ok", "ok", "na", "ok")
        sleeps: list[float] = []
        monkeypatch.setattr(run_watchdog.time, "sleep", sleeps.append)
        assert run_watchdog.main(
            ["--loop", "1", "--max-iterations", "2"]) == 0
        out = capsys.readouterr().out
        assert out.count("overall:") == 2
        assert len(sleeps) == 1  # sleeps between passes, not after last

    def test_loop_writes_heartbeat_file(
            self, pin_checks, monkeypatch: pytest.MonkeyPatch,
            capsys: pytest.CaptureFixture) -> None:
        pin_checks("ok", "ok", "na", "ok", "ok", "na", "ok")
        monkeypatch.setattr(run_watchdog.time, "sleep", lambda s: None)
        run_watchdog.main(["--loop", "1", "--max-iterations", "1"])
        hb = credentials._config_dir() / run_watchdog.HEARTBEAT_FILENAME
        assert hb.is_file()
        assert hb.read_text(encoding="utf-8").strip()

    def test_loop_returns_worst_code_seen(
            self, monkeypatch: pytest.MonkeyPatch,
            capsys: pytest.CaptureFixture) -> None:
        # First pass alarms, second recovers -- exit reflects the worst.
        passes = [
            _fake_results("ok", "ok", "na", "alarm", "ok", "na", "ok"),
            _fake_results("ok", "ok", "na", "ok", "ok", "na", "ok"),
        ]
        monkeypatch.setattr(watchdog, "run_checks",
                            lambda **kwargs: passes.pop(0))
        monkeypatch.setattr(run_watchdog.time, "sleep", lambda s: None)
        assert run_watchdog.main(
            ["--loop", "1", "--max-iterations", "2"]) == 2
