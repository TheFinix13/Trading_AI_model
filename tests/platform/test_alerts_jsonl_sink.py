"""F023 -- optional JSONL sink for the alerts bus (I010).

Acceptance pins:

- Default OFF: with the sink unconfigured, publish() writes nothing to
  disk -- behaviour byte-identical to F014.
- Opt-in persistence: sink on -> publish -> the event survives a
  simulated restart (bus reset drops the ring; the file keeps it).
- Failure isolation: an unwritable sink leaves publish() returning
  normally and consumers receiving the event; ONE warning per process.
- Append format: one sorted-key JSON object per line, carrying the
  same id/type/ts/payload the ring buffer holds.
- Config wiring: [alerts] jsonl_sink is literal-true opt-in;
  max_sse_streams parses positive ints only.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import alerts, credentials  # noqa: E402
from agent.platform.config import load_config  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    alerts.reset()
    yield
    alerts.reset()


class TestDefaultOff:
    def test_sink_disabled_by_default(self):
        assert alerts.sink_is_enabled() is False

    def test_publish_writes_nothing_when_off(self, tmp_path):
        sink = tmp_path / "alerts_log.jsonl"
        # Even with a path configured, enabled=False writes nothing.
        alerts.configure_sink(False, path=sink)
        alerts.publish("trade_fill", {"symbol": "EURUSD"})
        assert not sink.exists()

    def test_only_literal_true_enables(self, tmp_path):
        sink = tmp_path / "alerts_log.jsonl"
        for junk in (1, "true", "yes", [True]):
            alerts.configure_sink(junk, path=sink)
            assert alerts.sink_is_enabled() is False
        alerts.publish("trade_fill", {})
        assert not sink.exists()


class TestOptInPersistence:
    def test_publish_appends_to_disk(self, tmp_path):
        sink = tmp_path / "alerts_log.jsonl"
        alerts.configure_sink(True, path=sink)
        ev1 = alerts.publish("trade_fill", {"symbol": "EURUSD"})
        ev2 = alerts.publish("kill_switch_trip", {"scope": "GLOBAL"})
        lines = sink.read_text(encoding="utf-8").strip().splitlines()
        assert [json.loads(l)["id"] for l in lines] == [ev1["id"],
                                                        ev2["id"]]

    def test_event_survives_simulated_restart(self, tmp_path):
        sink = tmp_path / "alerts_log.jsonl"
        alerts.configure_sink(True, path=sink)
        ev = alerts.publish("kill_switch_trip", {"scope": "GLOBAL"})
        # Simulated crash/restart: the in-process bus state is gone...
        alerts.reset()
        assert alerts.recent() == []
        # ...but the sink kept the evidence trail.
        row = json.loads(sink.read_text(encoding="utf-8").splitlines()[0])
        assert row["id"] == ev["id"]
        assert row["type"] == "kill_switch_trip"
        assert row["payload"] == {"scope": "GLOBAL"}

    def test_line_format_matches_ring_event(self, tmp_path):
        sink = tmp_path / "alerts_log.jsonl"
        alerts.configure_sink(True, path=sink)
        ev = alerts.publish("stop_hit", {"symbol": "GBPUSD"}, ts=1_800_000_000.0)
        row = json.loads(sink.read_text(encoding="utf-8").splitlines()[0])
        assert row == ev

    def test_parent_dir_created(self, tmp_path):
        sink = tmp_path / "nested" / "dir" / "alerts_log.jsonl"
        alerts.configure_sink(True, path=sink)
        alerts.publish("trade_fill", {})
        assert sink.is_file()

    def test_default_path_rides_config_dir_seam(self, tmp_path):
        credentials.set_config_dir(tmp_path / "cfg")
        try:
            alerts.configure_sink(True)
            assert alerts.sink_path() == \
                credentials._config_dir() / alerts.SINK_FILENAME
            assert str(alerts.sink_path()).startswith(
                str(tmp_path / "cfg"))
        finally:
            credentials.set_config_dir(None)


class TestFailureIsolation:
    def test_unwritable_sink_never_breaks_publish(self, tmp_path):
        # A directory at the sink path makes every open("a") fail.
        bad = tmp_path / "alerts_log.jsonl"
        bad.mkdir()
        alerts.configure_sink(True, path=bad)
        received: list[dict] = []
        alerts.subscribe(lambda ev: received.append(ev))
        ev = alerts.publish("trade_fill", {"symbol": "EURUSD"})
        # publish() returned normally, the consumer got the event, and
        # the ring buffer holds it.
        assert received == [ev]
        assert alerts.recent(1)[0]["id"] == ev["id"]

    def test_failure_warns_once_per_process(self, tmp_path, caplog):
        bad = tmp_path / "alerts_log.jsonl"
        bad.mkdir()
        alerts.configure_sink(True, path=bad)
        with caplog.at_level(logging.WARNING,
                             logger="agent.platform.alerts"):
            alerts.publish("trade_fill", {})
            alerts.publish("stop_hit", {})
        warnings = [r for r in caplog.records
                    if "sink write failed" in r.getMessage()]
        assert len(warnings) == 1

    def test_reconfigure_rearms_the_warning(self, tmp_path, caplog):
        bad = tmp_path / "alerts_log.jsonl"
        bad.mkdir()
        alerts.configure_sink(True, path=bad)
        with caplog.at_level(logging.WARNING,
                             logger="agent.platform.alerts"):
            alerts.publish("trade_fill", {})
            alerts.configure_sink(True, path=bad)
            alerts.publish("trade_fill", {})
        warnings = [r for r in caplog.records
                    if "sink write failed" in r.getMessage()]
        assert len(warnings) == 2


class TestConfigWiring:
    def test_defaults(self, tmp_path):
        cfg = load_config(tmp_path)
        assert cfg["alerts"]["jsonl_sink"] is False
        assert cfg["alerts"]["max_sse_streams"] == 8

    def test_literal_true_opt_in(self, tmp_path):
        (tmp_path / "platform.toml").write_text(
            "[alerts]\njsonl_sink = true\n", encoding="utf-8")
        assert load_config(tmp_path)["alerts"]["jsonl_sink"] is True

    def test_non_boolean_sink_value_stays_off(self, tmp_path):
        (tmp_path / "platform.toml").write_text(
            '[alerts]\njsonl_sink = "yes"\n', encoding="utf-8")
        assert load_config(tmp_path)["alerts"]["jsonl_sink"] is False

    def test_max_sse_streams_positive_int(self, tmp_path):
        (tmp_path / "platform.toml").write_text(
            "[alerts]\nmax_sse_streams = 3\n", encoding="utf-8")
        assert load_config(tmp_path)["alerts"]["max_sse_streams"] == 3

    def test_max_sse_streams_rejects_nonpositive(self, tmp_path):
        for bad in ("0", "-2", '"many"'):
            (tmp_path / "platform.toml").write_text(
                f"[alerts]\nmax_sse_streams = {bad}\n", encoding="utf-8")
            assert load_config(tmp_path)["alerts"]["max_sse_streams"] == 8

    def test_alerts_table_still_parses_telegram_block(self, tmp_path):
        (tmp_path / "platform.toml").write_text(
            "[alerts]\njsonl_sink = true\n"
            "[alerts.telegram]\nenabled = true\n", encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg["alerts"]["jsonl_sink"] is True
        assert cfg["alerts"]["telegram"]["enabled"] is True
