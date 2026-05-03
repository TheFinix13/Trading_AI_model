"""Tests for the LLM extractor & schema validation.

These tests don't hit the actual Ollama daemon — they use a fake client that
returns canned JSON. Anything that requires a live model goes in an integration
suite (not run on CI)."""
from __future__ import annotations

import json
from datetime import date

import pytest

from agent.llm.extractor import EXTRACT_SYSTEM, LessonExtractor, TradeLesson, _strip_to_json
from agent.llm.ollama import OllamaUnavailable


class FakeClient:
    """Minimal stand-in for OllamaClient. ``next_response`` is the literal text
    the next .chat() call will return."""

    def __init__(self, response: str = "", alive: bool = True, models: list[str] | None = None):
        self.next_response = response
        self.last_messages = None
        self.last_model = None
        self.last_kwargs = None
        self._alive = alive
        self._models = models or ["qwen2.5:14b-instruct"]

    def is_alive(self) -> bool:
        return self._alive

    def has_model(self, name: str) -> bool:
        return any(name.split(":")[0] in m for m in self._models)

    def chat(self, model, messages, **kwargs):
        self.last_model = model
        self.last_messages = messages
        self.last_kwargs = kwargs
        return self.next_response


def test_strip_to_json_handles_fences():
    assert _strip_to_json("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert _strip_to_json("blah {\"a\":1} blah") == '{"a":1}'
    assert _strip_to_json('{"a":1}') == '{"a":1}'


def test_extract_happy_path():
    fake = FakeClient(json.dumps({
        "symbol": "EURUSD",
        "trade_date": "2026-04-28",
        "direction": "short",
        "entry_price": 1.17328,
        "stop_price": 1.17642,
        "tp_price": 1.16884,
        "outcome": "win",
        "pnl_pips": 44.4,
        "pnl_usd": 144.05,
        "daily_bias": "bearish",
        "confluences": [
            {"tf": "D1", "type": "session_bias", "detail": "bearish"},
            {"tf": "M15", "type": "fvg", "detail": "below structure"},
        ],
        "session": "London-NY overlap",
        "emotion": "confident",
        "notes": "",
    }))
    ext = LessonExtractor(client=fake)
    lesson = ext.extract("On Tuesday I went short EURUSD M15 ...")
    assert isinstance(lesson, TradeLesson)
    assert lesson.direction == "short"
    assert lesson.trade_date == date(2026, 4, 28)
    assert len(lesson.confluences) == 2
    assert lesson.confluences[1].type == "fvg"
    # raw_text is preserved for audit
    assert "On Tuesday" in lesson.raw_text
    # JSON mode requested
    assert fake.last_kwargs.get("json_mode") is True


def test_extract_invalid_json_raises():
    fake = FakeClient("this is not json at all")
    ext = LessonExtractor(client=fake)
    with pytest.raises(ValueError, match="valid JSON"):
        ext.extract("anything")


def test_extract_invalid_schema_raises():
    fake = FakeClient(json.dumps({
        "symbol": "EURUSD",
        # missing required fields like trade_date / direction / entry_price
    }))
    ext = LessonExtractor(client=fake)
    with pytest.raises(ValueError, match="schema"):
        ext.extract("anything")


def test_extract_empty_input_raises():
    ext = LessonExtractor(client=FakeClient())
    with pytest.raises(ValueError, match="empty"):
        ext.extract("   ")


def test_extract_propagates_ollama_unavailable():
    class DownClient(FakeClient):
        def chat(self, *a, **k):
            raise OllamaUnavailable("daemon offline")
    ext = LessonExtractor(client=DownClient())
    with pytest.raises(OllamaUnavailable):
        ext.extract("hello")


def test_system_prompt_mentions_schema():
    # Smoke check — easy to break the contract by editing the docstring.
    assert "trade_date" in EXTRACT_SYSTEM
    assert "confluences" in EXTRACT_SYSTEM
    assert "JSON ONLY" in EXTRACT_SYSTEM
