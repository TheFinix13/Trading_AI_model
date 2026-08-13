"""Dedicated typed rows land on events.jsonl (2026-08-13 fix).

Until this fix the live engine wrote proposals / rejections / trades
only to the split jsonl files; events.jsonl carried tick_summary rows
alone, so every narrative surface reading the tape (/highlights, F001,
F002, the weekly squad report) saw an all-quiet week that wasn't --
the Aug 1-10 "0 shots" report while the squad actually fired 5 shots
on the NFP bar.

Pin: for every row in the split files there is a matching dedicated
row on events.jsonl (self-consistency, independent of which bars the
agents chose to trade).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.config import load_config
from agent.data.loader import BarLoader
from agent.squad.engine import SquadEngine
from agent.squad.roster import build_roster
from agent.types import Timeframe

SLICE_START = datetime(2015, 2, 17, tzinfo=timezone.utc)
SLICE_END = datetime(2015, 5, 17, tzinfo=timezone.utc)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


@pytest.fixture(scope="module")
def tape_dir(tmp_path_factory) -> Path:
    cfg = load_config()
    loader = BarLoader(cache_root=cfg.data_dir)
    warmup_start = SLICE_START - timedelta(days=120)
    bars_by_symbol = {}
    for sym in ("EURUSD", "GBPUSD", "USDCAD"):
        try:
            bars = loader.get_bars(sym, Timeframe.H4, warmup_start,
                                   SLICE_END)
        except Exception as exc:  # noqa: BLE001 - cache absent on CI
            pytest.skip(f"parquet cache unavailable for {sym}: {exc}")
        if len(bars) < 250:
            pytest.skip(f"insufficient parquet history for {sym}")
        bars_by_symbol[sym] = bars

    out = tmp_path_factory.mktemp("squad_tape") / "run"
    roster = build_roster(barou_v12=False, barou_v13=False)
    engine = SquadEngine(
        roster, out, aggregator_arm="phi41", source_label="tape_test",
    )
    engine.run_batch(bars_by_symbol, max_bars=3000)
    return out


def _events_by_type(out: Path) -> dict[str, list[dict]]:
    by_type: dict[str, list[dict]] = {}
    for row in _read_jsonl(out / "events.jsonl"):
        by_type.setdefault(str(row.get("type")), []).append(row)
    return by_type


def test_proposal_rows_mirror_proposals_all(tape_dir):
    n_split = len(_read_jsonl(tape_dir / "proposals_all.jsonl"))
    ev = _events_by_type(tape_dir)
    assert n_split > 0, "slice must produce at least one proposal"
    assert len(ev.get("proposal", [])) == n_split


def test_blocked_rows_mirror_proposals_rejected(tape_dir):
    n_split = len(_read_jsonl(tape_dir / "proposals_rejected.jsonl"))
    ev = _events_by_type(tape_dir)
    assert len(ev.get("blocked", [])) == n_split


def test_close_rows_mirror_trades(tape_dir):
    n_split = len(_read_jsonl(tape_dir / "trades.jsonl"))
    ev = _events_by_type(tape_dir)
    assert len(ev.get("close", [])) == n_split


def test_every_close_had_an_open(tape_dir):
    ev = _events_by_type(tape_dir)
    assert len(ev.get("open", [])) >= len(ev.get("close", []))


def test_event_rows_carry_render_fields(tape_dir):
    """Each type carries what highlights._line_for needs to narrate."""
    ev = _events_by_type(tape_dir)
    for row in ev.get("proposal", [])[:5]:
        assert row["agent_id"] and row["symbol"]
        assert row["direction"] in ("long", "short")
        assert 0.0 <= float(row["conviction"]) <= 1.0
        assert row["timestamp"]
    for row in ev.get("blocked", [])[:5]:
        assert row["agent_id"] and row["symbol"] and row["reason"]
        assert ("rule" in row) or ("by" in row)
    for row in ev.get("open", [])[:5]:
        assert row["agent_id"] and row["symbol"]
        assert float(row["entry"]) > 0 and float(row["stop"]) > 0
    for row in ev.get("close", [])[:5]:
        assert row["agent_id"] and row["symbol"]
        assert "pnl_pips" in row and "r" in row and "exit_reason" in row


def test_match_report_sees_the_activity(tape_dir):
    """End to end: the /highlights report on this tape is not quiet."""
    from agent.platform import highlights

    reports = highlights.list_reports(60, live_dir=tape_dir)
    assert reports, "tape must yield at least one match day"
    assert any(r["shots"] > 0 for r in reports), (
        "an active tape must show shots in the match reports"
    )
