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

import secrets as _secrets

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
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
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


# =====================================================================
# Sprint 2b EXTENSIONS (F018). Everything above this line is the
# Sprint 2 pin, unmodified. D097 superseded D065 NARROWLY: the four
# gates now have exactly ONE caller (live_executor.execute_approved),
# for DEMO accounts only. These cases pin the caller's own gates.
# =====================================================================

from agent.platform import broker_connection, live_executor  # noqa: E402


def _executor_reset():
    live_executor.reset_state_for_tests()


def _demo_cfg(**overrides) -> dict:
    """A fully-open executor config; tests close one door at a time."""
    cfg = {
        "enabled": True,
        "demo_only": True,
        "allowed_server_patterns": ["*Trial*", "*Demo*", "*demo*"],
        "max_volume_lots": 0.01,
        "broker_alias": "v2-demo",
    }
    cfg.update(overrides)
    return cfg


def _approved_entry(size: float = 0.01) -> str:
    """Open all four Sprint-2 gates and return the approval id."""
    approval_queue.set_live_mode(True)
    aid = approval_queue.submit({
        "symbol": "EURUSD",
        "side": "buy",
        "size": size,
        "entry": 1.0850,
        "stop": 1.0820,
        "take_profit": 1.0920,
        "rationale": "P0 extension test",
        "source_agent": "A1_baseline",
        "risk_snapshot": {"worst_case_loss": 5.0},
    })
    approval_queue.approve(aid)
    return aid


def _store_demo_creds() -> None:
    broker_connection.reset_rate_limiter()
    assert broker_connection.save_credentials(
        "v2-demo", 436983644, "x" * 16,
        "Exness-MT5Trial9", "demo") is True


class TestExecutorDisabledByDefault:
    """Gate #5 pin: a clean install's executor refuses EVERYTHING,
    even with all four Sprint-2 gates open, creds stored, and a
    healthy demo adapter."""

    def test_config_default_is_disabled(self) -> None:
        assert live_executor.is_enabled({}) is False
        assert live_executor.load_executor_config({})["enabled"] is False

    def test_junk_enabled_values_stay_disabled(self) -> None:
        for junk in ("true", 1, "yes", [], {"on": True}):
            assert live_executor.is_enabled(
                {"live_executor": {"enabled": junk}}) is False

    def test_refuses_even_when_everything_else_is_open(self) -> None:
        _executor_reset()
        _store_demo_creds()
        aid = _approved_entry()
        adapter = live_executor.FakeMt5OrderAdapter()
        result = live_executor.execute_approved(
            aid, adapter, _demo_cfg(enabled=False))
        assert result["ok"] is False
        assert result["status"] == "refused"
        assert "disabled" in result["reason"]
        assert adapter.calls == []  # never even connected


class TestExecutorRefusesOnAnyGateFailure:
    """The executor re-runs can_send_live_order fresh; each Sprint-2
    gate individually closed keeps the adapter untouched."""

    def test_live_mode_off_refuses(self) -> None:
        _executor_reset()
        _store_demo_creds()
        aid = _approved_entry()
        approval_queue.set_live_mode(False)
        adapter = live_executor.FakeMt5OrderAdapter()
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "refused"
        assert "live-mode" in result["reason"]
        assert adapter.calls == []

    def test_kill_switch_refuses(self) -> None:
        _executor_reset()
        _store_demo_creds()
        aid = _approved_entry()
        assert kill_switch_admin.activate_kill(
            symbol=None, reason="P0 extension", by="test") is True
        kill_switches.reset_cache_for_tests()
        adapter = live_executor.FakeMt5OrderAdapter()
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "refused"
        assert "kill" in result["reason"].lower()
        assert adapter.calls == []

    def test_risk_budget_refuses(self) -> None:
        _executor_reset()
        _store_demo_creds()
        aid = _approved_entry()
        risk_budget.save_config({"per_day": {"max_loss": 1.0}})
        adapter = live_executor.FakeMt5OrderAdapter()
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "refused"
        assert "cap" in result["reason"].lower()
        assert adapter.calls == []

    def test_unapproved_entry_refuses(self) -> None:
        _executor_reset()
        _store_demo_creds()
        approval_queue.set_live_mode(True)
        aid = approval_queue.submit({
            "symbol": "EURUSD", "side": "buy", "size": 0.01,
            "entry": 1.0850, "stop": 1.0820, "take_profit": 1.0920,
            "rationale": "left pending", "source_agent": "A1_baseline",
            "risk_snapshot": {"worst_case_loss": 5.0},
        })  # deliberately NOT approved
        adapter = live_executor.FakeMt5OrderAdapter()
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "refused"
        assert "approval" in result["reason"].lower()
        assert adapter.calls == []


class TestExecutorRefusesWithoutBrokerCreds:
    def test_no_alias_configured(self) -> None:
        _executor_reset()
        aid = _approved_entry()
        adapter = live_executor.FakeMt5OrderAdapter()
        result = live_executor.execute_approved(
            aid, adapter, _demo_cfg(broker_alias=""))
        assert result["status"] == "refused"
        assert "broker_alias" in result["reason"]
        assert adapter.calls == []

    def test_alias_without_stored_credentials(self) -> None:
        _executor_reset()
        aid = _approved_entry()
        adapter = live_executor.FakeMt5OrderAdapter()
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "refused"
        assert "credentials" in result["reason"]
        assert adapter.calls == []


class TestDemoOnlyGuard:
    """Invariant #3: structurally unable to reach a non-demo server."""

    def test_real_looking_server_refused(self) -> None:
        _executor_reset()
        _store_demo_creds()
        aid = _approved_entry()
        adapter = live_executor.FakeMt5OrderAdapter(server="Exness-MT5Real8")
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "refused"
        assert "demo guard" in result["reason"]
        # Connected for the server check, but NO order call happened.
        assert not any(c[0] == "send_market_order" for c in adapter.calls)
        assert adapter.shutdown_called is True

    def test_missing_demo_only_ack_refused(self) -> None:
        _executor_reset()
        _store_demo_creds()
        aid = _approved_entry()
        adapter = live_executor.FakeMt5OrderAdapter()  # proper demo server
        result = live_executor.execute_approved(
            aid, adapter, _demo_cfg(demo_only=False))
        assert result["status"] == "refused"
        assert "demo_only" in result["reason"]
        assert not any(c[0] == "send_market_order" for c in adapter.calls)

    def test_demo_server_with_ack_reaches_send(self) -> None:
        _executor_reset()
        _store_demo_creds()
        aid = _approved_entry()
        adapter = live_executor.FakeMt5OrderAdapter(server="Exness-MT5Trial9")
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["ok"] is True
        assert result["status"] == "filled"


# =====================================================================
# 2026-07-24 audit EXTENSION (A005 -- stale approvals). Everything
# above this line is the Sprint 2 pin + Sprint 2b extension,
# unmodified. These cases pin the two A005 fixes: (a) a click landing
# after timeout_at can never approve an expired entry; (b) an
# `approved` entry goes stale after the approved-freshness window and
# every gate -- including the F018 executor via composition --
# refuses it.
# =====================================================================

import time  # noqa: E402


class TestStaleApprovalRefused:
    def test_late_click_cannot_approve_expired_entry(self) -> None:
        """(a) `_resolve` reaps first: approving after the pending
        timeout has passed fails and the entry reads timed_out."""
        approval_queue.set_timeout_seconds(1)
        aid = approval_queue.submit({
            "symbol": "EURUSD", "side": "buy", "size": 0.01,
            "entry": 1.0850, "stop": 1.0820, "take_profit": 1.0920,
            "rationale": "late click", "source_agent": "A1_baseline",
            "risk_snapshot": {"worst_case_loss": 5.0},
        })
        time.sleep(1.1)
        assert approval_queue.approve(aid) is False
        entry = approval_queue.get_entry(aid)
        assert entry is not None
        assert entry["status"] == "timed_out"
        assert approval_queue.can_send_order(aid) is False

    def test_approved_entry_expires_after_ttl(self) -> None:
        """(b) approved entries carry a freshness window; past it the
        status flips to approval_expired and the gate refuses."""
        aid = _approved_entry()
        assert approval_queue.can_send_order(aid) is True
        # Reap as-if the TTL (default 300 s) has elapsed.
        approval_queue.timeout_reap(now=time.time() + 301)
        assert approval_queue.can_send_order(aid) is False
        entry = approval_queue.get_entry(aid)
        assert entry is not None
        assert entry["status"] == "approval_expired"
        assert entry["resolution_reason"] == "approved_ttl_expired"

    def test_stale_approval_refuses_composed_gate(self) -> None:
        """can_send_live_order (the P0 composition) refuses a stale
        approval even with every other gate open."""
        aid = _approved_entry()
        entry = _valid_entry(approval_id=aid)
        assert approval_queue.can_send_live_order(entry)[0] is True
        approval_queue.timeout_reap(now=time.time() + 301)
        ok, reason = approval_queue.can_send_live_order(entry)
        assert ok is False
        assert "approval" in reason.lower()

    def test_executor_refuses_stale_approval_via_composition(self) -> None:
        """The F018 executor re-runs can_send_live_order fresh, so a
        stale approval never reaches the adapter."""
        _executor_reset()
        _store_demo_creds()
        aid = _approved_entry()
        approval_queue.timeout_reap(now=time.time() + 301)
        adapter = live_executor.FakeMt5OrderAdapter(server="Exness-MT5Trial9")
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "refused"
        assert "approval" in result["reason"].lower()
        assert adapter.calls == []

    def test_ttl_config_knob_and_default(self) -> None:
        assert approval_queue.DEFAULT_APPROVED_TTL_SECONDS == 300
        assert approval_queue.get_approved_ttl_seconds() == 300
        approval_queue.set_approved_ttl_seconds(60)
        assert approval_queue.get_approved_ttl_seconds() == 60
