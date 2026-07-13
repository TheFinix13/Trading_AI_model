"""Telegram notifier for trade events.

Reads `TG_BOT_TOKEN` and `TG_CHAT_ID` from the environment by default,
or accepts an explicit `TelegramConfig`. All HTTP calls go through
`httpx` (already a project dependency).

`TG_CHAT_ID` may be a single chat id or a comma-separated list (e.g. your
personal DM id plus a group id: "8851293239,-5204264219") to fan the same
message out to multiple chats -- useful for keeping a personal copy while
also posting into a shared group.

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
    chat_id: str = ""  # single id, or comma-separated for multiple recipients
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
    def chat_ids(self) -> list[str]:
        """Parsed, whitespace-trimmed recipient list (handles a plain
        single id transparently -- splitting a string with no commas just
        returns a one-element list)."""
        return [c.strip() for c in self.chat_id.split(",") if c.strip()]

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_ids) or self.dry_run


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
# Live-agent message builders (symbol-tagged). Pure -- no I/O.
#
# Three symbol processes (EURUSD / GBPUSD / USDCAD) post into ONE shared
# Telegram group, so every message MUST lead with the symbol or the reader
# cannot tell which pair it refers to (before 2026-07 they had to infer it
# from the price magnitude). Every builder below puts `*SYMBOL | <event>*`
# on the first line. Keep messages compact -- they are read on a phone.
# ---------------------------------------------------------------------------


def _header(symbol: str, event: str) -> str:
    """First line of every live message: `*EURUSD | Trade OPENED*`."""
    return f"*{symbol} | {event}*"


def _fmt_money(amount: float) -> str:
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _fmt_duration(seconds: float) -> str:
    """Compact human duration: '42m', '3h 36m', '2d 4h'."""
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        h, rem = divmod(seconds, 3600)
        return f"{h}h {rem // 60}m"
    d, rem = divmod(seconds, 86400)
    return f"{d}d {rem // 3600}h"


#: exit_reason -> plain-words description shown in the Trade CLOSED message.
_EXIT_REASON_WORDS = {
    "tp": "take-profit hit",
    "soft_sl_close": "soft stop (bar closed beyond level)",
    "soft_sl_panic": "soft stop (price blew through level)",
    "soft_sl_inferred_overshoot": "soft stop (adopted position, level already breached)",
    "sl": "broker stop-loss hit",
    "catastrophe_sl": "catastrophe stop hit",
    "stop_out": "margin stop-out",
    "expert": "closed by EA/expert",
    "manual": "closed (cause unconfirmed)",
    "unknown": "closed (cause unconfirmed)",
}


def format_exit_reason(reason: str) -> str:
    """Map an internal exit_reason tag to plain words for the phone."""
    return _EXIT_REASON_WORDS.get(str(reason), str(reason) or "?")


def format_halt_reason(reason: str) -> str:
    """Turn internal halt/kill-switch reason strings into plain words."""
    text = (reason or "").strip()
    lower = text.lower()
    if "daily dd" in lower or "drawdown" in lower:
        return f"Daily drawdown limit hit ({text})"
    if "kill switch" in lower or "auto-kill" in lower:
        return f"Kill switch engaged ({text})"
    if "autotrading disabled" in lower:
        return "Broker AutoTrading is OFF — enable it in MT5"
    if "consecutive error" in lower:
        return f"Process halted after repeated errors ({text})"
    return text or "Trading paused (reason unknown)"


def _format_ladder_note(ladder_note: str) -> str:
    """Break a long ladder string into short phone-friendly lines."""
    if not ladder_note:
        return ""
    raw = ladder_note.strip()
    if raw.startswith("Extension ladder"):
        # Caller may pass the full prefix + backticked rungs; unwrap for layout.
        prefix, _, rungs = raw.partition(":")
        rungs = rungs.strip().strip("`")
        if not rungs:
            return f"\n{raw}"
        lines = [f"\n{prefix.strip()} (opinion only):"]
        for chunk in rungs.split(" · "):
            chunk = chunk.strip()
            if chunk:
                lines.append(f"  - {chunk}")
        return "\n".join(lines)
    return f"\n{raw}"


def build_agent_online(symbol: str, broker_type: str, alphas: list[str]) -> str:
    return (
        f"{_header(symbol, 'Agent ONLINE')}\n"
        f"Broker: `{broker_type}` Alphas: `{', '.join(alphas)}`"
    )


def build_agent_offline(symbol: str) -> str:
    return _header(symbol, "Agent OFFLINE")


def build_critical_halt(symbol: str, n_errors: int, last_error: str) -> str:
    return (
        f"{_header(symbol, 'CRITICAL: Agent halted')}\n"
        f"{n_errors} consecutive errors.\n"
        f"Last: `{last_error[:200]}`"
    )


def build_trade_opened(
    *,
    symbol: str,
    alpha: str,
    direction: str,
    ticket: int | None,
    entry: float,
    lots: float,
    soft_sl: float,
    catastrophe_sl: float,
    tp: float,
    tp_r: float | None = None,
    risk_pct: float = 0.0,
    risk_amount: float | None = None,
    balance: float | None = None,
    route_scale: float | None = None,
    ladder_note: str = "",
) -> str:
    tp_part = f"TP `{tp:.5f}`"
    if tp_r is not None and tp_r > 0:
        tp_part += f" ({tp_r:.1f}R)"
    risk_part = f"Risk `{risk_pct * 100:.2f}%`"
    if risk_amount is not None:
        risk_part += f" ({_fmt_money(risk_amount)} at risk)"
    lines = [
        f"{_header(symbol, 'Trade OPENED')} {direction.upper()} {alpha}",
    ]
    if ticket:
        lines.append(f"Ticket `{ticket}`")
    lines.append(f"Entry `{entry:.5f}` | Lots `{lots:.2f}`")
    lines.append(
        f"Soft SL `{soft_sl:.5f}` | Cat SL `{catastrophe_sl:.5f}` | {tp_part}"
    )
    ctx_bits = [risk_part]
    if route_scale is not None:
        ctx_bits.append(f"Route scale `{route_scale:.2f}x`")
    if balance is not None:
        ctx_bits.append(f"Balance `{_fmt_money(balance)}`")
    lines.append(" | ".join(ctx_bits))
    lines.append(_format_ladder_note(ladder_note).lstrip("\n") if ladder_note else "")
    return "\n".join(line for line in lines if line)


def build_trade_closed(
    *,
    symbol: str,
    ticket: int,
    pnl: float,
    pnl_pips: float,
    r_multiple: float | None,
    exit_reason: str,
    be_moved: bool = False,
    held_seconds: float | None = None,
    balance_after: float | None = None,
) -> str:
    outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"
    # R is computed against the ORIGINAL soft-stop risk (see PositionMonitor.
    # _handle_close); after a breakeven move the position is risk-free, so we
    # say that in words instead of printing a confusing post-BE "+0.00R".
    if r_multiple is not None:
        r_part = f", {r_multiple:+.2f}R vs original risk"
    else:
        r_part = ""
    be_part = " -- risk-free after BE" if be_moved else ""
    lines = [
        f"{_header(symbol, f'Trade CLOSED {outcome}')} ticket=`{ticket}`",
        f"P&L: `{_fmt_money(pnl)}` ({_fmt_pips(pnl_pips)}{r_part}){be_part}",
    ]
    ctx_bits = []
    if held_seconds is not None:
        ctx_bits.append(f"Held: {_fmt_duration(held_seconds)}")
    ctx_bits.append(f"Exit: {format_exit_reason(exit_reason)}")
    lines.append(" | ".join(ctx_bits))
    if balance_after is not None:
        lines.append(f"Balance: `{_fmt_money(balance_after)}`")
    return "\n".join(lines)


def build_be_move(*, symbol: str, ticket: int, old_sl: float,
                  new_sl: float, r_multiple: float) -> str:
    return (
        f"{_header(symbol, 'BE Move')} ticket=`{ticket}`\n"
        f"SL `{old_sl:.5f}` -> `{new_sl:.5f}` at {r_multiple:.1f}R "
        f"-- trade now risk-free"
    )


def build_soft_stop_exit(*, symbol: str, ticket: int, detail: str,
                         adopted: bool = False) -> str:
    event = "Adopted soft-stop exit" if adopted else "Soft stop exit"
    return (
        f"{_header(symbol, event)} ticket=`{ticket}`\n"
        f"`{detail}`"
    )


def build_partial_scaleout(*, symbol: str, ticket: int, closed_lots: float,
                           r_multiple: float) -> str:
    return (
        f"{_header(symbol, 'Partial scale-out')} ticket=`{ticket}`\n"
        f"closed `{closed_lots:.2f}` lots at `{r_multiple:.1f}R`, runner chasing draw"
    )


def build_emergency_close(
    *,
    symbol: str,
    reason: str,
    positions_closed: int,
    balance: float | None = None,
    equity: float | None = None,
) -> str:
    lines = [
        f"{_header(symbol, 'TRADING HALTED')}",
        format_halt_reason(reason),
        "Agent still running -- no new trades until kill.txt is removed.",
        f"Closed {positions_closed} open position(s) on {symbol}",
    ]
    if balance is not None and equity is not None:
        lines.append(f"Balance `{_fmt_money(balance)}` | Equity `{_fmt_money(equity)}`")
    return "\n".join(lines)


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
        client = self._client or self._default_client()
        all_ok = True
        for chat_id in self.config.chat_ids:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": self.config.parse_mode,
                "disable_web_page_preview": True,
            }
            try:
                resp = client.post(url, json=payload, timeout=self.config.timeout_seconds)
                ok = getattr(resp, "status_code", 0) // 100 == 2
                if not ok:
                    log.warning("Telegram API returned %s for chat_id=%s: %s",
                                getattr(resp, "status_code", "?"), chat_id,
                                getattr(resp, "text", ""))
                all_ok = all_ok and ok
            except Exception as e:
                # Never raise -- live trade flow must not be killed by a
                # failed notification.
                log.warning("Telegram send failed for chat_id=%s: %s", chat_id, e)
                all_ok = False
        return all_ok

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
    "format_exit_reason",
    "format_halt_reason",
    "build_agent_online",
    "build_agent_offline",
    "build_critical_halt",
    "build_trade_opened",
    "build_trade_closed",
    "build_be_move",
    "build_soft_stop_exit",
    "build_partial_scaleout",
    "build_emergency_close",
]
