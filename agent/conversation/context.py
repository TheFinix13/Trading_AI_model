"""Build the CONTEXT block injected into every LLM chat turn.

The chat LLM is generic — it knows nothing about the journal, the current
EURUSD bias, or yesterday's losing trade unless we hand it those facts.
:class:`ContextBuilder` is a small, fast assembler that pulls only what's
relevant for the current user question:

  * Always: agent identity, configured TFs, today's NY date.
  * If the question mentions a trade# / lesson# : full record for that ID.
  * If the question mentions "today" / "now" / "bias" : latest bars +
    HTF bias snapshot + active range phase + last few signals.
  * If the question is "how did I do this week" : weekly stats from journal.

Heuristics are intentionally cheap (substring match). The LLM still does the
hard part; we just stop it from hallucinating prices it can't see.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from agent.config import Config, load_config
from agent.journal.db import Journal

log = logging.getLogger(__name__)


@dataclass
class ContextBuilder:
    cfg: Config
    journal_path: Path

    @classmethod
    def from_config(cls) -> "ContextBuilder":
        cfg = load_config()
        return cls(cfg=cfg, journal_path=Path(cfg.journal_db))

    # ------------------------------------------------------------------ public

    def build(self, question: str) -> str:
        parts: list[str] = [self._header()]

        ids = _extract_ids(question)
        q = question.lower()

        journal = Journal(self.journal_path) if self.journal_path.exists() else None

        if ids and journal:
            parts.append(self._lookup_records(journal, ids))

        # Live price snapshot is added whenever the user asks anything that
        # could reference a price level. The vision LLM can read levels off a
        # chart but doesn't know the actual current EURUSD quote — this fills
        # that gap so questions like "what's EURUSD trading at?" are answerable.
        price_keywords = ("price", "trading at", "level", "quote", "current", "now",
                           "bias", "today", "where is", "where's", "chart", "screen")
        if any(k in q for k in price_keywords):
            snap = self._latest_price_snapshot()
            if snap:
                parts.append(snap)

        if any(k in q for k in ("today", "now", "current", "bias", "next trade", "should i", "looks like")):
            parts.append(self._live_snapshot(journal))

        if any(k in q for k in ("week", "this week", "last week", "weekly", "summary", "performance")):
            if journal:
                parts.append(self._week_stats(journal))

        if any(k in q for k in ("lesson", "lessons", "i traded", "i went", "yesterday", "monday", "tuesday",
                                  "wednesday", "thursday", "friday")):
            if journal:
                parts.append(self._recent_lessons(journal, limit=10))

        if journal:
            journal.close()

        parts = [p for p in parts if p.strip()]
        return "\n\n".join(parts)

    # ----------------------------------------------------------------- private

    def _header(self) -> str:
        today = datetime.now(timezone.utc).astimezone().date()
        return (
            f"# Agent identity\n"
            f"Symbol: {self.cfg.symbol}\n"
            f"Trading TFs: H1, M15, M5 (entries) — D1, H4 are bias-only\n"
            f"Display TZ: {self.cfg.display_timezone}\n"
            f"Today (local): {today.isoformat()} ({today.strftime('%A')})\n"
            f"Risk per trade: {self.cfg.risk.pct_target * 100:.1f}% target, "
            f"{self.cfg.risk.pct_floor * 100:.1f}% floor (account < ${self.cfg.risk.pct_floor_threshold_account:.0f})\n"
            f"Min confluences: {self.cfg.rules.min_confluences}, RR min: {self.cfg.rules.rr_min}\n"
            f"Gates active: candle-close confirmation={self.cfg.rules.require_close_confirmation}, "
            f"false-breakout filter={self.cfg.rules.reject_false_breakouts}"
        )

    def _lookup_records(self, journal: Journal, ids: dict[str, list[int]]) -> str:
        out: list[str] = ["# Referenced records"]
        for tid in ids.get("trade", []):
            row = journal._conn.execute(
                "SELECT * FROM trades WHERE id=?", (tid,)
            ).fetchone()
            if row:
                t = dict(row)
                out.append(f"  trade#{tid}: {t['direction']} {t['entry_price']:.5f} "
                           f"-> {t.get('exit_price') or 'OPEN'} "
                           f"({t.get('exit_reason') or '...'}, P&L ${t.get('pnl') or 0:.2f})")
        for lid in ids.get("lesson", []):
            row = journal.get_lesson(lid)
            if row:
                conf = json.loads(row.get("confluences_json") or "[]")
                conf_str = ", ".join(f"{c.get('type')}({c.get('tf')})" for c in conf[:5])
                out.append(f"  lesson#{lid}: {row['trade_date']} {row['direction']} "
                           f"@ {row['entry_price']:.5f} ({row['outcome']}, {row.get('pnl_pips') or 0:.1f} pips) "
                           f"— {conf_str}")
        return "\n".join(out) if len(out) > 1 else ""

    def _latest_price_snapshot(self) -> str:
        """Read the most recent close from each cached TF and surface it.

        We use the parquet cache (``data/parquet/EURUSD_*.parquet``) which is
        kept fresh by ``scripts/download_data.py`` / the live data ingestion
        pipeline. This is the closest the agent can get to "live price" without
        an MT5 / broker tick stream — perfectly fine for end-of-day or weekend
        analysis questions.
        """
        try:
            import pandas as pd
            # cfg.data_dir may already point at the parquet folder (older installs)
            # or at the parent data/ folder. Try both so the lookup works either way.
            base = Path(self.cfg.data_dir)
            for cache_root in (base, base / "parquet"):
                if cache_root.exists() and any(cache_root.glob(f"{self.cfg.symbol}_*.parquet")):
                    break
            else:
                return ""
            tfs = ["M5", "M15", "H1", "H4", "D1"]
            rows: list[str] = []
            latest_ts = None
            for tf in tfs:
                p = cache_root / f"{self.cfg.symbol}_{tf}.parquet"
                if not p.exists():
                    continue
                df = pd.read_parquet(p, columns=["open", "high", "low", "close"])
                if df.empty:
                    continue
                last = df.iloc[-1]
                ts = df.index[-1]
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts
                rows.append(
                    f"  {tf:3s} @ {ts.strftime('%Y-%m-%d %H:%M %Z')}  "
                    f"O={last['open']:.5f} H={last['high']:.5f} "
                    f"L={last['low']:.5f} C={last['close']:.5f}"
                )
            if not rows:
                return ""
            header = (
                f"# Latest cached prices ({self.cfg.symbol})\n"
                f"Most recent bar across cache: {latest_ts}\n"
                "Per-TF last bar (these are bid; spread varies by broker):"
            )
            return header + "\n" + "\n".join(rows)
        except Exception as e:
            log.debug("price snapshot failed: %s", e)
            return ""

    def _live_snapshot(self, journal: Journal | None) -> str:
        out = ["# Live snapshot"]
        if journal:
            row = journal._conn.execute(
                "SELECT detected_at, timeframe, direction, confluences, decision "
                "FROM signals ORDER BY id DESC LIMIT 5"
            ).fetchall()
            if row:
                out.append("Last 5 signals (most recent first):")
                for r in row:
                    confs = ", ".join(json.loads(r["confluences"] or "[]")[:5])
                    out.append(f"  {r['detected_at'][:16]} {r['timeframe']} {r['direction']} "
                               f"[{confs}] -> {r['decision']}")
        out.append("(For real-time D1/H4 bias and live prices, run scripts/htf_snapshot.py.)")
        return "\n".join(out)

    def _week_stats(self, journal: Journal) -> str:
        today = datetime.now(timezone.utc).date()
        monday = today - timedelta(days=today.weekday())
        rows = journal._conn.execute(
            "SELECT * FROM trades WHERE entry_time >= ? AND exit_time IS NOT NULL "
            "AND exit_reason != 'end_of_data' ORDER BY entry_time",
            (monday.isoformat(),),
        ).fetchall()
        n = len(rows)
        if n == 0:
            return "# This week\nNo agent trades closed this week."
        wins = [dict(r) for r in rows if (r["pnl"] or 0) > 0]
        losses = [dict(r) for r in rows if (r["pnl"] or 0) < 0]
        total = sum((r["pnl"] or 0) for r in rows)
        wr = len(wins) / n * 100
        return (
            f"# This week (agent, {monday.isoformat()} -> today)\n"
            f"Trades: {n}  Wins: {len(wins)}  Losses: {len(losses)}  "
            f"WR: {wr:.1f}%  Net P&L: ${total:.2f}"
        )

    def _recent_lessons(self, journal: Journal, limit: int = 10) -> str:
        rows = journal._conn.execute(
            "SELECT id, trade_date, direction, entry_price, outcome, pnl_pips, daily_bias "
            "FROM human_lessons ORDER BY trade_date DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return "# Recent human lessons\n(none yet — run scripts/teach.py to add some)"
        out = ["# Recent human lessons"]
        for r in rows:
            r = dict(r)
            out.append(f"  L#{r['id']} {r['trade_date']} {r['direction']:5s} "
                       f"@ {r['entry_price']:.5f} -> {r['outcome']:9s} "
                       f"({r.get('pnl_pips') or 0:+.1f} pips) | bias: {r.get('daily_bias') or '—'}")
        return "\n".join(out)


# -- helpers --------------------------------------------------------------------

_TRADE_RE = re.compile(r"\btrade\s*#?(\d+)|\bt#?(\d+)\b", re.IGNORECASE)
_LESSON_RE = re.compile(r"\blesson\s*#?(\d+)|\bl#?(\d+)\b", re.IGNORECASE)


def _extract_ids(text: str) -> dict[str, list[int]]:
    out = {"trade": [], "lesson": []}
    for m in _TRADE_RE.finditer(text):
        for g in m.groups():
            if g and g.isdigit():
                out["trade"].append(int(g))
    for m in _LESSON_RE.finditer(text):
        for g in m.groups():
            if g and g.isdigit():
                out["lesson"].append(int(g))
    return out
