"""F014 -- alerts_telegram bridge unit tests (spec asked 5)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.platform import alerts, alerts_telegram


class _FakeClient:
    def __init__(self, status_code: int = 200):
        self.calls: list[tuple[str, dict]] = []
        self.status_code = status_code

    def post(self, url: str, json: dict | None = None,
             timeout: float | None = None):
        self.calls.append((url, dict(json or {})))
        return SimpleNamespace(status_code=self.status_code)


@pytest.fixture(autouse=True)
def _clean():
    alerts.reset()
    alerts_telegram.reset()
    yield
    alerts.reset()
    alerts_telegram.reset()


class TestConfigure:
    def test_defaults_when_missing_bot_token(self) -> None:
        alerts_telegram.configure(bot_token="", chat_id="",
                                  enabled=True)
        assert alerts_telegram.is_enabled() is False
        cfg = alerts_telegram.load_config()
        assert cfg["bot_token_configured"] is False
        assert cfg["chat_id_configured"] is False

    def test_enabled_only_when_all_conditions_met(self) -> None:
        alerts_telegram.configure(
            bot_token="tkn", chat_id="cid", enabled=True)
        assert alerts_telegram.is_enabled() is True


class TestSend:
    def test_correct_payload_posted(self) -> None:
        client = _FakeClient()
        alerts_telegram.configure(
            bot_token="tkn", chat_id="cid", enabled=True)
        event = alerts.publish("trade_fill",
                               {"symbol": "EURUSD", "size": 0.10})
        ok = alerts_telegram.send(event, client=client)
        assert ok is True
        assert len(client.calls) == 1
        url, payload = client.calls[0]
        assert url == "https://api.telegram.org/bottkn/sendMessage"
        assert payload["chat_id"] == "cid"
        assert "trade_fill" in payload["text"]
        assert "EURUSD" in payload["text"]

    def test_disabled_config_no_post(self) -> None:
        client = _FakeClient()
        alerts_telegram.configure(
            bot_token="tkn", chat_id="cid", enabled=False)
        event = alerts.publish("trade_fill", {})
        ok = alerts_telegram.send(event, client=client)
        assert ok is False
        assert client.calls == []

    def test_missing_bot_token_no_post(self) -> None:
        client = _FakeClient()
        alerts_telegram.configure(
            bot_token="", chat_id="cid", enabled=True)
        event = alerts.publish("trade_fill", {})
        ok = alerts_telegram.send(event, client=client)
        assert ok is False
        assert client.calls == []

    def test_per_event_filter_respected(self) -> None:
        client = _FakeClient()
        alerts_telegram.configure(
            bot_token="tkn", chat_id="cid", enabled=True,
            per_event={"trade_fill": True, "stop_hit": False,
                       "kill_switch_trip": True,
                       "risk_budget_breach": True,
                       "approval_submitted": False,
                       "platform_down": True})
        alerts_telegram.send(
            alerts.publish("trade_fill", {}), client=client)
        alerts_telegram.send(
            alerts.publish("stop_hit", {}), client=client)
        alerts_telegram.send(
            alerts.publish("approval_submitted", {}), client=client)
        # Only trade_fill made it through.
        assert len(client.calls) == 1
        assert "trade_fill" in client.calls[0][1]["text"]


class TestStartStop:
    def test_start_routes_bus_events_to_telegram(self) -> None:
        client = _FakeClient()
        alerts_telegram.configure(
            bot_token="tkn", chat_id="cid", enabled=True)
        sub_id = alerts_telegram.start(client=client)
        assert sub_id is not None
        alerts.publish("trade_fill", {"symbol": "EURUSD"})
        assert len(client.calls) == 1

    def test_start_when_disabled_returns_none(self) -> None:
        alerts_telegram.configure(
            bot_token="", chat_id="", enabled=False)
        assert alerts_telegram.start() is None
