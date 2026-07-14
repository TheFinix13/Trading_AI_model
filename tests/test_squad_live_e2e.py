"""End-to-end: fake feed → engine → JSONL schema + state resume."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.platform.event_schema import validate_events
from agent.platform.squad_events import build_timeline
from agent.squad.engine import SquadEngine
from agent.squad.feed import FakeFeed
from agent.squad.roster import build_roster
from agent.types import Bar, Timeframe

UTC = timezone.utc


def _bar(t: datetime, *, o=1.10, h=1.11, l=1.09, c=1.105) -> Bar:
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=100.0,
               timeframe=Timeframe.H4)


def _series(n: int, start: datetime) -> list[Bar]:
    return [_bar(start + timedelta(hours=4 * i)) for i in range(n)]


def test_e2e_fake_feed_three_bars_schema_and_resume(tmp_path: Path):
    # Warmup + a few live bars. Engine's WARMUP_BARS=200, so seed a
    # 205-bar history then push 3 new ones through the live path.
    start = datetime(2020, 1, 1, tzinfo=UTC)
    hist = {
        "EURUSD": _series(205, start),
        "GBPUSD": _series(205, start),
        "USDCAD": _series(205, start),
    }
    out = tmp_path / "squad_live"
    roster = build_roster(barou_v13=False)
    engine = SquadEngine(
        roster, out, aggregator_arm="phi41", source_label="live_market:fake",
    )
    engine.prepare(hist)

    # Drive the last 3 historical bars through on_bar (simulating a
    # fresh closed-bar stream after warmup). Indices 200,201,202 have
    # successors at 201,202,203.
    for i in (200, 201, 202):
        bar = hist["EURUSD"][i]
        nxt = hist["EURUSD"][i + 1]
        engine.on_bar("EURUSD", bar, bar_index=i, next_bar=nxt)

    # JSONL files must exist (even if empty of proposals — schema of
    # whatever DID get written must validate via the platform parser).
    assert (out / "state.json").exists()
    state = json.loads((out / "state.json").read_text())
    assert state["source"] == "live_market:fake"
    assert state["tick_id"] >= 3

    # Build a timeline from whatever was written; validate events.
    # If no proposals fired on these particular synthetic bars, the
    # empty timeline is still a valid outcome — we assert the parser
    # doesn't explode and state resumes cleanly.
    events = build_timeline(out)
    # build_timeline returns (events, meta); accept either shape.
    if isinstance(events, tuple):
        events = events[0]
    if events:
        errs = validate_events(events)
        assert errs == []

    # Resume: new engine, same out_dir, must not duplicate by
    # re-processing the same bar_index with last_bar_times gate in the
    # runtime — here we check state.load restores tick_id + open pos.
    tick_before = state["tick_id"]
    engine2 = SquadEngine(
        build_roster(barou_v13=False), out,
        aggregator_arm="phi41", source_label="live_market:fake",
    )
    engine2.prepare(hist)
    assert engine2.tick_id == tick_before

    # Process one NEW bar (index 203) — tick advances, no crash.
    engine2.on_bar(
        "EURUSD", hist["EURUSD"][203],
        bar_index=203, next_bar=hist["EURUSD"][204],
    )
    state2 = json.loads((out / "state.json").read_text())
    assert state2["tick_id"] == tick_before + 1


def test_fake_feed_queues_into_engine(tmp_path: Path):
    """FakeFeed.push → poll → engine.on_bar path used by the runtime."""
    start = datetime(2021, 6, 1, tzinfo=UTC)
    hist = {"EURUSD": _series(210, start)}
    feed = FakeFeed(bars_by_symbol={"EURUSD": list(hist["EURUSD"][:200])},
                    warmup=0)
    out = tmp_path / "live2"
    engine = SquadEngine(
        build_roster(barou_v13=False), out,
        aggregator_arm="phi41", source_label="cache_replay",
    )
    engine.prepare(hist)

    # Push three fresh bars past warmup.
    for i in range(200, 203):
        feed.push("EURUSD", hist["EURUSD"][i])
    closed = feed.poll_new_closed()
    assert len(closed) == 3
    for fb in closed:
        nxt = hist["EURUSD"][fb.bar_index + 1]
        engine.on_bar(fb.symbol, fb.bar, bar_index=fb.bar_index, next_bar=nxt)
    assert (out / "state.json").exists()
    assert json.loads((out / "state.json").read_text())["tick_id"] == 3
