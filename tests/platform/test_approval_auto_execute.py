"""F025 B1 -- right-of-first-refusal auto-execution.

Enabling `auto_execute_on_timeout` inverts the meaning of operator
inaction: an ignored proposal becomes an order instead of a discard.
That is a safety-relevant inversion, so the tests here pin both
directions -- what the flag changes, and (more importantly) what it must
NOT change.

The load-bearing ones are `TestAuditAttribution` (the audit trail must
never record a machine decision as a human one) and
`TestAutoPathDoesNotBypassGates` (auto-approval opens gate #4 only; the
other three still refuse).
"""
from __future__ import annotations

import json
import secrets as _secrets
import time as _time

from pathlib import Path

import pytest

from agent.platform import approval_queue, credentials


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    approval_queue.reset_state()
    approval_queue.set_timeout_seconds(1)
    yield
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
        "rationale": "auto-execute test",
        "source_agent": "A1_baseline",
        "risk_snapshot": {"worst_case_loss": 24.0},
    }
    base.update(over)
    return base


def _audit_events(approval_id: str) -> list[dict]:
    path = approval_queue._audit_path()
    if not path.exists():
        return []
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("id") == approval_id]


class TestDefaultOffIsUnchanged:
    """A clean install must keep the original F013 promise."""

    def test_flag_defaults_off(self) -> None:
        assert approval_queue.get_auto_execute_on_timeout() is False

    def test_ignored_proposal_is_discarded_not_sent(self) -> None:
        aid = approval_queue.submit(_payload())
        approval_queue.timeout_reap(now=_time.time() + 2)
        assert approval_queue.get_entry(aid)["status"] == "timed_out"
        assert approval_queue.can_send_order(aid) is False

    def test_reset_state_clears_the_flag(self) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        approval_queue.reset_state()
        assert approval_queue.get_auto_execute_on_timeout() is False


class TestRefusalWindowElapsed:
    def test_ignored_proposal_becomes_auto_approved(self) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        aid = approval_queue.submit(_payload())
        assert approval_queue.get_entry(aid)["status"] == "pending"
        approval_queue.timeout_reap(now=_time.time() + 2)
        assert approval_queue.get_entry(aid)["status"] == "auto_approved"

    def test_auto_approved_opens_gate_four(self) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        aid = approval_queue.submit(_payload())
        approval_queue.timeout_reap(now=_time.time() + 2)
        assert approval_queue.can_send_order(aid) is True

    def test_reap_returns_the_auto_approved_id(self) -> None:
        """The driver relies on this to know what to execute."""
        approval_queue.set_auto_execute_on_timeout(True)
        aid = approval_queue.submit(_payload())
        assert aid in approval_queue.timeout_reap(now=_time.time() + 2)

    def test_window_is_the_timeout_not_the_approved_ttl(self) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        approval_queue.set_timeout_seconds(1800)
        aid = approval_queue.submit(_payload())
        # Well past the 5-minute approved-TTL, still inside the
        # 30-minute refusal window: must remain pending.
        approval_queue.timeout_reap(now=_time.time() + 600)
        assert approval_queue.get_entry(aid)["status"] == "pending"
        approval_queue.timeout_reap(now=_time.time() + 1801)
        assert approval_queue.get_entry(aid)["status"] == "auto_approved"


class TestOperatorStillWins:
    def test_reject_inside_the_window_prevents_execution(self) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        approval_queue.set_timeout_seconds(1800)
        aid = approval_queue.submit(_payload())
        assert approval_queue.reject(aid, "wrong pair") is True
        # A later reap must not resurrect a rejected entry.
        approval_queue.timeout_reap(now=_time.time() + 1801)
        assert approval_queue.get_entry(aid)["status"] == "rejected"
        assert approval_queue.can_send_order(aid) is False

    def test_approve_inside_the_window_is_recorded_as_human(self) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        approval_queue.set_timeout_seconds(1800)
        aid = approval_queue.submit(_payload())
        assert approval_queue.approve(aid) is True
        entry = approval_queue.get_entry(aid)
        assert entry["status"] == "approved"
        assert entry["resolved_by"] == "user"

    def test_reject_after_the_window_fails_loudly(self) -> None:
        """Once the window closes the entry is no longer pending, so a
        late click returns False rather than silently appearing to
        cancel an order that is already going out. The unwind for this
        case is the F025 B4 close path, not a late reject."""
        approval_queue.set_auto_execute_on_timeout(True)
        aid = approval_queue.submit(_payload())
        approval_queue.timeout_reap(now=_time.time() + 2)
        assert approval_queue.reject(aid, "too late") is False
        assert approval_queue.get_entry(aid)["status"] == "auto_approved"


class TestAuditAttribution:
    """The audit trail must never let a machine decision read as human."""

    def test_auto_approval_is_not_recorded_as_approved(self) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        aid = approval_queue.submit(_payload())
        approval_queue.timeout_reap(now=_time.time() + 2)
        events = {r["event"] for r in _audit_events(aid)}
        assert "auto_approved" in events
        assert "approved" not in events

    def test_auto_approval_names_the_machine_as_resolver(self) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        aid = approval_queue.submit(_payload())
        approval_queue.timeout_reap(now=_time.time() + 2)
        row = [r for r in _audit_events(aid)
               if r["event"] == "auto_approved"][0]
        assert row["resolved_by"] == "auto_timeout"
        assert row["resolution_reason"] == "refusal_window_elapsed"
        assert approval_queue.get_entry(aid)["resolved_by"] == "auto_timeout"

    def test_status_is_distinguishable_for_filtering(self) -> None:
        approval_queue.set_auto_execute_on_timeout(True)
        auto_id = approval_queue.submit(_payload())
        approval_queue.timeout_reap(now=_time.time() + 2)
        approval_queue.set_timeout_seconds(1800)
        human_id = approval_queue.submit(_payload(symbol="GBPUSD"))
        approval_queue.approve(human_id)
        auto_rows = approval_queue.list_entries(status="auto_approved")
        human_rows = approval_queue.list_entries(status="approved")
        assert [r["id"] for r in auto_rows] == [auto_id]
        assert [r["id"] for r in human_rows] == [human_id]


class TestFreshnessAppliesToAutoApprovals:
    def test_stale_auto_approval_expires(self) -> None:
        """If the executor is down when the window closes, the entry
        must go cold rather than fire whenever it returns."""
        approval_queue.set_auto_execute_on_timeout(True)
        approval_queue.set_approved_ttl_seconds(60)
        aid = approval_queue.submit(_payload())
        now = _time.time()
        approval_queue.timeout_reap(now=now + 2)
        assert approval_queue.get_entry(aid)["status"] == "auto_approved"
        approval_queue.timeout_reap(now=now + 2 + 61)
        entry = approval_queue.get_entry(aid)
        assert entry["status"] == "approval_expired"
        assert entry["resolution_reason"] == "approved_ttl_expired"
        assert approval_queue.can_send_order(aid) is False


class TestAutoPathDoesNotBypassGates:
    """Auto-approval opens gate #4 and nothing else."""

    def _auto_approved_entry(self) -> dict:
        approval_queue.set_auto_execute_on_timeout(True)
        aid = approval_queue.submit(_payload())
        approval_queue.timeout_reap(now=_time.time() + 2)
        return approval_queue.get_entry(aid)

    def test_live_mode_off_still_refuses(self) -> None:
        entry = self._auto_approved_entry()
        ok, reason = approval_queue.can_send_live_order(
            entry, live_mode_check=lambda: (False, "live-mode disabled"))
        assert ok is False

    def test_kill_switch_still_refuses(self) -> None:
        entry = self._auto_approved_entry()
        ok, _ = approval_queue.can_send_live_order(
            entry,
            live_mode_check=lambda: (True, ""),
            kill_switch_check=lambda sym: (False, f"kill-switch on {sym}"))
        assert ok is False

    def test_risk_budget_still_refuses(self) -> None:
        entry = self._auto_approved_entry()
        ok, _ = approval_queue.can_send_live_order(
            entry,
            live_mode_check=lambda: (True, ""),
            kill_switch_check=lambda sym: (True, ""),
            risk_budget_check=lambda s, st, w: (False, "risk budget spent"))
        assert ok is False

    def test_all_gates_open_permits_the_auto_entry(self) -> None:
        entry = self._auto_approved_entry()
        ok, _ = approval_queue.can_send_live_order(
            entry,
            live_mode_check=lambda: (True, ""),
            kill_switch_check=lambda sym: (True, ""),
            risk_budget_check=lambda s, st, w: (True, ""))
        assert ok is True
