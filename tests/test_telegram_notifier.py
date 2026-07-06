"""TelegramNotifier tests, focused on the multi-recipient fan-out.

`TG_CHAT_ID` can be a single id or a comma-separated list (e.g. a
personal DM id plus a Telegram group id), so the same trade/halt message
reaches every configured chat with one call site.
"""
from __future__ import annotations

from agent.notifications.telegram import TelegramConfig, TelegramNotifier


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
