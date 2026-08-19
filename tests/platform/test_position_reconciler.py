"""F025 B6 + B8 -- position reconciliation and aggregate open risk.

B6's headline ("record_fill is called with literal zero") understates
the problem. Passing zero at fill time is correct -- nothing is realised
yet. The defect is that nothing records the loss when the position
CLOSES, and the closes that matter most are the ones this platform never
performs: a stop-out executes at the broker and never calls back. So a
daily-loss cap built only on voluntary closes misses precisely the
losses it exists to limit.

B8 depends on the same capability, because "total risk currently open"
is unanswerable without knowing which positions are still open.

The load-bearing tests here are `TestNeverGuesses` (a broker we cannot
reach must change nothing) and `TestWinsDoNotMintBudget`.
"""
from __future__ import annotations

import secrets as _secrets

from pathlib import Path

import pytest

from agent.platform import (
    credentials, live_executor, position_reconciler, risk_budget)


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    risk_budget.reset_state()
    yield
    credentials._reset_state_for_tests()
    risk_budget.reset_state()


def _fill_row(ticket: int, *, symbol: str = "EURUSD",
              agent: str = "bachira_meguru",
              worst_case_loss: float = 24.0,
              status: str = "filled") -> None:
    live_executor._append_execution({
        "at": "2026-08-19T10:00:00Z",
        "approval_id": f"apr_{ticket}",
        "symbol": symbol,
        "side": "buy",
        "volume": 0.08,
        "status": status,
        "reason": "ok",
        "ticket": ticket,
        "magic": live_executor.DEFAULT_MAGIC,
        "source_agent": agent,
        "worst_case_loss": worst_case_loss,
    })


def _today_total() -> float:
    return risk_budget._today_losses().total


class TestOpenRisk:
    def test_sums_worst_case_loss_of_open_fills(self) -> None:
        _fill_row(1, worst_case_loss=24.0)
        _fill_row(2, symbol="GBPUSD", worst_case_loss=20.0)
        assert position_reconciler.open_risk() == pytest.approx(44.0)

    def test_closed_tickets_drop_out(self) -> None:
        _fill_row(1, worst_case_loss=24.0)
        _fill_row(2, symbol="GBPUSD", worst_case_loss=20.0)
        _fill_row(1, worst_case_loss=24.0, status="closed")
        assert position_reconciler.open_risk() == pytest.approx(20.0)

    def test_empty_log_is_zero(self) -> None:
        assert position_reconciler.open_risk() == 0.0

    def test_rows_without_worst_case_loss_contribute_zero(self) -> None:
        live_executor._append_execution({
            "at": "2026-08-19T10:00:00Z", "approval_id": "apr_old",
            "symbol": "EURUSD", "status": "filled", "ticket": 99,
        })
        assert position_reconciler.open_risk() == 0.0


class TestAggregateCap:
    def test_cap_refuses_once_total_open_risk_would_breach(self) -> None:
        # 10% of $500 = $50. Two $24 positions open = $48; a third $24
        # ask would reach $72.
        ok, reason = risk_budget.can_send_order(
            "EURUSD", "bachira_meguru", 24.0,
            open_risk=48.0, equity=500.0)
        assert ok is False
        assert "aggregate open-risk cap" in reason

    def test_cap_admits_inside_the_budget(self) -> None:
        ok, reason = risk_budget.can_send_order(
            "EURUSD", "bachira_meguru", 24.0,
            open_risk=24.0, equity=500.0)
        assert ok is True, reason

    def test_omitting_the_pair_preserves_three_cap_behaviour(self) -> None:
        """A caller with no way to observe open positions cannot
        honestly assert a total, so the aggregate check is skipped
        rather than guessed. $40 clears the three caps (per-day 100,
        per-symbol 50) but would breach a $50 aggregate at any
        meaningful open risk."""
        ok, reason = risk_budget.can_send_order(
            "EURUSD", "bachira_meguru", 40.0)
        assert ok is True, reason
        blocked, _ = risk_budget.can_send_order(
            "EURUSD", "bachira_meguru", 40.0,
            open_risk=20.0, equity=500.0)
        assert blocked is False

    def test_configured_fraction_is_honoured(self) -> None:
        risk_budget.save_config({"aggregate": {"max_open_risk_frac": 0.05}})
        ok, _ = risk_budget.can_send_order(
            "EURUSD", "a", 10.0, open_risk=20.0, equity=500.0)
        assert ok is False  # 30 > 25
        ok2, _ = risk_budget.can_send_order(
            "EURUSD", "a", 4.0, open_risk=20.0, equity=500.0)
        assert ok2 is True  # 24 <= 25

    def test_default_fraction_is_ten_percent(self) -> None:
        cfg = risk_budget.load_config()
        assert cfg["aggregate"]["max_open_risk_frac"] == pytest.approx(0.10)

    @pytest.mark.parametrize("open_risk,equity", [
        (-1.0, 500.0), (float("nan"), 500.0), (10.0, 0.0), (10.0, -5.0),
        ("junk", 500.0), (10.0, "junk"),
    ])
    def test_degenerate_inputs_refuse(self, open_risk, equity) -> None:
        ok, _ = risk_budget.can_send_order(
            "EURUSD", "a", 1.0, open_risk=open_risk, equity=equity)
        assert ok is False


class TestReconcileChargesRealisedLosses:
    def test_externally_closed_loss_hits_the_budget(self) -> None:
        _fill_row(1)
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result=set(), deal_profits={1: -22.5})
        result = position_reconciler.reconcile(adapter)
        assert result["ok"] is True
        assert result["closed"] == 1
        assert result["recorded"] == 1
        assert _today_total() == pytest.approx(22.5)

    def test_still_open_positions_are_left_alone(self) -> None:
        _fill_row(1)
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result={1}, deal_profits={1: -22.5})
        result = position_reconciler.reconcile(adapter)
        assert result["closed"] == 0
        assert result["recorded"] == 0
        assert _today_total() == 0.0

    def test_reconciled_ticket_leaves_open_risk(self) -> None:
        _fill_row(1, worst_case_loss=24.0)
        assert position_reconciler.open_risk() == pytest.approx(24.0)
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result=set(), deal_profits={1: -22.5})
        position_reconciler.reconcile(adapter)
        assert position_reconciler.open_risk() == 0.0

    def test_second_pass_does_not_double_charge(self) -> None:
        _fill_row(1)
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result=set(), deal_profits={1: -22.5})
        position_reconciler.reconcile(adapter)
        position_reconciler.reconcile(adapter)
        assert _today_total() == pytest.approx(22.5)

    def test_realised_pnl_is_written_to_the_audit_row(self) -> None:
        _fill_row(1)
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result=set(), deal_profits={1: -22.5})
        position_reconciler.reconcile(adapter)
        rows = [r for r in live_executor._execution_rows()
                if r.get("status") == "reconciled_closed"]
        assert len(rows) == 1
        assert rows[0]["realised_pnl"] == pytest.approx(-22.5)
        assert rows[0]["ticket"] == 1


class TestWinsDoNotMintBudget:
    def test_a_winner_charges_nothing(self) -> None:
        """The caps are denominated in losses. Crediting a win as
        negative usage would hand back budget the caps never spent."""
        _fill_row(1)
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result=set(), deal_profits={1: +36.0})
        position_reconciler.reconcile(adapter)
        assert _today_total() == 0.0

    def test_a_winner_still_releases_open_risk(self) -> None:
        _fill_row(1, worst_case_loss=24.0)
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result=set(), deal_profits={1: +36.0})
        position_reconciler.reconcile(adapter)
        assert position_reconciler.open_risk() == 0.0


class TestNeverGuesses:
    def test_unreachable_broker_changes_nothing(self) -> None:
        _fill_row(1, worst_case_loss=24.0)
        adapter = live_executor.FakeMt5OrderAdapter(open_tickets_raises=True)
        result = position_reconciler.reconcile(adapter)
        assert result["ok"] is False
        assert result["errors"]
        assert _today_total() == 0.0
        # The position must still count against the aggregate cap.
        assert position_reconciler.open_risk() == pytest.approx(24.0)

    def test_missing_deal_history_is_not_treated_as_no_loss(self) -> None:
        _fill_row(1, worst_case_loss=24.0)
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result=set(), deal_profits={})
        result = position_reconciler.reconcile(adapter)
        assert result["closed"] == 1
        assert result["recorded"] == 0
        assert result["skipped"] == 1
        assert _today_total() == 0.0
        # Left in `filled`, so it retries next pass and keeps counting
        # toward open risk meanwhile.
        assert position_reconciler.open_risk() == pytest.approx(24.0)

    def test_history_available_on_a_later_pass_is_picked_up(self) -> None:
        _fill_row(1)
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result=set(), deal_profits={})
        position_reconciler.reconcile(adapter)
        adapter.deal_profits = {1: -18.0}
        position_reconciler.reconcile(adapter)
        assert _today_total() == pytest.approx(18.0)

    def test_empty_audit_log_is_a_clean_noop(self) -> None:
        adapter = live_executor.FakeMt5OrderAdapter()
        result = position_reconciler.reconcile(adapter)
        assert result["ok"] is True
        assert result["checked"] == 0


class TestAttribution:
    def test_loss_is_charged_to_the_proposing_agent(self) -> None:
        _fill_row(1, agent="chigiri_hyoma")
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result=set(), deal_profits={1: -30.0})
        position_reconciler.reconcile(adapter)
        losses = risk_budget._today_losses()
        assert losses.by_strategy.get("chigiri_hyoma") == pytest.approx(30.0)
        assert losses.by_symbol.get("EURUSD") == pytest.approx(30.0)

    def test_missing_agent_falls_back_to_unknown_not_crash(self) -> None:
        live_executor._append_execution({
            "at": "2026-08-19T10:00:00Z", "approval_id": "apr_1",
            "symbol": "EURUSD", "status": "filled", "ticket": 1,
            "worst_case_loss": 24.0,
        })
        adapter = live_executor.FakeMt5OrderAdapter(
            open_tickets_result=set(), deal_profits={1: -12.0})
        position_reconciler.reconcile(adapter)
        assert risk_budget._today_losses().by_strategy.get("unknown") \
            == pytest.approx(12.0)
