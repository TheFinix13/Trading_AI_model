"""Shared configuration for the news-defender family (Karasu + Sentinel R7).

Karasu (`a08_karasu.py`) and the Sentinel R7 (`sentinel.py`) both need
to know the same numbers: which impacts block, which impacts merely
scale, how much scale, how wide the ±minute window around each event
is, where the local news cache lives, and which currency pairs the
squad universe cares about. Rather than scatter those knobs across the
agent + rule modules, they live here as a frozen dataclass.

Callers construct :class:`NewsDefenderConfig` once at boot and pass it
to Karasu's constructor + the Sentinel context builder. Defaults match
the ForexFactory blackout doctrine already used by
:mod:`agent.news.blackout` — high-impact USD/EUR events, ±15 min. The
scale factor + tunable knobs are the new v1 surface.

Pip-scoping (Karasu-side): the mapping of ISO currency → symbols whose
base or quote is that currency is a static lookup; USDJPY / USDCHF get
first-class treatment for the future multi-pair panel even though v1
of the trading agent only trades EURUSD / GBPUSD / USDCAD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent.news.calendar import (
    DEFAULT_CACHE_PATH,
    DEFAULT_FEED_URL,
    DEFAULT_TTL_SECONDS,
)


DEFAULT_KARASU_SYMBOLS: tuple[str, ...] = (
    "EURUSD",
    "GBPUSD",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    "USDJPY",
    "USDCHF",
)


def _default_currency_symbol_map() -> dict[str, tuple[str, ...]]:
    """ISO currency -> tuple of symbols in :data:`DEFAULT_KARASU_SYMBOLS`
    whose base or quote is that currency.

    Used by Karasu to decide which symbols are affected by a given
    scheduled release: a USD event affects everything containing "USD",
    an EUR event affects EURUSD only, and so on. Keys are the ISO
    currency string used by ForexFactory (``NewsEvent.currency``).
    """
    return {
        "USD": ("EURUSD", "GBPUSD", "USDCAD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF"),
        "EUR": ("EURUSD",),
        "GBP": ("GBPUSD",),
        "CAD": ("USDCAD",),
        "AUD": ("AUDUSD",),
        "NZD": ("NZDUSD",),
        "JPY": ("USDJPY",),
        "CHF": ("USDCHF",),
    }


@dataclass(frozen=True)
class NewsDefenderConfig:
    """Locked knobs for Karasu + Sentinel R7.

    Attributes:
        feed_url:            ForexFactory weekly XML endpoint.
        cache_path:          On-disk JSON cache (see
                             ``agent.news.calendar``).
        cache_ttl_seconds:   Freshness window before cache is considered
                             stale (Karasu still fires on stale data;
                             the refresh loop is the one that logs).
        blackout_before_min: Minutes BEFORE each event start the
                             advisory / R7 window.
        blackout_after_min:  Minutes AFTER each event close the window.
        blocked_impacts:     Impact strings that trigger R7 BLOCK
                             (default {'High'}).
        scaled_impacts:      Impact strings that trigger R7 SCALE
                             (default {'Medium'}).
        scale_factor:        Risk-scale multiplier applied on medium
                             (default 0.5).
        watched_currencies:  ISO currency strings Karasu attends to;
                             events on other currencies emit no
                             advisories. Default {'USD','EUR','GBP',
                             'CAD','AUD','NZD','JPY','CHF'} — the full
                             DEFAULT_KARASU_SYMBOLS universe.
        currency_symbol_map: ISO currency -> tuple of symbols whose
                             base or quote is that currency.

    All defaults match :mod:`agent.news.blackout` so the two paths
    stay consistent when the same event fires the same window.
    """

    feed_url: str = DEFAULT_FEED_URL
    cache_path: Path = DEFAULT_CACHE_PATH
    cache_ttl_seconds: int = DEFAULT_TTL_SECONDS
    blackout_before_min: int = 15
    blackout_after_min: int = 15
    blocked_impacts: frozenset[str] = frozenset({"High"})
    scaled_impacts: frozenset[str] = frozenset({"Medium"})
    scale_factor: float = 0.5
    watched_currencies: frozenset[str] = frozenset(
        {"USD", "EUR", "GBP", "CAD", "AUD", "NZD", "JPY", "CHF"},
    )
    currency_symbol_map: dict[str, tuple[str, ...]] = field(
        default_factory=_default_currency_symbol_map,
    )


DEFAULT_NEWS_CONFIG = NewsDefenderConfig()


__all__ = [
    "DEFAULT_KARASU_SYMBOLS",
    "DEFAULT_NEWS_CONFIG",
    "NewsDefenderConfig",
]
