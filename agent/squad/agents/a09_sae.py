"""A9 -- Sae Itoshi v1 (`sae_itoshi`) -- event specialist striker.

Sae is the elite striker who takes over decisive moments. In v1 he
only proposes INSIDE a scheduled high-impact USD event window
(default [T - 30 min, T + 60 min]) via one of two mechanics:

**Fade** (fires at as_of >= T + fade_wait_min, default T + 15 min):
    The M15 bar covering [T, T + 15 min] is the "event bar". If its
    absolute move (close - open) exceeds ``fade_min_move_pips`` AND
    the wick opposite the move covers at least
    ``fade_min_wick_frac`` (default 50 %) of the bar's range, Sae
    proposes a trade in the OPPOSITE direction with stop at the
    wick extremum + ``fade_stop_padding_pips``. The reasoning: a
    50 %+ opposite wick on a big impulse is a failed impulse.

**Ride** (fires at as_of >= T + ride_wait_min, default T + 30 min,
only if fade did NOT fire for the same event):
    Take the impulse direction from the event bar. If the next M15
    bar (T + 15 min ... T + 30 min) closes same-direction and
    ``|next_bar.close - event_bar.open| >= ride_min_retention *
    |event_bar move|`` (default 70 % retention), Sae proposes in
    the impulse direction with stop at ``event_bar.open`` and
    ``target_rr = 1.5``.

Only one proposal per event window; a follow-up call after firing
returns None until the next scheduled event.

Universe: EURUSD-only in v1 (the parquet cache today has M15 for
EURUSD and GBPUSD only). The ``symbols`` constructor arg exists for
the future multi-pair expansion; Phase AE.2 will amend when the
M15 cache broadens.

**Disabled by default**: :class:`agent.squad.sae_config.SaeConfig`
has ``sae_enabled=False``. Callers wanting to enable Sae must pass
``SaeConfig(sae_enabled=True, ...)`` to ``build_roster``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

from agent.news.calendar import NewsEvent, load_calendar
from agent.squad.ledger import ThoughtLedger
from agent.squad.news_config import (
    DEFAULT_NEWS_CONFIG,
    NewsDefenderConfig,
)
from agent.squad.sae_config import DEFAULT_SAE_CONFIG, SaeConfig
from agent.squad.striker import BaseStriker
from agent.squad.types import (
    SCHEMA_VERSION,
    AgentProposal,
    CanonRole,
    Coordinate,
    LadderRung,
    MarketState,
    Thought,
    ThoughtRead,
)
from agent.types import Bar


log = logging.getLogger(__name__)


SAE_V1_CANON_ROLE = CanonRole(
    canon_player="sae_itoshi",
    weapon="event_release_impulse",
    ego=0.75,
    target_hold_hours=6.0,
    narrative_voice="elite_striker_decisive",
)


BarsProvider = Callable[[str, datetime, datetime], list[Bar]]
"""Type of the injectable M15 bar fetcher.

Signature: ``(symbol, start_utc, end_utc) -> list[Bar]``. Bars must be
sorted ascending by time and use the M15 timeframe. Tests pass a
synthetic in-memory list; the live runtime wires a
:class:`agent.data.loader.BarLoader` closure."""


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class A9SaeV1(BaseStriker):
    """A9 Sae Itoshi v1 -- event specialist striker (disabled by default).

    Constructor arguments:

    * ``agent_id`` / ``canon_role`` / ``home_tf``: standard BaseStriker.
    * ``symbols``: universe whitelist. Overrides config.symbols when
      supplied.
    * ``config``: :class:`SaeConfig` (defaults to DEFAULT_SAE_CONFIG,
      ``sae_enabled=False``).
    * ``news_config``: :class:`NewsDefenderConfig`; only used for the
      cache path / watched-currency lookup when Sae loads the
      calendar himself. Ideally Sae shares Karasu's already-loaded
      calendar via ``load_calendar(events=...)``.
    * ``bars_provider``: callable ``(symbol, start_utc, end_utc) ->
      list[Bar]``. Tests inject a synthetic function; the live
      runtime wires a BarLoader closure. If None, ``intend()``
      returns None (fail-open: no bars, no proposal).

    Home-TF: H4 (event windows still resolve within H4-close cadence,
    even though the mechanics work on M15).
    """

    def __init__(
        self,
        agent_id: str = "sae_itoshi",
        canon_role: Optional[CanonRole] = None,
        home_tf: str = "H4",
        symbols: Optional[Iterable[str]] = None,
        *,
        config: SaeConfig | None = None,
        news_config: NewsDefenderConfig | None = None,
        bars_provider: BarsProvider | None = None,
    ) -> None:
        cfg = config or DEFAULT_SAE_CONFIG
        super().__init__(
            agent_id=agent_id,
            canon_role=canon_role or SAE_V1_CANON_ROLE,
            home_tf=home_tf,
            symbols=list(symbols) if symbols is not None else list(cfg.symbols),
            playstyle="event_specialist",
            tier=1,
        )
        self._config: SaeConfig = cfg
        self._news_cfg: NewsDefenderConfig = news_config or DEFAULT_NEWS_CONFIG
        self._events: list[NewsEvent] = []
        self._bars_provider: BarsProvider | None = bars_provider
        # (event_time_utc_iso, symbol) tuples for which Sae has already
        # emitted a proposal (fade or ride). Prevents double-firing.
        self._fired_events: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    # Calendar hydration (mirrors Karasu.load_calendar)
    # ------------------------------------------------------------------

    def load_calendar(
        self,
        *,
        cache_path=None,
        events: Iterable[NewsEvent] | None = None,
    ) -> int:
        """Hydrate Sae's in-memory event list.

        Shares :func:`agent.news.calendar.load_calendar` with Karasu;
        callers that already hold a NewsEvent list should pass it
        via ``events=`` to avoid a second disk read.
        """
        if events is not None:
            self._events = list(events)
            return len(self._events)
        path = cache_path if cache_path is not None else self._news_cfg.cache_path
        loaded = load_calendar(path)
        self._events = list(loaded)
        return len(self._events)

    def set_bars_provider(self, provider: BarsProvider | None) -> None:
        """Late-bind the M15 bar fetcher (used by the engine at prepare-time)."""
        self._bars_provider = provider

    @property
    def n_events(self) -> int:
        return len(self._events)

    @property
    def enabled(self) -> bool:
        return self._config.sae_enabled

    # ------------------------------------------------------------------
    # Event lookup
    # ------------------------------------------------------------------

    def _nearest_scheduled_event(self, as_of: datetime) -> NewsEvent | None:
        """Return the nearest high-impact USD event in Sae's window.

        Sae only cares about high-impact USD events (per doctrine +
        Phase AE pre-reg). The window is centred on ``as_of`` with
        radius (fire_window_before_min, fire_window_after_min).
        Ties are broken by earliest ``time_utc``.
        """
        as_of = _ensure_utc(as_of)
        earliest = as_of - timedelta(minutes=self._config.fire_window_after_min)
        latest = as_of + timedelta(minutes=self._config.fire_window_before_min)
        candidates: list[NewsEvent] = []
        for e in self._events:
            if e.time_utc is None:
                continue
            if e.currency.upper() != "USD":
                continue
            if e.impact.lower() != "high":
                continue
            if earliest <= e.time_utc <= latest:
                candidates.append(e)
        if not candidates:
            return None
        candidates.sort(key=lambda e: e.time_utc)  # type: ignore[arg-type,return-value]
        return candidates[0]

    def _event_key(self, event: NewsEvent, symbol: str) -> tuple[str, str]:
        assert event.time_utc is not None
        return (event.time_utc.isoformat(), symbol)

    # ------------------------------------------------------------------
    # BlueLockStriker contract
    # ------------------------------------------------------------------

    def observe(self, market: MarketState, ledger: ThoughtLedger) -> Thought:  # noqa: ARG002
        tags = ["canon:sae", "weapon:event_release_impulse"]
        if market.symbol not in self.symbols:
            return self._abstain(market, tags + ["off_symbol"], "off_symbol")

        event = self._nearest_scheduled_event(market.as_of)
        if event is None or event.time_utc is None:
            return self._abstain(market, tags + ["no_event_in_window"], "no_event")

        mins_to_event = int((event.time_utc - market.as_of).total_seconds() // 60)
        narrative = (
            f"[sae v1] {market.symbol} {market.timeframe} @ {market.as_of}: "
            f"awaiting release ('{event.title}' {event.currency} "
            f"{event.impact}, {mins_to_event:+d} min); "
            f"fade wait={self._config.fade_wait_min}min, "
            f"ride wait={self._config.ride_wait_min}min."
        )
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=narrative,
            tags=tags + ["awaiting_event", f"minutes_to_event:{mins_to_event}"],
            confidence_in_thought=0.0,
            expected_action="await_event",
            coordinate=None,
            decision_horizon=market.as_of,
            ttl_ticks=1,
            references=[],
            read=ThoughtRead(
                signal_family="solo_king",  # Sae is elite-striker family
                direction_bias="flat",
                regime_read="event_pending",
                driving_evidence=("sae_awaiting_event",),
            ),
        )

    def intend(
        self,
        market: MarketState,
        my_recent_thought: Thought,
        **_kwargs: object,
    ) -> AgentProposal | None:
        if not self._config.sae_enabled:
            return None
        if market.timeframe != self.home_tf:
            return None
        if market.symbol not in self.symbols:
            return None
        if self._bars_provider is None:
            return None

        event = self._nearest_scheduled_event(market.as_of)
        if event is None or event.time_utc is None:
            return None

        key = self._event_key(event, market.symbol)
        if key in self._fired_events:
            return None

        as_of = _ensure_utc(market.as_of)
        event_time = _ensure_utc(event.time_utc)
        t_fade = event_time + timedelta(minutes=self._config.fade_wait_min)
        t_ride = event_time + timedelta(minutes=self._config.ride_wait_min)

        # Pull enough M15 bars around the event to cover both mechanics
        # (event bar + next bar).
        start = event_time - timedelta(minutes=30)
        end = as_of + timedelta(minutes=1)
        try:
            bars = self._bars_provider(market.symbol, start, end)
        except Exception as exc:   # noqa: BLE001
            log.warning(
                "A9SaeV1: bars_provider raised (%s) for %s -- skipping fire.",
                exc, market.symbol,
            )
            return None

        event_bar = _find_bar_covering(bars, event_time)
        if event_bar is None:
            return None

        proposal: AgentProposal | None = None

        # Fade mechanic (evaluated first; ride only fires if fade didn't).
        if as_of >= t_fade:
            proposal = self._try_fade(
                market=market,
                event=event,
                event_bar=event_bar,
                my_recent_thought=my_recent_thought,
            )
            if proposal is not None:
                self._fired_events.add(key)
                return proposal

        # Ride mechanic.
        if as_of >= t_ride:
            next_bar = _find_bar_covering(
                bars, event_time + timedelta(minutes=15),
            )
            if next_bar is None or next_bar.time == event_bar.time:
                return None
            proposal = self._try_ride(
                market=market,
                event=event,
                event_bar=event_bar,
                next_bar=next_bar,
                my_recent_thought=my_recent_thought,
            )
            if proposal is not None:
                self._fired_events.add(key)
                return proposal

        return None

    # ------------------------------------------------------------------
    # Mechanics
    # ------------------------------------------------------------------

    def _try_fade(
        self,
        *,
        market: MarketState,
        event: NewsEvent,
        event_bar: Bar,
        my_recent_thought: Thought,
    ) -> AgentProposal | None:
        cfg = self._config
        pip = cfg.pip_size
        move_price = event_bar.close - event_bar.open
        move_pips = abs(move_price) / pip
        rng = event_bar.high - event_bar.low
        if rng <= 0.0:
            return None
        if move_pips < cfg.fade_min_move_pips:
            return None

        if move_price > 0:
            # Bullish bar -> fade wants a short. Wick is the upper wick.
            wick = (event_bar.high - event_bar.close) / rng
            if wick < cfg.fade_min_wick_frac:
                return None
            direction = "short"
            stop_price = event_bar.high + cfg.fade_stop_padding_pips * pip
            entry_price = event_bar.close
            risk = stop_price - entry_price
            tp_price = entry_price - cfg.target_rr * risk
        else:
            # Bearish bar -> fade wants a long. Wick is the lower wick.
            wick = (event_bar.open - event_bar.low) / rng
            if wick < cfg.fade_min_wick_frac:
                return None
            direction = "long"
            stop_price = event_bar.low - cfg.fade_stop_padding_pips * pip
            entry_price = event_bar.close
            risk = entry_price - stop_price
            tp_price = entry_price + cfg.target_rr * risk

        if risk <= 0:
            return None

        rationale = {
            "mechanic": "sae_fade",
            "event_title": event.title,
            "event_time": event.time_utc.isoformat() if event.time_utc else None,
            "event_bar_open": float(event_bar.open),
            "event_bar_close": float(event_bar.close),
            "event_bar_high": float(event_bar.high),
            "event_bar_low": float(event_bar.low),
            "move_pips": float(move_pips),
            "wick_frac": float(wick),
            "target_rr": float(cfg.target_rr),
        }
        return _build_proposal(
            agent_id=self.agent_id,
            tick_id=int(market.tick_id),
            source_thought=my_recent_thought,
            symbol=market.symbol,
            direction=direction,
            entry=entry_price,
            stop=stop_price,
            tp=tp_price,
            timestamp=market.as_of,
            hold_hours=float(self.canon_role.target_hold_hours),
            rationale=rationale,
            tier=int(self.tier),
            tag="sae_fade",
        )

    def _try_ride(
        self,
        *,
        market: MarketState,
        event: NewsEvent,
        event_bar: Bar,
        next_bar: Bar,
        my_recent_thought: Thought,
    ) -> AgentProposal | None:
        cfg = self._config
        pip = cfg.pip_size
        move_price = event_bar.close - event_bar.open
        move_pips = abs(move_price) / pip
        if move_pips <= 0:
            return None
        impulse_direction = "long" if move_price > 0 else "short"

        # Same-direction close?
        next_bar_dir = "long" if next_bar.close >= next_bar.open else "short"
        if next_bar_dir != impulse_direction:
            return None

        retention = (next_bar.close - event_bar.open)
        if impulse_direction == "short":
            retention = -retention
        # retention now signed same-direction; measured on price scale.
        if abs(move_price) <= 0:
            return None
        retention_frac = retention / abs(move_price)
        if retention_frac < cfg.ride_min_retention:
            return None

        entry_price = float(next_bar.close)
        stop_price = float(event_bar.open)
        risk = abs(entry_price - stop_price)
        if risk <= 0:
            return None
        if impulse_direction == "long" and stop_price >= entry_price:
            return None
        if impulse_direction == "short" and stop_price <= entry_price:
            return None
        if impulse_direction == "long":
            tp_price = entry_price + cfg.target_rr * risk
        else:
            tp_price = entry_price - cfg.target_rr * risk

        rationale = {
            "mechanic": "sae_ride",
            "event_title": event.title,
            "event_time": event.time_utc.isoformat() if event.time_utc else None,
            "event_bar_open": float(event_bar.open),
            "event_bar_close": float(event_bar.close),
            "next_bar_open": float(next_bar.open),
            "next_bar_close": float(next_bar.close),
            "move_pips": float(move_pips),
            "retention_frac": float(retention_frac),
            "target_rr": float(cfg.target_rr),
        }
        return _build_proposal(
            agent_id=self.agent_id,
            tick_id=int(market.tick_id),
            source_thought=my_recent_thought,
            symbol=market.symbol,
            direction=impulse_direction,
            entry=entry_price,
            stop=stop_price,
            tp=tp_price,
            timestamp=market.as_of,
            hold_hours=float(self.canon_role.target_hold_hours),
            rationale=rationale,
            tier=int(self.tier),
            tag="sae_ride",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _abstain(
        self, market: MarketState, tags: list[str], reason: str,
    ) -> Thought:
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=(
                f"[sae v1] {market.symbol} {market.timeframe} @ "
                f"{market.as_of}: abstain ({reason})."
            ),
            tags=tags,
            confidence_in_thought=0.0,
            expected_action="wait",
            coordinate=None,
            decision_horizon=market.as_of,
            ttl_ticks=1,
            references=[],
        )


def _find_bar_covering(bars: list[Bar], target: datetime) -> Bar | None:
    """Return the M15 bar whose [time, time + 15 min) covers ``target``.

    Bars must be sorted ascending. Returns None when no bar covers
    the target.
    """
    target = _ensure_utc(target)
    for b in bars:
        b_time = _ensure_utc(b.time)
        if b_time <= target < b_time + timedelta(minutes=15):
            return b
    return None


def _build_proposal(
    *,
    agent_id: str,
    tick_id: int,
    source_thought: Thought,
    symbol: str,
    direction: str,
    entry: float,
    stop: float,
    tp: float,
    timestamp: datetime,
    hold_hours: float,
    rationale: dict,
    tier: int,
    tag: str,
) -> AgentProposal:
    valid_until = timestamp + timedelta(hours=hold_hours)
    ladder = [LadderRung(price=float(tp), fraction=1.0)]
    rationale = dict(rationale) | {"tag": tag}
    return AgentProposal(
        agent_id=agent_id,
        tick_id=int(tick_id),
        source_thought_id=source_thought.thought_id,
        timestamp=timestamp,
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        entry=float(entry),
        stop=float(stop),
        ladder=ladder,
        conviction=0.85,
        regime_fit=0.6,
        valid_until=valid_until,
        rationale=rationale,
        agent_tier=int(tier),
    )


SaeItoshi = A9SaeV1


__all__ = [
    "A9SaeV1",
    "BarsProvider",
    "SAE_V1_CANON_ROLE",
    "SaeItoshi",
]
