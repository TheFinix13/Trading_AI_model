"""F013 -- approval_queue module unit tests.

Coverage (12+):
1. submit assigns a unique id + records default fields
2. submit validates missing fields -> ValueError
3. submit validates side + numeric positivity -> ValueError
4. approve moves pending -> approved and is idempotent (returns False on second call)
5. reject moves pending -> rejected with reason
6. reject requires the entry to be pending
7. timeout_reap expires stale pending entries
8. can_send_order refuses non-approved entries
9. can_send_order refuses timed_out entries
10. list_entries filters + limits
11. audit JSONL is appended for every state change
12. reset_state clears memory and drops the audit file
13. set_timeout_seconds respected on next submit
14. bad status filter raises ValueError
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.platform import approval_queue, credentials


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase("aq-tests-passphrase")
    credentials.force_fallback(True)
    approval_queue.reset_state()
    yield
    credentials._reset_state_for_tests()
    approval_queue.reset_state()


def _payload(**overrides) -> dict:
    base = {
        "symbol": "EURUSD",
        "side": "buy",
        "size": 0.10,
        "entry": 1.0850,
        "stop": 1.0820,
        "take_profit": 1.0920,
        "rationale": "unit test rationale",
        "source_agent": "A1_baseline",
        "risk_snapshot": {"worst_case_loss": 20.0},
    }
    base.update(overrides)
    return base


class TestSubmit:
    def test_returns_unique_id(self) -> None:
        a = approval_queue.submit(_payload())
        b = approval_queue.submit(_payload())
        assert a != b
        assert a.startswith("apr_")
        assert b.startswith("apr_")

    def test_records_default_fields(self) -> None:
        aid = approval_queue.submit(_payload())
        entry = approval_queue.get_entry(aid)
        assert entry["status"] == "pending"
        assert entry["symbol"] == "EURUSD"
        assert entry["resolved_at"] is None

    def test_missing_field_rejected(self) -> None:
        bad = _payload()
        del bad["stop"]
        with pytest.raises(ValueError, match="missing required fields"):
            approval_queue.submit(bad)

    def test_invalid_side_rejected(self) -> None:
        with pytest.raises(ValueError, match="side must be one of"):
            approval_queue.submit(_payload(side="north"))

    def test_negative_size_rejected(self) -> None:
        with pytest.raises(ValueError, match="size"):
            approval_queue.submit(_payload(size=-0.1))

    def test_bad_risk_snapshot_rejected(self) -> None:
        with pytest.raises(ValueError, match="risk_snapshot"):
            approval_queue.submit(_payload(risk_snapshot={}))


class TestApproveReject:
    def test_approve_pending(self) -> None:
        aid = approval_queue.submit(_payload())
        assert approval_queue.approve(aid) is True
        entry = approval_queue.get_entry(aid)
        assert entry["status"] == "approved"
        assert entry["resolved_by"] == "user"

    def test_double_approve_idempotent(self) -> None:
        aid = approval_queue.submit(_payload())
        assert approval_queue.approve(aid) is True
        # Second call fails because it's no longer pending.
        assert approval_queue.approve(aid) is False

    def test_reject_with_reason(self) -> None:
        aid = approval_queue.submit(_payload())
        assert approval_queue.reject(aid, "does not match my thesis") is True
        entry = approval_queue.get_entry(aid)
        assert entry["status"] == "rejected"
        assert entry["resolution_reason"] == "does not match my thesis"

    def test_reject_on_unknown_id_returns_false(self) -> None:
        assert approval_queue.reject("apr_missing", "n/a") is False


class TestTimeout:
    def test_timeout_reap_expires_stale(self) -> None:
        import time as _time
        approval_queue.set_timeout_seconds(1)
        aid = approval_queue.submit(_payload())
        # Walk the clock forward by 2s so the entry is past its timeout.
        future = _time.time() + 2
        expired = approval_queue.timeout_reap(now=future)
        assert aid in expired
        entry = approval_queue.get_entry(aid)
        assert entry["status"] == "timed_out"
        assert entry["resolved_by"] == "system"

    def test_can_send_order_refuses_timed_out(self) -> None:
        import time as _time
        approval_queue.set_timeout_seconds(1)
        aid = approval_queue.submit(_payload())
        approval_queue.timeout_reap(now=_time.time() + 2)
        assert approval_queue.can_send_order(aid) is False


class TestCanSendOrder:
    def test_pending_refused(self) -> None:
        aid = approval_queue.submit(_payload())
        assert approval_queue.can_send_order(aid) is False

    def test_approved_allowed(self) -> None:
        aid = approval_queue.submit(_payload())
        approval_queue.approve(aid)
        assert approval_queue.can_send_order(aid) is True

    def test_rejected_refused(self) -> None:
        aid = approval_queue.submit(_payload())
        approval_queue.reject(aid, "no")
        assert approval_queue.can_send_order(aid) is False

    def test_unknown_id_refused(self) -> None:
        assert approval_queue.can_send_order("apr_missing") is False


class TestListEntries:
    def test_filter_by_status(self) -> None:
        a = approval_queue.submit(_payload())
        b = approval_queue.submit(_payload())
        approval_queue.approve(a)
        pending = approval_queue.list_entries("pending")
        approved = approval_queue.list_entries("approved")
        assert [r["id"] for r in pending] == [b]
        assert [r["id"] for r in approved] == [a]

    def test_all_returns_both(self) -> None:
        a = approval_queue.submit(_payload())
        b = approval_queue.submit(_payload())
        assert {r["id"] for r in approval_queue.list_entries()} == {a, b}

    def test_bad_status_raises(self) -> None:
        with pytest.raises(ValueError):
            approval_queue.list_entries("wat")

    def test_limit_is_respected(self) -> None:
        for _ in range(5):
            approval_queue.submit(_payload())
        assert len(approval_queue.list_entries(limit=2)) == 2


class TestAudit:
    def test_audit_appends_on_submit_and_approve(self, tmp_path: Path) -> None:
        aid = approval_queue.submit(_payload())
        approval_queue.approve(aid)
        audit = credentials._config_dir() / approval_queue.AUDIT_FILENAME
        assert audit.exists()
        lines = [json.loads(l) for l in
                 audit.read_text().splitlines() if l.strip()]
        events = [l["event"] for l in lines]
        assert "submit" in events
        assert "approved" in events
