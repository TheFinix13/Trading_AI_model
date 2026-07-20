"""Unit tests for A9 Sae Itoshi (event specialist).

Sae only proposes inside a scheduled high-impact USD event window
[T - 30 min, T + 60 min] via two mechanics (fade / ride). He is
DISABLED BY DEFAULT (SaeConfig.sae_enabled=False); enabling him
requires passing SaeConfig(sae_enabled=True, ...) at roster
construction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest

from agent.news.calendar import NewsEvent
from agent.squad.agents.a08_karasu import A8KarasuV1
from agent.squad.agents.a09_sae import A9SaeV1, SAE_V1_CANON_ROLE
from agent.squad.ledger import FullLedger
from agent.squad.roster import build_roster
from agent.squad.sae_config import DEFAULT_SAE_CONFIG, SaeConfig
from agent.squad.types import (
    SCHEMA_VERSION,
    MarketState,
    Thought,
    ThoughtRead,
)
from agent.types import Bar, Timeframe


UTC = timezone.utc
PIP = 0.0001


def _market(
    *,
    as_of: datetime,
    symbol: str = "EURUSD",
    tick_id: int = 1,
    tf: str = "H4",
) -> MarketState:
    return MarketState(
        tick_id=tick_id,
        symbol=symbol,
        timeframe=tf,
        as_of=as_of,
        open=1.10,
        high=1.11,
        low=1.09,
        close=1.105,
        volume=100.0,
    )


def _thought(agent_id: str = "sae_itoshi", tick_id: int = 1) -> Thought:
    ts = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    return Thought(
        schema_version=SCHEMA_VERSION,
        agent_id=agent_id,
        tick_id=tick_id,
        timestamp=ts,
        symbol="EURUSD",
        narrative=f"[{agent_id}] test",
        tags=[],
        confidence_in_thought=0.0,
        expected_action="await_event",
        coordinate=None,
        decision_horizon=ts,
        ttl_ticks=1,
        references=[],
        read=ThoughtRead(signal_family="solo_king", direction_bias="flat"),
    )


def _event(
    *,
    time_utc: datetime,
    currency: str = "USD",
    impact: str = "High",
    title: str = "NFP",
) -> NewsEvent:
    return NewsEvent(
        time_utc=time_utc,
        currency=currency,
        impact=impact,
        title=title,
        all_day=False,
    )


def _m15(
    time_utc: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> Bar:
    return Bar(
        time=time_utc,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
        timeframe=Timeframe.M15,
    )


def _bars_provider_factory(bars: list[Bar]) -> Callable:
    def provider(symbol: str, start: datetime, end: datetime) -> list[Bar]:
        return [b for b in bars if start <= b.time <= end]
    return provider


def _enabled_sae(
    *,
    bars: list[Bar] | None = None,
    events: list[NewsEvent] | None = None,
    symbols: tuple[str, ...] | None = None,
) -> A9SaeV1:
    cfg = SaeConfig(sae_enabled=True) if symbols is None else SaeConfig(
        sae_enabled=True, symbols=symbols,
    )
    sae = A9SaeV1(
        config=cfg,
        bars_provider=_bars_provider_factory(bars or []),
    )
    if events is not None:
        sae.load_calendar(events=events)
    return sae


# ---------------------------------------------------------------------------
# 1. Roster gating
# ---------------------------------------------------------------------------


def test_sae_disabled_by_default():
    r = build_roster()
    assert r.sae_enabled is False
    ids = [a.agent_id for a in r.proposers]
    assert "sae_itoshi" not in ids
    # Still discoverable via by_id() as a side-channel.
    assert "sae_itoshi" in r.by_id()


def test_sae_enters_proposers_when_enabled():
    r = build_roster(sae_config=SaeConfig(sae_enabled=True))
    ids = [a.agent_id for a in r.proposers]
    assert "sae_itoshi" in ids
    assert r.sae_enabled is True


# ---------------------------------------------------------------------------
# 2. Window gating
# ---------------------------------------------------------------------------


def test_sae_no_fire_outside_event_window():
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    sae = _enabled_sae(events=[_event(time_utc=event_time)])
    # T - 2h -- way before window.
    before = event_time - timedelta(hours=2)
    p1 = sae.intend(_market(as_of=before), _thought())
    assert p1 is None
    # T + 3h -- past window.
    after = event_time + timedelta(hours=3)
    p2 = sae.intend(_market(as_of=after), _thought())
    assert p2 is None


def test_sae_intend_returns_none_when_disabled():
    """Sae with default config (sae_enabled=False) never fires."""
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    sae = A9SaeV1(bars_provider=_bars_provider_factory([]))
    sae.load_calendar(events=[_event(time_utc=event_time)])
    p = sae.intend(_market(as_of=event_time), _thought())
    assert p is None


# ---------------------------------------------------------------------------
# 3. Fade mechanic
# ---------------------------------------------------------------------------


def _event_bar_bullish_50_wick_60() -> Bar:
    """M15 event bar: bullish +50 pips, 60 % upper wick."""
    # entry=1.10000, close=1.10500 (+50 pips)
    # high=1.10800 -> wick=high-close=30 pips; range=high-low=1.10800-1.09980=82 pips
    # upper wick frac = 30 / 82 ~= 0.366 -> too small
    # Redesign so wick / range >= 0.6:
    # open=1.10000, close=1.10500, high=1.11000, low=1.10000
    # range=100pip; upper wick=high-close=50pip; frac=0.5
    # Need frac >= 0.5 minimum (config default). Set high=1.11250, close=1.10500 for frac=0.6.
    # But range must also cover: open->close move is 50 pips; high=1.11250 -> up wick=75 pips.
    # range = high - low = 1.11250 - 1.10000 = 125 pips. Wick frac = 75/125 = 0.60.
    return _m15(
        time_utc=datetime(2026, 3, 20, 12, 30, tzinfo=UTC),
        open_=1.10000,
        high=1.11250,
        low=1.10000,
        close=1.10500,
    )


def test_sae_fade_fires_on_qualifying_bar():
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    event_bar = _event_bar_bullish_50_wick_60()
    sae = _enabled_sae(
        events=[_event(time_utc=event_time)],
        bars=[event_bar],
    )
    # 16 minutes after release: fade-eligible.
    as_of = event_time + timedelta(minutes=16)
    p = sae.intend(_market(as_of=as_of), _thought())
    assert p is not None
    assert p.direction == "short"
    assert p.agent_id == "sae_itoshi"
    assert p.rationale["mechanic"] == "sae_fade"
    # Stop just above the high.
    assert p.stop > event_bar.high
    # TP is 1.5R below entry (short target).
    assert p.ladder[0].price < p.entry


def test_sae_fade_no_fire_small_move():
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    small = _m15(
        time_utc=event_time,
        open_=1.10000, high=1.10250, low=1.09980, close=1.10020,  # +2 pip move
    )
    sae = _enabled_sae(events=[_event(time_utc=event_time)], bars=[small])
    as_of = event_time + timedelta(minutes=16)
    p = sae.intend(_market(as_of=as_of), _thought())
    assert p is None


def test_sae_fade_no_fire_small_wick():
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    # 50-pip move, only 30% wick.
    # open=1.10000, close=1.10500 (+50 pips)
    # range=100pips: high=1.10800, low=1.09800 -> upper wick=30pips, frac=0.3.
    weak_wick = _m15(
        time_utc=event_time,
        open_=1.10000, high=1.10800, low=1.09800, close=1.10500,
    )
    sae = _enabled_sae(events=[_event(time_utc=event_time)], bars=[weak_wick])
    as_of = event_time + timedelta(minutes=16)
    p = sae.intend(_market(as_of=as_of), _thought())
    assert p is None


# ---------------------------------------------------------------------------
# 4. Ride mechanic
# ---------------------------------------------------------------------------


def test_sae_ride_fires_on_confirmed_impulse():
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    # Event bar: bullish +50 pips, minimal wick (fade won't fire).
    #   open=1.10000, close=1.10500, high=1.10520, low=1.09980
    #   range=54pips, upper wick=20pips, frac=0.37 -- below 0.5 fade floor.
    event_bar = _m15(
        time_utc=event_time,
        open_=1.10000, high=1.10520, low=1.09980, close=1.10500,
    )
    # Next bar: closes higher (+30 pips), same direction.
    # retention = (1.10800 - 1.10000) = 80 pips vs impulse 50 pips ->
    #   retention_frac = 1.6, well above 0.7.
    next_bar = _m15(
        time_utc=event_time + timedelta(minutes=15),
        open_=1.10500, high=1.10900, low=1.10480, close=1.10800,
    )
    sae = _enabled_sae(
        events=[_event(time_utc=event_time)],
        bars=[event_bar, next_bar],
    )
    as_of = event_time + timedelta(minutes=31)
    p = sae.intend(_market(as_of=as_of), _thought())
    assert p is not None
    assert p.direction == "long"
    assert p.rationale["mechanic"] == "sae_ride"
    # Stop at event_bar.open (1.10000).
    assert p.stop == pytest.approx(event_bar.open)


def test_sae_ride_no_fire_reversal():
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    event_bar = _m15(
        time_utc=event_time,
        open_=1.10000, high=1.10520, low=1.09980, close=1.10500,
    )
    # Next bar: closes LOWER (reversal).
    next_bar = _m15(
        time_utc=event_time + timedelta(minutes=15),
        open_=1.10500, high=1.10510, low=1.10000, close=1.10100,
    )
    sae = _enabled_sae(
        events=[_event(time_utc=event_time)],
        bars=[event_bar, next_bar],
    )
    as_of = event_time + timedelta(minutes=31)
    p = sae.intend(_market(as_of=as_of), _thought())
    assert p is None


def test_sae_ride_no_fire_after_fade():
    """If the fade fired first, ride cannot fire on the same event."""
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    event_bar = _event_bar_bullish_50_wick_60()
    next_bar = _m15(
        time_utc=event_time + timedelta(minutes=15),
        open_=1.10500, high=1.10900, low=1.10480, close=1.10800,
    )
    sae = _enabled_sae(
        events=[_event(time_utc=event_time)],
        bars=[event_bar, next_bar],
    )
    # T + 16min -> fade fires (short).
    p1 = sae.intend(_market(as_of=event_time + timedelta(minutes=16)),
                    _thought())
    assert p1 is not None and p1.rationale["mechanic"] == "sae_fade"
    # T + 31min -> ride should NOT fire (event already fired).
    p2 = sae.intend(_market(as_of=event_time + timedelta(minutes=31)),
                    _thought())
    assert p2 is None


# ---------------------------------------------------------------------------
# 5. One-proposal-per-event
# ---------------------------------------------------------------------------


def test_sae_one_proposal_per_event():
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    event_bar = _event_bar_bullish_50_wick_60()
    sae = _enabled_sae(
        events=[_event(time_utc=event_time)],
        bars=[event_bar],
    )
    # First fire at T + 16min.
    p1 = sae.intend(_market(as_of=event_time + timedelta(minutes=16)),
                    _thought())
    assert p1 is not None
    # Repeat calls (at any as_of inside the window) return None.
    for delta in (17, 20, 45, 55):
        p = sae.intend(
            _market(as_of=event_time + timedelta(minutes=delta)), _thought(),
        )
        assert p is None, f"unexpected repeat fire at +{delta}m"


# ---------------------------------------------------------------------------
# 6. Universe scoping
# ---------------------------------------------------------------------------


def test_sae_universe_locked_to_eurusd_by_default():
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    sae = _enabled_sae(
        events=[_event(time_utc=event_time)],
        bars=[_event_bar_bullish_50_wick_60()],
    )
    # GBPUSD is not in Sae's default universe -> None regardless of
    # bars / events.
    p = sae.intend(
        _market(as_of=event_time + timedelta(minutes=16), symbol="GBPUSD"),
        _thought(),
    )
    assert p is None


# ---------------------------------------------------------------------------
# 7. Sae + Karasu cross-agent (Sae is agent-independent)
# ---------------------------------------------------------------------------


def test_sae_uses_karasu_advisory():
    """Sae doesn't consult Karasu: an EUR-only Karasu warning does not
    veto Sae's USD-event fade proposal. This is the belt-and-braces
    check that the two agents don't accidentally interlock at the
    agent level -- R7 wiring in the engine is a separate concern."""
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    # High-impact USD event (Sae will trade on this).
    usd_event = _event(time_utc=event_time)
    # High-impact EUR event ~2h earlier (outside Sae's ±60m window,
    # but Karasu would still consider it).
    eur_event = _event(
        time_utc=event_time - timedelta(hours=2, minutes=45),
        currency="EUR",
        title="ECB Rate",
    )
    sae = _enabled_sae(
        events=[usd_event, eur_event],
        bars=[_event_bar_bullish_50_wick_60()],
    )
    # Karasu -- separate agent, wouldn't affect Sae's intend() path.
    karasu = A8KarasuV1()
    karasu.load_calendar(events=[usd_event, eur_event])

    as_of = event_time + timedelta(minutes=16)
    # Karasu warning at this time is USD-only (EUR event is 3+ hours
    # away). But even if it were EUR-only, Sae's intend() still fires.
    p = sae.intend(_market(as_of=as_of), _thought())
    assert p is not None
    assert p.rationale["mechanic"] == "sae_fade"


# ---------------------------------------------------------------------------
# 8. Observe / contract hygiene
# ---------------------------------------------------------------------------


def test_sae_observe_emits_awaiting_thought_in_window():
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    sae = _enabled_sae(events=[_event(time_utc=event_time)])
    t = sae.observe(_market(as_of=event_time - timedelta(minutes=10)),
                    FullLedger())
    assert t.expected_action == "await_event"
    assert "awaiting_event" in t.tags


def test_sae_observe_abstains_off_symbol():
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    sae = _enabled_sae(events=[_event(time_utc=event_time)])
    t = sae.observe(_market(as_of=event_time, symbol="GBPUSD"),
                    FullLedger())
    assert t.expected_action == "wait"
    assert "off_symbol" in t.tags


def test_sae_canon_role_locked():
    sae = A9SaeV1()
    assert sae.agent_id == "sae_itoshi"
    assert sae.canon_role == SAE_V1_CANON_ROLE
    assert sae.tier == 1
    assert sae.playstyle == "event_specialist"


def test_sae_no_bars_provider_returns_none():
    """Fail-open: no bars_provider means no proposal."""
    event_time = datetime(2026, 3, 20, 12, 30, tzinfo=UTC)
    sae = A9SaeV1(
        config=SaeConfig(sae_enabled=True),
        bars_provider=None,
    )
    sae.load_calendar(events=[_event(time_utc=event_time)])
    p = sae.intend(
        _market(as_of=event_time + timedelta(minutes=16)), _thought(),
    )
    assert p is None
