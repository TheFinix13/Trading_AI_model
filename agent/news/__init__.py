"""News calendar + blackout filtering for the trading agent.

Public surface:
    * `NewsEvent`            -- parsed economic event dataclass
    * `fetch_calendar`       -- pull + cache the ForexFactory weekly XML
    * `load_calendar`        -- read cached events from disk
    * `parse_calendar_xml`   -- pure parser, used by tests + fetch
    * `is_news_blackout`     -- True if `now` is within a configured blackout window
    * `next_blackout`        -- introspection helper for the dashboard / logs
"""
from agent.news.calendar import (
    NewsEvent,
    fetch_calendar,
    load_calendar,
    parse_calendar_xml,
)
from agent.news.blackout import (
    DEFAULT_AFTER_MIN,
    DEFAULT_BEFORE_MIN,
    DEFAULT_CURRENCIES,
    DEFAULT_IMPACT_LEVELS,
    is_news_blackout,
    next_blackout,
)

__all__ = [
    "NewsEvent",
    "fetch_calendar",
    "load_calendar",
    "parse_calendar_xml",
    "is_news_blackout",
    "next_blackout",
    "DEFAULT_BEFORE_MIN",
    "DEFAULT_AFTER_MIN",
    "DEFAULT_CURRENCIES",
    "DEFAULT_IMPACT_LEVELS",
]
