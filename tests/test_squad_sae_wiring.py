"""Sae hydration wiring (F1/F2): flag plumbing, calendar refresh, M15 provider.

Sae used to be inert on the live runtime three separate ways: no
``sae_config`` at roster build (never in proposers), no
``load_calendar`` call (calendar-blind), and no ``set_bars_provider``
call (``intend()`` returns None without one). These tests pin the
wiring that closes all three gaps -- while keeping Sae DISABLED BY
DEFAULT (the Phase AE pre-registration gate; the P0 pin here).
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_squad_live import build_arg_parser, build_live_roster  # noqa: E402

from agent.squad.engine import SquadEngine  # noqa: E402
from agent.squad.feed import Mt5Feed  # noqa: E402
from agent.squad.news_refresher import NewsFeedRefresher  # noqa: E402
from agent.squad.agents.a08_karasu import A8KarasuV1  # noqa: E402
from agent.squad.agents.a09_sae import A9SaeV1  # noqa: E402
from agent.types import Bar, Timeframe  # noqa: E402

UTC = timezone.utc

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<weeklyevents>
  <event>
    <title>Non-Farm Employment Change</title>
    <country>USD</country>
    <date>07-24-2026</date>
    <time>1:30pm</time>
    <impact>High</impact>
    <forecast></forecast>
    <previous></previous>
  </event>
  <event>
    <title>German ZEW</title>
    <country>EUR</country>
    <date>07-24-2026</date>
    <time>9:00am</time>
    <impact>Medium</impact>
    <forecast></forecast>
    <previous></previous>
  </event>
</weeklyevents>
"""


# ---------------------------------------------------------------------------
# 1. Flag plumbing (P0: disabled by default)
# ---------------------------------------------------------------------------

def test_enable_sae_flag_default_off():
    """P0 Phase AE gate: the CLI default must NOT enable Sae."""
    args = build_arg_parser({}).parse_args([])
    assert args.enable_sae is False


def test_enable_sae_flag_parses_on():
    args = build_arg_parser({}).parse_args(["--enable-sae"])
    assert args.enable_sae is True


def test_build_live_roster_default_keeps_sae_out_of_proposers():
    """P0 Phase AE gate: default roster excludes Sae from proposers."""
    roster = build_live_roster(("EURUSD", "GBPUSD", "USDCAD"))
    assert roster.sae_enabled is False
    assert all(a.agent_id != "sae_itoshi" for a in roster.proposers)
    # Sae object still exists for hydration/diagnostics.
    assert isinstance(roster.sae, A9SaeV1)
    assert roster.sae.enabled is False


def test_build_live_roster_enable_sae_adds_proposer():
    roster = build_live_roster(
        ("EURUSD", "GBPUSD", "USDCAD"), enable_sae=True,
    )
    assert roster.sae_enabled is True
    assert any(a.agent_id == "sae_itoshi" for a in roster.proposers)


# ---------------------------------------------------------------------------
# 2. Refresher hydrates Karasu AND Sae
# ---------------------------------------------------------------------------

def test_refresher_kickoff_hydrates_both_agents(tmp_path: Path):
    cache = tmp_path / "news_calendar.json"
    karasu = A8KarasuV1()
    sae = A9SaeV1()
    refresher = NewsFeedRefresher(
        karasu=karasu,
        sae=sae,
        cache_path=cache,
        interval_seconds=3600,
        fetcher=lambda _url: SAMPLE_XML,
    )
    n = refresher.kickoff()
    assert n == 2
    assert karasu.n_events == 2
    assert sae.n_events == 2


def test_refresher_backward_compat_karasu_only(tmp_path: Path):
    """Existing karasu-only call sites keep working (no sae kwarg)."""
    cache = tmp_path / "news_calendar.json"
    karasu = A8KarasuV1()
    refresher = NewsFeedRefresher(
        karasu=karasu,
        cache_path=cache,
        interval_seconds=3600,
        fetcher=lambda _url: SAMPLE_XML,
    )
    assert refresher.kickoff() == 2
    assert karasu.n_events == 2
    assert refresher.sae is None


def test_refresher_sae_hydration_fails_open(tmp_path: Path):
    """A Sae hydration error must never propagate into the tick loop."""
    class _ExplodingSae:
        def load_calendar(self, **_kw):
            raise RuntimeError("boom")

    refresher = NewsFeedRefresher(
        karasu=A8KarasuV1(),
        sae=_ExplodingSae(),
        cache_path=tmp_path / "news_calendar.json",
        interval_seconds=3600,
        fetcher=lambda _url: SAMPLE_XML,
    )
    assert refresher.kickoff() == 2  # no raise


# ---------------------------------------------------------------------------
# 3. M15 provider adapter (mock MT5 -- never a live terminal)
# ---------------------------------------------------------------------------

class _FakeBroker:
    """Read-only broker stub for Mt5Feed. Records requested timeframes."""

    def __init__(self, h4: list[Bar], m15: list[Bar]) -> None:
        self._h4 = h4
        self._m15 = m15
        self.calls: list[tuple[str, str, int]] = []

    async def get_latest_bars(self, symbol: str, timeframe: str, count: int):
        self.calls.append((symbol, timeframe, count))
        return list(self._m15 if timeframe == "M15" else self._h4)


def _h4_bar(t: datetime) -> Bar:
    return Bar(time=t, open=1.10, high=1.11, low=1.09, close=1.105,
               volume=100.0, timeframe=Timeframe.H4)


def _m15_bar(t: datetime) -> Bar:
    return Bar(time=t, open=1.10, high=1.101, low=1.099, close=1.1005,
               volume=10.0, timeframe=Timeframe.M15)


def test_mt5_feed_m15_provider_contract(tmp_path: Path):
    start = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
    h4 = [_h4_bar(start + timedelta(hours=4 * i)) for i in range(3)]
    m15 = [_m15_bar(start + timedelta(minutes=15 * i)) for i in range(16)]
    broker = _FakeBroker(h4, m15)
    feed = Mt5Feed(broker, symbols=("EURUSD",), m15_symbols=("EURUSD",))
    asyncio.run(feed.refresh())

    # The refresh pulled an M15 window read-only.
    assert ("EURUSD", "M15", feed.m15_lookback) in broker.calls

    # Provider filters to [start, end] inclusive on open time, ascending.
    lo = start + timedelta(minutes=30)
    hi = start + timedelta(minutes=90)
    window = feed.m15_bars("EURUSD", lo, hi)
    assert [b.time for b in window] == [
        start + timedelta(minutes=m) for m in (30, 45, 60, 75, 90)
    ]
    assert all(b.timeframe == Timeframe.M15 for b in window)

    # Sync call, no event loop needed (safe inside intend()).
    again = feed.m15_bars("EURUSD", lo, hi)
    assert again == window


def test_mt5_feed_m15_provider_unknown_symbol_returns_empty():
    broker = _FakeBroker([], [])
    feed = Mt5Feed(broker, symbols=("EURUSD",), m15_symbols=())
    asyncio.run(feed.refresh())
    lo = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
    assert feed.m15_bars("EURUSD", lo, lo + timedelta(hours=1)) == []
    # No M15 pull was even attempted for an empty m15_symbols set.
    assert all(tf != "M15" for _, tf, _ in broker.calls)


def test_sae_fires_through_feed_provider(tmp_path: Path):
    """End-to-end mechanic check: an enabled Sae wired to the feed's
    M15 provider produces a fade proposal on a qualifying event bar."""
    from agent.news.calendar import NewsEvent
    from agent.squad.sae_config import SaeConfig
    from agent.squad.types import MarketState

    event_time = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    # Event M15 bar: +50 pip bullish move with a 60% upper wick -> fade.
    event_bar = Bar(
        time=event_time, open=1.1000, high=1.1130, low=1.0995,
        close=1.1050, volume=50.0, timeframe=Timeframe.M15,
    )
    pre = _m15_bar(event_time - timedelta(minutes=15))
    broker = _FakeBroker([], [pre, event_bar])
    feed = Mt5Feed(broker, symbols=("EURUSD",), m15_symbols=("EURUSD",))
    asyncio.run(feed.refresh())

    sae = A9SaeV1(config=SaeConfig(sae_enabled=True))
    sae.set_bars_provider(feed.m15_bars)
    sae.load_calendar(events=[NewsEvent(
        time_utc=event_time, currency="USD", impact="High",
        title="CPI", all_day=False,
    )])

    as_of = event_time + timedelta(minutes=20)  # past fade_wait_min=15
    market = MarketState(
        tick_id=1, symbol="EURUSD", timeframe="H4", as_of=as_of,
        open=1.10, high=1.12, low=1.09, close=1.105, volume=100.0,
    )
    thought = sae.observe(market, None)
    proposal = sae.intend(market, thought)
    assert proposal is not None
    assert proposal.direction == "short"
    assert proposal.rationale["mechanic"] == "sae_fade"


# ---------------------------------------------------------------------------
# 4. sae_enabled surfaced in state.json
# ---------------------------------------------------------------------------

def test_state_json_reports_sae_enabled_false_by_default(tmp_path: Path):
    engine = SquadEngine(
        build_live_roster(("EURUSD",)),
        tmp_path / "off",
        source_label="live_market:test",
    )
    engine.prepare({"EURUSD": []})
    engine.save_state()
    state = json.loads((tmp_path / "off" / "state.json").read_text())
    assert state["sae_enabled"] is False


def test_state_json_reports_sae_enabled_true_when_flagged(tmp_path: Path):
    engine = SquadEngine(
        build_live_roster(("EURUSD",), enable_sae=True),
        tmp_path / "on",
        source_label="live_market:test",
    )
    engine.prepare({"EURUSD": []})
    engine.save_state()
    state = json.loads((tmp_path / "on" / "state.json").read_text())
    assert state["sae_enabled"] is True
