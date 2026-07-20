"""A8 -- Karasu Tabito v1 (`karasu_tabito`) -- news-window defender.

Karasu v1 is the news-defender auxiliary. He reads the shared
ForexFactory calendar (via :mod:`agent.news.calendar`) and translates
scheduled high-impact / medium-impact currency events into two things:

1. Advisory Thoughts published to the F21 workspace when a symbol
   Karasu is watching is inside the ±minute blackout window. Advisory
   only -- ``expected_action="advisory_blackout"`` and
   ``conviction=0.0`` -- Karasu **NEVER proposes**.
2. A :class:`KarasuWarning` polled by the Sentinel R7 rule
   (``agent.squad.sentinel.check_r7_news_impact``) that turns the
   advisory into a hard BLOCK (high impact) or a 50 %-risk-scale
   (medium impact) on the specific symbol's proposal path.

He is the sibling of A10 Kunigami: same "never in roster.proposers"
shape, same ``warning_active_at`` sentinel-consumer API, same
observation-only contract. Where Kunigami reads *internal* state
(ledger + closed-trade outcomes), Karasu reads *external* state
(the calendar). Everything else is the same pattern.

Fail modes:

* Missing cache -> Karasu emits no advisories, all R7 checks
  pass through (fail-open on data absence; the trader isn't
  frozen just because the cache hasn't been fetched yet).
* Stale cache -> Karasu logs a warning ONCE per boot on the first
  ``observe()`` where staleness is detected, and continues to use
  the cached events. Rationale: fresh data would be safer, but a
  6-h-old FF calendar is far more accurate than "no data" for
  events scheduled within the next hour. Fail-open on data source,
  fail-closed on trades (the Sentinel R7 still enforces).

Cross-repo import: none. Karasu only depends on
``agent.news.calendar`` (in-repo) and the shared squad types.

Doctrine reference: `06-blue-lock-doctrine.md` §4.2c (news-window
defender addendum, 2026-07-20; pending amendment in Phase AD).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from agent.news.calendar import (
    NewsEvent,
    load_calendar,
)
from agent.squad.ledger import ThoughtLedger
from agent.squad.news_config import (
    DEFAULT_KARASU_SYMBOLS,
    DEFAULT_NEWS_CONFIG,
    NewsDefenderConfig,
)
from agent.squad.striker import BaseStriker
from agent.squad.types import (
    SCHEMA_VERSION,
    AgentProposal,
    CanonRole,
    MarketState,
    Thought,
    ThoughtRead,
)


log = logging.getLogger(__name__)


KARASU_V1_TTL_TICKS: int = 6

KARASU_V1_CANON_ROLE = CanonRole(
    canon_player="karasu_tabito",
    weapon="news_window_defender",
    ego=0.0,
    target_hold_hours=0.0,
    narrative_voice="cerebral_field_reader",
)


@dataclass(frozen=True)
class KarasuWarning:
    """The Sentinel-consumer view of Karasu's active advisory.

    Attributes:
        impact:            "high", "medium", or "none". "none" means
                           no active advisory affects this symbol.
        currencies:        ISO currency strings that triggered this
                           warning (a symbol can be affected by more
                           than one -- e.g. an EUR event and a USD
                           event both fire on EURUSD).
        event_title:       Human-readable event name from the calendar
                           (the FIRST matching event, deterministic
                           by earliest ``time_utc``). None when
                           ``impact == "none"``.
        minutes_to_event:  Signed integer minutes from ``as_of`` to
                           the event's scheduled time. Negative if
                           the event has already fired but is still
                           inside the after-window. None when
                           ``impact == "none"``.
    """

    impact: str
    currencies: frozenset[str]
    event_title: str | None = None
    minutes_to_event: int | None = None

    @property
    def active(self) -> bool:
        return self.impact != "none"


NO_WARNING = KarasuWarning(impact="none", currencies=frozenset())


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _rank_impact(impact: str) -> int:
    """Higher = more severe. Used to pick the strongest active event."""
    return {"high": 2, "medium": 1, "none": 0}.get(impact, 0)


class A8KarasuV1(BaseStriker):
    """A8 Karasu v1 -- news-window defender (never proposes).

    Public API (used by the engine):

    * ``observe(market, ledger) -> Thought`` -- always emits a Thought.
      When Karasu detects an active blackout/scale window on this
      symbol he emits an advisory Thought
      (``expected_action="advisory_blackout"``). Otherwise the Thought
      is observation-only and clean (``advisory_none`` tag). Second
      positional arg is the ThoughtLedger, kept for the BaseStriker
      contract; the F21 workspace is passed as a kwarg by the engine.
    * ``intend(market, my_recent_thought)`` -- ALWAYS returns None.

    Sentinel-consumer API:

    * ``warning_active_at(as_of, symbol) -> KarasuWarning`` -- polled
      by :func:`agent.squad.sentinel.check_r7_news_impact` on every
      proposal admission.

    Live-runtime API:

    * ``load_calendar(feed_url=..., cache_path=..., events=...)`` --
      hydrate Karasu's in-memory event list from cache or from a
      caller-supplied list (used in tests to avoid disk).
    """

    def __init__(
        self,
        agent_id: str = "karasu_tabito",
        canon_role: Optional[CanonRole] = None,
        home_tf: str = "H4",
        symbols: Optional[Iterable[str]] = None,
        *,
        config: NewsDefenderConfig | None = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            canon_role=canon_role or KARASU_V1_CANON_ROLE,
            home_tf=home_tf,
            symbols=list(symbols) if symbols is not None else list(DEFAULT_KARASU_SYMBOLS),
            playstyle="defensive_reader",
            tier=2,
        )
        self._config: NewsDefenderConfig = config or DEFAULT_NEWS_CONFIG
        self._events: list[NewsEvent] = []
        self._stale_warned: bool = False
        self._cache_fetched_at: datetime | None = None

    # ------------------------------------------------------------------
    # Calendar hydration
    # ------------------------------------------------------------------

    def load_calendar(
        self,
        *,
        feed_url: str | None = None,   # noqa: ARG002 -- reserved for future refresh path
        cache_path=None,
        events: Iterable[NewsEvent] | None = None,
        cache_fetched_at: datetime | None = None,
    ) -> int:
        """Hydrate Karasu's in-memory event list.

        Priority: ``events`` (explicit) > cache at ``cache_path`` >
        cache at the config default. Returns the number of events
        loaded (0 = fail-open state; Karasu will emit no advisories).

        The ``feed_url`` kwarg is accepted for signature-compatibility
        with the future non-blocking refresh hook; actual network I/O
        goes through :func:`agent.news.calendar.fetch_calendar` in
        the live-runtime refresher, not here.
        """
        if events is not None:
            self._events = list(events)
            self._stale_warned = False
            self._cache_fetched_at = _ensure_utc(cache_fetched_at) if cache_fetched_at else None
            log.info("A8KarasuV1 loaded %d events from caller", len(self._events))
            return len(self._events)

        path = cache_path if cache_path is not None else self._config.cache_path
        loaded = load_calendar(path)
        self._events = list(loaded)
        self._stale_warned = False
        self._cache_fetched_at = _ensure_utc(cache_fetched_at) if cache_fetched_at else None
        log.info(
            "A8KarasuV1 loaded %d events from cache %s", len(self._events), path,
        )
        return len(self._events)

    @property
    def n_events(self) -> int:
        return len(self._events)

    def _check_staleness(self, as_of: datetime) -> None:
        """Log a one-time warning when the cache appears stale.

        Karasu still USES stale data (fail-open on the data source);
        the log is so the operator knows to fix the refresh path.
        """
        if self._stale_warned or self._cache_fetched_at is None:
            return
        as_of = _ensure_utc(as_of)
        age = (as_of - self._cache_fetched_at).total_seconds()
        if age > self._config.cache_ttl_seconds:
            log.warning(
                "A8KarasuV1 news cache is stale (age=%.0fs > ttl=%ds); "
                "using cached data anyway (fail-open on data source).",
                age, self._config.cache_ttl_seconds,
            )
            self._stale_warned = True

    # ------------------------------------------------------------------
    # Sentinel-consumer API
    # ------------------------------------------------------------------

    def warning_active_at(
        self, as_of: datetime, symbol: str,
    ) -> KarasuWarning:
        """Return the strongest active KarasuWarning for ``symbol``.

        Impact ranking: high > medium > none. When multiple currencies
        would trigger on the same symbol, the aggregate warning carries
        ALL matching currencies but the impact is the strongest one.

        The event_title / minutes_to_event fields point to the FIRST
        (earliest by ``time_utc``) event that fired the strongest
        matching impact -- deterministic and useful for logs.
        """
        if not self._events:
            return NO_WARNING
        as_of = _ensure_utc(as_of)
        self._check_staleness(as_of)
        blocked = {i.lower() for i in self._config.blocked_impacts}
        scaled = {i.lower() for i in self._config.scaled_impacts}
        watched = {c.upper() for c in self._config.watched_currencies}
        currency_map = self._config.currency_symbol_map

        before = timedelta(minutes=self._config.blackout_before_min)
        after = timedelta(minutes=self._config.blackout_after_min)

        best_impact = "none"
        best_rank = 0
        matched_currencies: set[str] = set()
        best_event: NewsEvent | None = None

        for e in self._events:
            if e.time_utc is None:
                continue
            cur = e.currency.upper()
            if cur not in watched:
                continue
            affected = currency_map.get(cur, ())
            if symbol not in affected:
                continue
            imp = e.impact.lower()
            if imp in blocked:
                impact_here = "high"
            elif imp in scaled:
                impact_here = "medium"
            else:
                continue
            in_window = (e.time_utc - before) <= as_of <= (e.time_utc + after)
            if not in_window:
                continue
            matched_currencies.add(cur)
            rank = _rank_impact(impact_here)
            if rank > best_rank or (
                rank == best_rank
                and best_event is not None
                and e.time_utc < best_event.time_utc
            ):
                best_rank = rank
                best_impact = impact_here
                best_event = e

        if best_impact == "none":
            return NO_WARNING

        mins_to_event: int | None = None
        title: str | None = None
        if best_event is not None and best_event.time_utc is not None:
            delta = (best_event.time_utc - as_of).total_seconds()
            mins_to_event = int(delta // 60)
            title = best_event.title

        return KarasuWarning(
            impact=best_impact,
            currencies=frozenset(matched_currencies),
            event_title=title,
            minutes_to_event=mins_to_event,
        )

    # ------------------------------------------------------------------
    # BlueLockStriker contract
    # ------------------------------------------------------------------

    def observe(self, market: MarketState, ledger: ThoughtLedger) -> Thought:  # noqa: ARG002
        warning = self.warning_active_at(market.as_of, market.symbol)
        tags: list[str] = [
            "canon:karasu",
            "weapon:news_defender",
            "risk_auxiliary",
            "news_advisory",
        ]
        if not warning.active:
            return Thought(
                schema_version=SCHEMA_VERSION,
                agent_id=self.agent_id,
                tick_id=market.tick_id,
                timestamp=market.as_of,
                symbol=market.symbol,
                narrative=(
                    f"[karasu v1] {market.symbol} {market.timeframe} @ "
                    f"{market.as_of}: no scheduled release in the "
                    f"±{self._config.blackout_before_min}/"
                    f"{self._config.blackout_after_min}-min window; "
                    "field is clear."
                ),
                tags=tags + ["advisory_none"],
                confidence_in_thought=0.0,
                expected_action="wait",
                coordinate=None,
                decision_horizon=market.as_of,
                ttl_ticks=1,
                references=[],
                read=ThoughtRead(
                    signal_family="risk_watch",
                    direction_bias="flat",
                    regime_read="news_clear",
                    driving_evidence=("advisory_none",),
                ),
            )

        affected_symbols: set[str] = set()
        for cur in warning.currencies:
            affected_symbols.update(
                self._config.currency_symbol_map.get(cur.upper(), ()),
            )
        affected_sorted = sorted(affected_symbols)

        tags.extend([
            f"impact:{warning.impact}",
        ])
        for cur in sorted(warning.currencies):
            tags.append(f"currency:{cur}")

        narrative = (
            f"[karasu v1] {market.symbol} {market.timeframe} @ "
            f"{market.as_of}: {warning.impact}-impact "
            f"{'/'.join(sorted(warning.currencies))} event"
            + (
                f" ('{warning.event_title}'"
                + (
                    f" in {warning.minutes_to_event:+d} min"
                    if warning.minutes_to_event is not None else ""
                )
                + ")"
                if warning.event_title else ""
            )
            + f" -- advisory blackout ({warning.impact})."
        )

        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=narrative,
            tags=tags,
            confidence_in_thought=0.0,
            expected_action="advisory_blackout",
            coordinate=None,
            decision_horizon=market.as_of,
            ttl_ticks=KARASU_V1_TTL_TICKS,
            references=[],
            read=ThoughtRead(
                signal_family="risk_watch",
                direction_bias="flat",
                regime_read=f"news_{warning.impact}",
                driving_evidence=(
                    "news_blackout",
                    f"impact:{warning.impact}",
                    *(f"currency:{c}" for c in sorted(warning.currencies)),
                ),
            ),
        )

    def intend(
        self,
        market: MarketState,  # noqa: ARG002
        my_recent_thought: Thought,  # noqa: ARG002
        **_kwargs: object,
    ) -> AgentProposal | None:
        return None

    # ------------------------------------------------------------------
    # Rationale accessor (advisory payload for the workspace consumer)
    # ------------------------------------------------------------------

    def advisory_payload(
        self, as_of: datetime, symbol: str,
    ) -> dict:
        """Return the JSON-serialisable dict backing the Thought.reason.

        Exposed as a helper for callers that want to log the advisory
        outside the Thought stream (e.g. the dashboard).
        """
        warning = self.warning_active_at(as_of, symbol)
        if not warning.active:
            return {
                "advisory": "no_news",
                "impact": "none",
                "affected_symbols": [],
            }
        affected: set[str] = set()
        for cur in warning.currencies:
            affected.update(
                self._config.currency_symbol_map.get(cur.upper(), ()),
            )
        return {
            "advisory": "news_blackout",
            "event_title": warning.event_title,
            "event_currency": ",".join(sorted(warning.currencies)),
            "impact": warning.impact,
            "minutes_to_event": warning.minutes_to_event,
            "affected_symbols": sorted(affected),
        }


KarasuTabito = A8KarasuV1


__all__ = [
    "A8KarasuV1",
    "KARASU_V1_CANON_ROLE",
    "KARASU_V1_TTL_TICKS",
    "KarasuTabito",
    "KarasuWarning",
    "NO_WARNING",
]
