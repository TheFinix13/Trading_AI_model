"""``workspace_snapshot.json`` — engine-side snapshot of the last
~60 workspace Thoughts, written atomically on every ``on_bar`` call.

The /v2 LIVE dashboard reads this file via
``agent.platform.paper_loop.live_workspace`` so operators can peek at
what the squad is thinking right now. These tests pin:

1. The file is written on the first ``on_bar`` and every subsequent
   ``on_bar`` refreshes it (mtime advances).
2. The JSON payload has the expected top-level keys and is a valid
   round-trip of ``Thought.to_jsonable()``.
3. The ``thoughts`` array is capped at ``WORKSPACE_SNAPSHOT_CAP``
   entries and sorted newest-first (timestamp desc, agent_id asc).
4. The ``run_squad_live.py`` ``--reset`` file list includes the
   snapshot so a fresh run doesn't inherit stale content.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.squad.engine import (
    SquadEngine,
    WORKSPACE_SNAPSHOT_CAP,
    WORKSPACE_SNAPSHOT_FILE,
)
from agent.squad.roster import build_roster
from agent.squad.types import Thought, ThoughtRead
from agent.types import Bar, Timeframe


UTC = timezone.utc


def _bar(t: datetime) -> Bar:
    return Bar(
        time=t, open=1.10, high=1.11, low=1.09, close=1.105,
        volume=100.0, timeframe=Timeframe.H4,
    )


def _series(n: int, start: datetime) -> list[Bar]:
    return [_bar(start + timedelta(hours=4 * i)) for i in range(n)]


def _build_engine(tmp_path: Path) -> tuple[SquadEngine, list[Bar]]:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    hist = _series(210, start)
    engine = SquadEngine(
        build_roster(barou_v13=False),
        tmp_path / "squad_live",
        aggregator_arm="phi41",
        source_label="live_market:snapshot_test",
    )
    engine.prepare({"EURUSD": hist})
    return engine, hist


def _snap_path(engine: SquadEngine) -> Path:
    return engine.out_dir / WORKSPACE_SNAPSHOT_FILE


def test_on_bar_writes_workspace_snapshot(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    engine.on_bar("EURUSD", hist[201], bar_index=201, next_bar=hist[202])
    path = _snap_path(engine)
    assert path.exists(), "workspace_snapshot.json must be created by on_bar"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in ("as_of", "tick_id", "thought_count", "thoughts"):
        assert key in payload, f"missing key {key!r} in {payload!r}"
    assert isinstance(payload["thoughts"], list)
    # tick_id was incremented once
    assert payload["tick_id"] == 1
    assert payload["thought_count"] >= 0


def test_each_on_bar_refreshes_snapshot(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    engine.on_bar("EURUSD", hist[201], bar_index=201, next_bar=hist[202])
    path = _snap_path(engine)
    first = json.loads(path.read_text(encoding="utf-8"))
    engine.on_bar("EURUSD", hist[202], bar_index=202, next_bar=hist[203])
    second = json.loads(path.read_text(encoding="utf-8"))
    assert second["tick_id"] == first["tick_id"] + 1
    # thought_count is monotonically non-decreasing per bar (agents
    # keep publishing) until prune_before kicks in far beyond this run.
    assert second["thought_count"] >= first["thought_count"]


def test_snapshot_thoughts_are_round_trip_valid(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    engine.on_bar("EURUSD", hist[201], bar_index=201, next_bar=hist[202])
    payload = json.loads(_snap_path(engine).read_text(encoding="utf-8"))
    # For each thought entry the required Thought.to_jsonable() fields
    # must be present. We don't check every field (Thought schema is
    # richer than the UI needs) but confirm the ones the /v2 workspace
    # panel keys off of.
    for t in payload["thoughts"]:
        for field in ("agent_id", "symbol", "narrative",
                      "confidence_in_thought", "tags", "tick_id",
                      "timestamp"):
            assert field in t, f"missing field {field!r} in {t!r}"
        assert isinstance(t["tags"], list)
        assert 0.0 <= float(t["confidence_in_thought"]) <= 1.0


def test_snapshot_thoughts_sorted_newest_first(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    # Manually seed a workspace with thoughts of known timestamps so
    # the ordering assertion is deterministic.
    base = datetime(2024, 6, 1, tzinfo=UTC)
    for i, aid in enumerate(("bachira_meguru", "isagi_yoichi", "itoshi_rin")):
        t = Thought(
            schema_version=1,
            agent_id=aid,
            tick_id=100 + i,
            timestamp=base + timedelta(hours=i),
            symbol="EURUSD",
            narrative=f"thought {i}",
            tags=["seeded"],
            confidence_in_thought=0.5,
            expected_action=None,
            coordinate=None,
            decision_horizon=base + timedelta(hours=48),
            ttl_ticks=6,
            references=[],
            read=None,
        )
        engine.workspace.publish(t)
    engine._write_workspace_snapshot()
    payload = json.loads(_snap_path(engine).read_text(encoding="utf-8"))
    ts = [t["timestamp"] for t in payload["thoughts"]]
    # newest-first: timestamps descending
    assert ts == sorted(ts, reverse=True), (
        f"snapshot not newest-first: {ts}"
    )


def test_snapshot_caps_at_workspace_snapshot_cap(tmp_path: Path):
    engine, _ = _build_engine(tmp_path)
    # Publish more than the cap so we can pin the slice.
    base = datetime(2024, 6, 1, tzinfo=UTC)
    n = WORKSPACE_SNAPSHOT_CAP + 25
    for i in range(n):
        engine.workspace.publish(Thought(
            schema_version=1,
            agent_id="bachira_meguru",
            tick_id=1000 + i,
            timestamp=base + timedelta(minutes=i),
            symbol="EURUSD",
            narrative=f"thought {i}",
            tags=[],
            confidence_in_thought=0.5,
            expected_action=None,
            coordinate=None,
            decision_horizon=base + timedelta(hours=48),
            ttl_ticks=6,
            references=[],
            read=None,
        ))
    engine._write_workspace_snapshot()
    payload = json.loads(_snap_path(engine).read_text(encoding="utf-8"))
    assert len(payload["thoughts"]) == WORKSPACE_SNAPSHOT_CAP
    # Cap slice picks the newest ones -- the oldest slot should be the
    # (n - WORKSPACE_SNAPSHOT_CAP)-th entry we published, not #0.
    oldest_kept_narr = payload["thoughts"][-1]["narrative"]
    assert oldest_kept_narr == f"thought {n - WORKSPACE_SNAPSHOT_CAP}", (
        f"cap slice picked the wrong entries: {oldest_kept_narr!r}"
    )


def test_snapshot_thought_with_read_serialises_expected_fields(tmp_path: Path):
    engine, _ = _build_engine(tmp_path)
    base = datetime(2024, 6, 1, tzinfo=UTC)
    engine.workspace.publish(Thought(
        schema_version=1,
        agent_id="bachira_meguru",
        tick_id=200,
        timestamp=base,
        symbol="EURUSD",
        narrative="near demand zone at 1.0850",
        tags=["zone_touch", "pending_confirmation"],
        confidence_in_thought=0.72,
        expected_action="wait_ltf_confirm",
        coordinate=None,
        decision_horizon=base + timedelta(hours=48),
        ttl_ticks=6,
        references=[],
        read=ThoughtRead(
            signal_family="pattern_rebel",
            direction_bias="long",
            regime_read="range",
            expected_stop_pips=12.0,
            expected_r=1.8,
            driving_evidence=("demand_zone",),
        ),
    ))
    engine._write_workspace_snapshot()
    payload = json.loads(_snap_path(engine).read_text(encoding="utf-8"))
    t = payload["thoughts"][0]
    assert t["expected_action"] == "wait_ltf_confirm"
    assert t["read"] is not None
    assert t["read"]["direction_bias"] == "long"
    assert t["read"]["expected_stop_pips"] == 12.0
    assert "zone_touch" in t["tags"]


def test_run_squad_live_reset_includes_workspace_snapshot():
    """--reset must clear workspace_snapshot.json or a fresh live run
    could inherit thoughts from a previous stale process."""
    text = Path("scripts/run_squad_live.py").read_text(encoding="utf-8")
    assert "workspace_snapshot.json" in text, (
        "--reset must include workspace_snapshot.json in the file list"
    )
