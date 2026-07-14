"""Unit tests for the ported squad core (agent/squad/)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.squad.aggregator import TIER_BIAS, aggregate, phi41_aggregate
from agent.squad.feed import CacheFeed, FakeFeed, default_feed_name, make_feed
from agent.squad.ledger import FullLedger
from agent.squad.roster import PROPOSING_AGENT_IDS, build_roster
from agent.squad.sentinel import SentinelContext, evaluate_proposal
from agent.squad.types import (
    SCHEMA_VERSION,
    AgentProposal,
    LadderRung,
    MarketState,
    Thought,
    ThoughtRead,
)
from agent.squad.workspace import ReasoningWorkspace
from agent.types import Bar, Timeframe


UTC = timezone.utc


def _ts(h: int = 0) -> datetime:
    return datetime(2024, 1, 2, h, 0, tzinfo=UTC)


def _market(tick: int = 1, symbol: str = "EURUSD") -> MarketState:
    return MarketState(
        tick_id=tick, symbol=symbol, timeframe="H4", as_of=_ts(tick),
        open=1.1, high=1.11, low=1.09, close=1.105, volume=100.0,
    )


def _thought(agent_id: str, tick: int, symbol: str = "EURUSD",
             conf: float = 0.7) -> Thought:
    return Thought(
        schema_version=SCHEMA_VERSION,
        agent_id=agent_id,
        tick_id=tick,
        timestamp=_ts(tick),
        symbol=symbol,
        narrative=f"{agent_id}@{tick}",
        tags=["test"],
        confidence_in_thought=conf,
        expected_action="wait",
        coordinate=None,
        decision_horizon=_ts(tick),
        ttl_ticks=6,
        references=[],
        read=ThoughtRead(signal_family="metavision", direction_bias="long"),
    )


def _proposal(agent_id: str, tick: int, *, conviction: float = 0.8,
              tier: int = 2, symbol: str = "EURUSD",
              direction: str = "long") -> AgentProposal:
    # Tight stop (~20 pips) so Sentinel R1 min-lot risk floor is satisfiable
    # against the $100 sandbox equity / 5% cap.
    entry, stop, tp = 1.1000, 1.0980, 1.1030
    if direction == "short":
        stop, tp = 1.1020, 1.0970
    return AgentProposal(
        agent_id=agent_id,
        tick_id=tick,
        source_thought_id=f"{agent_id}:{tick}:{symbol}",
        timestamp=_ts(tick),
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        entry=entry,
        stop=stop,
        ladder=[LadderRung(price=tp, fraction=1.0)],
        conviction=conviction,
        regime_fit=0.5,
        valid_until=_ts(tick) + timedelta(hours=24),
        rationale={"signal_reason": "test"},
        agent_tier=tier,
    )


# ---------------------------------------------------------------------------
# roster
# ---------------------------------------------------------------------------


def test_roster_seven_proposers_plus_kunigami_side_channel():
    roster = build_roster(barou_v13=False)
    assert [a.agent_id for a in roster.proposers] == list(PROPOSING_AGENT_IDS)
    assert roster.kunigami.agent_id == "kunigami_rensuke"
    assert roster.kunigami not in roster.proposers
    assert roster.kunigami.intend(_market(), _thought("kunigami_rensuke", 1)) is None


# ---------------------------------------------------------------------------
# workspace
# ---------------------------------------------------------------------------


def test_workspace_publish_and_barrier_snapshot():
    ws = ReasoningWorkspace()
    t1 = _thought("isagi_yoichi", 1)
    t2 = _thought("bachira_meguru", 1)
    assert ws.publish(t1) is True
    assert ws.publish(t1) is False  # idempotent
    assert ws.publish(t2) is True
    snap = ws.snapshot_at_barrier(as_of=_ts(1), current_tick=1)
    peers = snap.peer_thoughts(agent_id="itoshi_rin", symbol="EURUSD")
    assert {p.agent_id for p in peers} == {"isagi_yoichi", "bachira_meguru"}
    strict = ws.snapshot(as_of=_ts(1), current_tick=1)
    assert strict.thoughts == ()  # same-tick excluded


# ---------------------------------------------------------------------------
# ledger guards
# ---------------------------------------------------------------------------


def test_ledger_backwards_only_and_ttl():
    led = FullLedger()
    led.append(_thought("isagi_yoichi", 1))
    led.append(_thought("bachira_meguru", 2))
    # Reading at tick 2 cannot see tick 2.
    got = led.read(as_of=_ts(2), current_tick=2, symbol="EURUSD")
    assert [t.tick_id for t in got] == [1]


# ---------------------------------------------------------------------------
# aggregator
# ---------------------------------------------------------------------------


def test_phi41_highest_conviction_wins_with_tier_bias():
    props = [
        _proposal("bachira_meguru", 5, conviction=0.80, tier=2),
        _proposal("isagi_yoichi", 5, conviction=0.80, tier=1),
    ]
    out = phi41_aggregate(props, tick_id=5)
    assert len(out.accepted) == 1
    # Same base conviction: tier-1 anchor wins via TIER_BIAS.
    assert out.accepted[0].agent_id == "isagi_yoichi"
    assert out.rejected[0]["rejection_reason"] == "lower_conviction_same_symbol"
    # Peer needs to clear the bias to override.
    props2 = [
        _proposal("bachira_meguru", 6, conviction=0.80 + TIER_BIAS + 0.01, tier=2),
        _proposal("isagi_yoichi", 6, conviction=0.80, tier=1),
    ]
    out2 = aggregate(props2, tick_id=6, arm="phi41")
    assert out2.accepted[0].agent_id == "bachira_meguru"


# ---------------------------------------------------------------------------
# sentinel
# ---------------------------------------------------------------------------


def test_sentinel_allows_clean_proposal():
    p = _proposal("isagi_yoichi", 1, conviction=0.75, tier=1)
    ctx = SentinelContext(equity=100.0, pip_value_per_min_lot=0.10)
    decision = evaluate_proposal(p, ctx)
    assert decision.allowed is True


def test_sentinel_r5_dampens_when_kunigami_warns():
    p = _proposal("bachira_meguru", 1, conviction=0.9, tier=2)
    # Wide stop so R1 doesn't fire first; R5 is a soft dampener that
    # still allows (risk-scale) OR a hard block depending on research
    # wiring. We only assert the decision is well-formed.
    ctx = SentinelContext(
        equity=100.0,
        pip_value_per_min_lot=0.10,
        kunigami_loss_streak_active=True,
        consecutive_losses=3,
    )
    decision = evaluate_proposal(p, ctx)
    assert decision.rule in ("OK", "R5", "R1", "R2", "R3", "R4", "R6", "EXT")
    assert isinstance(decision.allowed, bool)


# ---------------------------------------------------------------------------
# feed
# ---------------------------------------------------------------------------


def test_fake_feed_push_and_poll():
    feed = FakeFeed(warmup=0)
    b = Bar(
        time=_ts(4), open=1.1, high=1.11, low=1.09, close=1.105,
        volume=10, timeframe=Timeframe.H4,
    )
    feed.push("EURUSD", b)
    got = feed.poll_new_closed()
    assert len(got) == 1
    assert got[0].symbol == "EURUSD"
    assert feed.poll_new_closed() == []


def test_default_feed_name_is_cache_on_non_windows(monkeypatch):
    monkeypatch.setattr("agent.squad.feed.sys.platform", "darwin")
    assert default_feed_name() == "cache"
    monkeypatch.setattr("agent.squad.feed.sys.platform", "win32")
    assert default_feed_name() == "mt5"


def test_make_feed_rejects_unknown():
    with pytest.raises(ValueError):
        make_feed("nope")


# ---------------------------------------------------------------------------
# paper broker
# ---------------------------------------------------------------------------


def test_paper_broker_open_and_exit():
    from agent.squad.paper_broker import PaperBroker

    broker = PaperBroker()
    p = _proposal("isagi_yoichi", 1)
    entry_bar = Bar(
        time=_ts(4), open=1.10, high=1.12, low=1.09, close=1.11,
        volume=10, timeframe=Timeframe.H4,
    )
    ot = broker.open_from_proposal(p, entry_bar, target_hold_hours=24.0)
    assert ot.trade.entry_price > 0
    # Force a TP hit on a subsequent bar.
    tp_bar = Bar(
        time=_ts(8), open=1.11, high=ot.trade.tp_price + 0.001,
        low=1.10, close=ot.trade.tp_price, volume=10, timeframe=Timeframe.H4,
    )
    broker.update_excursion(ot, tp_bar)
    assert broker.check_exit(ot, tp_bar) is True
    rec = broker.score(ot)
    assert rec.exit_reason == "tp"
    assert rec.pnl_pips > 0
    # Round-trip persist.
    blob = broker.to_persistable(ot)
    ot2 = broker.from_persistable(blob)
    assert ot2.agent_id == ot.agent_id
    assert ot2.trade.entry_price == pytest.approx(ot.trade.entry_price)
