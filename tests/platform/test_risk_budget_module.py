"""F012 -- risk_budget module tests.

Coverage (10):
1. record_fill + remaining_budget honest (round-trip).
2. UTC-day boundary -- yesterday's fill doesn't count today.
3. can_send_order (True, "ok") when everything has headroom.
4. can_send_order (False, ...) when per-day cap would be exceeded.
5. can_send_order (False, ...) when per-symbol cap exceeded.
6. can_send_order (False, ...) when per-strategy cap exceeded.
7. Config load + save round-trip (values persist).
8. Missing config file returns defaults.
9. reset_state wipes the JSONL.
10. Malformed jsonl lines are silently skipped (no exception).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
import secrets as _secrets

from pathlib import Path

import pytest

from agent.platform import credentials, risk_budget


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    yield
    credentials._reset_state_for_tests()


class TestRecordAndRemaining:
    def test_record_and_remaining_roundtrip(self) -> None:
        risk_budget.record_fill("EURUSD", "A1", -12.5)
        payload = risk_budget.remaining_budget()
        assert payload["per_day"]["used"] == 12.5
        assert payload["per_symbol"]["EURUSD"]["used"] == 12.5
        assert payload["per_strategy"]["A1"]["used"] == 12.5
        assert payload["per_day"]["remaining"] == (
            risk_budget.DEFAULT_PER_DAY_MAX_LOSS - 12.5)

    def test_positive_pnl_recorded_but_no_headroom_credit(self) -> None:
        risk_budget.record_fill("EURUSD", "A1", +10.0)  # winning fill
        payload = risk_budget.remaining_budget()
        # Wins are recorded but do NOT free up cap.
        assert payload["per_day"]["used"] == 0
        assert payload["per_day"]["remaining"] == (
            risk_budget.DEFAULT_PER_DAY_MAX_LOSS)


class TestUtcDayBoundary:
    def test_yesterdays_fill_does_not_count_today(self) -> None:
        yesterday = datetime.now(tz=timezone.utc) - timedelta(days=1)
        yts = yesterday.timestamp()
        risk_budget.record_fill("EURUSD", "A1", -80.0, ts=yts)
        payload = risk_budget.remaining_budget()
        assert payload["per_day"]["used"] == 0
        assert payload["per_day"]["remaining"] == (
            risk_budget.DEFAULT_PER_DAY_MAX_LOSS)


class TestCanSendOrder:
    def test_clean_slate_allows_reasonable_ask(self) -> None:
        ok, reason = risk_budget.can_send_order("EURUSD", "A1", 10.0)
        assert ok is True
        assert reason == "ok"

    def test_per_day_cap_blocks_ask(self) -> None:
        risk_budget.record_fill("EURUSD", "A1", -95.0)
        ok, reason = risk_budget.can_send_order("GBPUSD", "A2", 10.0)
        assert ok is False
        assert "per-day cap" in reason

    def test_per_symbol_cap_blocks_ask(self) -> None:
        risk_budget.record_fill("EURUSD", "A1", -45.0)
        ok, reason = risk_budget.can_send_order("EURUSD", "A2", 10.0)
        assert ok is False
        assert "per-symbol cap" in reason
        assert "EURUSD" in reason

    def test_per_strategy_cap_blocks_ask(self) -> None:
        risk_budget.record_fill("EURUSD", "A1", -45.0)
        ok, reason = risk_budget.can_send_order("GBPUSD", "A1", 10.0)
        assert ok is False
        assert "per-strategy cap" in reason
        assert "A1" in reason

    def test_negative_worst_case_rejected(self) -> None:
        ok, reason = risk_budget.can_send_order("EURUSD", "A1", -1.0)
        assert ok is False
        assert "invalid worst_case_loss" in reason

    def test_non_numeric_worst_case_rejected(self) -> None:
        ok, reason = risk_budget.can_send_order(
            "EURUSD", "A1", "banana")  # type: ignore[arg-type]
        assert ok is False
        assert "invalid" in reason


class TestConfig:
    def test_missing_config_returns_defaults(self) -> None:
        cfg = risk_budget.load_config()
        assert cfg["per_day"]["max_loss"] == risk_budget.DEFAULT_PER_DAY_MAX_LOSS
        assert cfg["per_symbol"]["default"] == risk_budget.DEFAULT_PER_SYMBOL_MAX_LOSS

    def test_save_and_load_roundtrip(self) -> None:
        assert risk_budget.save_config({
            "per_day": {"max_loss": 250.0},
            "per_symbol": {"default": 60.0, "EURUSD": 80.0},
            "per_strategy": {"default": 40.0, "A1_baseline": 90.0},
        }) is True
        cfg = risk_budget.load_config()
        assert cfg["per_day"]["max_loss"] == 250.0
        assert cfg["per_symbol"]["EURUSD"] == 80.0
        assert cfg["per_strategy"]["A1_baseline"] == 90.0

    def test_saved_cap_used_by_can_send_order(self) -> None:
        risk_budget.save_config({"per_day": {"max_loss": 30.0}})
        ok, reason = risk_budget.can_send_order("EURUSD", "A1", 40.0)
        assert ok is False
        assert "per-day cap" in reason


class TestStateHandling:
    def test_reset_state_wipes_jsonl(self) -> None:
        risk_budget.record_fill("EURUSD", "A1", -20.0)
        risk_budget.reset_state()
        payload = risk_budget.remaining_budget()
        assert payload["per_day"]["used"] == 0

    def test_malformed_jsonl_skipped(self, tmp_path: Path) -> None:
        risk_budget.record_fill("EURUSD", "A1", -10.0)
        state_path = credentials._config_dir() / risk_budget.STATE_FILENAME
        with state_path.open("a", encoding="utf-8") as fh:
            fh.write("{not-json}\n")
            fh.write("\n")
        payload = risk_budget.remaining_budget()
        assert payload["per_day"]["used"] == 10.0
