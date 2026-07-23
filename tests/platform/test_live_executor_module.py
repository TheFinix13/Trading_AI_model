"""F018 -- live_executor module: config, demo guard, execution flow,
single-use consumption, audit trail, status surface."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import (  # noqa: E402
    alerts, approval_queue, broker_connection, credentials,
    kill_switches, live_executor, risk_budget,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase("live-executor-tests")
    credentials.force_fallback(True)
    monkeypatch.setenv(kill_switches.KILL_DIR_ENV,
                       str(tmp_path / "cfg" / "kill"))
    kill_switches.reset_cache_for_tests()
    broker_connection.reset_rate_limiter()
    risk_budget.reset_state()
    approval_queue.reset_state()
    alerts.reset()
    live_executor.reset_state_for_tests()
    yield
    credentials._reset_state_for_tests()
    broker_connection.reset_rate_limiter()
    risk_budget.reset_state()
    approval_queue.reset_state()
    alerts.reset()
    live_executor.reset_state_for_tests()


def _demo_cfg(**overrides) -> dict:
    cfg = {
        "enabled": True,
        "demo_only": True,
        "allowed_server_patterns": ["*Trial*", "*Demo*", "*demo*"],
        "max_volume_lots": 0.01,
        "broker_alias": "v2-demo",
    }
    cfg.update(overrides)
    return cfg


def _open_gates_and_approve(size: float = 0.01) -> str:
    approval_queue.set_live_mode(True)
    aid = approval_queue.submit({
        "symbol": "EURUSD", "side": "buy", "size": size,
        "entry": 1.0850, "stop": 1.0820, "take_profit": 1.0920,
        "rationale": "module test", "source_agent": "A1_baseline",
        "risk_snapshot": {"worst_case_loss": 5.0},
    })
    approval_queue.approve(aid)
    return aid


def _store_creds(alias: str = "v2-demo") -> None:
    assert broker_connection.save_credentials(
        alias, 436983644, "not-a-real-password-fixture",
        "Exness-MT5Trial9", "demo") is True


def _ready(aid_size: float = 0.01) -> str:
    _store_creds()
    return _open_gates_and_approve(aid_size)


# ---------------------------------------------------------------------
# config
# ---------------------------------------------------------------------

class TestLoadExecutorConfig:
    def test_empty_dict_gives_fail_closed_defaults(self) -> None:
        cfg = live_executor.load_executor_config({})
        assert cfg["enabled"] is False
        assert cfg["demo_only"] is False
        assert cfg["max_volume_lots"] == \
            live_executor.DEFAULT_MAX_VOLUME_LOTS
        assert cfg["allowed_server_patterns"] == \
            list(live_executor.DEFAULT_ALLOWED_SERVER_PATTERNS)
        assert cfg["broker_alias"] == ""

    def test_accepts_full_platform_config_shape(self) -> None:
        cfg = live_executor.load_executor_config(
            {"live_executor": {"enabled": True, "demo_only": True,
                               "broker_alias": " v2-demo "}})
        assert cfg["enabled"] is True
        assert cfg["demo_only"] is True
        assert cfg["broker_alias"] == "v2-demo"

    def test_accepts_bare_block_shape(self) -> None:
        cfg = live_executor.load_executor_config({"enabled": True})
        assert cfg["enabled"] is True

    def test_junk_volume_falls_back(self) -> None:
        for junk in ("lots", None, -1, 0):
            cfg = live_executor.load_executor_config(
                {"max_volume_lots": junk})
            assert cfg["max_volume_lots"] == \
                live_executor.DEFAULT_MAX_VOLUME_LOTS

    def test_junk_patterns_fall_back(self) -> None:
        cfg = live_executor.load_executor_config(
            {"allowed_server_patterns": "not-a-list"})
        assert cfg["allowed_server_patterns"] == \
            list(live_executor.DEFAULT_ALLOWED_SERVER_PATTERNS)

    def test_blank_patterns_are_dropped(self) -> None:
        cfg = live_executor.load_executor_config(
            {"allowed_server_patterns": ["  ", "*Demo*", ""]})
        assert cfg["allowed_server_patterns"] == ["*Demo*"]

    def test_demo_only_requires_literal_true(self) -> None:
        for junk in ("true", 1, "yes"):
            cfg = live_executor.load_executor_config({"demo_only": junk})
            assert cfg["demo_only"] is False


# ---------------------------------------------------------------------
# demo guard
# ---------------------------------------------------------------------

class TestDemoGuard:
    def test_designated_demo_server_passes(self) -> None:
        ok, why = live_executor.demo_guard("Exness-MT5Trial9", _demo_cfg())
        assert ok is True and why == "ok"

    @pytest.mark.parametrize("server", [
        "MetaQuotes-Demo", "ICMarkets-demo03", "Exness-MT5Trial12"])
    def test_common_demo_names_pass(self, server: str) -> None:
        assert live_executor.demo_guard(server, _demo_cfg())[0] is True

    @pytest.mark.parametrize("server", [
        "Exness-MT5Real8", "ICMarkets-Live04", "EXNESS-MT5TRIAL9"])
    def test_non_matching_servers_refused(self, server: str) -> None:
        """Case-sensitive on purpose: 'EXNESS-MT5TRIAL9' is NOT a
        shipped pattern match -- loosening this needs Legal review."""
        ok, why = live_executor.demo_guard(server, _demo_cfg())
        assert ok is False
        assert "allowlist" in why

    def test_blank_server_refused(self) -> None:
        ok, why = live_executor.demo_guard("", _demo_cfg())
        assert ok is False and "blank" in why

    def test_missing_ack_refused_even_for_demo_server(self) -> None:
        ok, why = live_executor.demo_guard(
            "Exness-MT5Trial9", _demo_cfg(demo_only=False))
        assert ok is False and "demo_only" in why

    def test_empty_allowlist_refuses(self) -> None:
        # load_executor_config keeps an explicitly-empty list: that is
        # the fail-closed direction.
        ok, why = live_executor.demo_guard(
            "Exness-MT5Trial9",
            _demo_cfg(allowed_server_patterns=[]))
        assert ok is False


# ---------------------------------------------------------------------
# execution flow
# ---------------------------------------------------------------------

class TestExecuteFill:
    def test_happy_path_fills(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter(
            send_result={"ticket": 555, "price": 1.0851, "volume": 0.01})
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["ok"] is True
        assert result["status"] == "filled"
        assert result["ticket"] == 555
        assert result["approval_id"] == aid

    def test_fill_sends_correct_order_params(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter()
        live_executor.execute_approved(aid, adapter, _demo_cfg())
        send = [c for c in adapter.calls
                if c[0] == "send_market_order"][0]
        assert send[1:] == ("EURUSD", "buy", 0.01, 1.0820, 1.0920)

    def test_fill_records_to_risk_budget(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter()
        live_executor.execute_approved(aid, adapter, _demo_cfg())
        state = (credentials._config_dir() / "risk_state.jsonl") \
            .read_text(encoding="utf-8").strip().splitlines()
        assert len(state) == 1
        row = json.loads(state[0])
        assert row["symbol"] == "EURUSD"
        assert row["strategy"] == "A1_baseline"
        assert row["pnl"] == 0.0

    def test_fill_publishes_trade_fill_alert(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter()
        live_executor.execute_approved(aid, adapter, _demo_cfg())
        events = [e for e in alerts.recent(10)
                  if e["type"] == "trade_fill"]
        assert len(events) == 1
        assert events[0]["payload"]["status"] == "filled"
        assert events[0]["payload"]["ticket"] == 10001

    def test_fill_appends_execution_row(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter()
        live_executor.execute_approved(aid, adapter, _demo_cfg())
        rows = live_executor.recent_executions()
        assert len(rows) == 1
        assert rows[0]["status"] == "filled"
        assert rows[0]["approval_id"] == aid
        assert rows[0]["ticket"] == 10001

    def test_adapter_shutdown_always_called(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter()
        live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert adapter.shutdown_called is True


class TestSingleUse:
    def test_second_execute_refused(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter()
        first = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert first["status"] == "filled"
        second = live_executor.execute_approved(
            aid, live_executor.FakeMt5OrderAdapter(), _demo_cfg())
        assert second["status"] == "refused"
        assert "consumed" in second["reason"]

    def test_errored_send_also_consumes(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter(
            send_result={"error": "off quotes"})
        first = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert first["status"] == "error"
        second = live_executor.execute_approved(
            aid, live_executor.FakeMt5OrderAdapter(), _demo_cfg())
        assert second["status"] == "refused"
        assert "consumed" in second["reason"]

    def test_consumption_survives_process_restart(self) -> None:
        aid = _ready()
        live_executor.execute_approved(
            aid, live_executor.FakeMt5OrderAdapter(), _demo_cfg())
        # Simulate a fresh process: wipe the in-memory set ONLY; the
        # executions.jsonl on disk must still refuse the replay.
        with live_executor._LOCK:
            live_executor._CONSUMED.clear()
        result = live_executor.execute_approved(
            aid, live_executor.FakeMt5OrderAdapter(), _demo_cfg())
        assert result["status"] == "refused"
        assert "consumed" in result["reason"]

    def test_refusal_does_not_consume(self) -> None:
        """A pre-send refusal (volume cap here) must not burn the
        human's approval -- fix the config, execute again, it fills."""
        aid = _ready(aid_size=0.01)
        result = live_executor.execute_approved(
            aid, live_executor.FakeMt5OrderAdapter(),
            _demo_cfg(max_volume_lots=0.005))
        assert result["status"] == "refused"
        retry = live_executor.execute_approved(
            aid, live_executor.FakeMt5OrderAdapter(), _demo_cfg())
        assert retry["status"] == "filled"


class TestErrorPaths:
    def test_unknown_approval_id(self) -> None:
        result = live_executor.execute_approved(
            "apr_nope", live_executor.FakeMt5OrderAdapter(), _demo_cfg())
        assert result["status"] == "refused"
        assert "unknown" in result["reason"]

    def test_volume_above_cap_refused(self) -> None:
        aid = _ready(aid_size=0.5)
        adapter = live_executor.FakeMt5OrderAdapter()
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "refused"
        assert "max_volume_lots" in result["reason"]
        assert not any(c[0] == "send_market_order" for c in adapter.calls)

    def test_connect_refused_is_a_refusal_not_error(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter(connect_ok=False)
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "refused"
        assert "connect" in result["reason"]

    def test_connect_raising_is_contained(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter(connect_raises=True)
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "refused"
        assert "connect failed" in result["reason"]

    def test_send_raising_becomes_error_and_alert(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter(send_raises=True)
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "error"
        assert "adapter raised" in result["reason"]
        events = [e for e in alerts.recent(10)
                  if e["type"] == "trade_fill"]
        assert events and events[0]["payload"]["status"] == "error"

    def test_error_send_publishes_error_alert(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter(
            send_result={"error": "requote"})
        live_executor.execute_approved(aid, adapter, _demo_cfg())
        events = [e for e in alerts.recent(10)
                  if e["type"] == "trade_fill"]
        assert len(events) == 1
        assert events[0]["payload"]["status"] == "error"
        assert events[0]["payload"]["reason"] == "requote"

    def test_no_ticket_in_result_is_an_error(self) -> None:
        aid = _ready()
        adapter = live_executor.FakeMt5OrderAdapter(send_result={})
        result = live_executor.execute_approved(aid, adapter, _demo_cfg())
        assert result["status"] == "error"

    def test_refusals_are_recorded_in_audit_trail(self) -> None:
        result = live_executor.execute_approved(
            "apr_nope", live_executor.FakeMt5OrderAdapter(), _demo_cfg())
        assert result["status"] == "refused"
        rows = live_executor.recent_executions()
        assert len(rows) == 1
        assert rows[0]["status"] == "refused"


# ---------------------------------------------------------------------
# audit trail + status
# ---------------------------------------------------------------------

class TestRecentExecutions:
    def test_empty_when_no_file(self) -> None:
        assert live_executor.recent_executions() == []

    def test_newest_first_and_limited(self) -> None:
        for i in range(5):
            live_executor._append_execution(
                {"at": f"2026-07-24T00:0{i}:00Z",
                 "approval_id": f"apr_{i}", "status": "refused",
                 "reason": "fixture"})
        rows = live_executor.recent_executions(limit=3)
        assert len(rows) == 3
        assert rows[0]["approval_id"] == "apr_4"

    def test_corrupt_lines_skipped(self) -> None:
        path = credentials._config_dir() / \
            live_executor.EXECUTIONS_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"approval_id": "apr_ok", "status": "filled"}\n'
                        "{broken\n", encoding="utf-8")
        rows = live_executor.recent_executions()
        assert len(rows) == 1


class TestExecutorStatus:
    def test_disabled_by_default(self) -> None:
        status = live_executor.executor_status({})
        assert status["enabled"] is False
        assert status["state"] == "disabled"

    def test_ready_when_enabled_and_adapter_available(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(live_executor, "adapter_available",
                            lambda: True)
        status = live_executor.executor_status(_demo_cfg())
        assert status["state"] == "ready"

    def test_not_on_windows_when_adapter_missing(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(live_executor, "adapter_available",
                            lambda: False)
        status = live_executor.executor_status(_demo_cfg())
        assert status["state"] == "not-on-windows"

    def test_status_never_echoes_credentials(self) -> None:
        _store_creds()
        status = live_executor.executor_status(_demo_cfg())
        text = json.dumps(status)
        assert "not-a-real-password-fixture" not in text
        assert "password" not in text
        assert status["broker_alias_configured"] is True

    def test_state_values_are_documented(self) -> None:
        for cfg in ({}, _demo_cfg()):
            assert live_executor.executor_status(cfg)["state"] in \
                live_executor.EXECUTOR_STATES

    def test_recent_executions_included(self) -> None:
        aid = _ready()
        live_executor.execute_approved(
            aid, live_executor.FakeMt5OrderAdapter(), _demo_cfg())
        status = live_executor.executor_status(_demo_cfg())
        assert len(status["recent_executions"]) == 1


class TestAdapterSeam:
    def test_adapter_available_is_bool(self) -> None:
        assert isinstance(live_executor.adapter_available(), bool)

    def test_real_adapter_constructs_without_mt5(self) -> None:
        # The lazy-import contract: constructing must never import
        # MetaTrader5 (this suite runs on macOS where it can't exist).
        adapter = live_executor.RealMt5OrderAdapter()
        assert adapter._connected is False

    def test_real_adapter_connect_refuses_unknown_alias(self) -> None:
        # No creds stored -> connect returns False BEFORE any
        # MetaTrader5 import is attempted.
        adapter = live_executor.RealMt5OrderAdapter()
        assert adapter.connect("no-such-alias") is False

    def test_fake_adapter_records_calls(self) -> None:
        fake = live_executor.FakeMt5OrderAdapter()
        fake.connect("x")
        fake.account_info()
        fake.send_market_order("EURUSD", "buy", 0.01, 1.0, 2.0)
        fake.close_position(7)
        fake.shutdown()
        assert [c[0] for c in fake.calls] == [
            "connect", "account_info", "send_market_order",
            "close_position", "shutdown"]
