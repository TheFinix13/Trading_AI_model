"""Live-loop observability: the 15-minute heartbeat line, the next-H4-close
helper it embeds, and the per-candle "evaluated, no setup" line.

All pure logging — these tests also pin that no broker round-trips are added
(the heartbeat reads the monitor's cached snapshot; the no-setup line fires
inside the existing per-close evaluation).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.alphas.base import Alpha
from agent.config import load_config
from agent.live.config import LiveConfig
from agent.live.signal_loop import (
    _HEARTBEAT_INTERVAL_SECONDS,
    SignalLoop,
    next_h4_close_utc,
)
from agent.types import Bar, Timeframe


# ----------------------------------------------------------------------
# next_h4_close_utc — H4 boundaries are 00/04/08/12/16/20 UTC
# ----------------------------------------------------------------------

def _utc(h, m=0, s=0):
    return datetime(2026, 6, 10, h, m, s, tzinfo=timezone.utc)


def test_next_h4_close_mid_period():
    assert next_h4_close_utc(_utc(13, 14)) == _utc(16, 0)


def test_next_h4_close_exactly_on_boundary_is_next_period():
    # At 16:00:00 the 16:00 close just happened — next one is 20:00.
    assert next_h4_close_utc(_utc(16, 0, 0)) == _utc(20, 0)


def test_next_h4_close_one_second_before_boundary():
    assert next_h4_close_utc(_utc(15, 59, 59)) == _utc(16, 0)


def test_next_h4_close_wraps_to_next_day():
    nxt = next_h4_close_utc(_utc(22, 30))
    assert nxt == datetime(2026, 6, 11, 0, 0, tzinfo=timezone.utc)


# ----------------------------------------------------------------------
# Heartbeat line format
# ----------------------------------------------------------------------

class _FlatAlpha(Alpha):
    """Alpha that never signals — exercises the no-setup path."""
    name = "flat"

    def signal(self, actx, i):
        return None


class _FakeBroker:
    """Minimal async stub — never touches MT5 / network."""

    def __init__(self, bars=None):
        self._bars = bars or []

    async def get_latest_bars(self, symbol, timeframe, count=300):
        return self._bars

    async def get_account_info(self):  # pragma: no cover - not exercised
        return SimpleNamespace(balance=10_000.0, equity=10_000.0,
                               leverage=500, free_margin=10_000.0)

    async def get_open_positions(self, symbol):  # pragma: no cover
        return []

    async def connect(self):  # pragma: no cover - not exercised
        return True

    async def disconnect(self):  # pragma: no cover - not exercised
        return None


def _make_loop(bars=None) -> SignalLoop:
    cfg = load_config()
    live = LiveConfig(symbol="EURUSD", timeframes=["H4"],
                      telegram_enabled=False, revenge_guard_enabled=False)
    return SignalLoop([_FlatAlpha()], config=cfg, live_config=live,
                      broker=_FakeBroker(bars))


def _force_heartbeat_due(loop: SignalLoop) -> None:
    loop._last_heartbeat = (datetime.now(tz=timezone.utc)
                            - timedelta(seconds=_HEARTBEAT_INTERVAL_SECONDS + 1))


def test_heartbeat_logs_balance_equity_positions_and_next_close(caplog):
    loop = _make_loop()
    # Simulate the monitor's 5s cycle snapshot — the heartbeat must read it
    # rather than calling the broker itself.
    loop.monitor.last_account = SimpleNamespace(balance=10_000.0, equity=10_005.25)
    loop.monitor.last_open_position_count = 1
    _force_heartbeat_due(loop)

    with caplog.at_level(logging.INFO, logger="agent.live.signal_loop"):
        loop._maybe_heartbeat()

    lines = [r.message for r in caplog.records if r.message.startswith("heartbeat:")]
    assert len(lines) == 1
    line = lines[0]
    assert "balance=$10000.00" in line
    assert "equity=$10005.25" in line
    assert "open_positions=1" in line
    assert "| next H4 close ~" in line
    expected = next_h4_close_utc(datetime.now(tz=timezone.utc)).strftime("%H:%M")
    assert f"~{expected} UTC" in line


def test_heartbeat_without_monitor_snapshot_omits_balance(caplog):
    loop = _make_loop()  # monitor.last_account is still None
    _force_heartbeat_due(loop)
    with caplog.at_level(logging.INFO, logger="agent.live.signal_loop"):
        loop._maybe_heartbeat()
    lines = [r.message for r in caplog.records if r.message.startswith("heartbeat:")]
    assert len(lines) == 1
    assert "balance=$" not in lines[0]
    assert "next H4 close ~" in lines[0]


def test_heartbeat_respects_interval(caplog):
    loop = _make_loop()
    loop._last_heartbeat = datetime.now(tz=timezone.utc)  # not due yet
    with caplog.at_level(logging.INFO, logger="agent.live.signal_loop"):
        loop._maybe_heartbeat()
    assert not [r for r in caplog.records if r.message.startswith("heartbeat:")]


# ----------------------------------------------------------------------
# Healthcheck ping must survive the kill switch: halted-but-alive must
# never look like downtime to the external watchdog (July 11-12 false
# DOWN alerts while the agents were halted by kill.txt)
# ----------------------------------------------------------------------

def test_heartbeat_pings_healthcheck_when_running(tmp_path):
    loop = _make_loop()
    loop.live_config.kill_file = str(tmp_path / "absent-kill.txt")
    loop.healthcheck = MagicMock()
    _force_heartbeat_due(loop)
    loop._maybe_heartbeat()
    loop.healthcheck.ping.assert_called_once_with()


def test_heartbeat_pings_healthcheck_with_halted_note_when_kill_switch_active(
        tmp_path, caplog):
    loop = _make_loop()
    kill = tmp_path / "kill.txt"
    kill.write_text("Auto-kill: Daily DD halt: 3.0% (limit 3.0%)\n")
    loop.live_config.kill_file = str(kill)
    loop.healthcheck = MagicMock()
    _force_heartbeat_due(loop)

    with caplog.at_level(logging.INFO, logger="agent.live.signal_loop"):
        loop._maybe_heartbeat()

    # Success ping still fires (the process IS alive), annotated so the
    # healthchecks.io event log shows the halt context.
    loop.healthcheck.ping.assert_called_once()
    body = loop.healthcheck.ping.call_args[0][0]
    assert "HALTED" in body
    assert "EURUSD" in body
    # ping_fail is reserved for genuine process death, not risk halts.
    loop.healthcheck.ping_fail.assert_not_called()
    lines = [r.message for r in caplog.records if r.message.startswith("heartbeat:")]
    assert len(lines) == 1
    assert "HALTED" in lines[0]


def test_heartbeat_annotates_daily_dd_halt_as_self_clearing(tmp_path, caplog):
    """A clean daily-DD auto-kill heartbeat says it will re-arm at the next
    UTC rollover (so the operator knows NOT to rush to the VM)."""
    loop = _make_loop()
    kill = tmp_path / "kill.txt"
    kill.write_text("Auto-kill: Daily DD halt: 3.0% (limit 3.0%)\n"
                    "2026-07-10T02:15:16+00:00\n")
    loop.live_config.kill_file = str(kill)
    loop.healthcheck = MagicMock()
    _force_heartbeat_due(loop)
    with caplog.at_level(logging.INFO, logger="agent.live.signal_loop"):
        loop._maybe_heartbeat()
    line = [r.message for r in caplog.records
            if r.message.startswith("heartbeat:")][0]
    assert "re-arms at next UTC rollover" in line
    body = loop.healthcheck.ping.call_args[0][0]
    assert "re-arms at next UTC rollover" in body


def test_heartbeat_annotates_manual_kill_as_sticky(tmp_path, caplog):
    loop = _make_loop()
    kill = tmp_path / "kill.txt"
    kill.write_text("manual: operator stop\n")
    loop.live_config.kill_file = str(kill)
    loop.healthcheck = MagicMock()
    _force_heartbeat_due(loop)
    with caplog.at_level(logging.INFO, logger="agent.live.signal_loop"):
        loop._maybe_heartbeat()
    line = [r.message for r in caplog.records
            if r.message.startswith("heartbeat:")][0]
    assert "manual clear required" in line


# ----------------------------------------------------------------------
# "evaluated, no setup" line at each candle-close evaluation
# ----------------------------------------------------------------------

def _h4_bars(n: int) -> list[Bar]:
    start = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        px = 1.10 + 0.0001 * (i % 7)
        bars.append(Bar(
            time=start + timedelta(hours=4 * i),
            open=px, high=px + 0.0010, low=px - 0.0010, close=px + 0.0002,
            volume=100.0, timeframe=Timeframe.H4,
        ))
    return bars


def test_no_setup_line_logged_on_new_close_only_once(caplog):
    bars = _h4_bars(150)
    loop = _make_loop(bars)
    with caplog.at_level(logging.INFO, logger="agent.live.signal_loop"):
        asyncio.run(loop._check_for_signals("H4"))
        asyncio.run(loop._check_for_signals("H4"))  # same bar — no repeat

    lines = [r.message for r in caplog.records if "no setup" in r.message]
    assert len(lines) == 1
    line = lines[0]
    # Close label = the closed bar's OPEN time + 4h, i.e. the actual close.
    last_closed = bars[-2]
    expected_label = (last_closed.time + timedelta(hours=4)).strftime("%H:%M")
    assert line.startswith(f"H4 close {expected_label} UTC: evaluated, no setup")
    assert "flat" in line  # names the alphas that were checked
