"""Frozen-prepare fix (2026-08-04): live bars re-prepare the roster.

The Jul 28 - Aug 3 live week produced 0 proposals because every
bar-based agent's ``_PreparedSeries`` (zones, swings, ``index_by_ts``)
was built exactly once, at the startup ``prepare()``. Every H4 bar
that closed AFTER startup was absent from the frozen timestamp index,
so Isagi / Bachira / Rin / Chigiri / Barou all abstained with
``timestamp_miss`` at confidence 0.00 forever (160 such abstains on
the week's tape). The research replay never caught it because batch
mode prepares on the FULL series -- including every "future" bar --
up front.

Pinned here:

1. A live-shaped flow (prepare on history, then genuinely new bars via
   ``on_bar``) produces ZERO ``timestamp_miss`` thoughts and the new
   bar lands in the agents' prepared index.
2. The engine's history is append-only under the live calling
   convention (``bar_index=None``): no historical bar is overwritten.
3. Parity: batch/replay paths never trigger a roster re-prepare --
   ``run_batch`` byte-identical behavior is preserved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import agent.squad.engine as engine_mod
from agent.squad.engine import SquadEngine
from agent.squad.roster import build_roster
from agent.types import Bar, Timeframe

UTC = timezone.utc


def _bar(t: datetime, *, o: float = 1.10, h: float = 1.11,
         l: float = 1.09, c: float = 1.105) -> Bar:
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=100.0,
               timeframe=Timeframe.H4)


def _series(n: int, start: datetime) -> list[Bar]:
    return [_bar(start + timedelta(hours=4 * i)) for i in range(n)]


def _build_engine(tmp_path: Path, n_hist: int = 210) -> tuple[SquadEngine, list[Bar]]:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    hist = _series(n_hist, start)
    engine = SquadEngine(
        build_roster(barou_v13=False),
        tmp_path / "squad_live",
        aggregator_arm="phi41",
        source_label="live_market:test",
    )
    engine.prepare({"EURUSD": hist})
    return engine, hist


def _next_times(hist: list[Bar], n: int) -> list[Bar]:
    """``n`` genuinely NEW closed bars continuing the H4 grid."""
    last = hist[-1].time
    return [_bar(last + timedelta(hours=4 * (i + 1))) for i in range(n)]


def _has_timestamp_miss(thoughts) -> bool:
    return any(
        "timestamp_miss" in tag for t in thoughts for tag in t.tags
    )


# ---------------------------------------------------------------------------
# 1. Live-shaped flow: no timestamp_miss on post-startup bars
# ---------------------------------------------------------------------------

def test_new_live_bar_is_in_prepared_index_no_timestamp_miss(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    engine.seed_warmup("EURUSD", len(hist))
    new1, new2 = _next_times(hist, 2)

    # Live calling convention: engine assigns its own index; the fill
    # bar is the (synthetic) forming bar.
    r1 = engine.on_bar("EURUSD", new1, next_bar=new2)
    assert not _has_timestamp_miss(r1.thoughts), (
        "first post-startup bar must be visible to the roster "
        "(the Jul 28 - Aug 3 regression: it was not)"
    )
    r2 = engine.on_bar("EURUSD", new2, next_bar=_next_times([new2], 1)[0])
    assert not _has_timestamp_miss(r2.thoughts)

    # The new bars are literally in the agents' timestamp index.
    isagi_index = engine.roster.isagi._prepared["EURUSD"].index_by_ts
    assert new1.time in isagi_index
    assert new2.time in isagi_index
    bachira = next(
        a for a in engine.roster.proposers if a.agent_id == "bachira_meguru"
    )
    assert new2.time in bachira._prepared["EURUSD"].index_by_ts


def test_many_live_bars_stay_visible(tmp_path: Path):
    """The week-long failure shape: bar after bar after bar, all new."""
    engine, hist = _build_engine(tmp_path)
    engine.seed_warmup("EURUSD", len(hist))
    stream = _next_times(hist, 6)
    for i, b in enumerate(stream[:-1]):
        result = engine.on_bar("EURUSD", b, next_bar=stream[i + 1])
        assert not _has_timestamp_miss(result.thoughts), (
            f"bar {i} ({b.time}) fell out of the prepared index"
        )


# ---------------------------------------------------------------------------
# 2. Engine history integrity under the live calling convention
# ---------------------------------------------------------------------------

def test_live_bars_append_never_overwrite_history(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    engine.seed_warmup("EURUSD", len(hist))
    new1, new2 = _next_times(hist, 2)
    engine.on_bar("EURUSD", new1, next_bar=new2)
    engine.on_bar("EURUSD", new2, next_bar=_next_times([new2], 1)[0])

    series = engine.bars_by_symbol["EURUSD"]
    assert len(series) == len(hist) + 2
    assert [b.time for b in series[:len(hist)]] == [b.time for b in hist], (
        "historical bars must never be overwritten by live bars "
        "(the old runner passed feed-window indices into engine space)"
    )
    assert series[-2].time == new1.time
    assert series[-1].time == new2.time


# ---------------------------------------------------------------------------
# 3. Parity: batch/replay paths never re-prepare
# ---------------------------------------------------------------------------

def _count_prepare_calls(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    orig = engine_mod.prepare_roster

    def _spy(roster, bars_by_symbol):
        calls.append({s: len(b) for s, b in bars_by_symbol.items()})
        return orig(roster, bars_by_symbol)

    monkeypatch.setattr(engine_mod, "prepare_roster", _spy)
    return calls


def test_run_batch_never_repreparesroster(tmp_path: Path, monkeypatch):
    calls = _count_prepare_calls(monkeypatch)
    start = datetime(2024, 1, 2, tzinfo=UTC)
    hist = _series(40, start)
    engine = SquadEngine(
        build_roster(barou_v13=False),
        tmp_path / "batch",
        aggregator_arm="phi41",
        source_label="parity_harness",
    )
    stats = engine.run_batch({"EURUSD": hist})
    assert stats["bars_processed"] == 40
    assert len(calls) == 1, (
        "batch replay must only prepare once, up front -- re-preparing "
        "would break byte-identical parity with the research harness"
    )


def test_live_new_bars_reprepare_only_their_symbol(tmp_path: Path, monkeypatch):
    calls = _count_prepare_calls(monkeypatch)
    engine, hist = _build_engine(tmp_path)
    engine.seed_warmup("EURUSD", len(hist))
    assert len(calls) == 1  # startup prepare

    new1, new2 = _next_times(hist, 2)
    engine.on_bar("EURUSD", new1, next_bar=new2)
    assert len(calls) == 2
    assert set(calls[-1]) == {"EURUSD"}

    # Re-processing a bar at-or-before the prepared horizon must NOT
    # re-prepare (duplicate poll / out-of-order guard).
    engine.on_bar("EURUSD", new1, next_bar=new2)
    assert len(calls) == 2
