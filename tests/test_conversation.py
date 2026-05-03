"""Tests for the conversation layer (context builder + replay differ)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.conversation.context import ContextBuilder, _extract_ids
from agent.config import load_config
from agent.journal.db import Journal


def test_extract_ids_finds_trade_and_lesson_refs():
    out = _extract_ids("explain trade #42 and lesson 7 please")
    assert 42 in out["trade"]
    assert 7 in out["lesson"]


def test_extract_ids_handles_no_match():
    assert _extract_ids("just say hi") == {"trade": [], "lesson": []}


def test_context_builder_header_is_self_describing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOURNAL_DB", str(tmp_path / "j.db"))
    load_config.cache_clear()  # type: ignore[attr-defined]
    cb = ContextBuilder.from_config()
    out = cb.build("hello")
    assert "Symbol: EURUSD" in out
    assert "bias-only" in out


def test_context_builder_pulls_referenced_lesson(tmp_path: Path, monkeypatch):
    db = tmp_path / "j.db"
    monkeypatch.setenv("JOURNAL_DB", str(db))
    load_config.cache_clear()  # type: ignore[attr-defined]
    j = Journal(db)
    j._conn.execute(
        """INSERT INTO human_lessons (trade_date, symbol, direction, entry_price, outcome, confluences_json)
           VALUES ('2026-04-28', 'EURUSD', 'short', 1.17328, 'win', ?)""",
        (json.dumps([{"tf": "M15", "type": "fvg", "detail": "x"}]),),
    )
    j.commit()
    j.close()

    cb = ContextBuilder.from_config()
    out = cb.build("explain lesson #1")
    assert "lesson#1" in out
    assert "1.17328" in out
