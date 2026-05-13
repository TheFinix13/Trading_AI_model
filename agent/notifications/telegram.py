"""Telegram notifier for trade events.

Reads `TG_BOT_TOKEN` and `TG_CHAT_ID` from the environment by default,
or accepts an explicit `TelegramConfig`. All HTTP calls go through
`httpx` (already a project dependency).

The notifier deliberately fails *open* -- if the network is broken or
the credentials are missing, it logs a warning but never raises. A
failed Telegram push must not crash a live trade or a backtest.

Public API:

    notifier = TelegramNotifier.from_env()
    notifier.notify_trade_open(trade)
    notifier.notify_trade_close(trade)
    notifier.notify_dd_halt(account, dd_pct=0.06)

Use `dry_run=True` (or pass `--dry-run` to scripts/notify_telegram.py)
to print messages to stdout instead of hitting the Telegram API.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

TELEGRAM_API_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    dry_run: bool = False
    timeout_seconds: float = 8.0
    parse_mode: str = "Markdown"  # Markdown / MarkdownV2 / HTML

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> "TelegramConfig":
        return cls(
            bot_token=os.getenv("TG_BOT_TOKEN", ""),
            chat_id=os.getenv("TG_CHAT_ID", ""),
            dry_run=dry_run,
        )

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id) or self.dry_run


# ---------------------------------------------------------------------------
# Message formatters. Pure -- no I/O. Tested in isolation.
# ---------------------------------------------------------------------------


def _fmt_pips(pips: float) -> str:
    sign = "+" if pips >= 0 else ""
    return f"{sign}{pips:.1f}p"


def _fmt_pnl(pnl: float) -> str:
    if pnl >= 0:
        return f"+${pnl:.2f}"
    return f"-${abs(pnl):.2f}"


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return getattr(obj, name, default)


def format_trade_open(trade) -> str:
    """Render a `Trade` (or duck-typed equivalent) as a 'just opened'
    Markdown message."""
    direction = _attr(trade, "direction", "?")
    direction_str = direction.value.upper() if hasattr(direction, "value") else str(direction).upper()
    setup = _attr(trade, "setup", None)
    strategy = _attr(setup, "strategy_name", None) or "rule_engine"
    confluences = _attr(setup, "confluences", []) or []
    entry = _attr(trade, "entry_price", 0.0)
    stop = _attr(trade, "stop_price", 0.0)
    tp = _attr(trade, "tp_price", 0.0)
    lot = _attr(trade, "lot_size", 0.0)
    when = _attr(trade, "entry_time", None)
    when_str = when.isoformat(timespec="minutes") if when else "?"

    lines = [
        f"*Trade OPEN* `{direction_str}` ({strategy})",
        f"`{when_str}` lot=`{lot:.2f}`",
        f"entry `{entry:.5f}`  stop `{stop:.5f}`  tp `{tp:.5f}`",
    ]
    if confluences:
        lines.append("conf: " + ", ".join(f"`{c}`" for c in confluences[:8]))
    return "\n".join(lines)


def format_trade_close(trade) -> str:
    """Render a closed `Trade` as a Markdown message with PnL."""
    direction = _attr(trade, "direction", "?")
    direction_str = direction.value.upper() if hasattr(direction, "value") else str(direction).upper()
    setup = _attr(trade, "setup", None)
    strategy = _attr(setup, "strategy_name", None) or "rule_engine"
    pnl = _attr(trade, "pnl", 0.0) or 0.0
    pnl_pips = _attr(trade, "pnl_pips", 0.0) or 0.0
    reason = _attr(trade, "exit_reason", "?") or "?"
    when = _attr(trade, "exit_time", None)
    when_str = when.isoformat(timespec="minutes") if when else "?"

    emoji = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"
    return (
        f"*Trade CLOSE* `{direction_str}` ({strategy}) -- *{emoji}*\n"
        f"`{when_str}` exit=`{reason}`\n"
        f"P&L: {_fmt_pnl(pnl)} ({_fmt_pips(pnl_pips)})"
    )


def format_dd_halt(account: str, dd_pct: float) -> str:
    """Drawdown circuit-breaker message."""
    return (
        f"*DD HALT* `{account}`\n"
        f"Drawdown reached `{dd_pct * 100:.2f}%` -- engine paused. "
        f"Manual restart required."
    )


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------


class TelegramNotifier:
    """Posts messages to a Telegram chat via the Bot API.

    Usage:
        notifier = TelegramNotifier.from_env()
        notifier.notify_trade_open(trade)

    The constructor accepts an injected `client` (httpx.Client / mock)
    so tests can run without a network. When `dry_run=True` the notifier
    prints to stdout and returns the message instead of POSTing.
    """

    def __init__(self, config: TelegramConfig | None = None, *, client=None):
        self.config = config or TelegramConfig.from_env()
        self._client = client

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> "TelegramNotifier":
        return cls(TelegramConfig.from_env(dry_run=dry_run))

    # ---- public ----------------------------------------------------------

    def notify_trade_open(self, trade) -> bool:
        return self._send(format_trade_open(trade))

    def notify_trade_close(self, trade) -> bool:
        return self._send(format_trade_close(trade))

    def notify_dd_halt(self, account: str, dd_pct: float) -> bool:
        return self._send(format_dd_halt(account, dd_pct))

    def notify_text(self, text: str) -> bool:
        """Escape hatch for ad-hoc messages (status, errors, ...)."""
        return self._send(text)

    # ---- internals -------------------------------------------------------

    def _send(self, text: str) -> bool:
        if self.config.dry_run:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
            return True
        if not self.config.configured:
            log.warning("Telegram not configured (TG_BOT_TOKEN / TG_CHAT_ID missing); skipping")
            return False
        url = TELEGRAM_API_TEMPLATE.format(token=self.config.bot_token)
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": self.config.parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            client = self._client or self._default_client()
            resp = client.post(url, json=payload, timeout=self.config.timeout_seconds)
            ok = getattr(resp, "status_code", 0) // 100 == 2
            if not ok:
                log.warning("Telegram API returned %s: %s", getattr(resp, "status_code", "?"),
                            getattr(resp, "text", ""))
            return bool(ok)
        except Exception as e:
            # Never raise -- live trade flow must not be killed by a
            # failed notification.
            log.warning("Telegram send failed: %s", e)
            return False

    @staticmethod
    def _default_client():
        import httpx  # type: ignore
        return httpx.Client(timeout=8.0)


__all__ = [
    "TelegramConfig",
    "TelegramNotifier",
    "format_trade_open",
    "format_trade_close",
    "format_dd_halt",
]
