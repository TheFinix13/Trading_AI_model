"""Free-form trader paragraph -> typed :class:`TradeLesson`.

The user's flow is:

    >>> extractor = LessonExtractor()
    >>> raw = '''
    ... On Tuesday at 9:45 NY I went short EURUSD M15 from 1.17328
    ... stop 1.17642 target 1.16884. The daily was bearish, H4 trendline
    ... had just broken, and M15 printed an FVG below structure. Won 30 pips.
    ... '''
    >>> lesson = extractor.extract(raw)
    >>> lesson.direction
    'short'
    >>> lesson.confluences
    [Confluence(tf='D1', type='bias', detail='bearish'), ...]

The extractor keeps a strict Pydantic schema so downstream code (replay diff,
weekly retrospective, ML labelling) sees consistent shapes. The prompt asks
the LLM to emit JSON matching the schema exactly; we re-validate on our side
and surface clean errors (with the raw text) when the model goes off-script
so the user can edit and retry rather than silently failing.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from agent.llm.ollama import OllamaClient, OllamaUnavailable

log = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen2.5:14b-instruct"

Direction = Literal["long", "short"]
Outcome = Literal["win", "loss", "breakeven", "open", "skipped"]
Emotion = Literal["confident", "hesitant", "forced", "fomo", "patient", "rushed", "unknown"]


class Confluence(BaseModel):
    tf: Literal["D1", "H4", "H1", "M15", "M5", "M1"]
    type: str  # zone, fvg, bos, fib, trendline, liquidity_sweep, range_high_sweep, ...
    detail: str = ""  # free-form: "618 fib of last impulse", "PDH sweep", etc.


class TradeLesson(BaseModel):
    """A single human-taken trade with its reasoning, ready to be journaled.

    Designed to round-trip cleanly with the journal: every field maps to a
    column in ``human_lessons`` (see ``agent/journal/db.py``)."""

    symbol: str = "EURUSD"
    trade_date: date
    direction: Direction
    entry_price: float
    stop_price: Optional[float] = None
    tp_price: Optional[float] = None
    outcome: Outcome = "open"
    pnl_pips: Optional[float] = None
    pnl_usd: Optional[float] = None

    daily_bias: Optional[str] = None  # short prose: "bearish, failed PDH break"
    confluences: list[Confluence] = Field(default_factory=list)
    session: Optional[str] = None  # Asia / London / NY / overlap / off
    emotion: Emotion = "unknown"

    notes: str = ""  # any free-form context the extractor couldn't slot
    raw_text: str = ""  # original paragraph, kept for audit

    @field_validator("trade_date", mode="before")
    @classmethod
    def _parse_date(cls, v):
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            # Tolerate full ISO datetimes too — common LLM output.
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
            except ValueError:
                return date.fromisoformat(v[:10])
        return v


# -------- prompt ---------------------------------------------------------------

EXTRACT_SYSTEM = """You are a trade-journal extractor for a forex trader who runs a
top-down analysis (D1 + H4 = bias, H1 + M15 = entries) on EURUSD.

Read the user's free-form paragraph about ONE trade and return ONLY a JSON object
matching this exact schema:

{
  "symbol": "EURUSD",
  "trade_date": "YYYY-MM-DD",
  "direction": "long" | "short",
  "entry_price": <float>,
  "stop_price": <float or null>,
  "tp_price": <float or null>,
  "outcome": "win" | "loss" | "breakeven" | "open" | "skipped",
  "pnl_pips": <float or null>,
  "pnl_usd": <float or null>,
  "daily_bias": "<short prose, e.g. 'bearish — failed to break PDH at NY open'>",
  "confluences": [
    {"tf": "D1"|"H4"|"H1"|"M15"|"M5"|"M1", "type": "<one of: zone | fvg | bos | choch | fib | trendline | liquidity_sweep | range_high_sweep | range_low_sweep | session_bias | ema_pullback | other>", "detail": "<short explanation>"}
  ],
  "session": "Asia" | "London" | "NY" | "London-NY overlap" | "off-session",
  "emotion": "confident" | "hesitant" | "forced" | "fomo" | "patient" | "rushed" | "unknown",
  "notes": "<anything not captured above>"
}

Rules:
- Return JSON ONLY, no markdown fences, no commentary.
- If a field is unclear, use null (or "unknown" for emotion).
- For confluences, extract every distinct factor the trader mentions, with the
  correct timeframe. Examples:
    "daily was bearish"      -> {"tf":"D1","type":"session_bias","detail":"bearish"}
    "H4 trendline broke"     -> {"tf":"H4","type":"trendline","detail":"broken"}
    "M15 FVG below structure"-> {"tf":"M15","type":"fvg","detail":"below structure"}
    "swept PDH then reversed"-> {"tf":"D1","type":"range_high_sweep","detail":"PDH sweep + reversal"}
    "618 fib retrace"        -> {"tf":"M15","type":"fib","detail":"61.8 of last leg"} (use the LTF that the trader was reading the fib on)
- Times like "Tuesday 9:45 NY" -> use the date implied by the message context.
  If no year is given, assume 2026.
- Pips conventions: EURUSD pip = 0.0001.
"""


class LessonExtractor:
    """Wraps OllamaClient + JSON schema validation."""

    def __init__(self, client: OllamaClient | None = None, model: str = DEFAULT_MODEL):
        self.client = client or OllamaClient()
        self.model = model

    def is_available(self) -> bool:
        return self.client.is_alive() and self.client.has_model(self.model.split(":")[0])

    def extract(self, raw_text: str, *, today: date | None = None) -> TradeLesson:
        """Extract one trade lesson from a free-form paragraph.

        Raises:
            OllamaUnavailable: daemon not reachable / model missing.
            ValueError: model returned text we couldn't validate as TradeLesson.
        """
        if not raw_text.strip():
            raise ValueError("empty input")

        # Inject today's date so the model can resolve "Monday", "yesterday", etc.
        anchor = today or date.today()
        sys_prompt = EXTRACT_SYSTEM + f"\n\nFor relative dates assume today = {anchor.isoformat()} (a {anchor.strftime('%A')})."

        try:
            content = self.client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": raw_text.strip()},
                ],
                json_mode=True,
                temperature=0.1,
            )
        except OllamaUnavailable:
            raise

        # JSON-mode usually returns clean JSON, but guard against rare leading prose.
        cleaned = _strip_to_json(content)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM did not return valid JSON: {e}\n--- raw output ---\n{content[:500]}") from e

        try:
            lesson = TradeLesson(**data)
        except ValidationError as e:
            raise ValueError(f"LLM JSON failed schema:\n{e}\n--- raw output ---\n{content[:500]}") from e

        lesson.raw_text = raw_text.strip()
        return lesson


def _strip_to_json(text: str) -> str:
    """Defensive: peel ```json fences or stray prose off the model output."""
    t = text.strip()
    if t.startswith("```"):
        # strip first fence line and trailing fence
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3].rstrip()
    # Find first '{' and last '}' to bracket the JSON block.
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start : end + 1]
    return t
