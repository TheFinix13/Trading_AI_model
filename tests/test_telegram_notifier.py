"""TelegramNotifier tests: multi-recipient fan-out + the symbol-tagged
live message builders.

`TG_CHAT_ID` can be a single id or a comma-separated list (e.g. a
personal DM id plus a Telegram group id), so the same trade/halt message
reaches every configured chat with one call site.

The builders exist because 3 symbol processes post into ONE shared group:
every message must lead with `*SYMBOL | <event>*` so the reader can tell
which pair it refers to (before 2026-07 the only clue was the price
magnitude).
"""
from __future__ import annotations

import pytest

from agent.notifications.telegram import (
    TelegramConfig,
    TelegramNotifier,
    build_agent_offline,
    build_agent_online,
    build_be_move,
    build_critical_halt,
    build_emergency_close,
    build_partial_scaleout,
    build_soft_stop_exit,
    build_trade_closed,
    build_trade_opened,
    format_exit_reason,
    format_halt_reason,
)


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    def __init__(self, status_by_chat: dict[str, int] | None = None, default_status: int = 200):
        self.status_by_chat = status_by_chat or {}
        self.default_status = default_status
        self.calls: list[dict] = []

    def post(self, url, json=None, timeout=None):
        self.calls.append(json)
        status = self.status_by_chat.get(json["chat_id"], self.default_status)
        return _FakeResponse(status)


class _RaisingClient:
    def post(self, url, json=None, timeout=None):
        raise ConnectionError("network unreachable")


def test_single_chat_id_still_works():
    cfg = TelegramConfig(bot_token="tok", chat_id="12345")
    assert cfg.chat_ids == ["12345"]


def test_comma_separated_chat_ids_parsed_and_trimmed():
    cfg = TelegramConfig(bot_token="tok", chat_id="12345, -5204264219 ,  67890")
    assert cfg.chat_ids == ["12345", "-5204264219", "67890"]


def test_empty_chat_id_is_unconfigured():
    cfg = TelegramConfig(bot_token="tok", chat_id="")
    assert cfg.chat_ids == []
    assert not cfg.configured


def test_notify_text_fans_out_to_every_chat_id():
    client = _FakeClient()
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="tok", chat_id="12345,-5204264219"), client=client
    )
    assert notifier.notify_text("hello") is True
    sent_chat_ids = [call["chat_id"] for call in client.calls]
    assert sent_chat_ids == ["12345", "-5204264219"]


def test_partial_failure_returns_false_but_sends_to_all():
    client = _FakeClient(status_by_chat={"bad-chat": 400})
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="tok", chat_id="good-chat,bad-chat"), client=client
    )
    ok = notifier.notify_text("hello")
    assert ok is False
    assert len(client.calls) == 2


def test_network_failure_on_one_recipient_does_not_raise():
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="tok", chat_id="12345,67890"), client=_RaisingClient()
    )
    assert notifier.notify_text("hello") is False


# ---------------------------------------------------------------------------
# Symbol-tagged live message builders
# ---------------------------------------------------------------------------


def _all_builder_messages(symbol: str) -> list[str]:
    """One message per builder, minimal realistic arguments."""
    return [
        build_agent_online(symbol, "mt5", ["zone_h4_all"]),
        build_agent_offline(symbol),
        build_critical_halt(symbol, 5, "boom"),
        build_trade_opened(
            symbol=symbol, alpha="zone_h4_all", direction="short",
            ticket=123, entry=1.34016, lots=0.01, soft_sl=1.34518,
            catastrophe_sl=1.35273, tp=1.33259, tp_r=1.5,
            risk_pct=0.0051, risk_amount=5.10, balance=1004.33,
        ),
        build_trade_closed(
            symbol=symbol, ticket=123, pnl=6.03, pnl_pips=17.0,
            r_multiple=0.6, exit_reason="tp",
        ),
        build_be_move(symbol=symbol, ticket=123, old_sl=1.41306,
                      new_sl=1.41641, r_multiple=1.0),
        build_soft_stop_exit(symbol=symbol, ticket=123, detail="detail"),
        build_soft_stop_exit(symbol=symbol, ticket=123, detail="detail",
                             adopted=True),
        build_partial_scaleout(symbol=symbol, ticket=123, closed_lots=0.02,
                               r_multiple=1.2),
        build_emergency_close(symbol=symbol, reason="Daily DD halt: 3.0%",
                              positions_closed=1, balance=970.12,
                              equity=970.12),
    ]


def test_every_builder_leads_with_the_symbol():
    """With 3 processes posting into one group, EVERY message's first line
    must carry the symbol tag."""
    for msg in _all_builder_messages("GBPUSD"):
        first_line = msg.splitlines()[0]
        assert first_line.startswith("*GBPUSD | "), (
            f"builder message missing symbol header: {first_line!r}")


def test_trade_opened_includes_dollar_risk_route_scale_and_balance():
    msg = build_trade_opened(
        symbol="EURUSD", alpha="zone_h4_all", direction="long",
        ticket=42, entry=1.14212, lots=0.07, soft_sl=1.14413,
        catastrophe_sl=1.14719, tp=1.13903, tp_r=1.5,
        risk_pct=0.0146, risk_amount=14.60, balance=1000.0,
        route_scale=1.0,
    )
    assert "EURUSD | Trade OPENED" in msg
    assert "LONG zone_h4_all" in msg
    assert "Ticket `42`" in msg
    assert "Risk `1.46%` ($14.60 at risk)" in msg
    assert "Route scale `1.00x`" in msg
    assert "Balance `$1,000.00`" in msg
    assert "(1.5R)" in msg


def test_trade_closed_reports_r_vs_original_risk_and_be_note():
    """The old message printed the post-BE R ("+0.00R" on a winner). The new
    one reports R against the original risk and says "risk-free after BE"
    in words when the stop had been moved."""
    msg = build_trade_closed(
        symbol="EURUSD", ticket=2935258837, pnl=6.03, pnl_pips=17.0,
        r_multiple=1.02, exit_reason="tp", be_moved=True,
        held_seconds=3 * 3600 + 36 * 60, balance_after=1010.36,
    )
    assert "Trade CLOSED WIN" in msg
    assert "+1.02R vs original risk" in msg
    assert "risk-free after BE" in msg
    assert "Held: 3h 36m" in msg
    assert "Exit: take-profit hit" in msg
    assert "Balance: `$1,010.36`" in msg
    assert "+0.00R" not in msg


def test_trade_closed_loss_without_be():
    msg = build_trade_closed(
        symbol="GBPUSD", ticket=2936602523, pnl=-14.38, pnl_pips=-72.0,
        r_multiple=-2.04, exit_reason="soft_sl_panic", be_moved=False,
        held_seconds=5 * 3600 + 20 * 60, balance_after=690.55,
    )
    assert "Trade CLOSED LOSS" in msg
    assert "-$14.38" in msg
    assert "-2.04R vs original risk" in msg
    assert "risk-free after BE" not in msg
    assert "Exit: soft stop (price blew through level)" in msg


@pytest.mark.parametrize("reason,words", [
    ("tp", "take-profit hit"),
    ("soft_sl_close", "soft stop (bar closed beyond level)"),
    ("soft_sl_panic", "soft stop (price blew through level)"),
    ("catastrophe_sl", "catastrophe stop hit"),
    ("stop_out", "margin stop-out"),
    ("manual", "closed (cause unconfirmed)"),
])
def test_exit_reasons_translate_to_plain_words(reason, words):
    assert format_exit_reason(reason) == words


def test_unknown_exit_reason_passes_through():
    assert format_exit_reason("weird_new_tag") == "weird_new_tag"


def test_emergency_close_names_the_reporting_process_and_account_state():
    msg = build_emergency_close(
        symbol="USDCAD", reason="Daily DD halt: 3.1% (limit 3.0%)",
        positions_closed=0, balance=970.12, equity=969.88,
    )
    assert msg.splitlines()[0] == "*USDCAD | TRADING HALTED*"
    assert "Daily drawdown limit hit" in msg
    assert "Agent still running" in msg
    assert "Closed 0 open position(s) on USDCAD" in msg
    assert "Balance `$970.12` | Equity `$969.88`" in msg


def test_halt_reason_translates_daily_dd():
    assert "Daily drawdown limit hit" in format_halt_reason(
        "Daily DD halt: 3.0% (limit 3.0%)")


def test_ladder_note_splits_across_lines_for_mobile():
    msg = build_trade_opened(
        symbol="GBPUSD", alpha="zone_h4_all", direction="short",
        ticket=1, entry=1.34, lots=0.01, soft_sl=1.35,
        catastrophe_sl=1.36, tp=1.33,
        ladder_note=(
            "\nExtension ladder (opinion only): "
            "`swing 1.33241 (1.6R) · zone_edge 1.32565 (2.9R)`"
        ),
    )
    assert "Extension ladder" in msg
    assert "  - swing 1.33241 (1.6R)" in msg
    assert "  - zone_edge 1.32565 (2.9R)" in msg


def test_emergency_close_omits_account_line_when_unknown():
    msg = build_emergency_close(
        symbol="USDCAD", reason="Kill switch activated", positions_closed=2,
    )
    assert "Balance" not in msg
