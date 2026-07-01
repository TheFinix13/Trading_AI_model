"""Weekly rejection-review digest.

Reads each symbol's near-miss vault (``~/Documents/TradingAgentLogs/{SYMBOL}/
near_misses/events.jsonl``), resolves unresolved events by walking forward
against the parquet bar cache, filters to a window of the last ``--days N``
days, and emits a **markdown digest + CSV** grouped by
``(symbol, rejection_reason, stop_bucket)``.

Purpose (Wave 2.1 of the research-pipeline plan, 2026-07-01)
------------------------------------------------------------

The live agent already vaults every downstream-rejected alpha signal via
``SignalLoop._record_near_miss`` for four reasons: ``post_loss_guard``,
``risk_manager``, ``sizing_skip``, ``broker_reject`` (plus the
alpha-level ``htf_gate``). The June 2026 replay showed that many of the
``sizing_skip`` rejections at $100 balance would have been winners under
wick-proof SL. This report surfaces that hidden edge to the operator on
a **weekly cadence**, without changing any gate:

* Rejection **stops of any given trade are not adjusted** by this report.
* The strategy parameters are not tuned.
* The report only READS from the vault + parquet cache; it never writes
  back to the live loop.

The digest is meant to be run as a weekly cron target::

    python -m agent.reports.rejection_review --days 7

or as a one-off audit::

    python -m agent.reports.rejection_review --days 30 \
        --output docs/reviews/rejection_review_2026-07-01.md

A hypothetically-strong rejection bucket is a CANDIDATE for the research
pipeline, not a promotion to production. Every gate change still needs
its pre-registered study in ``finance-research-experiments``. This
constraint is printed verbatim at the bottom of every digest.
"""
from __future__ import annotations

import argparse
import csv
import logging
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.journal.resolver import (
    _event_ts,
    load_events,
    resolve_event,
    write_events,
)
from agent.journal.vault import DEFAULT_VAULT_ROOT
from agent.types import Bar, Timeframe

log = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ("EURUSD", "GBPUSD", "USDCAD")

# Stop buckets are the same set used by the E011 pre-registered study
# (finance-research-experiments/experiments/E011_small_stop_subset_expectancy).
# Boundaries are in pips.
STOP_BUCKETS = (
    (0.0, 10.0, "0-10p"),
    (10.0, 20.0, "10-20p"),
    (20.0, 40.0, "20-40p"),
    (40.0, 80.0, "40-80p"),
    (80.0, float("inf"), "80p+"),
)

CAVEAT = (
    "**HYPOTHESIS-GENERATING EVIDENCE ONLY.** These are counterfactual "
    "outcomes computed without spread/slippage costs and with a "
    "conservative intrabar tie-break (SL wins ties). A rejection reason "
    "with a great hypothetical win rate is a **candidate for the research "
    "pipeline** (E011-E016 in `finance-research-experiments`), never a "
    "license to loosen a gate directly. Every gate change goes through "
    "its pre-registered study first."
)


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------

def _stop_bucket_label(stop_pips: float) -> str:
    for lo, hi, label in STOP_BUCKETS:
        if lo <= stop_pips < hi:
            return label
    return "unknown"


def _event_stop_pips(event: dict) -> float | None:
    try:
        entry = float(event.get("entry") or 0.0)
        stop = float(event.get("stop") or 0.0)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or stop <= 0:
        return None
    return abs(entry - stop) * 10_000.0


def _within_window(event: dict, since: datetime | None) -> bool:
    if since is None:
        return True
    ts = _event_ts(event)
    return ts is not None and ts >= since


# ---------------------------------------------------------------------------
# Per-symbol resolution
# ---------------------------------------------------------------------------

@dataclass
class SymbolLoad:
    symbol: str
    path: Path
    events: list[dict] = field(default_factory=list)
    resolved_now: int = 0
    load_error: str | None = None


def _load_bars_for_events(
    symbol: str, tf: str, events: Sequence[dict],
) -> list[Bar]:
    times = []
    for e in events:
        ts = _event_ts(e)
        if ts is not None:
            times.append(ts)
    if not times:
        return []
    cfg = load_config()
    loader = BarLoader(cache_root=cfg.data_dir)
    try:
        timeframe = Timeframe(tf)
    except ValueError:
        timeframe = Timeframe.H4
    start = min(times) - timedelta(days=60)
    end = max(times) + timedelta(days=60)
    df = loader.get(symbol, timeframe, start, end, refresh=False)
    return df_to_bars(df, timeframe)


def load_symbol(
    symbol: str, vault_root: Path, *, resolve: bool = True,
) -> SymbolLoad:
    """Load + (optionally) resolve one symbol's near-miss vault."""
    path = vault_root / symbol / "near_misses" / "events.jsonl"
    out = SymbolLoad(symbol=symbol, path=path)
    if not path.exists():
        return out

    events = load_events(path)
    if not events:
        return out

    if not resolve:
        out.events = events
        return out

    by_tf: dict[str, list[Bar]] = {}
    resolved: list[dict] = []
    for evt in events:
        if evt.get("resolved") is True:
            resolved.append(evt)
            continue
        tf = str(evt.get("tf") or "H4")
        if tf not in by_tf:
            same_tf_events = [
                e for e in events if str(e.get("tf") or "H4") == tf
            ]
            try:
                by_tf[tf] = _load_bars_for_events(symbol, tf, same_tf_events)
            except Exception as exc:
                log.warning("bar load failed for %s/%s: %s", symbol, tf, exc)
                by_tf[tf] = []
        bars = by_tf[tf]
        new = resolve_event(evt, bars)
        if new.get("resolved"):
            out.resolved_now += 1
        resolved.append(new)

    if out.resolved_now:
        try:
            write_events(path, resolved)
        except Exception as exc:
            log.warning("could not persist resolutions to %s: %s", path, exc)
    out.events = resolved
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

@dataclass
class BucketRow:
    symbol: str
    reason: str
    bucket: str
    n: int = 0
    wins: int = 0
    losses: int = 0
    open: int = 0
    stale: int = 0
    sum_r: float = 0.0
    median_r: float | None = None
    median_stop_pips: float | None = None

    @property
    def resolved(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float | None:
        return (self.wins / self.resolved) if self.resolved else None

    @property
    def avg_r(self) -> float | None:
        return (self.sum_r / self.resolved) if self.resolved else None

    def as_csv_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "reason": self.reason,
            "bucket": self.bucket,
            "n": self.n,
            "wins": self.wins,
            "losses": self.losses,
            "open": self.open,
            "stale": self.stale,
            "win_rate": (
                f"{self.win_rate:.3f}" if self.win_rate is not None else ""
            ),
            "avg_r": f"{self.avg_r:.3f}" if self.avg_r is not None else "",
            "median_r": (
                f"{self.median_r:.3f}" if self.median_r is not None else ""
            ),
            "median_stop_pips": (
                f"{self.median_stop_pips:.1f}"
                if self.median_stop_pips is not None else ""
            ),
        }


def aggregate(
    loads: Sequence[SymbolLoad], since: datetime | None,
) -> list[BucketRow]:
    """Aggregate events by (symbol, reason, stop-bucket) within window."""
    buckets: dict[tuple[str, str, str], BucketRow] = {}
    per_bucket_r: dict[tuple[str, str, str], list[float]] = {}
    per_bucket_stop: dict[tuple[str, str, str], list[float]] = {}

    for load in loads:
        for evt in load.events:
            if not _within_window(evt, since):
                continue
            stop_pips = _event_stop_pips(evt)
            if stop_pips is None:
                continue
            reason = str(evt.get("reason") or "unknown")
            bucket = _stop_bucket_label(stop_pips)
            key = (load.symbol, reason, bucket)
            row = buckets.get(key)
            if row is None:
                row = BucketRow(load.symbol, reason, bucket)
                buckets[key] = row
                per_bucket_r[key] = []
                per_bucket_stop[key] = []

            row.n += 1
            per_bucket_stop[key].append(stop_pips)

            outcome = evt.get("outcome")
            if outcome == "win":
                row.wins += 1
            elif outcome == "loss":
                row.losses += 1
            else:
                row.open += 1
                if int(evt.get("forward_bars_available") or 0) < 6:
                    row.stale += 1

            try:
                r_val = float(evt.get("outcome_r") or 0.0)
            except (TypeError, ValueError):
                r_val = 0.0
            if outcome in ("win", "loss"):
                row.sum_r += r_val
                per_bucket_r[key].append(r_val)

    for key, row in buckets.items():
        if per_bucket_r[key]:
            row.median_r = statistics.median(per_bucket_r[key])
        if per_bucket_stop[key]:
            row.median_stop_pips = statistics.median(per_bucket_stop[key])

    return sorted(
        buckets.values(),
        key=lambda r: (r.symbol, r.reason, r.bucket),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_markdown(
    rows: Sequence[BucketRow],
    *,
    days: int,
    since: datetime | None,
    generated_at: datetime,
    loads: Sequence[SymbolLoad],
) -> str:
    lines = []
    lines.append(f"# Weekly rejection-review — last {days} days")
    lines.append("")
    lines.append(f"Generated: {generated_at.isoformat()}")
    if since is not None:
        lines.append(f"Window: `{since.isoformat()}` → `{generated_at.isoformat()}`")
    else:
        lines.append("Window: all recorded events")
    lines.append("")

    lines.append("## Vault load summary")
    lines.append("")
    lines.append("| symbol | path | events | newly-resolved |")
    lines.append("|---|---|---:|---:|")
    for load in loads:
        note = ""
        if not load.path.exists():
            note = " (missing)"
        lines.append(
            f"| {load.symbol} | `{load.path}`{note} | {len(load.events):,} "
            f"| {load.resolved_now:,} |"
        )
    lines.append("")

    if not rows:
        lines.append("_No events in window - nothing to review._")
        lines.append("")
        lines.append(CAVEAT)
        return "\n".join(lines)

    lines.append("## By (symbol · reason · stop bucket)")
    lines.append("")
    lines.append(
        "| symbol | reason | bucket | n | wins | losses | open | stale | "
        "win% | avg R | median R | median stop (p) |"
    )
    lines.append(
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for r in rows:
        win_pct = f"{r.win_rate * 100:.0f}%" if r.win_rate is not None else "-"
        avg_r = f"{r.avg_r:+.2f}" if r.avg_r is not None else "-"
        med_r = f"{r.median_r:+.2f}" if r.median_r is not None else "-"
        med_stop = (
            f"{r.median_stop_pips:.1f}"
            if r.median_stop_pips is not None else "-"
        )
        lines.append(
            f"| {r.symbol} | {r.reason} | {r.bucket} | {r.n} | {r.wins} | "
            f"{r.losses} | {r.open} | {r.stale} | {win_pct} | {avg_r} | "
            f"{med_r} | {med_stop} |"
        )
    lines.append("")

    lines.append("## Reason rollup (all symbols)")
    lines.append("")
    per_reason: dict[str, list[BucketRow]] = {}
    for r in rows:
        per_reason.setdefault(r.reason, []).append(r)

    lines.append(
        "| reason | n | wins | losses | open | resolved win% | avg R |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for reason in sorted(per_reason):
        rs = per_reason[reason]
        n = sum(r.n for r in rs)
        w = sum(r.wins for r in rs)
        l = sum(r.losses for r in rs)
        o = sum(r.open for r in rs)
        resolved = w + l
        sum_r = sum(r.sum_r for r in rs)
        win_pct = f"{w / resolved * 100:.0f}%" if resolved else "-"
        avg_r = f"{sum_r / resolved:+.2f}" if resolved else "-"
        lines.append(
            f"| {reason} | {n} | {w} | {l} | {o} | {win_pct} | {avg_r} |"
        )
    lines.append("")
    lines.append(CAVEAT)

    return "\n".join(lines)


def write_csv(rows: Sequence[BucketRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "symbol", "reason", "bucket", "n", "wins", "losses", "open",
        "stale", "win_rate", "avg_r", "median_r", "median_stop_pips",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_csv_dict())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--days", type=int, default=7,
        help="Window size in days (default: 7).",
    )
    p.add_argument(
        "--symbol", "-s", nargs="+", default=list(DEFAULT_SYMBOLS),
        help=f"Symbols to include (default: {' '.join(DEFAULT_SYMBOLS)}).",
    )
    p.add_argument(
        "--vault-root", default=None,
        help="Vault root (default: ~/Documents/TradingAgentLogs).",
    )
    p.add_argument(
        "--output", "-o", default=None,
        help="Markdown output path (default: stdout).",
    )
    p.add_argument(
        "--csv", default=None,
        help="CSV output path (default: alongside markdown, .csv extension).",
    )
    p.add_argument(
        "--no-resolve", action="store_true",
        help="Skip walking-forward unresolved events (faster; only reads).",
    )
    p.add_argument("--log-level", default="WARNING")
    return p.parse_args(argv)


def _default_csv_for(md_path: Path | None) -> Path | None:
    if md_path is None:
        return None
    return md_path.with_suffix(".csv")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper())

    vault_root = (
        Path(args.vault_root) if args.vault_root else DEFAULT_VAULT_ROOT
    )
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.days) if args.days > 0 else None

    loads: list[SymbolLoad] = []
    for symbol in args.symbol:
        loads.append(
            load_symbol(
                symbol, vault_root, resolve=not args.no_resolve,
            )
        )

    rows = aggregate(loads, since)
    md = render_markdown(
        rows, days=args.days, since=since, generated_at=now, loads=loads,
    )

    if args.output:
        md_path = Path(args.output)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md + "\n", encoding="utf-8")
        print(f"Wrote markdown: {md_path}")
    else:
        md_path = None
        sys.stdout.write(md + "\n")

    csv_path = Path(args.csv) if args.csv else _default_csv_for(md_path)
    if csv_path is not None:
        write_csv(rows, csv_path)
        print(f"Wrote CSV: {csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
