"""Outbound notification adapters (Telegram first; Slack / email later)."""
from agent.notifications.telegram import (
    TelegramConfig,
    TelegramNotifier,
    format_dd_halt,
    format_trade_close,
    format_trade_open,
)

__all__ = [
    "TelegramConfig",
    "TelegramNotifier",
    "format_trade_open",
    "format_trade_close",
    "format_dd_halt",
]
