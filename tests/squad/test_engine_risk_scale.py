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


def _build_engine(
    tmp_path: Path,
    *,
    equity: float | None = None,
    risk_derived_sizing: bool = False,
) -> tuple[SquadEngine, list[Bar], datetime]:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    hist = _series(210, start)
    kwargs: dict = {}
    if equity is not None:
        kwargs["equity"] = equity
    engine = SquadEngine(
        build_roster(barou_v13=False),
        tmp_path / "squad_live",
        aggregator_arm="phi41",
        source_label="live_market:test",
        risk_derived_sizing=risk_derived_sizing,
        **kwargs,
    )
    engine.prepare({"EURUSD": hist})
    return engine, hist, start


def _admit_one(engine: SquadEngine, hist: list[Bar]) -> TickResult:
    bar_i, next_bar = hist[201], hist[202]
    proposal = _proposal(bar_i.time)
    outcome = AggregationOutcome(
        accepted=[proposal],
        rejected=[],
        ranked_by_symbol={"EURUSD": [proposal]},
    )
    result = TickResult()
    engine._admit(
        symbol="EURUSD", bar=bar_i, next_bar=next_bar, tick_id=42,
        outcome=outcome, result=result,
    )
    return result


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


# ---------------------------------------------------------------------------
# F025 blocker B3 -- risk-derived sizing (default OFF)
# ---------------------------------------------------------------------------

def test_default_off_still_fills_fixed_lot(tmp_path: Path) -> None:
    """The byte-identical guarantee.

    Every banked replay and the whole shadow tape were produced with a
    fixed-lot fill. If the default ever changes, all of that evidence
    silently stops being comparable -- so this is the test that has to
    fail before anyone flips the default.
    """
    engine, hist, _ = _build_engine(tmp_path, equity=500.0)
    assert engine.risk_derived_sizing is False
    _admit_one(engine, hist)
    assert engine.open_trades["EURUSD"].trade.lot_size == pytest.approx(FIXED_LOT)


def test_risk_derived_sizing_shrinks_the_fill_to_the_budget(
        tmp_path: Path) -> None:
    """20-pip stop on a $500 book: 5 % cap = $25, $200/lot -> 0.12 lots
    wanted, but never above FIXED_LOT, so it stays 0.1. Widen the stop
    and it must shrink -- see the next test for the biting case."""
    engine, hist, _ = _build_engine(
        tmp_path, equity=500.0, risk_derived_sizing=True,
    )
    _admit_one(engine, hist)
    lot = engine.open_trades["EURUSD"].trade.lot_size
    assert lot <= FIXED_LOT + 1e-9
    # Realised risk must respect the cap the sentinel advertises.
    sl_pips = 20.0                      # 1.1000 -> 1.0980
    assert sl_pips * lot * 10.0 <= 0.05 * 500.0 + 1e-9


def test_risk_derived_sizing_shrinks_hard_on_the_100_dollar_book(
        tmp_path: Path) -> None:
    """The case that motivated B3.

    On the $100 sandbox the 5 % budget is $5. A 20-pip EURUSD stop costs
    $200 per lot, so only 0.025 lots are affordable -> 0.02 after
    rounding down. The fixed-lot fill was 0.1, which is $40 of risk on a
    $100 account: 40 %, not the advertised 5 %.
    """
    engine, hist, _ = _build_engine(
        tmp_path, equity=100.0, risk_derived_sizing=True,
    )
    _admit_one(engine, hist)
    lot = engine.open_trades["EURUSD"].trade.lot_size
    assert lot == pytest.approx(0.02)
    assert 20.0 * lot * 10.0 == pytest.approx(4.0)      # $4 <= $5 cap
    # What it would have been, for the record.
    assert 20.0 * FIXED_LOT * 10.0 == pytest.approx(20.0)


def test_risk_derived_sizing_scales_commission_with_the_lot(
        tmp_path: Path) -> None:
    """Commission is per-lot, so a shrunk fill must not carry the cost
    of a full one -- otherwise the smaller position looks worse than it
    is and the tape's KPIs drift."""
    baseline, hist_b, _ = _build_engine(tmp_path / "a", equity=100.0)
    _admit_one(baseline, hist_b)
    full = baseline.open_trades["EURUSD"].trade

    sized, hist_s, _ = _build_engine(
        tmp_path / "b", equity=100.0, risk_derived_sizing=True,
    )
    _admit_one(sized, hist_s)
    small = sized.open_trades["EURUSD"].trade

    assert small.lot_size < full.lot_size
    if full.commission > 0:
        ratio = small.commission / full.commission
        assert ratio == pytest.approx(small.lot_size / full.lot_size, rel=1e-6)


def test_r1_catches_the_unfundable_case_before_sizing_runs(
        tmp_path: Path) -> None:
    """R1 and the budget lot share one cap, so the unfundable case is
    R1's by construction.

    $10 equity gives a $0.50 budget while one min-lot on a 20-pip stop
    costs $2. Both R1 and ``risk_budget_lot`` reject that -- and R1 runs
    first, so the sizing step never has to produce a zero lot. That
    ordering is why R1 stays exactly as it is: it is the floor check
    ("can this account hold the smallest legal position at all?"), and
    the budget lot is the cap. Wiring the sizing step did not make R1
    redundant.
    """
    engine, hist, _ = _build_engine(
        tmp_path, equity=10.0, risk_derived_sizing=True,
    )
    result = _admit_one(engine, hist)
    assert "EURUSD" not in engine.open_trades
    assert len(result.rejected) == 1
    assert result.rejected[0]["rejection_reason"] == "sentinel_R1_block"


def test_zero_lot_from_the_budget_is_reported_not_rounded_up(
        tmp_path: Path) -> None:
    """Defensive path: if the two caps ever drift apart so a proposal
    clears R1 but cannot fund a min-lot, the engine must skip and say so
    rather than round back up to MIN_LOT."""
    engine, hist, _ = _build_engine(
        tmp_path, equity=500.0, risk_derived_sizing=True,
    )
    # Simulate the drift by starving only the sizing step's budget.
    monkey_cap = 0.00001
    engine_module_cap = engine_module.SANDBOX_PER_TRADE_RISK_FRAC
    try:
        engine_module.SANDBOX_PER_TRADE_RISK_FRAC = monkey_cap
        result = _admit_one(engine, hist)
    finally:
        engine_module.SANDBOX_PER_TRADE_RISK_FRAC = engine_module_cap
    assert "EURUSD" not in engine.open_trades
    assert len(result.rejected) == 1
    rej = result.rejected[0]
    assert rej["rejection_reason"] == "sentinel_risk_scale_below_min_lot"
    assert "risk_budget_lot" in rej["sentinel_reason"]


def test_risk_derived_sizing_composes_with_an_advisory_risk_scale(
        tmp_path: Path, monkeypatch) -> None:
    """R5/R7 advisory scale-downs must still apply ON TOP of the budget
    lot, not replace it -- a loss-streak dampener during a news window
    should compound with the cap, never override it."""
    engine, hist, _ = _build_engine(
        tmp_path, equity=500.0, risk_derived_sizing=True,
    )

    def _accept_with_scale(_proposal, _ctx):
        return SentinelDecision(
            allowed=True, rule="R5", reason="stub_loss_streak",
            payload={}, risk_scale=0.5,
        )

    monkeypatch.setattr(
        engine_module, "sentinel_evaluate_proposal", _accept_with_scale,
    )
    _admit_one(engine, hist)
    lot = engine.open_trades["EURUSD"].trade.lot_size
    # Budget lot on $500 / 20-pip stop is capped at FIXED_LOT (0.1);
    # the 0.5 dampener then halves it.
    assert lot == pytest.approx(FIXED_LOT * 0.5)
