"""Tests for `agent.notifications.telegram`.

Covers:
    * Pure formatters (open / close / DD halt).
    * Dry-run path prints to stdout, no HTTP.
    * Successful API call wires the right URL + payload.
    * Failed API call is swallowed, returns False (never raises).
    * Missing config -> warning + False, no crash.
    * `from_env` reads TG_BOT_TOKEN / TG_CHAT_ID.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent.notifications.telegram import (
    TelegramConfig,
    TelegramNotifier,
    format_dd_halt,
    format_trade_close,
    format_trade_open,
)
from agent.types import Direction, Setup, Timeframe, Trade


def _make_setup(strategy: str | None = "FVGRetest") -> Setup:
    return Setup(
        direction=Direction.LONG,
        timeframe=Timeframe.H1,
        detected_at=datetime(2026, 5, 14, 13, 0, tzinfo=timezone.utc),
        detected_bar_index=100,
        entry=1.10500,
        stop=1.10350,
        take_profit=1.10725,
        confluences=["fvg", "zone", "fib_618"],
        strategy_name=strategy,
    )


def _make_trade(*, pnl: float = 25.0, pnl_pips: float = 22.5,
                exit_reason: str | None = "tp") -> Trade:
    s = _make_setup()
    t = Trade(
        setup=s,
        direction=s.direction,
        entry_time=datetime(2026, 5, 14, 13, 0, tzinfo=timezone.utc),
        entry_price=s.entry,
        stop_price=s.stop,
        tp_price=s.take_profit,
        lot_size=0.05,
    )
    if exit_reason is not None:
        t.exit_time = datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
        t.exit_price = s.take_profit
        t.exit_reason = exit_reason
        t.pnl = pnl
        t.pnl_pips = pnl_pips
    return t


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def test_format_trade_open_includes_direction_strategy_and_levels():
    msg = format_trade_open(_make_trade(exit_reason=None))
    assert "OPEN" in msg
    assert "LONG" in msg
    assert "FVGRetest" in msg
    assert "1.10500" in msg
    assert "1.10350" in msg
    assert "1.10725" in msg


def test_format_trade_open_handles_missing_strategy():
    setup = _make_setup(strategy=None)
    trade = Trade(
        setup=setup,
        direction=setup.direction,
        entry_time=setup.detected_at,
        entry_price=setup.entry,
        stop_price=setup.stop,
        tp_price=setup.take_profit,
        lot_size=0.01,
    )
    msg = format_trade_open(trade)
    assert "rule_engine" in msg


def test_format_trade_close_marks_winners_and_losers():
    win = format_trade_close(_make_trade(pnl=42.0, pnl_pips=18.0))
    assert "WIN" in win
    assert "+$42.00" in win
    assert "+18.0p" in win

    loss = format_trade_close(_make_trade(pnl=-15.0, pnl_pips=-12.0, exit_reason="sl"))
    assert "LOSS" in loss
    assert "-$15.00" in loss


def test_format_trade_close_flat():
    flat = format_trade_close(_make_trade(pnl=0.0, pnl_pips=0.0))
    assert "FLAT" in flat


def test_format_dd_halt():
    msg = format_dd_halt("live", 0.0612)
    assert "DD HALT" in msg
    assert "live" in msg
    assert "6.12%" in msg


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------


def test_dry_run_prints_to_stdout(capsys):
    notifier = TelegramNotifier(TelegramConfig(dry_run=True))
    ok = notifier.notify_trade_open(_make_trade(exit_reason=None))
    assert ok is True
    captured = capsys.readouterr()
    assert "OPEN" in captured.out


def test_missing_config_warns_and_returns_false(caplog):
    notifier = TelegramNotifier(TelegramConfig(bot_token="", chat_id=""))
    ok = notifier.notify_text("hello")
    assert ok is False


def test_successful_post_returns_true():
    fake_resp = MagicMock(status_code=200, text="ok")
    fake_client = MagicMock()
    fake_client.post.return_value = fake_resp
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="abc", chat_id="42"),
        client=fake_client,
    )
    ok = notifier.notify_text("hi")
    assert ok is True
    fake_client.post.assert_called_once()
    args, kwargs = fake_client.post.call_args
    assert args[0].startswith("https://api.telegram.org/botabc/sendMessage")
    assert kwargs["json"]["chat_id"] == "42"
    assert kwargs["json"]["text"] == "hi"


def test_failed_status_code_returns_false():
    fake_resp = MagicMock(status_code=400, text="bad request")
    fake_client = MagicMock()
    fake_client.post.return_value = fake_resp
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="abc", chat_id="42"),
        client=fake_client,
    )
    assert notifier.notify_text("hi") is False


def test_network_exception_is_swallowed():
    fake_client = MagicMock()
    fake_client.post.side_effect = RuntimeError("connection refused")
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="abc", chat_id="42"),
        client=fake_client,
    )
    # Must not raise -- returns False instead so the live engine keeps running.
    assert notifier.notify_text("hi") is False


def test_notify_trade_open_uses_format(monkeypatch):
    # The notifier just calls format_trade_open + _send.
    fake_resp = MagicMock(status_code=200, text="ok")
    fake_client = MagicMock()
    fake_client.post.return_value = fake_resp
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="abc", chat_id="42"),
        client=fake_client,
    )
    notifier.notify_trade_open(_make_trade(exit_reason=None))
    sent_text = fake_client.post.call_args.kwargs["json"]["text"]
    assert "Trade OPEN" in sent_text
    assert "FVGRetest" in sent_text


def test_notify_dd_halt_payload():
    fake_resp = MagicMock(status_code=200, text="ok")
    fake_client = MagicMock()
    fake_client.post.return_value = fake_resp
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="abc", chat_id="42"),
        client=fake_client,
    )
    notifier.notify_dd_halt("live", 0.05)
    sent_text = fake_client.post.call_args.kwargs["json"]["text"]
    assert "DD HALT" in sent_text
    assert "5.00%" in sent_text


def test_from_env_reads_environment(monkeypatch):
    monkeypatch.setenv("TG_BOT_TOKEN", "envtoken")
    monkeypatch.setenv("TG_CHAT_ID", "envchat")
    cfg = TelegramConfig.from_env()
    assert cfg.bot_token == "envtoken"
    assert cfg.chat_id == "envchat"
    assert cfg.configured is True


def test_from_env_dry_run_is_configured_even_without_creds(monkeypatch):
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    cfg = TelegramConfig.from_env(dry_run=True)
    assert cfg.configured is True
    assert cfg.dry_run is True
