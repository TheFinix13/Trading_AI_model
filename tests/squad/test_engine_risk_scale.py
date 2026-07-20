"""Engine-level enforcement of SentinelDecision.risk_scale.

Sentinel R7 (news-impact medium) and R5 (loss-streak) already return
``SentinelDecision.risk_scale`` between 0.0 and 1.0. Historically the
engine ignored that field and let the paper broker fill FIXED_LOT
regardless. These tests pin the closed gap:

1. A medium-impact R7 decision (risk_scale=0.5) on an otherwise-passing
   proposal produces a fill at exactly 0.5 x FIXED_LOT.
2. A risk_scale that drives the scaled lot below the broker's MIN_LOT
   floor causes the proposal to be skipped entirely -- NOT rounded up
   back to MIN_LOT (which would defeat the point of the scale-down).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.alphas.backtest import FIXED_LOT
from agent.squad import engine as engine_module
from agent.squad.aggregator import AggregationOutcome
from agent.squad.engine import SquadEngine, TickResult
from agent.squad.roster import build_roster
from agent.squad.sentinel import MIN_LOT, SentinelDecision
from agent.squad.types import AgentProposal, LadderRung
from agent.types import Bar, Timeframe


UTC = timezone.utc


def _bar(t: datetime, *, o: float = 1.10, h: float = 1.11,
         l: float = 1.09, c: float = 1.105) -> Bar:
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=100.0,
               timeframe=Timeframe.H4)


def _series(n: int, start: datetime) -> list[Bar]:
    return [_bar(start + timedelta(hours=4 * i)) for i in range(n)]


def _proposal(ts: datetime, *, agent_id: str = "isagi_yoichi",
              symbol: str = "EURUSD") -> AgentProposal:
    entry, stop, tp = 1.1000, 1.0980, 1.1030
    return AgentProposal(
        agent_id=agent_id,
        tick_id=1,
        source_thought_id=f"{agent_id}:1:{symbol}",
        timestamp=ts,
        symbol=symbol,
        direction="long",
        entry=entry,
        stop=stop,
        ladder=[LadderRung(price=tp, fraction=1.0)],
        conviction=0.75,
        regime_fit=0.5,
        valid_until=ts + timedelta(hours=24),
        rationale={"signal_reason": "test"},
        agent_tier=1,
    )


def _build_engine(tmp_path: Path) -> tuple[SquadEngine, list[Bar], datetime]:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    hist = _series(210, start)
    engine = SquadEngine(
        build_roster(barou_v13=False),
        tmp_path / "squad_live",
        aggregator_arm="phi41",
        source_label="live_market:test",
    )
    engine.prepare({"EURUSD": hist})
    return engine, hist, start


def test_risk_scale_half_produces_half_lot(tmp_path: Path, monkeypatch) -> None:
    """R7 medium-impact (risk_scale=0.5) -> filled lot == 0.5 x FIXED_LOT."""
    engine, hist, _ = _build_engine(tmp_path)

    def _accept_with_scale(_proposal, _ctx):
        return SentinelDecision(
            allowed=True,
            rule="R7",
            reason="stub_r7_medium_scale",
            payload={},
            risk_scale=0.5,
        )

    monkeypatch.setattr(
        engine_module, "sentinel_evaluate_proposal", _accept_with_scale,
    )

    bar_i = hist[201]
    next_bar = hist[202]
    proposal = _proposal(bar_i.time)
    outcome = AggregationOutcome(
        accepted=[proposal],
        rejected=[],
        ranked_by_symbol={"EURUSD": [proposal]},
    )
    result = TickResult()

    engine._admit(
        symbol="EURUSD",
        bar=bar_i,
        next_bar=next_bar,
        tick_id=42,
        outcome=outcome,
        result=result,
    )

    assert "EURUSD" in engine.open_trades, (
        "R7 scale-only path must fill (allowed=True), not skip"
    )
    ot = engine.open_trades["EURUSD"]
    assert ot.trade.lot_size == pytest.approx(FIXED_LOT * 0.5)
    assert result.rejected == []


def test_risk_scale_below_min_lot_skips_trade(
        tmp_path: Path, monkeypatch, capsys) -> None:
    """risk_scale that pushes scaled_lot below MIN_LOT -> no fill, reject row."""
    engine, hist, _ = _build_engine(tmp_path)

    # risk_scale=0.05 -> scaled_lot = 0.1 * 0.05 = 0.005, below MIN_LOT (0.01).
    tiny_scale = 0.05
    assert FIXED_LOT * tiny_scale + 1e-9 < MIN_LOT, "test premise broken"

    def _accept_with_tiny_scale(_proposal, _ctx):
        return SentinelDecision(
            allowed=True,
            rule="R7",
            reason="stub_r7_scale_below_min_lot",
            payload={},
            risk_scale=tiny_scale,
        )

    monkeypatch.setattr(
        engine_module, "sentinel_evaluate_proposal", _accept_with_tiny_scale,
    )

    bar_i = hist[201]
    next_bar = hist[202]
    proposal = _proposal(bar_i.time)
    outcome = AggregationOutcome(
        accepted=[proposal],
        rejected=[],
        ranked_by_symbol={"EURUSD": [proposal]},
    )
    result = TickResult()

    engine._admit(
        symbol="EURUSD",
        bar=bar_i,
        next_bar=next_bar,
        tick_id=42,
        outcome=outcome,
        result=result,
    )

    assert "EURUSD" not in engine.open_trades, (
        "sub-min-lot risk_scale must NOT round back up to MIN_LOT"
    )
    assert len(result.rejected) == 1
    rej = result.rejected[0]
    assert rej["rejection_reason"] == "sentinel_risk_scale_below_min_lot"
    assert rej["sentinel_rule"] == "R7"
    assert "min_lot" in rej["sentinel_reason"]
