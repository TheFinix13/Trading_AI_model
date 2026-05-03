"""Replay the agent at a human-trade timestamp and produce a side-by-side diff.

Workflow:

  1. User runs ``scripts/teach.py`` to ingest a paragraph about a trade.
  2. The lesson lands in ``human_lessons`` via :func:`Journal.log_human_lesson`.
  3. We call :meth:`ReplayDiffer.diff_for_lesson` which:
       * loads enough cached bars to cover ``lesson.trade_date``;
       * runs ``RuleEngine.evaluate_precomputed`` at the bar closest to the
         human's claimed entry price/time;
       * compares directions, confluences, and SL/TP placement;
       * writes the result into ``agent_disagreements``.
  4. The result is shown to the user immediately AND surfaced on the dashboard
     trade-detail page so we can spot patterns over time.

The replay is *non-destructive* — it never logs new trades to the agent journal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from agent.config import Config, load_config
from agent.data.loader import BarLoader, filter_bars_by_date
from agent.journal.db import Journal
from agent.rules.engine import RuleEngine, precompute
from agent.types import Direction, Setup, Timeframe

log = logging.getLogger(__name__)


@dataclass
class ReplayDiff:
    agreement: str                 # agree | disagree | partial | no_signal
    diff_summary: str
    agent_setup: Setup | None = None


class ReplayDiffer:
    def __init__(self, cfg: Config | None = None, loader: BarLoader | None = None):
        self.cfg = cfg or load_config()
        self.loader = loader or BarLoader(cache_root=self.cfg.data_dir)

    # ----------------------------------------------------------- public

    def diff_for_lesson(
        self,
        lesson: dict,
        timeframe: Timeframe = Timeframe.M15,
        warmup_days: int = 60,
    ) -> ReplayDiff:
        """Run the agent at the lesson's date+price and return the diff.

        ``lesson`` is a dict from :meth:`Journal.get_lesson` (or the equivalent
        Pydantic ``TradeLesson.model_dump()``)."""
        td = lesson["trade_date"]
        if isinstance(td, str):
            td = date.fromisoformat(td[:10])

        end = datetime.combine(td + timedelta(days=1), time.min, tzinfo=timezone.utc)
        start = end - timedelta(days=warmup_days)

        try:
            bars = self.loader.get_bars(self.cfg.symbol, timeframe, start, end)
        except Exception as e:
            return ReplayDiff(agreement="no_signal",
                              diff_summary=f"could not load bars for {td}: {e}")
        if not bars:
            return ReplayDiff(agreement="no_signal",
                              diff_summary=f"no bars cached for {td}")

        # Find the bar that covers (or sits closest to) the lesson's entry day,
        # picking by close-to-entry-price as a tiebreaker.
        target_idx = self._closest_bar_index(bars, td, lesson["entry_price"])
        if target_idx is None or target_idx < 50:
            return ReplayDiff(agreement="no_signal",
                              diff_summary=f"insufficient bars before {td} (target_idx={target_idx})")

        ctx = precompute(bars, self.cfg)
        engine = RuleEngine(self.cfg)
        agent_setup = engine.evaluate_precomputed(ctx, target_idx)

        return self._compare(lesson, agent_setup)

    def write_diff(self, journal: Journal, lesson_id: int, diff: ReplayDiff) -> int:
        """Persist the diff into ``agent_disagreements``."""
        s = diff.agent_setup
        return journal.log_disagreement(
            lesson_id=lesson_id,
            agreement=diff.agreement,
            agent_direction=s.direction.value if s else None,
            agent_entry=s.entry if s else None,
            agent_stop=s.stop if s else None,
            agent_tp=s.take_profit if s else None,
            agent_confluences=s.confluences if s else [],
            agent_ml_score=s.ml_score if s else None,
            diff_summary=diff.diff_summary,
            detected_at=s.detected_at if s else None,
        )

    # ---------------------------------------------------------- internals

    def _closest_bar_index(self, bars, td: date, entry_price: float) -> int | None:
        candidates: list[tuple[float, int]] = []
        for i, b in enumerate(bars):
            bdate = b.time.date() if b.time.tzinfo else b.time.date()
            if bdate == td:
                # Prefer bars whose range contains the human's entry price.
                if b.low <= entry_price <= b.high:
                    return i
                candidates.append((min(abs(b.high - entry_price), abs(b.low - entry_price)), i))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][1]

    def _compare(self, lesson: dict, agent_setup: Setup | None) -> ReplayDiff:
        if agent_setup is None:
            return ReplayDiff(
                agreement="no_signal",
                diff_summary=("Agent saw NO setup at this timestamp. "
                              "Check whether your trade was discretion / instinct only."),
            )

        agent_dir = agent_setup.direction.value
        human_dir = lesson["direction"]
        same_dir = agent_dir == human_dir

        confs = list(agent_setup.confluences)
        confs_short = ", ".join(confs[:6])

        if same_dir:
            agreement = "agree" if len(confs) >= 2 else "partial"
            summary = (
                f"AGREE on direction ({human_dir}). Agent confluences: [{confs_short}]. "
                f"Agent SL {agent_setup.stop:.5f} vs your {lesson.get('stop_price') or '—'}; "
                f"Agent TP {agent_setup.take_profit:.5f} vs your {lesson.get('tp_price') or '—'}."
            )
        else:
            agreement = "disagree"
            summary = (
                f"DISAGREE: agent saw {agent_dir.upper()}, you went {human_dir.upper()}. "
                f"Agent confluences: [{confs_short}]. Worth a closer look — either you read "
                f"a level the agent's detectors missed, or the agent's bias filter contradicts."
            )
        return ReplayDiff(agreement=agreement, diff_summary=summary, agent_setup=agent_setup)
