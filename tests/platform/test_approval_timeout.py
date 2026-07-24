"""F013 -- approval timeout behaviour.

Focused pinning on the timeout semantics (spec asked 2 tests here):

1. A pending entry past its timeout expires cleanly and cannot be
   approved.
2. can_send_order() calls timeout_reap under the hood so a stale
   pending is refused without a manual reap.
"""
from __future__ import annotations

import secrets as _secrets

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


def _payload() -> dict:
    return {
        "symbol": "EURUSD",
        "side": "buy",
        "size": 0.10,
        "entry": 1.0850,
        "stop": 1.0820,
        "take_profit": 1.0920,
        "rationale": "timeout test",
        "source_agent": "A1_baseline",
        "risk_snapshot": {"worst_case_loss": 20.0},
    }


class TestExpiryCleanliness:
    def test_expired_pending_cannot_be_approved(self) -> None:
        import time as _time
        aid = approval_queue.submit(_payload())
        approval_queue.timeout_reap(now=_time.time() + 2)
        # Cannot flip a timed_out entry back to approved.
        assert approval_queue.approve(aid) is False
        entry = approval_queue.get_entry(aid)
        assert entry["status"] == "timed_out"


class TestAutomaticReap:
    def test_can_send_order_reaps_before_answering(self) -> None:
        import time as _time
        approval_queue.set_timeout_seconds(1)
        aid = approval_queue.submit(_payload())
        approval_queue.timeout_reap(now=_time.time() + 2)
        assert approval_queue.can_send_order(aid) is False
