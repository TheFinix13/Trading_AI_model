"""Fresh, present-time live journal with quant-grade learning fields.

Produces ONE structured markdown log per calendar day under ``data/journal/live/``
(plus a JSON-lines sidecar for machine retraining / aggregation). Every event is
**dual-layer**: a human-readable prose narrative AND structured machine fields.

On top of the base capture (entry/exit, R-multiple, MAE/MFE, setup signature,
loss-focused reflection) each closed trade now also records:

* **Win/loss attribution** — ``good_setup_won`` / ``marginal_win`` /
  ``good_setup_failed`` / ``bad_setup`` — derived from conviction at entry vs the
  outcome, because the two failure types need opposite fixes (tighten the filter
  vs accept variance).
* **Counterfactual** from MAE/MFE — whether a different stop/target would have
  changed the result (e.g. "stopped out but MFE was +1.4R").

Declined setups (detected but not taken) are logged lightly so an over-strict
filter is visible. The daily roll-up adds a **conviction-calibration** table
(do high-conviction trades actually win more?) and an **anticipated-vs-reactive
scorecard** (how many marked vs acted, which perspective paid).

The store is deliberately separate from the legacy SQLite journal so the agent
learns only from when it runs *now*. Existing data can be archived aside (never
deleted) via :meth:`archive_existing`.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Conviction thresholds. A trade is "high conviction" (right-process) at/above
# HIGH_CONVICTION; calibration bands split low/med/high at BAND_LOW / BAND_HIGH.
HIGH_CONVICTION = 0.66
BAND_LOW = 0.55
BAND_HIGH = 0.70


# ──────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested directly)
# ──────────────────────────────────────────────────────────────────────────
def conviction_band(conviction: float | None) -> str:
    """Bucket a conviction score into 'low' | 'med' | 'high'."""
    c = 0.5 if conviction is None else conviction
    if c < BAND_LOW:
        return "low"
    if c < BAND_HIGH:
        return "med"
    return "high"


def classify_outcome(
    conviction: float | None, r_multiple: float,
    *, high_conviction: float = HIGH_CONVICTION,
) -> str:
    """Attribute a closed trade to one of four learning categories.

    The split is conviction-at-entry vs win/loss, because a high-conviction loss
    (right process, lost to variance) and a low-conviction loss (shouldn't have
    been taken) demand opposite responses.
    """
    won = r_multiple > 0
    high = conviction is not None and conviction >= high_conviction
    if won and high:
        return "good_setup_won"
    if won:
        return "marginal_win"
    if high:
        return "good_setup_failed"
    return "bad_setup"


def counterfactual(
    r_multiple: float, mae_pips: float, mfe_pips: float, stop_pips: float,
    exit_reason: str = "",
) -> dict:
    """From MAE/MFE, infer whether a different stop/target would have changed the
    result. Returns structured fields plus a one-line human note."""
    sp = stop_pips if stop_pips and stop_pips > 0 else 0.0
    mae_r = round((mae_pips / sp), 2) if sp else 0.0
    mfe_r = round((mfe_pips / sp), 2) if sp else 0.0
    won = r_multiple > 0
    alt_tp = False
    alt_stop = False
    gave_back_r = None

    if not won:
        if mfe_r >= 1.0:
            alt_tp = True
            note = (
                f"stopped out but MFE was +{mfe_r:.1f}R — TP too far / exit too "
                f"late; a target near +{mfe_r:.1f}R would have won"
            )
        elif mfe_r < 0.3:
            note = (
                f"never worked (MFE only +{mfe_r:.1f}R) — entry likely against "
                f"true momentum"
            )
        else:
            note = (
                f"lost with MFE +{mfe_r:.1f}R — modest follow-through, entry "
                f"probably premature"
            )
    else:
        gave_back_r = round(max(0.0, mfe_r - r_multiple), 2)
        if mae_r >= 0.8:
            alt_stop = True
            note = (
                f"winner but MAE was -{mae_r:.1f}R — entry early / stop nearly "
                f"hit; a tighter entry would de-risk this signature"
            )
        elif gave_back_r >= 1.0:
            note = (
                f"winner but gave back {gave_back_r:.1f}R after peak "
                f"(MFE +{mfe_r:.1f}R) — consider a trailing stop / partial"
            )
        else:
            note = f"clean winner (MFE +{mfe_r:.1f}R, MAE -{mae_r:.1f}R)"

    return {
        "mae_r": mae_r,
        "mfe_r": mfe_r,
        "gave_back_r": gave_back_r,
        "alt_tp_would_have_helped": alt_tp,
        "alt_stop_would_have_helped": alt_stop,
        "note": note,
    }


def calibration_report(records: list[dict], *, min_n: int = 3) -> dict:
    """Bucket trade records by conviction band and report realized win-rate +
    expectancy per band, plus a miscalibration flag.

    ``records`` are dicts with ``conviction`` and ``r_multiple`` (and optionally
    ``pnl``). The key quant question: do high-conviction trades actually win more
    than low-conviction ones? If not, conviction is miscalibrated.
    """
    buckets: dict[str, dict] = {}
    for band in ("low", "med", "high"):
        buckets[band] = {"band": band, "n": 0, "wins": 0, "sum_r": 0.0,
                         "sum_conv": 0.0}
    for rec in records:
        band = conviction_band(rec.get("conviction"))
        b = buckets[band]
        b["n"] += 1
        b["sum_r"] += rec.get("r_multiple", 0.0)
        b["sum_conv"] += rec.get("conviction") or 0.0
        if rec.get("r_multiple", 0.0) > 0:
            b["wins"] += 1

    rows = []
    for band in ("low", "med", "high"):
        b = buckets[band]
        n = b["n"]
        rows.append({
            "band": band,
            "n": n,
            "win_rate": round(b["wins"] / n, 3) if n else 0.0,
            "expectancy_r": round(b["sum_r"] / n, 3) if n else 0.0,
            "avg_conviction": round(b["sum_conv"] / n, 3) if n else 0.0,
        })

    # Miscalibration: among bands with enough samples, the high band should have
    # the best expectancy. Flag if a lower band beats it by a meaningful margin.
    qualified = {r["band"]: r for r in rows if r["n"] >= min_n}
    miscalibrated = False
    message = "insufficient samples for a calibration verdict"
    if "high" in qualified and (("low" in qualified) or ("med" in qualified)):
        lower_best = max(
            qualified[b]["expectancy_r"] for b in ("low", "med") if b in qualified
        )
        if qualified["high"]["expectancy_r"] < lower_best - 0.05:
            miscalibrated = True
            message = (
                "high-conviction trades are NOT outperforming lower-conviction "
                "ones — conviction model looks miscalibrated (tighten the signal)"
            )
        else:
            message = "high-conviction trades outperform — conviction looks calibrated"
    return {"buckets": rows, "miscalibrated": miscalibrated, "message": message}


def scorecard(trades: list[dict], declines: list[dict]) -> dict:
    """Anticipated-vs-reactive scorecard: per perspective, how many were marked
    (detected) vs acted (taken), the win-rate/expectancy of those acted, and how
    many declined setups would have worked (backtest only)."""
    out: dict[str, dict] = {}
    for source in ("anticipation", "reaction"):
        acted = [t for t in trades if t.get("source") == source]
        decl = [d for d in declines if d.get("source") == source]
        wins = sum(1 for t in acted if t.get("r_multiple", 0.0) > 0)
        sum_r = sum(t.get("r_multiple", 0.0) for t in acted)
        would = sum(1 for d in decl if d.get("would_have_won") is True)
        out[source] = {
            "marked": len(acted) + len(decl),
            "acted": len(acted),
            "declined": len(decl),
            "win_rate": round(wins / len(acted), 3) if acted else 0.0,
            "expectancy_r": round(sum_r / len(acted), 3) if acted else 0.0,
            "declined_would_have_won": would,
        }
    # Which perspective paid the most (by total R from acted trades). Only
    # perspectives that actually traded are eligible; "none" if neither did.
    acted_sources = [s for s in ("anticipation", "reaction") if out[s]["acted"] > 0]
    if acted_sources:
        out["best_perspective"] = max(
            acted_sources,
            key=lambda s: sum(
                t.get("r_multiple", 0.0) for t in trades if t.get("source") == s
            ),
        )
    else:
        out["best_perspective"] = "none"
    return out


class LiveJournal:
    def __init__(
        self,
        root: Path | str = "data/journal/live",
        *,
        archive_root: Path | str = "data/journal/archive",
        scope: str = "live",
        max_decline_detail_per_day: int = 15,
    ):
        self.root = Path(root)
        self.archive_root = Path(archive_root)
        self.scope = scope
        self.max_decline_detail_per_day = max_decline_detail_per_day
        self.root.mkdir(parents=True, exist_ok=True)
        self._day_initialised: set[str] = set()

        # In-memory accumulators powering the daily roll-up + calibration.
        self._open: dict[int | str, dict] = {}       # entry ctx by ticket
        self._day_trades: dict[str, list[dict]] = {}
        self._day_declines: dict[str, list[dict]] = {}
        self._all_trades: list[dict] = []            # rolling, for calibration
        self._rollup_done: set[str] = set()
        self._decline_detail_count: dict[str, int] = {}

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

        # Remember entry context so the eventual exit can attribute the outcome.
        self._open[ticket] = {
            "conviction": conviction, "source": source, "strategy": strategy,
            "signature": signature, "direction": direction, "stop_pips": stop_pips,
        }

        block = (
            f"\n### Trade #{ticket} — {direction.upper()} {symbol} "
            f"({source}/{strategy})\n\n"
            f"- **Opened:** {t}\n"
            f"- **Entry / Stop / TP:** {entry:.5f} / {stop:.5f} ({stop_pips:.0f}p) "
            f"/ {take_profit:.5f} ({tp_pips:.0f}p)  → R:R 1:{rr:.1f}\n"
            f"- **Lot:** {lot:.2f} | **Conviction:** {conviction:.2f} "
            f"({conviction_band(conviction)})\n"
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
                "conviction_band": conviction_band(conviction),
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
        conviction: float | None = None,
        source: str = "",
        stop_pips: float | None = None,
        lesson: str | None = None,
    ) -> dict:
        """Log a closed trade with attribution + counterfactual. Returns the
        structured record (also fed into the daily calibration roll-up)."""
        day = self._day_of(time)
        if day not in self._day_initialised and not self._md_path(day).exists():
            self.start_day(day)
        t = time if isinstance(time, str) else time.strftime("%Y-%m-%d %H:%M")

        # Pull entry context recorded at open (conviction / source / stop).
        octx = self._open.pop(ticket, {})
        conviction = conviction if conviction is not None else octx.get("conviction")
        source = source or octx.get("source", "")
        strategy = octx.get("strategy", "")
        signature = signature or octx.get("signature", "")
        if stop_pips is None:
            stop_pips = octx.get("stop_pips", 0.0)

        attribution = classify_outcome(conviction, r_multiple)
        cf = counterfactual(r_multiple, mae_pips, mfe_pips, stop_pips or 0.0, exit_reason)
        if lesson is None:
            base = self._reflection(pnl, r_multiple, mae_pips, mfe_pips, exit_reason)
            lesson = f"[{attribution}] {cf['note']}. {base}"

        outcome = "WIN ✅" if pnl > 0 else "LOSS ❌"
        block = (
            f"- **Closed #{ticket}:** {t} @ {exit_price:.5f} ({exit_reason}) — "
            f"**{outcome}** {pnl:+.2f} ({pnl_pips:+.0f}p, {r_multiple:+.2f}R)\n"
            f"- **Attribution:** `{attribution}` | conviction "
            f"{('%.2f' % conviction) if conviction is not None else 'n/a'}\n"
            f"- **Excursion:** MAE {mae_pips:.0f}p (-{cf['mae_r']:.1f}R) / "
            f"MFE {mfe_pips:.0f}p (+{cf['mfe_r']:.1f}R)\n"
            f"- **Counterfactual:** {cf['note']}\n"
            f"- **Lesson:** {lesson}\n"
        )
        self._append_md(day, block)

        record = {
            "event": "trade_exit",
            "ticket": ticket,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl": pnl,
            "pnl_pips": pnl_pips,
            "r_multiple": r_multiple,
            "mae_pips": mae_pips,
            "mfe_pips": mfe_pips,
            "mae_r": cf["mae_r"],
            "mfe_r": cf["mfe_r"],
            "gave_back_r": cf["gave_back_r"],
            "alt_tp_would_have_helped": cf["alt_tp_would_have_helped"],
            "alt_stop_would_have_helped": cf["alt_stop_would_have_helped"],
            "attribution": attribution,
            "conviction": conviction,
            "conviction_band": conviction_band(conviction),
            "source": source,
            "strategy": strategy,
            "signature": signature,
            "lesson": lesson,
        }
        self._append_jsonl(day, record)

        # Feed the calibration accumulators.
        agg = {"conviction": conviction, "r_multiple": r_multiple, "pnl": pnl,
               "source": source, "attribution": attribution, "signature": signature}
        self._day_trades.setdefault(day, []).append(agg)
        self._all_trades.append(agg)
        return record

    # ------------------------------------------------------------------
    # Declined setups (detected but NOT taken)
    # ------------------------------------------------------------------
    def log_declined(
        self,
        day: str | datetime | None,
        *,
        signature: str,
        reason: str,
        source: str,
        conviction: float | None = None,
        direction: str = "",
        would_have_won: bool | None = None,
        would_have_note: str = "",
    ) -> None:
        """Record a setup that was detected but not taken. Cheap by design: in
        live mode just the signature + reason; in the backtest the caller can
        supply a would-have outcome so an over-strict filter becomes visible."""
        day = self._day_of(day)
        if day not in self._day_initialised and not self._md_path(day).exists():
            self.start_day(day)

        rec = {
            "source": source, "signature": signature, "reason": reason,
            "conviction": conviction, "direction": direction,
            "would_have_won": would_have_won, "would_have_note": would_have_note,
        }
        self._day_declines.setdefault(day, []).append(rec)
        self._append_jsonl(day, {"event": "declined", **rec})

        # Cap the human-readable detail lines so quiet bars don't flood the log.
        seen = self._decline_detail_count.get(day, 0)
        if seen < self.max_decline_detail_per_day:
            self._decline_detail_count[day] = seen + 1
            conv = f"{conviction:.2f}" if conviction is not None else "n/a"
            extra = f" — would-have: {would_have_note}" if would_have_note else ""
            self._append_md(
                day,
                f"- `declined` ({source}) `{signature}` conv={conv}: {reason}{extra}",
            )

    # ------------------------------------------------------------------
    # Daily roll-up: calibration + scorecard
    # ------------------------------------------------------------------
    def log_daily_rollup(self, day: str | datetime | None) -> dict:
        """Write the end-of-day learning summary: conviction calibration (day +
        rolling), the anticipated-vs-reactive scorecard, and a declined-setup
        summary. Idempotent per day."""
        day = self._day_of(day)
        if day in self._rollup_done:
            return {}
        self._rollup_done.add(day)
        if day not in self._day_initialised and not self._md_path(day).exists():
            self.start_day(day)

        trades = self._day_trades.get(day, [])
        declines = self._day_declines.get(day, [])
        day_cal = calibration_report(trades)
        roll_cal = calibration_report(self._all_trades)
        card = scorecard(trades, declines)

        n = len(trades)
        wins = sum(1 for t in trades if t.get("r_multiple", 0.0) > 0)
        total_r = sum(t.get("r_multiple", 0.0) for t in trades)
        attr_counts: dict[str, int] = {}
        for t in trades:
            a = t.get("attribution", "?")
            attr_counts[a] = attr_counts.get(a, 0) + 1
        would_win = sum(1 for d in declines if d.get("would_have_won") is True)

        lines = ["", "## Daily Roll-up", ""]
        lines.append(
            f"- **Trades:** {n} | wins {wins} | expectancy "
            f"{(total_r / n) if n else 0:+.2f}R"
        )
        if attr_counts:
            lines.append(
                "- **Attribution:** "
                + ", ".join(f"{k}={v}" for k, v in sorted(attr_counts.items()))
            )

        lines.append("- **Conviction calibration (today):**")
        lines.append("")
        lines.append("  | band | n | win% | expectancy R |")
        lines.append("  | --- | --- | --- | --- |")
        for b in day_cal["buckets"]:
            lines.append(
                f"  | {b['band']} | {b['n']} | {b['win_rate'] * 100:.0f}% | "
                f"{b['expectancy_r']:+.2f} |"
            )
        flag = "⚠️ MISCALIBRATED" if day_cal["miscalibrated"] else "ok"
        lines.append(f"- **Calibration verdict (today):** {flag} — {day_cal['message']}")
        roll_flag = "⚠️ MISCALIBRATED" if roll_cal["miscalibrated"] else "ok"
        lines.append(
            f"- **Calibration verdict (rolling, n={len(self._all_trades)}):** "
            f"{roll_flag} — {roll_cal['message']}"
        )

        lines.append("- **Anticipated vs reactive scorecard:**")
        for source in ("anticipation", "reaction"):
            s = card[source]
            lines.append(
                f"  - **{source}:** marked {s['marked']} / acted {s['acted']} / "
                f"declined {s['declined']} | win {s['win_rate'] * 100:.0f}% | "
                f"exp {s['expectancy_r']:+.2f}R"
                + (f" | declined-would-have-won {s['declined_would_have_won']}"
                   if s['declined_would_have_won'] else "")
            )
        if card.get("best_perspective"):
            lines.append(f"  - **Paid the most:** {card['best_perspective']}")

        if declines:
            lines.append(
                f"- **Declined setups:** {len(declines)}"
                + (f" (of which {would_win} would have won — filter may be too "
                   f"strict)" if would_win else "")
            )
        lines.append("")
        self._append_md(day, "\n".join(lines))

        rollup = {
            "event": "daily_rollup",
            "day": day,
            "trades": n,
            "wins": wins,
            "expectancy_r": round((total_r / n) if n else 0.0, 3),
            "attribution_counts": attr_counts,
            "calibration_today": day_cal,
            "calibration_rolling": roll_cal,
            "scorecard": card,
            "declined": len(declines),
            "declined_would_have_won": would_win,
        }
        self._append_jsonl(day, rollup)
        return rollup

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
