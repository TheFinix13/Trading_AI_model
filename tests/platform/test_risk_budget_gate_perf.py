"""A007 (2026-07-24 audit) -- risk-gate O(today) behaviour.

Pins: the gate's `_today_losses` cache is correct across a UTC day
boundary, invalidates on a new fill, and does NOT re-parse a large
history file on a repeated call.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import credentials, risk_budget  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path)
    risk_budget.reset_state()
    yield
    risk_budget.reset_state()
    credentials._reset_state_for_tests()


def _epoch(day: str, hh: int = 12) -> float:
    dt = datetime.fromisoformat(f"{day}T{hh:02d}:00:00+00:00")
    return dt.timestamp()


class TestDayBoundary:
    def test_losses_reset_across_utc_day_roll(self) -> None:
        day1 = _epoch("2026-07-23")
        day2 = _epoch("2026-07-24")
        assert risk_budget.record_fill("EURUSD", "A1", -30.0, ts=day1)
        assert risk_budget.record_fill("EURUSD", "A1", -20.0, ts=day2)

        # Same file, different day key -> different answers.
        ok1, _ = risk_budget.can_send_order("EURUSD", "A1", 25.0, now=day1)
        assert ok1 is False  # 30 + 25 > 50 per-symbol default
        ok2, _ = risk_budget.can_send_order("EURUSD", "A1", 25.0, now=day2)
        assert ok2 is True  # 20 + 25 <= 50

    def test_remaining_budget_uses_requested_day(self) -> None:
        day1 = _epoch("2026-07-23")
        day2 = _epoch("2026-07-24")
        assert risk_budget.record_fill("EURUSD", "A1", -30.0, ts=day1)
        b1 = risk_budget.remaining_budget(now=day1)
        b2 = risk_budget.remaining_budget(now=day2)
        assert b1["per_day"]["used"] == 30.0
        assert b2["per_day"]["used"] == 0.0


class TestCacheInvalidation:
    def test_new_fill_is_seen_immediately(self) -> None:
        now = time.time()
        ok, _ = risk_budget.can_send_order("EURUSD", "A1", 45.0, now=now)
        assert ok is True
        assert risk_budget.record_fill("EURUSD", "A1", -30.0, ts=now)
        ok, reason = risk_budget.can_send_order("EURUSD", "A1", 45.0, now=now)
        assert ok is False
        assert "cap" in reason.lower()

    def test_reset_state_clears_cache(self) -> None:
        now = time.time()
        assert risk_budget.record_fill("EURUSD", "A1", -60.0, ts=now)
        assert risk_budget.can_send_order("EURUSD", "A1", 1.0,
                                          now=now)[0] is False
        risk_budget.reset_state()
        assert risk_budget.can_send_order("EURUSD", "A1", 1.0,
                                          now=now)[0] is True


class TestLargeFilePerformance:
    def test_second_gate_call_does_not_reparse(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Build a 10k-row historical fixture directly (faster than
        # 10k record_fill calls) plus one loss today.
        now = time.time()
        state = risk_budget._state_path()
        state.parent.mkdir(parents=True, exist_ok=True)
        old_day = "2026-01-15"
        rows = [json.dumps({"ts": f"{old_day}T10:00:00+00:00",
                            "symbol": "EURUSD", "strategy": "A1",
                            "pnl": -1.0})
                for _ in range(10_000)]
        rows.append(json.dumps({"ts": risk_budget._now_iso(now),
                                "symbol": "EURUSD", "strategy": "A1",
                                "pnl": -5.0}))
        state.write_text("\n".join(rows) + "\n", encoding="utf-8")

        calls = {"n": 0}
        real_iter = risk_budget._iter_state

        def _counting_iter(path):
            calls["n"] += 1
            return real_iter(path)

        monkeypatch.setattr(risk_budget, "_iter_state", _counting_iter)

        ok, _ = risk_budget.can_send_order("EURUSD", "A1", 1.0, now=now)
        assert ok is True
        assert calls["n"] == 1
        # Second (and third) gate call: cache hit, no re-parse.
        risk_budget.can_send_order("EURUSD", "A1", 1.0, now=now)
        risk_budget.remaining_budget(now=now)
        assert calls["n"] == 1

    def test_large_history_correctness(self) -> None:
        now = time.time()
        state = risk_budget._state_path()
        state.parent.mkdir(parents=True, exist_ok=True)
        rows = [json.dumps({"ts": "2026-01-15T10:00:00+00:00",
                            "symbol": "EURUSD", "strategy": "A1",
                            "pnl": -1.0})
                for _ in range(10_000)]
        rows.append(json.dumps({"ts": risk_budget._now_iso(now),
                                "symbol": "EURUSD", "strategy": "A1",
                                "pnl": -5.0}))
        state.write_text("\n".join(rows) + "\n", encoding="utf-8")

        budget = risk_budget.remaining_budget(now=now)
        # Only TODAY's 5.0 counts; the 10k historical rows do not.
        assert budget["per_day"]["used"] == 5.0
