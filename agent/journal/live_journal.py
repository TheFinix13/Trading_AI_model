"""Fresh, present-time live journal.

Produces ONE structured markdown log per calendar day under ``data/journal/live/``
(plus a JSON-lines sidecar for machine retraining), capturing the day's market
read, the anticipated-vs-reactive view, how price actually moved, every trade
with its outcome / R-multiple / MAE / MFE / setup signature, and a loss-focused
reflection per trade. A full feature snapshot is recorded at entry for every
trade so the heavier offline scorer retrain has clean, recent data to learn from.

The store is deliberately separate from the legacy SQLite journal (``journal.db``)
so the agent learns only from when it runs *now*. Existing live-journal data can
be archived aside (never deleted) via :meth:`archive_existing`.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class LiveJournal:
    def __init__(
        self,
        root: Path | str = "data/journal/live",
        *,
        archive_root: Path | str = "data/journal/archive",
        scope: str = "live",
    ):
        self.root = Path(root)
        self.archive_root = Path(archive_root)
        self.scope = scope
        self.root.mkdir(parents=True, exist_ok=True)
        self._day_initialised: set[str] = set()

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------
    def archive_existing(self) -> Path | None:
        """Move any existing day logs in ``root`` aside into a timestamped
        archive folder. Returns the archive path, or None if nothing to move.
        History is preserved, never deleted."""
        existing = [p for p in self.root.glob("*") if p.is_file()]
        if not existing:
            return None
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = self.archive_root / f"{self.scope}_{ts}"
        dest.mkdir(parents=True, exist_ok=True)
        for p in existing:
            shutil.move(str(p), str(dest / p.name))
        log.info("Archived %d existing journal files to %s", len(existing), dest)
        return dest

    def _md_path(self, day: str) -> Path:
        return self.root / f"{day}.md"

    def _jsonl_path(self, day: str) -> Path:
        return self.root / f"{day}.jsonl"

    @staticmethod
    def _day_of(ts: datetime | str | None) -> str:
        if ts is None:
            ts = datetime.now(tz=timezone.utc)
        if isinstance(ts, str):
            return ts[:10]
        return ts.strftime("%Y-%m-%d")

    def _append_md(self, day: str, text: str) -> None:
        with self._md_path(day).open("a") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")

    def _append_jsonl(self, day: str, record: dict) -> None:
        record = {"ts": datetime.now(tz=timezone.utc).isoformat(), **record}
        with self._jsonl_path(day).open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    # ------------------------------------------------------------------
    # Day-level analysis
    # ------------------------------------------------------------------
    def start_day(
        self,
        day: str | datetime | None,
        *,
        htf_bias: str = "N/A",
        anticipated_view: str = "",
        reactive_view: str = "",
        zones: str = "",
        mode: str = "hybrid",
    ) -> str:
        """Write the day header once (idempotent within a process)."""
        day = self._day_of(day)
        if day in self._day_initialised or self._md_path(day).exists():
            self._day_initialised.add(day)
            return day
        self._day_initialised.add(day)
        header = (
            f"# {self.scope.title()} Trading Journal — {day}\n\n"
            f"**Mode:** {mode}\n\n"
            f"## Market Read (open)\n\n"
            f"- **HTF bias:** {htf_bias}\n"
            f"- **Anticipated view:** {anticipated_view or 'pending'}\n"
            f"- **Reactive view:** {reactive_view or 'pending'}\n"
            f"- **Active zones:** {zones or 'none yet'}\n\n"
            f"## Intraday Notes\n\n"
        )
        self._append_md(day, header)
        self._append_jsonl(day, {"event": "day_start", "day": day,
                                 "htf_bias": htf_bias, "mode": mode})
        return day

    def note(self, day: str | datetime | None, text: str, *, kind: str = "note") -> None:
        """Append a timestamped intraday note (market move, level taken, flip…)."""
        day = self._day_of(day)
        if day not in self._day_initialised and not self._md_path(day).exists():
            self.start_day(day)
        now = datetime.now(tz=timezone.utc).strftime("%H:%M")
        marker = {"note": "", "move": "📈 ", "flip": "🔁 ", "level": "🎯 "}.get(kind, "")
        self._append_md(day, f"- `{now}` {marker}{text}")
        self._append_jsonl(day, {"event": kind, "text": text})

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------
    def log_trade_entry(
        self,
        *,
        ticket: int | str,
        time: datetime | str,
        symbol: str,
        direction: str,
        source: str,            # 'reaction' | 'anticipation'
        strategy: str,
        signature: str,
        entry: float,
        stop: float,
        take_profit: float,
        lot: float,
        conviction: float,
        sizing_summary: str = "",
        rationale: str = "",
        features: dict | None = None,
        reaction_components: dict | None = None,
    ) -> None:
        day = self._day_of(time)
        if day not in self._day_initialised and not self._md_path(day).exists():
            self.start_day(day)
        t = time if isinstance(time, str) else time.strftime("%Y-%m-%d %H:%M")
        stop_pips = abs(entry - stop) * 10000
        tp_pips = abs(take_profit - entry) * 10000
        rr = (tp_pips / stop_pips) if stop_pips else 0.0
        block = (
            f"\n### Trade #{ticket} — {direction.upper()} {symbol} "
            f"({source}/{strategy})\n\n"
            f"- **Opened:** {t}\n"
            f"- **Entry / Stop / TP:** {entry:.5f} / {stop:.5f} ({stop_pips:.0f}p) "
            f"/ {take_profit:.5f} ({tp_pips:.0f}p)  → R:R 1:{rr:.1f}\n"
            f"- **Lot:** {lot:.2f} | **Conviction:** {conviction:.2f}\n"
            f"- **Signature:** `{signature}`\n"
        )
        if sizing_summary:
            block += f"- **Sizing:** {sizing_summary}\n"
        if rationale:
            block += f"- **Why:** {rationale}\n"
        self._append_md(day, block)
        self._append_jsonl(
            day,
            {
                "event": "trade_entry",
                "ticket": ticket,
                "symbol": symbol,
                "direction": direction,
                "source": source,
                "strategy": strategy,
                "signature": signature,
                "entry": entry,
                "stop": stop,
                "take_profit": take_profit,
                "lot": lot,
                "conviction": conviction,
                "rr": rr,
                "features": features or {},
                "reaction_components": reaction_components or {},
            },
        )

    def log_trade_exit(
        self,
        *,
        ticket: int | str,
        time: datetime | str,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        pnl_pips: float,
        r_multiple: float,
        mae_pips: float = 0.0,
        mfe_pips: float = 0.0,
        signature: str = "",
        lesson: str | None = None,
    ) -> None:
        day = self._day_of(time)
        if day not in self._day_initialised and not self._md_path(day).exists():
            self.start_day(day)
        t = time if isinstance(time, str) else time.strftime("%Y-%m-%d %H:%M")
        outcome = "WIN ✅" if pnl > 0 else "LOSS ❌"
        if lesson is None:
            lesson = self._reflection(pnl, r_multiple, mae_pips, mfe_pips, exit_reason)
        block = (
            f"- **Closed #{ticket}:** {t} @ {exit_price:.5f} ({exit_reason}) — "
            f"**{outcome}** {pnl:+.2f} ({pnl_pips:+.0f}p, {r_multiple:+.2f}R)\n"
            f"- **Excursion:** MAE {mae_pips:.0f}p / MFE {mfe_pips:.0f}p\n"
            f"- **Lesson:** {lesson}\n"
        )
        self._append_md(day, block)
        self._append_jsonl(
            day,
            {
                "event": "trade_exit",
                "ticket": ticket,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "pnl": pnl,
                "pnl_pips": pnl_pips,
                "r_multiple": r_multiple,
                "mae_pips": mae_pips,
                "mfe_pips": mfe_pips,
                "signature": signature,
                "lesson": lesson,
            },
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _reflection(
        pnl: float, r: float, mae: float, mfe: float, exit_reason: str
    ) -> str:
        """Heuristic, loss-focused reflection. Cheap but genuinely useful for
        spotting recurring failure modes in the daily review."""
        if pnl > 0:
            if mfe > 0 and r > 0 and mfe > (r * 1.8 * max(mae, 1.0)):
                return (
                    "Winner, but price ran far past target before/after exit — "
                    "consider a runner / trailing stop to capture more of the move."
                )
            return "Clean winner — setup behaved as read; repeat this signature."
        # Losses — the focus of the learning loop.
        if exit_reason == "sl" and mfe < 3:
            return (
                "Went straight to stop with almost no favourable excursion — the "
                "entry was likely premature or against true momentum. Wait for a "
                "stronger commitment / level reaction before firing this signature."
            )
        if mfe >= 8 and r < 0:
            return (
                f"Reached ~{mfe:.0f}p in favour ({(mfe):.0f}p MFE) then reversed to a "
                "loss — give back too much. Move to break-even sooner or bank a "
                "partial once the move stalls at the next level."
            )
        if mae >= 0 and exit_reason == "sl":
            return (
                "Stopped out. Re-check whether the stop was structurally placed "
                "(beyond the swing/level) rather than a fixed distance, and whether "
                "HTF context actually supported the direction."
            )
        return "Loss — log the context and watch if this signature keeps failing."
