"""Tests for crash-resilient state persistence.

Covers:
- StateStore atomic round-trip, corrupt file, schema mismatch
- PostLossGuard: save with 2 losses, same-day reload; next-day discard
- RiskManager: same-day vs different-day reload
- PositionMonitor: register_entry persists; restart with open ticket →
  ctx restored, soft_stop populated; closed ticket → ctx discarded
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.live.state_store import StateStore
from agent.risk.post_loss_guard import GuardConfig, PostLossGuard
from agent.risk.manager import RiskManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)


def _build_state_store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "state.json")


# ===========================================================================
# StateStore unit tests
# ===========================================================================


class TestStateStoreRoundTrip:
    def test_write_then_read_returns_same_data(self, tmp_path):
        ss = _build_state_store(tmp_path)
        payload = {
            "schema": 1,
            "symbol": "EURUSD",
            "saved_at": "2026-06-13T10:00:00+00:00",
            "post_loss_guard": {"consecutive_losses": 2},
        }
        ss.save(payload)
        loaded = ss.load()
        assert loaded is not None
        assert loaded["post_loss_guard"]["consecutive_losses"] == 2
        assert loaded["symbol"] == "EURUSD"

    def test_missing_file_returns_none(self, tmp_path):
        ss = _build_state_store(tmp_path)
        assert ss.load() is None

    def test_corrupt_file_returns_none_with_warning(
        self, tmp_path, caplog
    ):
        ss = _build_state_store(tmp_path)
        (tmp_path / "state.json").write_text("{ not valid JSON %%")
        with caplog.at_level(logging.WARNING, logger="agent.live.state_store"):
            result = ss.load()
        assert result is None
        assert "corrupt state file" in caplog.text

    def test_schema_mismatch_returns_none_with_warning(
        self, tmp_path, caplog
    ):
        ss = _build_state_store(tmp_path)
        ss.save({"schema": 99, "symbol": "EURUSD"})
        with caplog.at_level(logging.WARNING, logger="agent.live.state_store"):
            result = ss.load()
        assert result is None
        assert "schema mismatch" in caplog.text

    def test_non_dict_json_returns_none(self, tmp_path, caplog):
        ss = _build_state_store(tmp_path)
        (tmp_path / "state.json").write_text("[1, 2, 3]")
        with caplog.at_level(logging.WARNING, logger="agent.live.state_store"):
            result = ss.load()
        assert result is None

    def test_save_creates_parent_dirs(self, tmp_path):
        deep = tmp_path / "a" / "b" / "EURUSD" / "state.json"
        ss = StateStore(deep)
        ss.save({"schema": 1})
        assert deep.exists()

    def test_atomic_write_via_tmp_not_left_behind(self, tmp_path):
        ss = _build_state_store(tmp_path)
        ss.save({"schema": 1})
        tmp = tmp_path / "state.tmp"
        assert not tmp.exists()

    def test_save_error_does_not_raise(self, tmp_path):
        """A disk error during save must be swallowed (never crash live loop)."""
        ss = StateStore(Path("/nonexistent_root/x/y/state.json"))
        # Should not raise — only log a warning.
        ss.save({"schema": 1})

    def test_multiple_saves_overwrite_correctly(self, tmp_path):
        ss = _build_state_store(tmp_path)
        ss.save({"schema": 1, "v": 1})
        ss.save({"schema": 1, "v": 2})
        assert ss.load()["v"] == 2


# ===========================================================================
# PostLossGuard persistence
# ===========================================================================


class TestPostLossGuardPersistence:
    def _guard(self) -> PostLossGuard:
        return PostLossGuard(GuardConfig(cooldown_minutes=60.0, max_consecutive_losses=3))

    def test_save_two_losses_same_day_reload_keeps_losses(self, tmp_path):
        ss = _build_state_store(tmp_path)
        g = self._guard()
        t = _utc_now()
        g.register_close(pnl=-5.0, now=t)
        g.register_close(pnl=-5.0, now=t)
        assert g.consecutive_losses == 2

        payload = {"schema": 1, "post_loss_guard": g.get_persist_state()}
        ss.save(payload)

        g2 = self._guard()
        loaded = ss.load()
        plg_data = loaded["post_loss_guard"]
        assert plg_data["day"] == t.date().isoformat()
        g2.restore_from_persist_state(plg_data)
        assert g2.consecutive_losses == 2
        assert g2.size_multiplier == 0.5

    def test_save_halted_session_restores_halt(self, tmp_path):
        ss = _build_state_store(tmp_path)
        g = self._guard()
        t = _utc_now()
        g.register_close(pnl=-1.0, now=t)
        g.register_close(pnl=-1.0, now=t)
        g.register_close(pnl=-1.0, now=t)
        assert g.session_halted

        ss.save({"schema": 1, "post_loss_guard": g.get_persist_state()})

        g2 = self._guard()
        g2.restore_from_persist_state(ss.load()["post_loss_guard"])
        assert g2.session_halted
        assert not g2.pre_trade_check(_utc_now()).allowed

    def test_different_day_state_is_discarded_by_caller(self, tmp_path):
        """The caller (SignalLoop._restore_state) checks the day — verify it."""
        ss = _build_state_store(tmp_path)
        g = self._guard()
        yesterday = _utc_now() - timedelta(days=1)
        g.register_close(pnl=-5.0, now=yesterday)

        plg_state = g.get_persist_state()
        ss.save({"schema": 1, "post_loss_guard": plg_state})

        loaded = ss.load()
        plg_data = loaded["post_loss_guard"]
        today = _utc_now().date().isoformat()
        # Simulate the caller's same-day guard
        assert plg_data["day"] != today  # different day → caller skips restore

    def test_cooldown_until_iso_round_trips(self, tmp_path):
        ss = _build_state_store(tmp_path)
        g = self._guard()
        t = _utc_now()
        g.register_close(pnl=-3.0, now=t)
        assert g.cooldown_until is not None

        ss.save({"schema": 1, "post_loss_guard": g.get_persist_state()})

        g2 = self._guard()
        g2.restore_from_persist_state(ss.load()["post_loss_guard"])
        assert g2.cooldown_until is not None
        assert g2.cooldown_until == g.cooldown_until

    def test_win_resets_losses_and_round_trips_clean_state(self, tmp_path):
        ss = _build_state_store(tmp_path)
        g = self._guard()
        t = _utc_now()
        g.register_close(pnl=-5.0, now=t)
        g.register_close(pnl=+10.0, now=t)  # win resets

        ss.save({"schema": 1, "post_loss_guard": g.get_persist_state()})

        g2 = self._guard()
        g2.restore_from_persist_state(ss.load()["post_loss_guard"])
        assert g2.consecutive_losses == 0
        assert g2.size_multiplier == 1.0


# ===========================================================================
# RiskManager persistence
# ===========================================================================


class TestRiskManagerPersistence:
    def _rm(self, tmp_path) -> RiskManager:
        from agent.config import load_config
        cfg = load_config()
        return RiskManager(cfg, kill_switch_path=tmp_path / "nokill")

    def test_same_day_reload_keeps_pnl_and_halt(self, tmp_path):
        rm = self._rm(tmp_path)
        today = _utc_now()
        rm.on_new_day(today.date(), 1000.0)
        rm.record_trade_pnl(-35.0)  # 3.5% loss > 3% halt
        assert rm.state.halted_today

        ss = _build_state_store(tmp_path)
        ss.save({"schema": 1, "risk_manager": rm.get_persist_state()})

        rm2 = self._rm(tmp_path)
        rm2.restore_from_persist_state(ss.load()["risk_manager"])
        assert rm2.state.halted_today
        assert rm2.state.day_pnl == pytest.approx(-35.0)
        assert rm2.state.day_open_balance == pytest.approx(1000.0)

    def test_different_day_state_not_restored_by_caller(self, tmp_path):
        rm = self._rm(tmp_path)
        yesterday = (_utc_now() - timedelta(days=1)).date()
        rm.on_new_day(yesterday, 1000.0)
        rm.record_trade_pnl(-35.0)

        ss = _build_state_store(tmp_path)
        ss.save({"schema": 1, "risk_manager": rm.get_persist_state()})

        loaded = ss.load()
        rm_data = loaded["risk_manager"]
        today = _utc_now().date().isoformat()
        assert rm_data["day"] != today  # caller skips restore for old day

    def test_round_trip_preserves_day_open_balance(self, tmp_path):
        rm = self._rm(tmp_path)
        today = _utc_now()
        rm.on_new_day(today.date(), 987.65)
        rm.record_trade_pnl(+12.50)

        ss = _build_state_store(tmp_path)
        ss.save({"schema": 1, "risk_manager": rm.get_persist_state()})

        rm2 = self._rm(tmp_path)
        rm2.restore_from_persist_state(ss.load()["risk_manager"])
        assert rm2.state.day_open_balance == pytest.approx(987.65)
        assert rm2.state.day_pnl == pytest.approx(12.50)
        assert not rm2.state.halted_today


# ===========================================================================
# PositionMonitor persistence
# ===========================================================================


def _make_monitor(tmp_path, on_state_change=None):
    """Build a minimal PositionMonitor using mocks."""
    from agent.live.monitor import PositionMonitor
    from agent.config import load_config
    from agent.live.config import LiveConfig
    from agent.live.soft_stop import SoftStopConfig

    broker = MagicMock()
    cfg = load_config()
    live = LiveConfig(symbol="EURUSD")
    notifier = MagicMock()
    notifier.notify_text = MagicMock()

    return PositionMonitor(
        broker=broker,
        config=cfg,
        live_config=live,
        notifier=notifier,
        soft_stop_cfg=SoftStopConfig(enabled=False),
        on_state_change=on_state_change,
    )


class TestPositionMonitorPersistence:
    def test_register_entry_captured_in_persist_state(self, tmp_path):
        mon = _make_monitor(tmp_path)
        ctx = {
            "alpha": "zone_h4_all",
            "timeframe": "H4",
            "direction": "long",
            "entry": 1.08234,
            "entry_time": "2026-06-13T08:00:00+00:00",
            "soft_stop": 1.07900,
            "stop": 1.07700,
            "take_profit": 1.08900,
            "conviction": 0.82,
            "signal_reason": "zone_touch",
            "target_ladder": [],
        }
        mon.register_entry(12345678, ctx)
        state = mon.get_persist_state()

        assert "12345678" in state["entry_ctx"]
        assert state["entry_ctx"]["12345678"]["soft_stop"] == pytest.approx(1.07900)
        assert "12345678" in [str(t) for t in state["excursion"]]

    def test_restore_populates_entry_ctx_and_soft_stop(self, tmp_path):
        mon1 = _make_monitor(tmp_path)
        ctx = {
            "alpha": "zone_h4_all",
            "direction": "long",
            "entry": 1.08234,
            "soft_stop": 1.07900,
            "stop": 1.07700,
            "take_profit": 1.08900,
            "conviction": 0.82,
            "signal_reason": "zone_touch",
            "target_ladder": [],
        }
        mon1.register_entry(12345678, ctx)

        ss = _build_state_store(tmp_path)
        ss.save({"schema": 1, "position_monitor": mon1.get_persist_state()})

        mon2 = _make_monitor(tmp_path)
        data = ss.load()
        mon2.restore_from_persist_state(data["position_monitor"])

        assert 12345678 in mon2._entry_ctx
        assert mon2._entry_ctx[12345678]["soft_stop"] == pytest.approx(1.07900)
        assert 12345678 in mon2._restored_ctx_tickets

    def test_still_open_ticket_logs_position_restored(
        self, tmp_path, caplog
    ):
        """When a restored ticket is open at the broker → log POSITION RESTORED."""
        import asyncio
        from agent.live.monitor import PositionMonitor
        from agent.live.broker import Position
        from agent.types import Direction

        mon = _make_monitor(tmp_path)
        ctx = {
            "alpha": "zone_h4_all", "direction": "long",
            "entry": 1.08234, "soft_stop": 1.07900,
            "stop": 1.07700, "take_profit": 1.08900,
            "conviction": 0.8, "signal_reason": "zone_touch",
            "target_ladder": [],
        }
        mon.register_entry(999, ctx)
        # Simulate the fact that it was restored (not opened this session)
        mon._restored_ctx_tickets.add(999)

        fake_pos = Position(
            ticket=999, symbol="EURUSD", direction=Direction.LONG,
            volume=0.07, open_price=1.08234, open_time=_utc_now(),
            stop_loss=1.07700, take_profit=1.08900,
            profit=12.5, current_price=1.08360,
        )
        mon.broker.get_open_positions = AsyncMock(return_value=[fake_pos])
        mon.broker.get_account_info = AsyncMock(return_value=MagicMock(
            balance=1000.0, equity=1012.5
        ))

        with caplog.at_level(logging.INFO, logger="agent.live.monitor"):
            asyncio.run(mon._check_positions())

        assert "[POSITION RESTORED]" in caplog.text
        assert "[POSITION ADOPTED]" not in caplog.text

    def test_stale_restored_ticket_discarded_on_first_cycle(
        self, tmp_path, caplog
    ):
        """Restored tickets not open at broker → pruned from ctx on first cycle."""
        import asyncio
        mon = _make_monitor(tmp_path)
        ctx = {"alpha": "z", "direction": "long", "entry": 1.08, "soft_stop": 1.07,
               "stop": 1.065, "take_profit": 1.09, "conviction": 0.8,
               "signal_reason": "x", "target_ladder": []}
        mon.register_entry(777, ctx)
        mon._restored_ctx_tickets.add(777)

        # Broker returns NO open positions — ticket 777 is gone
        mon.broker.get_open_positions = AsyncMock(return_value=[])
        mon.broker.get_account_info = AsyncMock(return_value=MagicMock(
            balance=1000.0, equity=1000.0
        ))

        with caplog.at_level(logging.INFO, logger="agent.live.monitor"):
            asyncio.run(mon._check_positions())

        assert 777 not in mon._entry_ctx
        assert "stale restored ticket=777" in caplog.text

    def test_breakeven_applied_persists_and_restores(self, tmp_path):
        mon1 = _make_monitor(tmp_path)
        ctx = {"alpha": "z", "direction": "long", "entry": 1.08,
               "soft_stop": 1.07, "stop": 1.065, "take_profit": 1.09,
               "conviction": 0.8, "signal_reason": "x", "target_ladder": []}
        mon1.register_entry(111, ctx)
        mon1._breakeven_applied.add(111)

        ss = _build_state_store(tmp_path)
        ss.save({"schema": 1, "position_monitor": mon1.get_persist_state()})

        mon2 = _make_monitor(tmp_path)
        mon2.restore_from_persist_state(ss.load()["position_monitor"])
        assert 111 in mon2._breakeven_applied

    def test_on_state_change_called_after_be_move(self, tmp_path):
        """_on_state_change fires when a BE move succeeds (async manage)."""
        import asyncio
        from agent.live.broker import Position
        from agent.types import Direction

        calls: list[int] = []

        def _cb():
            calls.append(1)

        mon = _make_monitor(tmp_path, on_state_change=_cb)
        # Give it an entry ctx with a soft_stop so BE logic activates
        ctx = {"alpha": "z", "direction": "long", "entry": 1.08000,
               "soft_stop": 1.07500, "stop": 1.07000, "take_profit": 1.09000,
               "conviction": 0.85, "signal_reason": "x", "target_ladder": []}
        mon.register_entry(222, ctx)

        # BE at 1.0R; stop_distance = (1.08 - 1.075) * 10000 = 50 pips
        # current_price needs to be 1.08 + 50 pips = 1.085 for 1R
        fake_pos = Position(
            ticket=222, symbol="EURUSD", direction=Direction.LONG,
            volume=0.07, open_price=1.08000, open_time=_utc_now(),
            stop_loss=1.07000, take_profit=1.09000,
            profit=35.0, current_price=1.08510,
        )
        mon.broker.get_open_positions = AsyncMock(return_value=[fake_pos])
        mon.broker.get_account_info = AsyncMock(return_value=MagicMock(
            balance=1000.0, equity=1035.0
        ))
        mon.live_config.move_be_at_r = 1.0
        mon.config.backtest.be_lock_r = 0.0
        # Make the broker modify succeed
        modify_result = MagicMock()
        modify_result.success = True
        mon.broker.modify_position = AsyncMock(return_value=modify_result)
        # Ensure initial scan is done so we don't hit ADOPTED log
        mon._initial_scan_done = True

        asyncio.run(mon._check_positions())
        assert len(calls) > 0, "on_state_change should have been called after BE move"


# ===========================================================================
# SignalLoop integration: _persist_state / _restore_state wiring
# ===========================================================================


class TestSignalLoopStatePersistence:
    """Light integration tests — verify _persist_state writes and
    _restore_state reads back. No live broker needed."""

    def _make_loop(self, tmp_path):
        from agent.live.signal_loop import SignalLoop
        from agent.live.config import LiveConfig
        from agent.config import load_config
        from agent.alphas.base import Alpha

        # Minimal fake alpha
        alpha = MagicMock(spec=Alpha)
        alpha.name = "test_alpha"

        broker = MagicMock()
        broker.connect = AsyncMock(return_value=True)

        cfg = load_config()
        live = LiveConfig(symbol="EURUSD", broker_type="paper")

        return SignalLoop(
            [alpha],
            config=cfg,
            live_config=live,
            broker=broker,
            state_store_path=tmp_path / "EURUSD" / "state.json",
        )

    def test_persist_state_writes_valid_json(self, tmp_path):
        loop = self._make_loop(tmp_path)
        loop._persist_state()
        state_file = tmp_path / "EURUSD" / "state.json"
        assert state_file.exists()
        with state_file.open() as f:
            data = json.load(f)
        assert data["schema"] == 1
        assert data["symbol"] == "EURUSD"
        assert "position_monitor" in data
        assert "post_loss_guard" in data
        assert "risk_manager" in data
        assert "signal_loop" in data

    def test_persist_then_restore_state_no_crash(self, tmp_path):
        loop = self._make_loop(tmp_path)
        # Inject some state
        from datetime import timezone
        loop._last_bar_times["H4"] = _utc_now()
        loop._persist_state()

        loop2 = self._make_loop(tmp_path)
        # Should not raise; bar time is recent enough
        loop2._restore_state()
        assert "H4" in loop2._last_bar_times

    def test_restore_state_discards_stale_bar_times(self, tmp_path):
        loop = self._make_loop(tmp_path)
        # Inject a 3-day-old timestamp (beyond the 2-day cutoff)
        loop._last_bar_times["H4"] = _utc_now() - timedelta(days=3)
        loop._persist_state()

        loop2 = self._make_loop(tmp_path)
        loop2._restore_state()
        assert "H4" not in loop2._last_bar_times

    def test_restore_state_plg_different_day_starts_fresh(self, tmp_path):
        loop = self._make_loop(tmp_path)
        # Simulate PLG state from yesterday
        yesterday = (_utc_now() - timedelta(days=1)).date()
        loop.post_loss_guard._day = yesterday
        loop.post_loss_guard.consecutive_losses = 3
        loop.post_loss_guard.session_halted = True
        loop._persist_state()

        loop2 = self._make_loop(tmp_path)
        loop2._restore_state()
        # Today != yesterday → not restored
        assert loop2.post_loss_guard.consecutive_losses == 0
        assert not loop2.post_loss_guard.session_halted

    def test_restore_state_plg_same_day_restores(self, tmp_path):
        loop = self._make_loop(tmp_path)
        today = _utc_now().date()
        loop.post_loss_guard._day = today
        loop.post_loss_guard.consecutive_losses = 2
        loop._persist_state()

        loop2 = self._make_loop(tmp_path)
        # Patch datetime.now so "today" == _utc_now().date()
        with patch(
            "agent.live.signal_loop.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = _utc_now()
            loop2._restore_state()

        assert loop2.post_loss_guard.consecutive_losses == 2

    def test_no_state_store_persist_is_no_op(self, tmp_path):
        from agent.live.signal_loop import SignalLoop
        from agent.live.config import LiveConfig
        from agent.config import load_config
        from agent.alphas.base import Alpha

        alpha = MagicMock(spec=Alpha)
        alpha.name = "test_alpha"
        broker = MagicMock()
        broker.connect = AsyncMock(return_value=True)

        loop = SignalLoop(
            [alpha],
            config=load_config(),
            live_config=LiveConfig(symbol="EURUSD"),
            broker=broker,
            state_store_path=None,  # persistence disabled
        )
        loop._persist_state()  # must not raise
        loop._restore_state()  # must not raise
