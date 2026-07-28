"""I017 -- squad_tape_freshness watchdog check.

Motivated by the 2026-07-15..28 weekly v2 review: the squad runtime
was silent on 8 of 10 weekdays (6 symbol-bars ingested out of ~180
expected) and nothing flagged it. ``runtime_heartbeat`` catches a dead
process; this check catches a live-but-starved one (stale MT5 feed,
terminal logged out) and a runtime nobody restarted -- by measuring
the age of ``last_bar_times`` in ``state.json`` in MARKET seconds
(Saturdays/Sundays excluded, so weekends never false-alarm).
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from agent.platform import watchdog


def _epoch(*args) -> float:
    return datetime(*args, tzinfo=timezone.utc).timestamp()


def _write_state(live_dir: Path, last_bar_times: dict | None,
                 warmup: dict | None = None, raw: str | None = None) -> None:
    path = live_dir / "state.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return
    state: dict = {"schema": 1}
    if last_bar_times is not None:
        state["last_bar_times"] = last_bar_times
    if warmup is not None:
        state["warmup"] = warmup
    path.write_text(json.dumps(state), encoding="utf-8")


class TestMarketSecondsBetween(unittest.TestCase):

    def test_same_weekday_is_wall_clock(self):
        # Wed 2026-07-22 03:00 -> 07:00 UTC = 4 h.
        t0 = _epoch(2026, 7, 22, 3)
        t1 = _epoch(2026, 7, 22, 7)
        self.assertAlmostEqual(
            watchdog._market_seconds_between(t0, t1), 4 * 3600.0)

    def test_weekend_excluded(self):
        # Fri 2026-07-24 21:00 -> Sun 2026-07-26 23:00: only the Friday
        # 21:00-24:00 slice counts (Sat + Sun excluded) = 3 h.
        t0 = _epoch(2026, 7, 24, 21)
        t1 = _epoch(2026, 7, 26, 23)
        self.assertAlmostEqual(
            watchdog._market_seconds_between(t0, t1), 3 * 3600.0)

    def test_friday_close_to_monday_open_under_warn(self):
        # Fri 23:00 last close -> Mon 03:05: 1 h Friday + 3 h 5 m Monday
        # = 4 h 5 m market time, comfortably under the warn threshold.
        t0 = _epoch(2026, 7, 24, 23)
        t1 = _epoch(2026, 7, 27, 3, 5)
        got = watchdog._market_seconds_between(t0, t1)
        self.assertAlmostEqual(got, (4 * 3600.0) + 300.0)
        self.assertLess(got, watchdog.TAPE_WARN_MARKET_SECONDS)

    def test_reversed_or_equal_is_zero(self):
        t = _epoch(2026, 7, 22, 3)
        self.assertEqual(watchdog._market_seconds_between(t, t), 0.0)
        self.assertEqual(
            watchdog._market_seconds_between(t + 60.0, t), 0.0)


class TestSquadTapeFreshness(unittest.TestCase):

    # Reference "now": Tue 2026-07-28 14:30 UTC (a weekday).
    NOW = _epoch(2026, 7, 28, 14, 30)

    def test_na_when_no_live_dir(self):
        res = watchdog.check_squad_tape_freshness(None, now=self.NOW)
        self.assertEqual(res["status"], "na")

    def test_na_when_no_state_json(self):
        with TemporaryDirectory() as td:
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "na")
        self.assertIn("state.json", res["detail"])

    def test_na_when_no_bars_ingested_yet(self):
        with TemporaryDirectory() as td:
            _write_state(Path(td), last_bar_times={})
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "na")
        self.assertIn("no bar ingested", res["detail"])

    def test_ok_when_fresh(self):
        with TemporaryDirectory() as td:
            _write_state(Path(td), {
                "EURUSD": "2026-07-28T11:00:00+00:00",
                "GBPUSD": "2026-07-28T11:00:00+00:00",
            })
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "ok")

    def test_ok_at_top_of_healthy_open_label_band(self):
        # D133 regression: last_bar_times stores bar OPEN labels, so a
        # perfectly healthy tape reads 4-8 h old right before the next
        # close. First live reading (2026-07-28) warned at 7.1 h on a
        # tape ingested an hour earlier. 7.9 h must be ok.
        with TemporaryDirectory() as td:
            _write_state(Path(td), {
                "EURUSD": "2026-07-28T06:36:00+00:00",  # 7 h 54 m old
            })
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "ok")

    def test_warn_after_one_missed_close(self):
        # 10.5 h stale on a weekday: the 8 h healthy ceiling plus one
        # missed close. Past warn (9 h), under alarm (13 h).
        with TemporaryDirectory() as td:
            _write_state(Path(td), {
                "EURUSD": "2026-07-28T04:00:00+00:00",
            })
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "warn")
        self.assertIn("EURUSD", res["detail"])

    def test_alarm_when_days_stale(self):
        # The actual 2026-07-28 incident shape: bars pinned at Jul 24
        # 07:00 while "now" is Jul 28 14:30 -> ~55 h of market time.
        with TemporaryDirectory() as td:
            _write_state(Path(td), {
                "EURUSD": "2026-07-24T07:00:00+00:00",
                "GBPUSD": "2026-07-24T07:00:00+00:00",
                "USDCAD": "2026-07-24T07:00:00+00:00",
            })
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "alarm")

    def test_weekend_gap_does_not_alarm(self):
        # Friday 23:00 last bar, checked Sunday 22:00: 1 h market time.
        sunday = _epoch(2026, 7, 26, 22)
        with TemporaryDirectory() as td:
            _write_state(Path(td), {
                "EURUSD": "2026-07-24T23:00:00+00:00",
            })
            res = watchdog.check_squad_tape_freshness(td, now=sunday)
        self.assertEqual(res["status"], "ok")

    def test_worst_symbol_wins(self):
        # One stalled pair is a real failure even if the others are
        # fresh -- that player is blind.
        with TemporaryDirectory() as td:
            _write_state(Path(td), {
                "EURUSD": "2026-07-28T11:00:00+00:00",
                "USDCAD": "2026-07-27T03:00:00+00:00",  # ~35 h market
            })
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "alarm")
        self.assertIn("USDCAD", res["detail"])

    def test_burn_in_noted_in_detail(self):
        with TemporaryDirectory() as td:
            _write_state(
                Path(td),
                {"EURUSD": "2026-07-28T11:00:00+00:00"},
                warmup={"EURUSD": {"burn_in_remaining": 2}},
            )
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "ok")
        self.assertIn("burn-in pending", res["detail"])

    def test_corrupt_state_alarms(self):
        with TemporaryDirectory() as td:
            _write_state(Path(td), None, raw="{not json")
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "alarm")

    def test_unparseable_bar_time_alarms(self):
        with TemporaryDirectory() as td:
            _write_state(Path(td), {"EURUSD": "not-a-time"})
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "alarm")
        self.assertIn("EURUSD", res["detail"])

    def test_never_raises_contract(self):
        # Directory unreadable shapes / odd payloads must degrade,
        # never raise (F017 hard rule).
        with TemporaryDirectory() as td:
            _write_state(Path(td), None, raw='["a", "list"]')
            res = watchdog.check_squad_tape_freshness(td, now=self.NOW)
        self.assertEqual(res["status"], "alarm")


class TestRegistryWiring(unittest.TestCase):

    def test_check_id_registered(self):
        self.assertIn("squad_tape_freshness", watchdog.CHECK_IDS)

    def test_run_check_dispatch(self):
        with TemporaryDirectory() as td:
            _write_state(Path(td), {
                "EURUSD": "2026-07-28T11:00:00+00:00",
            })
            res = watchdog.run_check(
                "squad_tape_freshness", live_dir=td,
                now=_epoch(2026, 7, 28, 14, 30))
        self.assertEqual(res["id"], "squad_tape_freshness")
        self.assertEqual(res["status"], "ok")

    def test_run_checks_covers_registry(self):
        with TemporaryDirectory() as td:
            results = watchdog.run_checks(live_dir=td)
        self.assertEqual([r["id"] for r in results],
                         list(watchdog.CHECK_IDS))


if __name__ == "__main__":
    unittest.main()
