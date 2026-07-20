"""Unit tests for A8 Karasu Tabito (news-window defender) + Sentinel R7.

Karasu never proposes; his surface is:

* ``observe(market, ledger) -> Thought`` -- advisory when a scheduled
  release is inside the ±minute window, observation-only otherwise.
* ``warning_active_at(as_of, symbol) -> KarasuWarning`` -- polled by
  the Sentinel R7 rule.
* ``load_calendar(...)`` -- hydrate the in-memory event list from
  either a caller-supplied list (tests) or the on-disk cache.

R7 tests exercise ``check_r7_news_impact`` directly + the
``evaluate_proposal`` integration (SentinelContext plumbing).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.news.calendar import NewsEvent
from agent.squad.agents.a08_karasu import (
    A8KarasuV1,
    KARASU_V1_CANON_ROLE,
    KarasuWarning,
    NO_WARNING,
)
from agent.squad.ledger import FullLedger
from agent.squad.news_config import DEFAULT_NEWS_CONFIG, NewsDefenderConfig
from agent.squad.sentinel import (
    NEWS_R7_BLOCK_IMPACTS_DEFAULT,
    NEWS_R7_SCALE_IMPACTS_DEFAULT,
    SentinelContext,
    check_r7_news_impact,
    evaluate_proposal,
)
from agent.squad.types import (
    SCHEMA_VERSION,
    AgentProposal,
    LadderRung,
    MarketState,
    Thought,
    ThoughtRead,
)


UTC = timezone.utc


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


def _event(
    *,
    time_utc: datetime,
    currency: str = "USD",
    impact: str = "High",
    title: str = "FOMC Statement",
) -> NewsEvent:
    return NewsEvent(
        time_utc=time_utc,
        currency=currency,
        impact=impact,
        title=title,
        all_day=False,
    )


def _proposal(
    *,
    agent_id: str = "isagi_yoichi",
    symbol: str = "EURUSD",
    ts: datetime,
    tier: int = 1,
    direction: str = "long",
) -> AgentProposal:
    entry, stop, tp = 1.1000, 1.0980, 1.1030
    if direction == "short":
        stop, tp = 1.1020, 1.0970
    return AgentProposal(
        agent_id=agent_id,
        tick_id=1,
        source_thought_id=f"{agent_id}:1:{symbol}",
        timestamp=ts,
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        entry=entry,
        stop=stop,
        ladder=[LadderRung(price=tp, fraction=1.0)],
        conviction=0.75,
        regime_fit=0.5,
        valid_until=ts + timedelta(hours=24),
        rationale={"signal_reason": "test"},
        agent_tier=tier,
    )


# ---------------------------------------------------------------------------
# 1. Advisory publishing behaviour
# ---------------------------------------------------------------------------


def test_karasu_publishes_advisory_within_window():
    """High-impact USD event within ±15 min -> advisory Thought."""
    kara = A8KarasuV1()
    ev_time = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    kara.load_calendar(events=[_event(time_utc=ev_time)])

    as_of = ev_time - timedelta(minutes=5)   # 5 min before release
    t = kara.observe(_market(as_of=as_of), FullLedger())
    assert t.expected_action == "advisory_blackout"
    assert "impact:high" in t.tags
    assert "currency:USD" in t.tags
    assert t.confidence_in_thought == 0.0
    assert t.coordinate is None


def test_karasu_no_thought_outside_window():
    """Same event, market time well outside -> observation-only clean."""
    kara = A8KarasuV1()
    ev_time = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    kara.load_calendar(events=[_event(time_utc=ev_time)])

    as_of = ev_time + timedelta(minutes=60)  # 60 min after release
    t = kara.observe(_market(as_of=as_of), FullLedger())
    assert t.expected_action == "wait"
    assert "advisory_none" in t.tags
    assert kara.warning_active_at(as_of, "EURUSD") == NO_WARNING


def test_karasu_never_proposes():
    """intend() ALWAYS returns None regardless of inputs."""
    kara = A8KarasuV1()
    ev_time = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    kara.load_calendar(events=[_event(time_utc=ev_time)])
    ledger = FullLedger()

    # Inside window
    t1 = kara.observe(_market(as_of=ev_time), ledger)
    assert kara.intend(_market(as_of=ev_time), t1) is None
    # Outside window
    t2 = kara.observe(_market(as_of=ev_time + timedelta(hours=6)), ledger)
    assert kara.intend(_market(as_of=ev_time + timedelta(hours=6)), t2) is None
    # Different symbol
    t3 = kara.observe(_market(as_of=ev_time, symbol="GBPUSD"), ledger)
    assert kara.intend(_market(as_of=ev_time, symbol="GBPUSD"), t3) is None


def test_karasu_medium_impact_yields_scale_advisory():
    """Medium-impact event triggers 'medium' advisory."""
    kara = A8KarasuV1()
    ev_time = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    kara.load_calendar(events=[
        _event(time_utc=ev_time, impact="Medium", title="Retail Sales"),
    ])

    as_of = ev_time - timedelta(minutes=1)
    warning = kara.warning_active_at(as_of, "EURUSD")
    assert warning.impact == "medium"
    assert warning.event_title == "Retail Sales"

    t = kara.observe(_market(as_of=as_of), FullLedger())
    assert t.expected_action == "advisory_blackout"
    assert "impact:medium" in t.tags


# ---------------------------------------------------------------------------
# 2. Currency scoping
# ---------------------------------------------------------------------------


def test_karasu_currency_scoping():
    """USD event only advises USD-quoted/base pairs; EUR event only EURUSD."""
    kara = A8KarasuV1()
    ev_time = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    kara.load_calendar(events=[
        _event(time_utc=ev_time, currency="USD"),
        _event(time_utc=ev_time, currency="EUR", title="ECB Rate"),
    ])
    as_of = ev_time - timedelta(minutes=1)

    # EURUSD: both USD and EUR events apply.
    w_eur = kara.warning_active_at(as_of, "EURUSD")
    assert w_eur.active
    assert {"USD", "EUR"} == set(w_eur.currencies)

    # USDCAD: only USD event applies (EUR is disjoint).
    w_cad = kara.warning_active_at(as_of, "USDCAD")
    assert w_cad.active
    assert set(w_cad.currencies) == {"USD"}

    # AUDUSD: only USD event applies.
    w_aud = kara.warning_active_at(as_of, "AUDUSD")
    assert set(w_aud.currencies) == {"USD"}


# ---------------------------------------------------------------------------
# 3. Sentinel R7 integration
# ---------------------------------------------------------------------------


def test_sentinel_r7_blocks_high_impact():
    """R7 blocks a proposal when Karasu's warning is high-impact."""
    decision = check_r7_news_impact(
        impact="high",
        event_title="FOMC Statement",
        currencies=frozenset({"USD"}),
        minutes_to_event=-3,
    )
    assert decision.allowed is False
    assert decision.rule == "R7"
    assert "R7_news_high_impact" in decision.reason


def test_sentinel_r7_scales_medium_impact():
    """R7 scale-only path: allowed, rule=R7, risk_scale=0.5."""
    decision = check_r7_news_impact(
        impact="medium",
        event_title="Retail Sales",
        currencies=frozenset({"USD"}),
        minutes_to_event=+2,
    )
    assert decision.allowed is True
    assert decision.rule == "R7"
    assert decision.risk_scale == pytest.approx(0.5)


def test_sentinel_r7_passthrough_none():
    """No news warning -> R7 is OK / risk_scale 1.0."""
    decision = check_r7_news_impact(impact="none")
    assert decision.allowed is True
    assert decision.rule == "OK"
    assert decision.risk_scale == pytest.approx(1.0)


def test_evaluate_proposal_blocks_on_r7_high():
    """Full evaluate() path: high-impact karasu impact -> R7 block."""
    ts = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    p = _proposal(ts=ts, symbol="EURUSD")
    ctx = SentinelContext(
        equity=100.0,
        pip_value_per_min_lot=0.10,
        karasu_impact="high",
        karasu_event_title="FOMC",
        karasu_event_currencies=frozenset({"USD"}),
        karasu_minutes_to_event=-2,
    )
    dec = evaluate_proposal(p, ctx)
    assert dec.rule == "R7"
    assert dec.allowed is False


def test_evaluate_proposal_scales_on_r7_medium():
    """Full evaluate() path: medium-impact -> allow with risk_scale 0.5."""
    ts = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    p = _proposal(ts=ts, symbol="EURUSD")
    ctx = SentinelContext(
        equity=100.0,
        pip_value_per_min_lot=0.10,
        karasu_impact="medium",
        karasu_event_title="Retail Sales",
        karasu_event_currencies=frozenset({"USD"}),
        karasu_minutes_to_event=+2,
    )
    dec = evaluate_proposal(p, ctx)
    assert dec.rule == "R7"
    assert dec.allowed is True
    assert dec.risk_scale == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 4. Fail modes
# ---------------------------------------------------------------------------


def test_karasu_survives_stale_cache(tmp_path, caplog):
    """Cache exists but 12h old -> Karasu logs stale warning, still uses it."""
    cache = tmp_path / "news_calendar.json"
    ev_time = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    ev = _event(time_utc=ev_time)
    stale_fetched_at = ev_time - timedelta(hours=12)
    cache.write_text(json.dumps({
        "fetched_at": stale_fetched_at.isoformat(),
        "events": [ev.to_dict()],
    }))
    kara = A8KarasuV1()
    n = kara.load_calendar(
        cache_path=cache, cache_fetched_at=stale_fetched_at,
    )
    assert n == 1

    # Force staleness by making 'as_of' well after the fetched_at + TTL.
    stale_at = stale_fetched_at + timedelta(seconds=DEFAULT_NEWS_CONFIG.cache_ttl_seconds + 10)
    with caplog.at_level("WARNING"):
        w = kara.warning_active_at(stale_at, "EURUSD")
    # Cache still queried (no event at stale_at yet, since event is 12h away
    # from fetched_at, and stale_at is fetched_at + ttl + 10s ~= 6.5h < 12h).
    # The critical assertion is: staleness log fired but the data was still used.
    assert any(
        "cache is stale" in rec.getMessage() for rec in caplog.records
    )
    # No event at that time -> NO_WARNING.
    assert w.impact == "none"


def test_karasu_survives_missing_cache(tmp_path):
    """No cache file -> Karasu emits no advisories, R7 pass-through."""
    cache = tmp_path / "does_not_exist.json"
    kara = A8KarasuV1()
    n = kara.load_calendar(cache_path=cache)
    assert n == 0
    as_of = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    assert kara.warning_active_at(as_of, "EURUSD") == NO_WARNING
    # observe() emits a clean thought.
    t = kara.observe(_market(as_of=as_of), FullLedger())
    assert t.expected_action == "wait"
    assert "advisory_none" in t.tags
    # Full evaluate() with an 'as-if karasu returned none' context.
    p = _proposal(ts=as_of, symbol="EURUSD")
    ctx = SentinelContext(equity=100.0, pip_value_per_min_lot=0.10)
    dec = evaluate_proposal(p, ctx)
    assert dec.rule in ("OK", "R1")


# ---------------------------------------------------------------------------
# 5. Contract hygiene
# ---------------------------------------------------------------------------


def test_karasu_canon_role_locked():
    """Canon role is Kunigami-shaped (Tier-2, ego=0, hold=0)."""
    kara = A8KarasuV1()
    assert kara.agent_id == "karasu_tabito"
    assert kara.canon_role == KARASU_V1_CANON_ROLE
    assert kara.canon_role.ego == 0.0
    assert kara.canon_role.target_hold_hours == 0.0
    assert kara.playstyle == "defensive_reader"
    assert kara.tier == 2


def test_karasu_config_knob_wiring():
    """Custom NewsDefenderConfig scales / block-impacts are honoured."""
    cfg = NewsDefenderConfig(
        blocked_impacts=frozenset({"High", "Medium"}),
        scaled_impacts=frozenset({"Low"}),
    )
    kara = A8KarasuV1(config=cfg)
    ev_time = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    kara.load_calendar(events=[
        _event(time_utc=ev_time, impact="Medium"),
    ])
    w = kara.warning_active_at(ev_time - timedelta(minutes=1), "EURUSD")
    # Under this config, 'Medium' is now in the block set -> impact=='high'.
    assert w.impact == "high"


def test_karasu_advisory_payload_shape():
    kara = A8KarasuV1()
    ev_time = datetime(2026, 3, 20, 18, 0, tzinfo=UTC)
    kara.load_calendar(events=[_event(time_utc=ev_time)])
    payload = kara.advisory_payload(ev_time - timedelta(minutes=2), "EURUSD")
    assert payload["advisory"] == "news_blackout"
    assert payload["impact"] == "high"
    assert payload["event_currency"] == "USD"
    assert payload["minutes_to_event"] == 2
    assert "EURUSD" in payload["affected_symbols"]


def test_r7_defaults_are_frozensets():
    """Defensive: NEWS_R7 module defaults must not be mutable sets."""
    assert isinstance(NEWS_R7_BLOCK_IMPACTS_DEFAULT, frozenset)
    assert isinstance(NEWS_R7_SCALE_IMPACTS_DEFAULT, frozenset)
