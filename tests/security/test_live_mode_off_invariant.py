"""P0 INVARIANT PIN -- the single most important test in Sprint 2.

Sprint 2 explicitly does NOT wire any pathway from the squad to the
broker. But it DOES ship the four safety gates that a future integration
sprint will call. This test pins the composition of those gates:

    live_mode_enabled                          # (1) F013
    NOT kill_switches.is_killed(symbol)        # (2) F011
    risk_budget.can_send_order(...)            # (3) F012
    approval_queue.can_send_order(id)          # (4) F013

The invariant proven here is:

    From a clean install, `can_send_live_order(any_entry)` returns
    (False, <reason>). It ONLY returns (True, "ok") when ALL FOUR
    checks pass -- and turning off any single one takes it back to
    False.

If this test ever fails, HALT Sprint 2 and escalate. It is the
single guarantee that the D065 SCAFFOLDING-only invariant holds.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.platform import (
    approval_queue, credentials, kill_switch_admin, kill_switches,
    risk_budget,
)


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase("live-mode-invariant-tests")
    credentials.force_fallback(True)
    monkeypatch.setenv(kill_switches.KILL_DIR_ENV,
                       str(tmp_path / "cfg" / "kill"))
    kill_switches.reset_cache_for_tests()
    risk_budget.reset_state()
    approval_queue.reset_state()
    yield
    credentials._reset_state_for_tests()
    risk_budget.reset_state()
    approval_queue.reset_state()


def _valid_entry(approval_id: str = "apr_test") -> dict:
    return {
        "symbol": "EURUSD",
        "side": "buy",
        "size": 0.10,
        "entry": 1.0850,
        "stop": 1.0820,
        "take_profit": 1.0920,
        "rationale": "unit test",
        "source_agent": "A1_baseline",
        "risk_snapshot": {"worst_case_loss": 10.0},
        "approval_id": approval_id,
    }


class TestCleanInstallBlocks:
    """Case 1 of the spec: clean install refuses everything."""

    def test_default_is_off(self) -> None:
        assert approval_queue.is_live_mode_enabled() is False

    def test_can_send_live_order_refuses_by_default(self) -> None:
        ok, reason = approval_queue.can_send_live_order(_valid_entry())
        assert ok is False
        assert "live-mode" in reason


class TestLiveModeAloneIsNotEnough:
    """Case 2: enabling live-mode alone still doesn't clear the gate --
    the entry has no approval."""

    def test_enable_but_no_approval(self) -> None:
        assert approval_queue.set_live_mode(True) is True
        assert approval_queue.is_live_mode_enabled() is True
        ok, reason = approval_queue.can_send_live_order(_valid_entry())
        assert ok is False
        assert "approval" in reason.lower()


class TestApprovalButNoBudget:
    """Case 3: even with live-mode + approval, an over-budget order
    is still refused by the risk-budget gate."""

    def test_over_budget_still_refused(self) -> None:
        approval_queue.set_live_mode(True)
        aid = approval_queue.submit({
            "symbol": "EURUSD",
            "side": "buy",
            "size": 0.10,
            "entry": 1.0850,
            "stop": 1.0820,
            "take_profit": 1.0920,
            "rationale": "unit test",
            "source_agent": "A1_baseline",
            "risk_snapshot": {"worst_case_loss": 10.0},
        })
        approval_queue.approve(aid)

        # Set a tiny per-day cap and drain it.
        risk_budget.save_config({"per_day": {"max_loss": 5.0}})
        entry = _valid_entry(approval_id=aid)
        entry["risk_snapshot"] = {"worst_case_loss": 10.0}
        ok, reason = approval_queue.can_send_live_order(entry)
        assert ok is False
        assert "cap" in reason.lower() or "budget" in reason.lower()


class TestAllFourPassAllowsOrder:
    """Case 4 (the ONLY True-outcome case): every gate open ->
    can_send_live_order returns True."""

    def test_all_four_gates_open(self) -> None:
        approval_queue.set_live_mode(True)
        aid = approval_queue.submit({
            "symbol": "EURUSD",
            "side": "buy",
            "size": 0.10,
            "entry": 1.0850,
            "stop": 1.0820,
            "take_profit": 1.0920,
            "rationale": "unit test",
            "source_agent": "A1_baseline",
            "risk_snapshot": {"worst_case_loss": 10.0},
        })
        approval_queue.approve(aid)
        entry = _valid_entry(approval_id=aid)
        ok, reason = approval_queue.can_send_live_order(entry)
        assert ok is True, f"expected True but got False: {reason}"
        assert reason == "ok"


class TestKillSwitchTripsMidFlow:
    """Case 5: even after every gate was clear, activating the kill
    switch mid-flow refuses the next call. The pathway is not sticky."""

    def test_kill_switch_flip_refuses(self) -> None:
        approval_queue.set_live_mode(True)
        aid = approval_queue.submit({
            "symbol": "EURUSD",
            "side": "buy",
            "size": 0.10,
            "entry": 1.0850,
            "stop": 1.0820,
            "take_profit": 1.0920,
            "rationale": "unit test",
            "source_agent": "A1_baseline",
            "risk_snapshot": {"worst_case_loss": 10.0},
        })
        approval_queue.approve(aid)
        entry = _valid_entry(approval_id=aid)
        # Baseline: all four should pass.
        assert approval_queue.can_send_live_order(entry)[0] is True
        # Trip the global kill switch.
        assert kill_switch_admin.activate_kill(
            symbol=None, reason="pin test", by="test") is True
        kill_switches.reset_cache_for_tests()
        ok, reason = approval_queue.can_send_live_order(entry)
        assert ok is False
        assert "kill" in reason.lower()
