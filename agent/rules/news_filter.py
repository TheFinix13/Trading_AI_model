"""News-blackout middleware that wraps `RuleEngine.evaluate_precomputed`.

This module deliberately does NOT modify `agent/rules/engine.py`. Instead
it composes around the engine: callers pass an engine instance + a
calendar, and this wrapper short-circuits the evaluation when the
decision-time bar falls inside a high-impact blackout window.

Wiring (future PR, after the edge-fix subagent finishes):

    from agent.rules.news_filter import NewsAwareRuleEngine
    from agent.news import load_calendar

    base = RuleEngine(cfg, htf_biases=...)
    engine = NewsAwareRuleEngine(
        base,
        events=load_calendar(),
        before_min=cfg.news.before_min,
        after_min=cfg.news.after_min,
        currencies=cfg.news.currencies,
        impact_levels=cfg.news.impact_levels,
        enabled=cfg.news.enabled,
    )
    setup = engine.evaluate_precomputed(ctx, i)

The wrapper exposes the same surface as `RuleEngine` (via duck typing)
so existing backtest / live-runner code can swap it in without
modification.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from agent.news.blackout import (
    DEFAULT_AFTER_MIN,
    DEFAULT_BEFORE_MIN,
    DEFAULT_CURRENCIES,
    DEFAULT_IMPACT_LEVELS,
    is_news_blackout,
)
from agent.news.calendar import NewsEvent

log = logging.getLogger(__name__)


@dataclass
class NewsFilterStats:
    """Lightweight counters so a backtest can report 'N setups blocked
    by news blackout' at the end."""
    blocked: int = 0
    last_blocked_event_titles: list[str] = field(default_factory=list)


class NewsAwareRuleEngine:
    """Composes a base `RuleEngine` with a news-blackout veto.

    Duck-typed against `RuleEngine` so it can be substituted directly.
    """

    def __init__(
        self,
        base_engine,
        *,
        events: list[NewsEvent] | None = None,
        before_min: int = DEFAULT_BEFORE_MIN,
        after_min: int = DEFAULT_AFTER_MIN,
        currencies: Iterable[str] = DEFAULT_CURRENCIES,
        impact_levels: str | Iterable[str] | None = "High",
        enabled: bool = True,
    ):
        self.base = base_engine
        self.events: list[NewsEvent] = events or []
        self.before_min = before_min
        self.after_min = after_min
        self.currencies = tuple({c.upper() for c in currencies})
        self.impact_levels = impact_levels
        self.enabled = enabled
        self.stats = NewsFilterStats()

    @property
    def cfg(self):
        return self.base.cfg

    @property
    def htf_biases(self):
        return getattr(self.base, "htf_biases", [])

    def _decision_time(self, ctx, at_index: int) -> datetime | None:
        if at_index < 0 or at_index >= len(ctx.bars):
            return None
        return ctx.bars[at_index].time

    def _is_blackout(self, when: datetime) -> bool:
        if not self.enabled or not self.events:
            return False
        return is_news_blackout(
            when,
            self.events,
            before_min=self.before_min,
            after_min=self.after_min,
            currencies=self.currencies,
            impact_min=self.impact_levels,
        )

    def evaluate_precomputed(self, ctx, at_index: int):
        when = self._decision_time(ctx, at_index)
        if when is not None and self._is_blackout(when):
            self.stats.blocked += 1
            return None
        return self.base.evaluate_precomputed(ctx, at_index)

    def evaluate(self, bars, at_index: int):
        if 0 <= at_index < len(bars):
            when = bars[at_index].time
            if self._is_blackout(when):
                self.stats.blocked += 1
                return None
        return self.base.evaluate(bars, at_index)


def filter_setup(
    setup,
    *,
    when: datetime,
    events: list[NewsEvent],
    before_min: int = DEFAULT_BEFORE_MIN,
    after_min: int = DEFAULT_AFTER_MIN,
    currencies: Iterable[str] = DEFAULT_CURRENCIES,
    impact_levels: str | Iterable[str] | None = "High",
):
    """Stateless functional variant: take an already-evaluated Setup and
    drop it (return None) if `when` is inside a blackout window.

    Useful for callers that can't easily wrap their engine instance --
    they can just call `filter_setup(engine.evaluate_precomputed(ctx, i), ...)`.
    """
    if setup is None:
        return None
    if is_news_blackout(
        when,
        events,
        before_min=before_min,
        after_min=after_min,
        currencies=currencies,
        impact_min=impact_levels,
    ):
        return None
    return setup


__all__ = ["NewsAwareRuleEngine", "NewsFilterStats", "filter_setup"]
