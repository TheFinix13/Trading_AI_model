"""Ops-Telegram split (CEO requirement 2026-07-24) -- routing matrix.

Pins: ops events -> ops destination; trading events -> primary;
safety events -> BOTH; fallback of ops events to primary when the ops
block is absent/disabled; fail-closed ops enablement; no raw token in
`load_config()` (Legal rolling constraint extended to the ops block).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import alerts, alerts_telegram  # noqa: E402

PRIMARY_TOKEN = "primary-tkn"
PRIMARY_CHAT = "primary-chat"
OPS_TOKEN = "ops-tkn"
OPS_CHAT = "ops-chat"


class _FakeClient:
    def __init__(self, status_code: int = 200):
        self.calls: list[tuple[str, dict]] = []
        self.status_code = status_code

    def post(self, url: str, json: dict | None = None,
             timeout: float | None = None):
        self.calls.append((url, dict(json or {})))
        return SimpleNamespace(status_code=self.status_code)

    def chats(self) -> list[str]:
        return [payload["chat_id"] for _, payload in self.calls]


@pytest.fixture(autouse=True)
def _clean():
    alerts.reset()
    alerts_telegram.reset()
    yield
    alerts.reset()
    alerts_telegram.reset()


def _configure_both(per_event: dict | None = None) -> None:
    alerts_telegram.configure(
        bot_token=PRIMARY_TOKEN, chat_id=PRIMARY_CHAT,
        per_event=per_event, enabled=True)
    alerts_telegram.configure_ops(
        bot_token=OPS_TOKEN, chat_id=OPS_CHAT, enabled=True)


class TestRoutingMatrix:
    def test_ops_event_goes_to_ops_destination_only(self) -> None:
        client = _FakeClient()
        _configure_both()
        event = alerts.publish("watchdog_alert", {"check": "risk_state"})
        assert alerts_telegram.send(event, client=client) is True
        assert client.chats() == [OPS_CHAT]
        assert OPS_TOKEN in client.calls[0][0]

    def test_trading_events_stay_on_primary(self) -> None:
        client = _FakeClient()
        _configure_both(per_event={"approval_submitted": True})
        for ev_type in ("trade_fill", "stop_hit", "risk_budget_breach",
                        "approval_submitted"):
            client.calls.clear()
            event = alerts.publish(ev_type, {})
            assert alerts_telegram.send(event, client=client) is True
            assert client.chats() == [PRIMARY_CHAT], ev_type

    @pytest.mark.parametrize("ev_type", ["kill_switch_trip",
                                         "platform_down"])
    def test_safety_events_go_to_both(self, ev_type: str) -> None:
        client = _FakeClient()
        _configure_both()
        event = alerts.publish(ev_type, {})
        assert alerts_telegram.send(event, client=client) is True
        assert sorted(client.chats()) == sorted([PRIMARY_CHAT, OPS_CHAT])

    def test_ops_event_set_is_explicit_constant(self) -> None:
        assert alerts_telegram.OPS_EVENTS == frozenset({"watchdog_alert"})
        assert alerts_telegram.DUAL_ROUTE_EVENTS == frozenset(
            {"kill_switch_trip", "platform_down"})


class TestFallback:
    def test_ops_event_falls_back_to_primary_when_ops_disabled(self) -> None:
        # Better a mis-channeled alert than a dropped one.
        client = _FakeClient()
        alerts_telegram.configure(
            bot_token=PRIMARY_TOKEN, chat_id=PRIMARY_CHAT, enabled=True)
        event = alerts.publish("watchdog_alert", {})
        assert alerts_telegram.send(event, client=client) is True
        assert client.chats() == [PRIMARY_CHAT]

    def test_ops_event_falls_back_when_ops_partially_configured(self) -> None:
        client = _FakeClient()
        alerts_telegram.configure(
            bot_token=PRIMARY_TOKEN, chat_id=PRIMARY_CHAT, enabled=True)
        alerts_telegram.configure_ops(
            bot_token=OPS_TOKEN, chat_id="", enabled=True)
        event = alerts.publish("watchdog_alert", {})
        assert alerts_telegram.send(event, client=client) is True
        assert client.chats() == [PRIMARY_CHAT]

    def test_safety_event_single_destination_when_ops_disabled(self) -> None:
        client = _FakeClient()
        alerts_telegram.configure(
            bot_token=PRIMARY_TOKEN, chat_id=PRIMARY_CHAT, enabled=True)
        event = alerts.publish("kill_switch_trip", {})
        assert alerts_telegram.send(event, client=client) is True
        assert client.chats() == [PRIMARY_CHAT]


class TestFailClosed:
    def test_ops_disabled_unless_all_three_present(self) -> None:
        alerts_telegram.configure_ops(
            bot_token=OPS_TOKEN, chat_id=OPS_CHAT, enabled=False)
        assert alerts_telegram.ops_is_enabled() is False
        alerts_telegram.configure_ops(
            bot_token="", chat_id=OPS_CHAT, enabled=True)
        assert alerts_telegram.ops_is_enabled() is False
        alerts_telegram.configure_ops(
            bot_token=OPS_TOKEN, chat_id="", enabled=True)
        assert alerts_telegram.ops_is_enabled() is False
        alerts_telegram.configure_ops(
            bot_token=OPS_TOKEN, chat_id=OPS_CHAT, enabled=True)
        assert alerts_telegram.ops_is_enabled() is True

    def test_nothing_enabled_sends_nothing(self) -> None:
        client = _FakeClient()
        event = alerts.publish("watchdog_alert", {})
        assert alerts_telegram.send(event, client=client) is False
        assert client.calls == []

    def test_ops_only_config_still_carries_ops_events(self) -> None:
        # Primary unconfigured; ops fully configured -> ops events
        # flow, trading events are refused (primary is fail-closed).
        client = _FakeClient()
        alerts_telegram.configure_ops(
            bot_token=OPS_TOKEN, chat_id=OPS_CHAT, enabled=True)
        ops_event = alerts.publish("watchdog_alert", {})
        assert alerts_telegram.send(ops_event, client=client) is True
        assert client.chats() == [OPS_CHAT]
        client.calls.clear()
        trade_event = alerts.publish("trade_fill", {})
        assert alerts_telegram.send(trade_event, client=client) is False
        assert client.calls == []

    def test_start_attaches_when_only_ops_enabled(self) -> None:
        client = _FakeClient()
        alerts_telegram.configure_ops(
            bot_token=OPS_TOKEN, chat_id=OPS_CHAT, enabled=True)
        sub_id = alerts_telegram.start(client=client)
        assert sub_id is not None
        alerts.publish("watchdog_alert", {})
        assert client.chats() == [OPS_CHAT]


class TestNoTokenEcho:
    def test_load_config_never_echoes_ops_token(self) -> None:
        _configure_both()
        cfg = alerts_telegram.load_config()
        assert cfg["ops"] == {
            "enabled": True,
            "bot_token_configured": True,
            "chat_id_configured": True,
        }
        flat = repr(cfg)
        assert OPS_TOKEN not in flat
        assert OPS_CHAT not in flat
        assert PRIMARY_TOKEN not in flat

    def test_per_event_filter_still_gates_ops_events(self) -> None:
        client = _FakeClient()
        _configure_both(per_event={"watchdog_alert": False})
        event = alerts.publish("watchdog_alert", {})
        assert alerts_telegram.send(event, client=client) is False
        assert client.calls == []
