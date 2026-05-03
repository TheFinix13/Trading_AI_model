"""Weekly trading log: structured representation of a multi-day trader review.

A *single* trade (paragraph) is handled by :class:`agent.llm.extractor.TradeLesson`.
A *whole week* of discretionary trading - the kind of review the user writes in a
Word document with screenshots, daily OHLC, multiple trades per day, observations,
open conceptual questions, and predictions for next week - is bigger than that and
needs its own typed shape.

This module defines that shape:

  * :class:`DayOHLC`         - one trading day's open/high/low/close.
  * :class:`DailyReview`     - one day: OHLC + bias + trades + observations + questions.
  * :class:`WeeklyTradingLog`- the whole week: daily reviews + week-level patterns,
                               conceptual questions, and forward predictions.

Why a separate module instead of stretching :class:`TradeLesson`?

  * Trades are the **atom**. A weekly log is a **document** — it has structural
    sections that aren't trade-specific (questions, predictions, week-level
    patterns) and we want to query/render those independently.
  * The agent's *learning* loop uses both. Each ``DailyReview.trades[i]`` becomes
    a ``human_lessons`` row; the document as a whole becomes one ``weekly_logs``
    row that holds the standardized markdown + the broader observations.
  * A clean schema means we can later round-trip:
        .docx  ->  WeeklyTradingLog  ->  standardized.md  ->  WeeklyTradingLog
    so the human can edit the markdown and re-feed it.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from agent.llm.extractor import Confluence, Direction, Emotion, Outcome


PIP = 0.0001  # EURUSD


class DayOHLC(BaseModel):
    open: float
    high: float
    low: float
    close: float

    @property
    def range_pips(self) -> float:
        return round((self.high - self.low) / PIP, 1)

    @property
    def body_pips(self) -> float:
        return round((self.close - self.open) / PIP, 1)

    @property
    def open_close_clustered(self) -> bool:
        """Open ≈ Close (within 25% of the day's range). Signals indecision /
        liquidity sweep day. The user explicitly flagged this pattern in the doc."""
        if self.range_pips <= 1:
            return False
        body = abs(self.close - self.open)
        return body / (self.high - self.low) <= 0.25


class WeeklyTrade(BaseModel):
    """Trade as it appears inside a weekly review (a thinner cousin of TradeLesson).

    We keep this duck-compatible with TradeLesson so that ingest_docx can convert
    1-for-1 when journalling each trade as a human lesson."""

    direction: Direction
    entry_price: float
    stop_price: Optional[float] = None
    tp_price: Optional[float] = None  # primary / final TP
    tp_levels: list[float] = Field(default_factory=list)  # e.g. [TP1, TP2]
    outcome: Outcome = "open"
    pnl_pips: Optional[float] = None
    pnl_usd: Optional[float] = None
    confluences: list[Confluence] = Field(default_factory=list)
    session: Optional[str] = None
    emotion: Emotion = "unknown"
    notes: str = ""
    raw_text: str = ""

    def to_lesson_dict(self, *, trade_date: date, symbol: str = "EURUSD") -> dict:
        """Render as a kwargs-dict suitable for TradeLesson(**...)."""
        return {
            "symbol": symbol,
            "trade_date": trade_date,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "tp_price": self.tp_price or (self.tp_levels[-1] if self.tp_levels else None),
            "outcome": self.outcome,
            "pnl_pips": self.pnl_pips,
            "pnl_usd": self.pnl_usd,
            "daily_bias": None,
            "confluences": [c.model_dump() for c in self.confluences],
            "session": self.session,
            "emotion": self.emotion,
            "notes": self.notes,
            "raw_text": self.raw_text,
        }


class DailyReview(BaseModel):
    trade_date: date
    weekday: str
    ohlc: Optional[DayOHLC] = None
    bias: str = ""
    trades: list[WeeklyTrade] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    image_refs: list[str] = Field(default_factory=list)  # ["FIGURE 7", ...]
    raw_text: str = ""  # full block, kept for audit


class WeeklyTradingLog(BaseModel):
    schema_version: int = 1
    symbol: str = "EURUSD"
    week_start: date
    week_end: date
    days: list[DailyReview] = Field(default_factory=list)
    week_patterns: list[str] = Field(default_factory=list)
    week_questions: list[str] = Field(default_factory=list)
    next_week_predictions: list[str] = Field(default_factory=list)
    psychology_notes: list[str] = Field(default_factory=list)
    source_path: Optional[str] = None
    source_kind: str = "docx"

    # ----- aggregates the dashboard / retrospective will want -------------------

    @property
    def n_trades(self) -> int:
        return sum(len(d.trades) for d in self.days)

    @property
    def n_wins(self) -> int:
        return sum(1 for d in self.days for t in d.trades if t.outcome == "win")

    @property
    def n_losses(self) -> int:
        return sum(1 for d in self.days for t in d.trades if t.outcome == "loss")

    @property
    def total_pips(self) -> float:
        return round(sum((t.pnl_pips or 0.0) for d in self.days for t in d.trades), 1)

    @property
    def total_usd(self) -> float:
        return round(sum((t.pnl_usd or 0.0) for d in self.days for t in d.trades), 2)

    @property
    def open_close_cluster_days(self) -> list[date]:
        return [d.trade_date for d in self.days if d.ohlc and d.ohlc.open_close_clustered]

    # ---------- standardized markdown rendering ---------------------------------

    def to_markdown(self) -> str:
        """Round-trippable markdown. Humans can edit and re-feed this."""
        lines: list[str] = []
        lines.append("---")
        lines.append(f"schema_version: {self.schema_version}")
        lines.append(f"symbol: {self.symbol}")
        lines.append(f"week_start: {self.week_start.isoformat()}")
        lines.append(f"week_end: {self.week_end.isoformat()}")
        if self.source_path:
            lines.append(f"source: {self.source_path}")
        lines.append("---")
        lines.append("")
        lines.append("# Week summary")
        lines.append(f"- trades: {self.n_trades}  (wins: {self.n_wins}, losses: {self.n_losses})")
        lines.append(f"- total: {self.total_pips:+.1f} pips, ${self.total_usd:+.2f}")
        if self.open_close_cluster_days:
            ds = ", ".join(d.isoformat() for d in self.open_close_cluster_days)
            lines.append(f"- open=close cluster days: {ds}")
        lines.append("")

        for d in self.days:
            lines.append(f"# Day: {d.weekday} {d.trade_date.isoformat()}")
            if d.ohlc:
                lines.append("## OHLC")
                lines.append(f"- open : {d.ohlc.open:.5f}")
                lines.append(f"- high : {d.ohlc.high:.5f}")
                lines.append(f"- low  : {d.ohlc.low:.5f}")
                lines.append(f"- close: {d.ohlc.close:.5f}")
                lines.append(f"- range: {d.ohlc.range_pips:.1f} pips    body: {d.ohlc.body_pips:+.1f} pips")
                if d.ohlc.open_close_clustered:
                    lines.append("- pattern: open≈close (indecision / two-sided liquidity)")
            if d.bias:
                lines.append("## Bias")
                lines.append(d.bias)
            if d.trades:
                lines.append("## Trades")
                for i, t in enumerate(d.trades, 1):
                    lines.append(f"### T{i} — {t.direction}")
                    lines.append(f"- entry: {t.entry_price:.5f}")
                    if t.stop_price is not None:
                        lines.append(f"- stop : {t.stop_price:.5f}")
                    if t.tp_levels:
                        for j, tp in enumerate(t.tp_levels, 1):
                            lines.append(f"- TP{j} : {tp:.5f}")
                    elif t.tp_price is not None:
                        lines.append(f"- tp   : {t.tp_price:.5f}")
                    lines.append(f"- outcome: {t.outcome}    pnl: "
                                 f"{(t.pnl_pips if t.pnl_pips is not None else 0):+.1f} pips")
                    if t.confluences:
                        confs = ", ".join(f"({c.tf}, {c.type})" for c in t.confluences)
                        lines.append(f"- confluences: {confs}")
                    if t.session:
                        lines.append(f"- session: {t.session}")
                    if t.notes:
                        lines.append(f"- notes: {t.notes}")
            if d.observations:
                lines.append("## Observations")
                for o in d.observations:
                    lines.append(f"- {o}")
            if d.questions:
                lines.append("## Questions")
                for q in d.questions:
                    lines.append(f"- {q}")
            lines.append("")

        if self.week_patterns:
            lines.append("# Week-level patterns")
            for p in self.week_patterns:
                lines.append(f"- {p}")
            lines.append("")
        if self.week_questions:
            lines.append("# Open conceptual questions")
            for q in self.week_questions:
                lines.append(f"- {q}")
            lines.append("")
        if self.next_week_predictions:
            lines.append("# Predictions for next week")
            for p in self.next_week_predictions:
                lines.append(f"- {p}")
            lines.append("")
        if self.psychology_notes:
            lines.append("# Psychology / process notes")
            for p in self.psychology_notes:
                lines.append(f"- {p}")
            lines.append("")

        return "\n".join(lines)
