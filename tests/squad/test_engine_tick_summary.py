"""Per-tick summary events (``tick_summary`` in ``events.jsonl``).

The live squad engine emits one ``tick_summary`` row per ``on_bar`` call
regardless of whether any proposals fired. That row is the /v2
dashboard's proof-of-life signal on quiet H4 bars (the ~99% case at
current activity) so operators can tell the squad is evaluating rather
than asleep.

These tests pin:

1. A silent tick (0 proposals) still writes exactly one row.
2. The row's ``players_evaluated`` matches the eligible proposer roster
   for the symbol (Karasu / Kunigami excluded — they are side channels).
3. When a proposal fires and passes Sentinel, ``proposal_count`` and
   ``post_sentinel_count`` are both 1 and ``players_who_proposed``
   contains the firing agent.
4. The written row round-trips through
   :func:`agent.platform.squad_events.build_timeline` as a
   ``tick_summary`` timeline event AND does NOT contribute to the
   per-agent goal / trade / proposal tallies (those come only from
   proposal / rejected / trade files).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.platform import squad_events
from agent.squad import engine as engine_module
from agent.squad.aggregator import AggregationOutcome
from agent.squad.engine import SquadEngine, TickResult
from agent.squad.roster import build_roster
from agent.squad.sentinel import SentinelDecision
from agent.squad.types import AgentProposal, LadderRung
from agent.types import Bar, Timeframe


UTC = timezone.utc


def _bar(t: datetime, *, o: float = 1.10, h: float = 1.11,
         l: float = 1.09, c: float = 1.105) -> Bar:
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=100.0,
               timeframe=Timeframe.H4)


def _series(n: int, start: datetime) -> list[Bar]:
    return [_bar(start + timedelta(hours=4 * i)) for i in range(n)]


def _read_events_jsonl(out_dir: Path) -> list[dict]:
    path = out_dir / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x]


def _build_engine(tmp_path: Path) -> tuple[SquadEngine, list[Bar]]:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    hist = _series(210, start)
    engine = SquadEngine(
        build_roster(barou_v13=False),
        tmp_path / "squad_live",
        aggregator_arm="phi41",
        source_label="live_market:test",
    )
    engine.prepare({"EURUSD": hist})
    return engine, hist


def test_silent_tick_emits_summary_with_zero_proposals(tmp_path: Path):
    """Every on_bar call writes exactly one tick_summary row even when
    no agent proposes — the whole point of the fix."""
    engine, hist = _build_engine(tmp_path)
    bar_i = hist[201]
    engine.on_bar("EURUSD", bar_i, bar_index=201, next_bar=hist[202])

    rows = _read_events_jsonl(engine.out_dir)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["type"] == "tick_summary"
    assert row["symbol"] == "EURUSD"
    assert row["tick_id"] == 1
    assert row["proposal_count"] == 0
    assert row["post_sentinel_count"] == 0
    assert row["players_who_proposed"] == []
    # Karasu (a8) and Kunigami (a10) are NOT proposers -> not in the
    # evaluated list. The 7-proposer roster provides players evaluated
    # on EURUSD (Barou is USDCAD-only, so 6 remain — pinning that
    # would over-couple to Barou's config; we just assert the shape).
    assert isinstance(row["players_evaluated"], list)
    assert "karasu_defender" not in row["players_evaluated"]
    assert "kunigami_rensuke" not in row["players_evaluated"]
    assert row["players_evaluated"] == sorted(row["players_evaluated"])
    assert isinstance(row["workspace_thought_count"], int)


def test_multiple_ticks_each_emit_their_own_summary(tmp_path: Path):
    """N on_bar calls -> N tick_summary rows, one per tick, in order."""
    engine, hist = _build_engine(tmp_path)
    for i in (201, 202, 203):
        engine.on_bar("EURUSD", hist[i], bar_index=i, next_bar=hist[i + 1])
    rows = _read_events_jsonl(engine.out_dir)
    assert len(rows) == 3
    tids = [r["tick_id"] for r in rows]
    assert tids == sorted(tids), "rows must be written in tick order"
    for r in rows:
        assert r["type"] == "tick_summary"
        assert r["symbol"] == "EURUSD"


def test_warmup_tick_also_emits_summary(tmp_path: Path):
    """Warmup ticks (bars_seen <= WARMUP_BARS) still emit a summary —
    proof of life fires from the very first bar the engine sees."""
    start = datetime(2024, 2, 1, tzinfo=UTC)
    hist = _series(210, start)
    engine = SquadEngine(
        build_roster(barou_v13=False),
        tmp_path / "squad_live",
        aggregator_arm="phi41",
        source_label="live_market:warmup",
    )
    # Seed history from an empty state so the very first on_bar is
    # inside the warmup window (bars_seen == 1 << WARMUP_BARS = 200).
    engine.prepare({"EURUSD": []})
    engine.on_bar("EURUSD", hist[0], bar_index=0, next_bar=hist[1])
    rows = _read_events_jsonl(engine.out_dir)
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "tick_summary"
    assert row["proposal_count"] == 0


def test_proposal_that_passes_sentinel_recorded_in_summary(
        tmp_path: Path, monkeypatch):
    """When Sentinel allows a proposal, tick_summary records
    proposal_count=1, post_sentinel_count=1, players_who_proposed=[id]."""
    engine, hist = _build_engine(tmp_path)

    # Craft a proposal for the current bar and force it through both
    # aggregator and Sentinel via monkeypatch so we don't depend on
    # any agent's live intend() heuristics firing on synthetic bars.
    bar_i = hist[201]
    next_bar = hist[202]
    proposal = AgentProposal(
        agent_id="isagi_yoichi",
        tick_id=1,
        source_thought_id="isagi_yoichi:1:EURUSD",
        timestamp=bar_i.time,
        symbol="EURUSD",
        direction="long",
        entry=1.1000,
        stop=1.0980,
        ladder=[LadderRung(price=1.1030, fraction=1.0)],
        conviction=0.75,
        regime_fit=0.5,
        valid_until=bar_i.time + timedelta(hours=24),
        rationale={"signal_reason": "test"},
        agent_tier=1,
    )

    def _accept(_p, _ctx):
        return SentinelDecision(
            allowed=True, rule="R0", reason="test_accept",
            payload={}, risk_scale=1.0,
        )

    monkeypatch.setattr(
        engine_module, "sentinel_evaluate_proposal", _accept,
    )

    # Drive the tick's admit path directly so we skip any agent-side
    # intend heuristics that might yield None on synthetic bars.
    engine.tick_id = 1
    engine.bars_seen["EURUSD"] = 300  # past warmup
    engine.last_bar_times["EURUSD"] = bar_i.time.isoformat()
    result = TickResult()
    result.proposals.append(proposal)
    outcome = AggregationOutcome(
        accepted=[proposal],
        rejected=[],
        ranked_by_symbol={"EURUSD": [proposal]},
    )
    engine._admit(
        symbol="EURUSD", bar=bar_i, next_bar=next_bar,
        tick_id=1, outcome=outcome, result=result,
    )
    engine._emit_tick_summary(
        symbol="EURUSD", bar_time_iso=bar_i.time.isoformat(),
        eligible=[a for a in engine.roster.proposers if "EURUSD" in a.symbols],
        result=result,
    )

    rows = _read_events_jsonl(engine.out_dir)
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "tick_summary"
    assert row["proposal_count"] == 1
    assert row["post_sentinel_count"] == 1
    assert row["players_who_proposed"] == ["isagi_yoichi"]


def test_tick_summary_does_not_count_toward_trade_tally(tmp_path: Path):
    """build_timeline sees the tick_summary row but _summarise MUST
    NOT double-count it as a proposal / block / trade / goal."""
    engine, hist = _build_engine(tmp_path)
    for i in (201, 202):
        engine.on_bar("EURUSD", hist[i], bar_index=i, next_bar=hist[i + 1])

    events, summary = squad_events.build_timeline(engine.out_dir)
    ticks = [e for e in events if e["type"] == "tick_summary"]
    assert len(ticks) == 2, "one tick_summary event per on_bar"
    # No per-agent counts should have moved -- tick_summary is a footer.
    for aid, d in summary["per_agent"].items():
        assert d["proposals"] == 0, (aid, d)
        assert d["blocked"] == 0, (aid, d)
        assert d["trades"] == 0, (aid, d)
        assert d["goals"] == 0, (aid, d)
