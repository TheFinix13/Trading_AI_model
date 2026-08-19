"""F025 B1 -- the approval driver (refusal-window clock).

The driver exists because `timeout_reap` is lazy. Without it a
30-minute refusal window would resolve whenever an HTTP request next
touched the queue, so proposals would fire when the operator opened the
dashboard and never while the machine was unattended.

These tests drive `tick()` directly rather than waiting on wall-clock,
and stub the executor so nothing reaches a broker adapter.
"""
from __future__ import annotations

import secrets as _secrets
import time as _time

from pathlib import Path

import pytest

from agent.platform import (
    approval_driver, approval_queue, credentials, live_executor)


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    approval_queue.reset_state()
    approval_queue.set_timeout_seconds(1)
    yield
    approval_driver.stop()
    credentials._reset_state_for_tests()
    approval_queue.reset_state()


def _payload(**over) -> dict:
    base = {
        "symbol": "EURUSD",
        "side": "buy",
        "size": 0.08,
        "entry": 1.0850,
        "stop": 1.0820,
        "take_profit": 1.0920,
        "rationale": "driver test",
        "source_agent": "A1_baseline",
        "risk_snapshot": {"worst_case_loss": 24.0},
    }
    base.update(over)
    return base


@pytest.fixture
def sent(monkeypatch) -> list[str]:
    """Record every approval_id handed to the executor."""
    calls: list[str] = []

    def _fake(approval_id, adapter, cfg=None):
        calls.append(approval_id)
        return {"ok": True, "status": "filled", "approval_id": approval_id}

    monkeypatch.setattr(live_executor, "execute_approved", _fake)
    return calls


def _stub_adapter():
    return object()


class TestOnlyAutoApprovedIsSent:
    def test_auto_approved_entry_is_executed(self, sent) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        aid = approval_queue.submit(_payload())
        approval_queue.set_timeout_seconds(1)
        _time.sleep(1.1)
        results = approval_driver.tick(adapter_factory=_stub_adapter)
        assert sent == [aid]
        assert results[0]["status"] == "filled"

    def test_timed_out_entry_is_not_executed(self, sent) -> None:
        """Auto-execution off: the reap discards, and the driver must
        not treat a discard as a send."""
        assert approval_queue.get_auto_execute_on_timeout() is False
        approval_queue.submit(_payload())
        _time.sleep(1.1)
        approval_driver.tick(adapter_factory=_stub_adapter)
        assert sent == []

    def test_pending_inside_window_is_not_executed(self, sent) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        approval_queue.set_timeout_seconds(1800)
        approval_queue.submit(_payload())
        approval_driver.tick(adapter_factory=_stub_adapter)
        assert sent == []

    def test_rejected_entry_is_not_executed(self, sent) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        approval_queue.set_timeout_seconds(1800)
        aid = approval_queue.submit(_payload())
        approval_queue.reject(aid, "no thanks")
        approval_driver.tick(adapter_factory=_stub_adapter)
        assert sent == []

    def test_empty_queue_is_a_cheap_noop(self, sent) -> None:
        assert approval_driver.tick(adapter_factory=_stub_adapter) == []
        assert sent == []


class TestOneBadEntryDoesNotStrandTheRest:
    def test_exception_is_contained_and_later_entries_still_send(
            self, monkeypatch) -> None:
        """A raising executor must not kill the driver -- that would
        leave every later proposal in `pending` with no clock."""
        seen: list[str] = []

        def _explode(approval_id, adapter, cfg=None):
            seen.append(approval_id)
            if len(seen) == 1:
                raise RuntimeError("broker connection reset")
            return {"ok": True, "status": "filled",
                    "approval_id": approval_id}

        monkeypatch.setattr(live_executor, "execute_approved", _explode)
        approval_queue.set_auto_execute_on_timeout(True)
        approval_queue.submit(_payload())
        approval_queue.submit(_payload(symbol="GBPUSD"))
        _time.sleep(1.1)
        results = approval_driver.tick(adapter_factory=_stub_adapter)
        assert len(seen) == 2
        statuses = {r["status"] for r in results}
        assert "driver_error" in statuses
        assert "filled" in statuses

    def test_driver_error_is_reported_not_swallowed(self, monkeypatch) -> None:
        def _explode(approval_id, adapter, cfg=None):
            raise RuntimeError("boom")

        monkeypatch.setattr(live_executor, "execute_approved", _explode)
        approval_queue.set_auto_execute_on_timeout(True)
        aid = approval_queue.submit(_payload())
        _time.sleep(1.1)
        results = approval_driver.tick(adapter_factory=_stub_adapter)
        assert results == [{"ok": False, "approval_id": aid,
                            "status": "driver_error"}]


class TestThreadLifecycle:
    def test_start_is_idempotent(self) -> None:
        assert approval_driver.start(tick_seconds=60,
                                    adapter_factory=_stub_adapter) is True
        assert approval_driver.start(tick_seconds=60,
                                    adapter_factory=_stub_adapter) is False
        assert approval_driver.is_running() is True

    def test_stop_halts_the_thread(self) -> None:
        approval_driver.start(tick_seconds=60,
                              adapter_factory=_stub_adapter)
        approval_driver.stop()
        assert approval_driver.is_running() is False

    def test_not_running_before_start(self) -> None:
        assert approval_driver.is_running() is False

    def test_thread_actually_fires_a_tick(self, sent) -> None:
        """End-to-end on the real clock: submit, wait, and the entry
        should execute without anyone touching the queue."""
        approval_queue.set_auto_execute_on_timeout(True)
        approval_queue.set_timeout_seconds(1)
        aid = approval_queue.submit(_payload())
        approval_driver.start(tick_seconds=1, adapter_factory=_stub_adapter)
        deadline = _time.time() + 10
        while _time.time() < deadline and not sent:
            _time.sleep(0.2)
        approval_driver.stop()
        assert sent == [aid]
