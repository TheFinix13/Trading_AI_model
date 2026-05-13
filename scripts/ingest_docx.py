"""Ingest a multi-day .docx weekly trading log into the agent's journal.

What this does, step by step:

  1. Parse the .docx (paragraphs + embedded images via ``python-docx``).
  2. Walk the paragraphs and split into per-day blocks using heading regexes
     (MONDAY / TUESDAY / ... + a date like 27TH or "30TH").
  3. For each day block:
       * pull OHLC out of "[O - 1.17220, H - 1.17550, ...]" lines,
       * pull bracketed trades like "[buy – 1.17230 – 1.17360]" and
         "[sell – 1.17560 – 1.16890]" (en/em dashes both supported),
       * keep the surrounding prose as the trade's narrative + the day's bias,
       * keep figure references like "FIGURE 7" so the dashboard can show
         the matching screenshot.
  4. Pull week-level "patterns I'm noticing" / "questions for you" / "next
     week predictions" / psychology process notes from the trailing prose.
  5. Build a :class:`agent.llm.weekly.WeeklyTradingLog` and render it as a
     standardized Markdown document the human can review/edit.
  6. Persist to ``weekly_logs`` and log every trade to ``human_lessons``,
     replay-diff each one against the agent.

The parser is deliberately deterministic for everything load-bearing (dates,
prices, outcomes). The LLM (when available) is used to fill in nuance like
session, emotion, and to convert prose narrative into structured confluences.
We never let the LLM fabricate prices.

Usage:
    PYTHONPATH=. python scripts/ingest_docx.py \
        --input "/abs/path/to/weekly.docx" \
        --out-dir tmp/weekly_log

    Add --no-llm to skip the per-trade LLM enrichment (works fully offline).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from docx import Document  # noqa: E402

from agent.config import load_config  # noqa: E402
from agent.conversation.replay import ReplayDiffer  # noqa: E402
from agent.journal.db import Journal  # noqa: E402
from agent.llm.extractor import Confluence, LessonExtractor, TradeLesson  # noqa: E402
from agent.llm.ollama import OllamaUnavailable  # noqa: E402
from agent.llm.weekly import (  # noqa: E402
    DailyReview,
    DayOHLC,
    WeeklyTrade,
    WeeklyTradingLog,
)
from scripts.extract_docx import iter_block_items  # noqa: E402

log = logging.getLogger("ingest_docx")


# ---------------------------------------------------------------- regexes ----

# "MONDAY 27TH", "FRIDAY – 1ST May", "WEDNESDAY – 29TH", "THURDAY – 30TH" (typo tolerated)
DAY_RE = re.compile(
    r"\b(MON(?:DAY)?|TUE(?:SDAY)?|WED(?:NESDAY)?|THU(?:R(?:S)?DAY|RDAY)?|FRI(?:DAY)?|SAT(?:URDAY)?|SUN(?:DAY)?)\b\s*[\-–—]?\s*(\d{1,2})\s*(?:ST|ND|RD|TH)?",
    re.IGNORECASE,
)

# OHLC: "O - 1.1.220", "H – 1.17550", "L- 1.16935", "C - 1.17208"
# We tolerate weird "1.1.220" typos by trying to repair them.
OHLC_RE = re.compile(
    r"([OHLC])\s*[-–—]\s*([0-9]+\.[0-9.]+)",
    re.IGNORECASE,
)

# Trade markers come in three flavours in the user's doc:
#   1. "[buy – 1.17230 – 1.17360]"
#   2. "[sell trade – 1.17210 – 1.16990]"
#   3. "[1.16715 – 1.16846]"  with side mentioned in the prose right before
# We use TRADE_PRICE_PAIR_RE for the price-pair shape, then rely on context
# to figure out the side.
TRADE_PRICE_PAIR_RE = re.compile(
    r"\[\s*(?:(buy|sell|long|short)(?:\s+trade)?\s*[-–—]\s*)?"
    r"([12]\.\d{4,5})\s*[-–—]\s*([12]\.\d{4,5})\s*\]",
    re.IGNORECASE,
)
SIDE_LOOKBEHIND_RE = re.compile(r"\b(buy|sell|long|short)\s+(?:trade\s+)?(?:from\s+)?$", re.IGNORECASE)
SIDE_LOOKBEHIND_PROSE_RE = re.compile(r"\b(buy|sell|long|short)\b", re.IGNORECASE)

# A weekday name on its own (used by next-week section detection)
WEEKDAYS = {"MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY","SUNDAY"}
WEEKDAY_NAMES = {
    "MON":"Monday","MONDAY":"Monday","TUE":"Tuesday","TUESDAY":"Tuesday",
    "WED":"Wednesday","WEDNESDAY":"Wednesday","THU":"Thursday","THUR":"Thursday",
    "THURDAY":"Thursday","THURSDAY":"Thursday",
    "FRI":"Friday","FRIDAY":"Friday","SAT":"Saturday","SATURDAY":"Saturday",
    "SUN":"Sunday","SUNDAY":"Sunday",
}

FIGURE_RE = re.compile(r"FIGURE\s+\d+", re.IGNORECASE)

# Inline broker CSV lines: "ticket,date,date,buy/sell,lots,...,EURUSD,entry,exit,...,profit,..."
CSV_TRADE_RE = re.compile(
    r"(\d{5,}),\s*(\d{4}-\d{2}-\d{2}T[\d:]+),\s*(\d{4}-\d{2}-\d{2}T[\d:]+),\s*"
    r"(buy|sell),\s*([\d.]+),\s*[\d.]+,\s*EURUSD,\s*"
    r"([\d.]+),\s*([\d.]+),\s*[^,]*,\s*[^,]*,\s*[^,]*,\s*[^,]*,\s*"
    r"([-\d.]+)",
    re.IGNORECASE,
)


@dataclass
class _DocBlock:
    text: str
    style: str


# ---------------------------------------------------------------- parsing ----


def load_paragraphs(input_path: Path) -> tuple[list[_DocBlock], list[dict]]:
    """Return (blocks_in_order, image_records).

    Image records have only enough metadata to copy the file out for the
    dashboard later; we don't OCR the charts (that's a future enhancement).
    """
    from docx.table import Table as _Table

    doc = Document(str(input_path))
    blocks: list[_DocBlock] = []
    for block in iter_block_items(doc):
        if isinstance(block, _Table):
            # Flatten each table row into a CSV-like line so trade parsers can
            # match broker-export data embedded in docx tables.
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells]
                line = ",".join(cells)
                blocks.append(_DocBlock(text=line, style="TableRow"))
        elif hasattr(block, "text"):
            text = block.text.strip()
            style = block.style.name if block.style else "Normal"
            blocks.append(_DocBlock(text=text, style=style))
    images: list[dict] = []
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            images.append({"target": rel.target_ref, "size": len(rel.target_part.blob)})
    return blocks, images


def repair_ohlc_number(s: str, *, expect_near: float | None = None) -> float | None:
    """Parse one OHLC price from messy free text. Returns None when unrepairable.

    Accepted shapes for EURUSD: "1.17220", "1.1722", "1,17220", and the typo-class
    "1.1.220" / "1.1.722" (extra dot from fast typing). When ``expect_near`` is
    given (e.g. the day's close), we use it to disambiguate fat-fingers like
    "1.1.220" which is locally ambiguous between 1.1220 and 1.17220.
    """
    s = s.strip().replace(",", ".")
    # Direct parse
    if s.count(".") == 1:
        try:
            v = float(s)
            if 0.5 < v < 2.0:
                return v
            return None
        except ValueError:
            return None
    parts = s.split(".")
    if len(parts) != 3 or parts[0] != "1":
        return None

    # Candidates we'd accept:
    #   "1.1.220"  -> "1.1220" or "1.17220" (drop the extra dot vs prepend a 7)
    candidates = []
    glued_left = "1." + parts[1] + parts[2]               # "1.1.220" -> "1.1220"
    glued_with_7 = "1." + parts[1] + "7" + parts[2]       # "1.1.220" -> "1.17220"
    glued_with_0 = "1." + parts[1] + "0" + parts[2]       # "1.1.220" -> "1.10220"
    for cand in (glued_left, glued_with_7, glued_with_0):
        try:
            v = float(cand)
            if 0.5 < v < 2.0:
                candidates.append(v)
        except ValueError:
            pass
    if not candidates:
        return None
    if expect_near is None:
        return candidates[0]
    return min(candidates, key=lambda v: abs(v - expect_near))


def parse_day_header(text: str, anchor_year: int, anchor_month: int) -> tuple[str, date] | None:
    m = DAY_RE.search(text)
    if not m:
        return None
    name_raw = m.group(1).upper()
    weekday = WEEKDAY_NAMES.get(name_raw)
    if not weekday:
        return None
    day_num = int(m.group(2))
    # Pick the month/year that lines up with the weekday
    for off_month in (0, 1, -1):
        month = anchor_month + off_month
        year = anchor_year
        if month <= 0:
            month += 12
            year -= 1
        if month > 12:
            month -= 12
            year += 1
        try:
            d = date(year, month, day_num)
        except ValueError:
            continue
        if d.strftime("%A") == weekday:
            return weekday, d
    # As a last resort, accept anchor month even if weekday doesn't match.
    try:
        return weekday, date(anchor_year, anchor_month, day_num)
    except ValueError:
        return None


def parse_ohlc(text: str) -> DayOHLC | None:
    """Pull O/H/L/C from a paragraph. Returns None if any leg is missing.

    Two-pass: first parse the legs we can read directly, then re-parse the
    ambiguous ones using a clean leg as the anchor for typo repair.
    """
    raw: dict[str, str] = {}
    for m in OHLC_RE.finditer(text):
        raw[m.group(1).upper()] = m.group(2)
    if not raw or set(raw.keys()) != {"O", "H", "L", "C"}:
        return None

    parsed: dict[str, float] = {}
    for leg, s in raw.items():
        v = repair_ohlc_number(s)
        if v is not None:
            parsed[leg] = v

    if not parsed:
        return None
    anchor = parsed.get("C") or parsed.get("H") or next(iter(parsed.values()))

    final: dict[str, float] = {}
    for leg, s in raw.items():
        v = repair_ohlc_number(s, expect_near=anchor)
        if v is not None:
            final[leg] = v

    if {"O", "H", "L", "C"} <= set(final.keys()):
        return DayOHLC(open=final["O"], high=final["H"],
                       low=final["L"], close=final["C"])
    return None


def _looks_like_ohlc_bracket(inner: str) -> bool:
    """Reject "[O - 1.17208, H - 1.17272, ...]" style brackets that match our
    price-pair regex by accident (we already extract OHLC separately)."""
    return any(c in inner for c in ("O ", "O -", "O–", "H ", "L ", "C "))


def _pick_side(text: str, m: re.Match) -> str | None:
    """Decide buy/sell for a bracket without an explicit prefix. Walk backwards
    through the prose looking for the most recent buy|sell|long|short word."""
    if m.group(1):
        s = m.group(1).lower()
        return "long" if s in ("buy", "long") else "short"
    # Look in the 250 chars before the bracket for the latest side word.
    window = text[max(0, m.start()-250): m.start()]
    sides = list(SIDE_LOOKBEHIND_PROSE_RE.finditer(window))
    if not sides:
        return None
    last = sides[-1].group(1).lower()
    return "long" if last in ("buy", "long") else "short"


def find_trades_in_text(text: str) -> list[WeeklyTrade]:
    """Pull every bracketed trade pair out of a passage. We support three
    variants (see TRADE_PRICE_PAIR_RE) and use surrounding prose to infer the
    side and outcome when not explicit."""
    trades: list[WeeklyTrade] = []
    for m in TRADE_PRICE_PAIR_RE.finditer(text):
        # Skip OHLC-shaped brackets that got captured by accident.
        bracket_inner = text[m.start()+1: m.end()-1]
        if _looks_like_ohlc_bracket(bracket_inner):
            continue
        try:
            entry = float(m.group(2))
            tp = float(m.group(3))
        except ValueError:
            continue
        # Sanity: EURUSD prices live in [0.5, 2.0]
        if not (0.5 < entry < 2.0 and 0.5 < tp < 2.0):
            continue
        side = _pick_side(text, m)
        if side is None:
            # Fall back to direction from price delta if context fails entirely.
            side = "long" if tp > entry else "short"
        # P&L = signed (entry -> tp): if the math is positive, the trade made
        # money under the assumption that TP was reached. We then refine the
        # outcome label using prose context (loss / breakeven / partial).
        pnl_pips = (tp - entry) / 0.0001 if side == "long" else (entry - tp) / 0.0001
        ctx = text[max(0, m.start()-300): m.end()+300].lower()
        outcome = "win" if pnl_pips > 0 else "loss"
        # Override only when prose is unambiguous about the outcome of THIS bracket.
        if any(w in ctx for w in ("stopped out", "sl hit", "wiped my account",
                                   "took the loss")):
            outcome = "loss"
        elif "moved to be" in ctx or "be hit" in ctx:
            outcome = "breakeven"
        elif "first tp" in ctx and "didn't get my full" in ctx:
            outcome = "win"  # partial — first TP hit, second missed
        trades.append(
            WeeklyTrade(
                direction=side,  # type: ignore[arg-type]
                entry_price=entry,
                tp_price=tp,
                outcome=outcome,  # type: ignore[arg-type]
                pnl_pips=round(pnl_pips, 1),
                raw_text=text[max(0, m.start()-250): m.end()+250],
            )
        )

    # Also parse inline broker CSV lines (ticket,open_time,close_time,type,...)
    seen_entries: set[float] = {t.entry_price for t in trades}
    for m in CSV_TRADE_RE.finditer(text):
        try:
            entry = float(m.group(6))
            exit_price = float(m.group(7))
            profit = float(m.group(8))
        except ValueError:
            continue
        if not (0.5 < entry < 2.0 and 0.5 < exit_price < 2.0):
            continue
        if entry in seen_entries:
            continue
        seen_entries.add(entry)
        side = "long" if m.group(4).lower() == "buy" else "short"
        pnl_pips = (exit_price - entry) / 0.0001 if side == "long" else (entry - exit_price) / 0.0001
        outcome = "win" if profit > 0 else ("loss" if profit < 0 else "breakeven")
        trades.append(
            WeeklyTrade(
                direction=side,  # type: ignore[arg-type]
                entry_price=entry,
                tp_price=exit_price,
                outcome=outcome,  # type: ignore[arg-type]
                pnl_pips=round(pnl_pips, 1),
                raw_text=text[max(0, m.start()-100): m.end()+100],
            )
        )
    return trades


# ---------------------------------------------------------------- splitter ---


def _looks_like_day_header(text: str, header: tuple[str, date]) -> bool:
    """A paragraph is a day header iff it's short AND contains the weekday name
    AND doesn't contain "TRADING ANALYSIS" / "REVIEW" (those are the document
    title which often contains the first weekday + date)."""
    if header is None:
        return False
    if len(text) > 200:
        return False
    upper = text.upper()
    if "TRADING ANALYSIS" in upper or "WEEKLY REVIEW" in upper or "WEEK REVIEW" in upper:
        return False
    weekday3 = header[0][:3].upper()
    # Must start with the weekday (allowing 2 prefix chars at most: "**", "[", etc.)
    if not (upper.startswith(weekday3) or upper[:2].lstrip("*[ ") in ("",) and upper[2:].startswith(weekday3)):
        # Be a bit lenient: also accept "FRIDAY – 1ST May" style starts.
        if not upper.lstrip("*[ –-").startswith(weekday3):
            # Also accept short intro sentences like "Lets look at Wednesday 6th May"
            if weekday3 not in upper or len(text) > 80:
                return False
    # Reject mentions in narrative like "On Monday 27th, ..."
    if upper.startswith("ON "):
        return False
    return True


def split_into_days(blocks: list[_DocBlock], anchor_year: int, anchor_month: int):
    """Returns (preamble_blocks, [(weekday, date, [block, ...]), ...], postamble_blocks)."""
    days: list[tuple[str, date, list[_DocBlock]]] = []
    preamble: list[_DocBlock] = []
    postamble: list[_DocBlock] = []
    current: tuple[str, date, list[_DocBlock]] | None = None
    seen_postamble = False

    for b in blocks:
        text = b.text
        # Postamble starts at "NEXT WEEKS PREDICAMENTS" / "NEXT WEEK" headers
        if not seen_postamble and re.search(r"NEXT WEEK", text, re.IGNORECASE):
            if current is not None:
                days.append(current)
                current = None
            seen_postamble = True
            postamble.append(b)
            continue
        if seen_postamble:
            postamble.append(b)
            continue

        header = parse_day_header(text, anchor_year, anchor_month)
        if header and _looks_like_day_header(text, header):
            if current is not None:
                days.append(current)
            current = (header[0], header[1], [b])
        else:
            if current is None:
                preamble.append(b)
            else:
                current[2].append(b)

    if current is not None:
        days.append(current)

    return preamble, days, postamble


# ---------------------------------------------------------------- builders --


# Day headings sometimes carry the OHLC inline (as in our user's doc); other
# times the OHLC is in a paragraph 1-2 below. We scan all blocks of a day for
# the first OHLC match and pull it.
def build_daily_review(weekday: str, d: date, day_blocks: list[_DocBlock]) -> DailyReview:
    raw_text = "\n".join(b.text for b in day_blocks if b.text).strip()
    ohlc = None
    for b in day_blocks:
        ohlc = parse_ohlc(b.text)
        if ohlc:
            break

    trades = find_trades_in_text(raw_text)

    # Bias = first sentence(s) of the day's prose (excluding figure ticks).
    bias_lines: list[str] = []
    for b in day_blocks[1:]:  # skip header
        if not b.text:
            continue
        if FIGURE_RE.search(b.text):
            continue
        bias_lines.append(b.text)
        if sum(len(x) for x in bias_lines) > 250:
            break
    bias = " ".join(bias_lines)[:600]

    # Observations: any line that mentions "noticed" / "pattern" / "range".
    obs: list[str] = []
    for b in day_blocks:
        t = b.text
        if not t:
            continue
        low = t.lower()
        if any(w in low for w in ("noticed", "pattern", "range", "wick for liquidity",
                                   "liquidity grab", "open and close", "open=close")):
            obs.append(t)

    questions: list[str] = []
    for b in day_blocks:
        if "?" in b.text and len(b.text) < 350:
            questions.append(b.text.strip())

    image_refs = sorted({m.group(0).upper() for b in day_blocks for m in FIGURE_RE.finditer(b.text)})

    return DailyReview(
        trade_date=d,
        weekday=weekday,
        ohlc=ohlc,
        bias=bias,
        trades=trades,
        observations=obs[:5],
        questions=questions[:5],
        image_refs=image_refs,
        raw_text=raw_text,
    )


def extract_postamble(post_blocks: list[_DocBlock]) -> tuple[list[str], list[str], list[str]]:
    """Pull (patterns, questions, predictions) from the trailing 'NEXT WEEK' section."""
    patterns: list[str] = []
    questions: list[str] = []
    predictions: list[str] = []
    for b in post_blocks:
        t = b.text.strip()
        if not t:
            continue
        if FIGURE_RE.fullmatch(t.split()[0] + " " + (t.split()[1] if len(t.split()) > 1 else "")):
            continue
        low = t.lower()
        if "?" in t and len(t) < 350:
            questions.append(t)
        if any(w in low for w in ("watch out", "may finally", "may drop", "we have to",
                                   "expecting", "predict", "going to", "should", "next week")):
            predictions.append(t)
        if any(w in low for w in ("pattern", "fakeout", "liquidity range",
                                   "open and close", "open=close")):
            patterns.append(t)
    # De-dup while preserving order
    seen: set[str] = set()
    def _uniq(xs):
        out = []
        for x in xs:
            if x not in seen:
                seen.add(x); out.append(x)
        return out
    return _uniq(patterns)[:6], _uniq(questions)[:6], _uniq(predictions)[:6]


def find_psychology_notes(blocks: list[_DocBlock]) -> list[str]:
    notes: list[str] = []
    for b in blocks:
        low = b.text.lower()
        if any(w in low for w in ("psychology", "principle", "i close for the day",
                                   "overtrading", "for me, once", "i closed my laptop")):
            notes.append(b.text.strip())
    return notes[:5]


# ---------------------------------------------------------------- LLM enrich -


def llm_enrich_trade(extractor: LessonExtractor, trade: WeeklyTrade, day: DailyReview) -> WeeklyTrade:
    """Re-run a single trade narrative through the LessonExtractor to backfill
    (session, emotion, confluences, daily_bias). Always preserves entry/stop/tp
    that we already parsed deterministically."""
    paragraph = (
        f"On {day.weekday} {day.trade_date.isoformat()}, the trader took a "
        f"{trade.direction} EURUSD trade. They wrote: \"{trade.raw_text}\". "
        f"Day OHLC: {day.ohlc.model_dump() if day.ohlc else 'unknown'}. "
        f"Day bias text: {day.bias[:300]}"
    )
    try:
        lesson = extractor.extract(paragraph, today=day.trade_date)
    except (OllamaUnavailable, ValueError) as e:
        log.warning("LLM enrich failed for %s %s: %s", day.trade_date, trade.direction, e)
        return trade
    enriched = trade.model_copy(deep=True)
    enriched.session = lesson.session or enriched.session
    enriched.emotion = lesson.emotion or enriched.emotion
    enriched.confluences = list(lesson.confluences) or enriched.confluences
    if lesson.notes and not enriched.notes:
        enriched.notes = lesson.notes
    return enriched


# ---------------------------------------------------------------- main flow --


def _promote_preamble_to_first_day(pre: list[_DocBlock], day_groups: list) -> list:
    """The user's docs often put Day-1 narrative (and Day-1's first trade) in
    the paragraphs preceding the first day-header. We move every paragraph that
    looks like Day-1 content (weekday mention, trade bracket, day-1 figures)
    into the front of the first day's block list."""
    if not day_groups:
        return day_groups
    weekday0 = day_groups[0][0].lower()
    promoted: list[_DocBlock] = []
    leftover: list[_DocBlock] = []
    for b in pre:
        low = b.text.lower()
        # Always promote: paragraphs that mention this weekday, contain a trade
        # bracket, or are figure markers we want preserved.
        if (weekday0[:3] in low
            or TRADE_PRICE_PAIR_RE.search(b.text)
            or FIGURE_RE.search(b.text)):
            promoted.append(b)
        else:
            leftover.append(b)
    if not promoted:
        return day_groups
    # New first day = (header, date, promoted + original_blocks).
    h, d, blocks = day_groups[0]
    day_groups[0] = (h, d, promoted + blocks)
    return day_groups


def build_weekly_log(input_path: Path,
                      anchor_year: int = 2026,
                      anchor_month: int = 4) -> tuple[WeeklyTradingLog, list[dict]]:
    blocks, images = load_paragraphs(input_path)
    pre, day_groups, post = split_into_days(blocks, anchor_year, anchor_month)
    day_groups = _promote_preamble_to_first_day(pre, day_groups)
    days: list[DailyReview] = [build_daily_review(*g) for g in day_groups]
    patterns, questions, predictions = extract_postamble(post)
    psych = find_psychology_notes(blocks)

    if days:
        ws, we = days[0].trade_date, days[-1].trade_date
    else:
        ws = we = date(anchor_year, anchor_month, 1)

    weekly = WeeklyTradingLog(
        symbol="EURUSD",
        week_start=ws - timedelta(days=ws.weekday() if ws.weekday() != 6 else 0),
        week_end=we,
        days=days,
        week_patterns=patterns,
        week_questions=questions,
        next_week_predictions=predictions,
        psychology_notes=psych,
        source_path=str(input_path),
        source_kind="docx",
    )
    return weekly, images


def write_outputs(weekly: WeeklyTradingLog, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "standardized.md").write_text(weekly.to_markdown(), encoding="utf-8")
    (out_dir / "standardized.json").write_text(weekly.model_dump_json(indent=2), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--out-dir", default="tmp/weekly_log")
    p.add_argument("--anchor-year", type=int, default=2026)
    p.add_argument("--anchor-month", type=int, default=4)
    p.add_argument("--no-llm", action="store_true",
                   help="Skip per-trade LLM enrichment (deterministic only).")
    p.add_argument("--no-replay", action="store_true",
                   help="Skip the agent replay diff per trade.")
    p.add_argument("--no-journal", action="store_true",
                   help="Don't write to the journal — useful for quick previews.")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)

    weekly, _ = build_weekly_log(input_path,
                                  anchor_year=args.anchor_year,
                                  anchor_month=args.anchor_month)

    # Optional LLM enrichment per trade.
    if not args.no_llm:
        extractor = LessonExtractor()
        if extractor.is_available():
            log.info("Enriching %d trades with LLM (session/emotion/confluences)…",
                     weekly.n_trades)
            for d in weekly.days:
                d.trades = [llm_enrich_trade(extractor, t, d) for t in d.trades]
        else:
            log.info("Ollama not reachable — skipping LLM enrichment.")

    write_outputs(weekly, out_dir)
    log.info("Wrote standardized markdown + JSON to %s", out_dir)
    log.info("Days: %d   Trades: %d   Open=close days: %d",
             len(weekly.days), weekly.n_trades, len(weekly.open_close_cluster_days))

    if args.no_journal:
        return 0

    cfg = load_config()
    journal = Journal(cfg.journal_db)
    weekly_id = journal.log_weekly_log(weekly)
    log.info("Logged weekly_logs#%d  (week %s → %s)",
             weekly_id, weekly.week_start, weekly.week_end)

    differ = None
    if not args.no_replay:
        differ = ReplayDiffer(cfg=cfg)

    saved_lessons = 0
    diff_summary: list[tuple[int, str]] = []
    for d in weekly.days:
        for t in d.trades:
            lesson_kwargs = t.to_lesson_dict(trade_date=d.trade_date, symbol=weekly.symbol)
            lesson = TradeLesson(**lesson_kwargs)
            lesson_id = journal.log_human_lesson(lesson, source="ingest_docx", weekly_log_id=weekly_id)
            saved_lessons += 1
            if differ is not None:
                try:
                    diff = differ.diff_for_lesson(journal.get_lesson(lesson_id))
                    differ.write_diff(journal, lesson_id, diff)
                    diff_summary.append((lesson_id, diff.agreement))
                except Exception as e:  # pragma: no cover — defensive
                    log.warning("replay-diff failed for lesson#%d: %s", lesson_id, e)

    journal.close()
    log.info("Saved %d human_lessons (linked to weekly_logs#%d).", saved_lessons, weekly_id)
    if diff_summary:
        agree = sum(1 for _, a in diff_summary if a == "agree")
        partial = sum(1 for _, a in diff_summary if a == "partial")
        disagree = sum(1 for _, a in diff_summary if a == "disagree")
        no_signal = sum(1 for _, a in diff_summary if a == "no_signal")
        log.info("Replay diffs: agree=%d  partial=%d  disagree=%d  no_signal=%d",
                 agree, partial, disagree, no_signal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
