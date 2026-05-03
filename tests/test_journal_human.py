"""Tests for the human-side journal extension (lessons / disagreements / chat / retros)."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

import pytest

from agent.journal.db import Journal
from agent.llm.extractor import Confluence, TradeLesson


@pytest.fixture()
def journal(tmp_path: Path):
    j = Journal(tmp_path / "j.db")
    yield j
    j.close()


def test_schema_creates_all_human_tables(journal):
    tables = {r[0] for r in journal._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    expected = {"signals", "trades", "equity", "model_versions",
                "human_lessons", "agent_disagreements",
                "weekly_retrospectives", "chat_sessions", "chat_messages"}
    assert expected.issubset(tables)


def _sample_lesson() -> TradeLesson:
    return TradeLesson(
        symbol="EURUSD",
        trade_date=date(2026, 4, 28),
        direction="short",
        entry_price=1.17328,
        stop_price=1.17642,
        tp_price=1.16884,
        outcome="win",
        pnl_pips=44.4,
        pnl_usd=144.05,
        daily_bias="bearish, failed PDH break at 8:15 NY",
        confluences=[
            Confluence(tf="D1", type="session_bias", detail="bearish"),
            Confluence(tf="H4", type="trendline", detail="broken"),
            Confluence(tf="M15", type="fvg", detail="below structure"),
            Confluence(tf="M15", type="liquidity_sweep", detail="equal highs swept"),
        ],
        session="London-NY overlap",
        emotion="confident",
        notes="patient entry after candle-close confirmation",
        raw_text="On Tuesday I went short ... [original paragraph]",
    )


def test_log_lesson_roundtrip(journal):
    lesson = _sample_lesson()
    lid = journal.log_human_lesson(lesson)
    assert lid > 0

    row = journal.get_lesson(lid)
    assert row["direction"] == "short"
    assert abs(row["entry_price"] - 1.17328) < 1e-9
    assert row["outcome"] == "win"
    assert row["session"] == "London-NY overlap"
    confs = json.loads(row["confluences_json"])
    assert len(confs) == 4
    assert confs[0]["tf"] == "D1"
    assert any(c["type"] == "liquidity_sweep" for c in confs)


def test_filter_lessons_by_date(journal):
    journal.log_human_lesson(_sample_lesson())
    other = _sample_lesson()
    other.trade_date = date(2026, 5, 5)
    journal.log_human_lesson(other)

    week = journal.all_lessons(start_date="2026-04-27", end_date="2026-05-03")
    assert len(week) == 1
    assert week[0]["trade_date"] == "2026-04-28"


def test_disagreement_logging(journal):
    lid = journal.log_human_lesson(_sample_lesson())
    did = journal.log_disagreement(
        lesson_id=lid,
        agreement="agree",
        agent_direction="short",
        agent_entry=1.17320,
        agent_stop=1.17640,
        agent_tp=1.16880,
        agent_confluences=["zone", "fvg", "htf_bias_short"],
        agent_ml_score=0.71,
        diff_summary="agreed direction, agent missed liquidity_sweep tag",
        detected_at=datetime(2026, 4, 28, 13, 45),
    )
    assert did > 0
    diffs = journal.disagreements_for_lesson(lid)
    assert len(diffs) == 1
    assert diffs[0]["agreement"] == "agree"
    assert json.loads(diffs[0]["agent_confluences_json"]) == ["zone", "fvg", "htf_bias_short"]


def test_chat_session_persistence(journal):
    sid = journal.create_chat_session("test session")
    journal.append_chat_message(sid, "user", "hi", {"context": "test ctx"})
    journal.append_chat_message(sid, "assistant", "hello back!")
    msgs = journal.chat_history(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert json.loads(msgs[0]["context_json"])["context"] == "test ctx"


def test_retrospective_logging(journal):
    rid = journal.log_retrospective(
        week_start="2026-04-27", week_end="2026-05-03",
        n_trades=5, n_wins=3, n_losses=2,
        total_pips=42.5, total_usd=128.75,
        failure_clusters=[{"label": "agent_disagreed", "count": 1, "example_lesson_ids": [3]}],
        lessons_learned="WIN PATTERN: London opens after PDH sweep ...",
    )
    assert rid > 0
    rows = journal.all_retrospectives()
    assert rows[0]["week_start"] == "2026-04-27"
    clusters = json.loads(rows[0]["failure_clusters_json"])
    assert clusters[0]["label"] == "agent_disagreed"
