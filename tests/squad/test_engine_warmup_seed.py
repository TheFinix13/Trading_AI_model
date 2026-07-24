"""F4 warm-up seeding fix: live feeds credit historical bars.

A fresh live runtime used to sit through 200 live H4 bars (~33 calendar
days) before proposing, because the MT5 feed's ~2,500 pre-loaded
historical bars hydrated ``prepare()`` but never counted toward
``bars_seen``. ``SquadEngine.seed_warmup`` closes that gap on the
live-market path only; cache/replay/parity paths never seed and stay
byte-identical.

Pinned here:

1. Seeding math (credit capped at WARMUP_BARS; short history credits
   its full length).
2. Burn-in countdown: the first N live bars after seeding are still
   withheld from Phase 2 (intend), then proposing opens up.
3. Never-regress semantics on resumed state (no burn-in re-arm).
4. Parity: non-seeded engines have empty seeding state, run_batch
   never seeds, and the un-seeded warm-up gate math is unchanged.
5. state.json round-trip of the additive ``warmup`` payload, and the
   fresh-boot re-seed after a ``--reset`` style state deletion.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.squad.engine import (
    DEFAULT_LIVE_BURN_IN_BARS,
    WARMUP_BARS,
    SquadEngine,
)
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


def _spy_intend(engine: SquadEngine) -> list[str]:
    """Replace every proposer's intend with a call recorder."""
    calls: list[str] = []

    def _make(aid):
        def _intend(market, thought, **kwargs):  # noqa: ARG001
            calls.append(aid)
            return None
        return _intend

    for agent in engine.roster.proposers:
        agent.intend = _make(agent.agent_id)
    return calls


# ---------------------------------------------------------------------------
# 1. Seeding math
# ---------------------------------------------------------------------------

def test_seed_credits_history_capped_at_warmup_bars(tmp_path: Path):
    engine, _ = _build_engine(tmp_path)
    applied = engine.seed_warmup("EURUSD", 2500)
    assert applied is True
    assert engine.bars_seen["EURUSD"] == WARMUP_BARS
    assert engine.warmup_seeded_bars["EURUSD"] == WARMUP_BARS
    assert engine.burn_in_remaining["EURUSD"] == DEFAULT_LIVE_BURN_IN_BARS


def test_seed_short_history_credits_full_length(tmp_path: Path):
    engine, _ = _build_engine(tmp_path)
    assert engine.seed_warmup("EURUSD", 150) is True
    assert engine.bars_seen["EURUSD"] == 150
    # Still 50 genuine bars of warm-up remain before burn-in kicks in.
    assert engine.warmup_seeded_bars["EURUSD"] == 150


def test_seed_zero_or_negative_history_is_noop(tmp_path: Path):
    engine, _ = _build_engine(tmp_path)
    assert engine.seed_warmup("EURUSD", 0) is False
    assert engine.seed_warmup("EURUSD", -5) is False
    assert engine.bars_seen["EURUSD"] == 0
    assert engine.burn_in_remaining == {}


def test_seed_never_regresses_past_state(tmp_path: Path):
    """A resumed runtime already past warm-up must not be re-gated."""
    engine, _ = _build_engine(tmp_path)
    engine.bars_seen["EURUSD"] = 250  # resumed well past warm-up
    assert engine.seed_warmup("EURUSD", 2500) is False
    assert engine.bars_seen["EURUSD"] == 250
    assert "EURUSD" not in engine.burn_in_remaining


def test_seed_does_not_rearm_partially_consumed_burn_in(tmp_path: Path):
    engine, _ = _build_engine(tmp_path)
    engine.bars_seen["EURUSD"] = WARMUP_BARS + 1
    engine.burn_in_remaining["EURUSD"] = 1  # mid-burn-in restart
    assert engine.seed_warmup("EURUSD", 2500) is False
    assert engine.burn_in_remaining["EURUSD"] == 1


# ---------------------------------------------------------------------------
# 2. Burn-in countdown gates Phase 2
# ---------------------------------------------------------------------------

def test_burn_in_countdown_withholds_then_opens_intend(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    calls = _spy_intend(engine)
    engine.seed_warmup("EURUSD", len(hist), burn_in_bars=2)
    assert engine.bars_seen["EURUSD"] == WARMUP_BARS

    # Bar 1: past warm-up but inside burn-in -> intend withheld.
    engine.on_bar("EURUSD", hist[201], bar_index=201, next_bar=hist[202])
    assert calls == []
    assert engine.burn_in_remaining["EURUSD"] == 1

    # Bar 2: last burn-in bar -> still withheld.
    engine.on_bar("EURUSD", hist[202], bar_index=202, next_bar=hist[203])
    assert calls == []
    assert engine.burn_in_remaining["EURUSD"] == 0

    # Bar 3: burn-in exhausted -> Phase 2 runs (intend called).
    engine.on_bar("EURUSD", hist[203], bar_index=203, next_bar=hist[204])
    assert calls, "intend must run once burn-in is exhausted"
    assert engine.burn_in_remaining["EURUSD"] == 0


def test_burn_in_bars_zero_opens_immediately(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    calls = _spy_intend(engine)
    engine.seed_warmup("EURUSD", len(hist), burn_in_bars=0)
    engine.on_bar("EURUSD", hist[201], bar_index=201, next_bar=hist[202])
    assert calls, "burn_in_bars=0 must allow intend on the first live bar"


def test_burn_in_ticks_still_emit_tick_summary(tmp_path: Path):
    """Silence during burn-in must stay legible: proof-of-life rows."""
    engine, hist = _build_engine(tmp_path)
    engine.seed_warmup("EURUSD", len(hist))
    engine.on_bar("EURUSD", hist[201], bar_index=201, next_bar=hist[202])
    rows = [
        json.loads(x)
        for x in (engine.out_dir / "events.jsonl").read_text().splitlines()
        if x
    ]
    assert len(rows) == 1
    assert rows[0]["type"] == "tick_summary"


# ---------------------------------------------------------------------------
# 3. Parity: non-seeded paths byte-identical
# ---------------------------------------------------------------------------

def test_unseeded_engine_has_empty_seeding_state(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    engine.on_bar("EURUSD", hist[201], bar_index=201, next_bar=hist[202])
    assert engine.warmup_seeded_bars == {}
    assert engine.burn_in_remaining == {}


def test_unseeded_warmup_gate_math_unchanged(tmp_path: Path):
    """Original semantics: intend withheld while bars_seen <= 200,
    runs on bar 201 with NO burn-in delay (replay/parity behavior)."""
    engine, hist = _build_engine(tmp_path)
    calls = _spy_intend(engine)
    engine.bars_seen["EURUSD"] = WARMUP_BARS - 1
    # This bar takes bars_seen to 200 -> still warm-up.
    engine.on_bar("EURUSD", hist[201], bar_index=201, next_bar=hist[202])
    assert calls == []
    # Next bar (201st seen) -> intend runs immediately, no burn-in.
    engine.on_bar("EURUSD", hist[202], bar_index=202, next_bar=hist[203])
    assert calls, "un-seeded engines must not incur any burn-in delay"


def test_run_batch_never_seeds(tmp_path: Path):
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
    assert engine.warmup_seeded_bars == {}
    assert engine.burn_in_remaining == {}
    # bars_seen counts processed bars exactly, as before the fix.
    assert engine.bars_seen["EURUSD"] == 40


# ---------------------------------------------------------------------------
# 4. Persistence
# ---------------------------------------------------------------------------

def test_state_json_carries_warmup_payload(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    engine.seed_warmup("EURUSD", len(hist))
    engine.save_state()
    state = json.loads((engine.out_dir / "state.json").read_text())
    w = state["warmup"]["EURUSD"]
    assert w["bars_seen"] == WARMUP_BARS
    assert w["warmup_bars"] == WARMUP_BARS
    assert w["burn_in_remaining"] == DEFAULT_LIVE_BURN_IN_BARS
    assert w["seeded_bars"] == WARMUP_BARS
    assert state["schema"] == 1, "warmup payload is additive, not v2"


def test_state_round_trip_restores_burn_in(tmp_path: Path):
    engine, hist = _build_engine(tmp_path)
    engine.seed_warmup("EURUSD", len(hist), burn_in_bars=2)
    engine.on_bar("EURUSD", hist[201], bar_index=201, next_bar=hist[202])
    assert engine.burn_in_remaining["EURUSD"] == 1

    engine2 = SquadEngine(
        build_roster(barou_v13=False),
        engine.out_dir,
        aggregator_arm="phi41",
        source_label="live_market:test",
    )
    engine2.prepare({"EURUSD": hist})
    assert engine2.bars_seen["EURUSD"] == WARMUP_BARS + 1
    assert engine2.burn_in_remaining["EURUSD"] == 1
    assert engine2.warmup_seeded_bars["EURUSD"] == WARMUP_BARS
    # Re-seeding on the restarted runtime is a no-op (never regress).
    assert engine2.seed_warmup("EURUSD", len(hist)) is False


def test_reset_then_fresh_boot_reseeds(tmp_path: Path):
    """--reset deletes state.json; the next boot re-seeds from fresh
    history, which is the correct behavior."""
    engine, hist = _build_engine(tmp_path)
    engine.seed_warmup("EURUSD", len(hist))
    engine.save_state()
    (engine.out_dir / "state.json").unlink()

    engine2 = SquadEngine(
        build_roster(barou_v13=False),
        engine.out_dir,
        aggregator_arm="phi41",
        source_label="live_market:test",
    )
    engine2.prepare({"EURUSD": hist})
    assert engine2.bars_seen["EURUSD"] == 0
    assert engine2.seed_warmup("EURUSD", len(hist)) is True
    assert engine2.bars_seen["EURUSD"] == WARMUP_BARS
    assert engine2.burn_in_remaining["EURUSD"] == DEFAULT_LIVE_BURN_IN_BARS
