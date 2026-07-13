"""Compile one shareable weekly-review bundle across all deployed symbols.

Run this ON THE VM (it reads the live evidence straight off disk, the same
folders ``daily_summary.py`` reads). It replaces "paste a dozen individual
.log files and events.jsonl into chat" with ONE zip containing:

  * A single ``REPORT.md`` — per-symbol trade list, near-miss breakdown,
    error/warning tally, balance curve, and (new vs. ``daily_summary.py``)
    an explicit UPTIME / DOWNTIME timeline: every kill-switch halt and
    emergency-close-all, when it started, when (if ever) it was cleared,
    and how many hours of the window were spent halted vs. actually live.
  * The raw daily ``.log`` files for the window, per symbol.
  * The near-miss and loss vault chart PNGs (+ their events.jsonl records)
    that fall inside the window, per symbol.
  * ``state.json`` as last seen, per symbol.

The downtime timeline exists because kill-switch halts are the single
biggest source of "the agent didn't do anything" — far more of a typical
week is lost to a halt sitting un-cleared than to any one bad trade, and
that's invisible unless someone reads every log line by hand.

Usage:
    python scripts/compile_review_bundle.py
    python scripts/compile_review_bundle.py --days 7
    python scripts/compile_review_bundle.py --symbol GBPUSD --days 12
    python scripts/compile_review_bundle.py --out C:\\Users\\Fiyin\\Desktop\\review.zip

Prints the final zip path on completion — attach that one file instead of
individual logs/screenshots. Everything here is observation-only; nothing
it does can affect trading behaviour (it only reads files and writes to a
separate ``reviews/`` output folder).

NOTE: for the ROUTINE weekly hand-off use ``scripts/weekly_report.py``
instead — it builds one markdown report with per-symbol trade tables, a
cross-symbol account view (external-equity-move detection), the parameter
snapshot and an auto-flagged review checklist, and bundles the vault
evidence (near-miss/loss/ladder JSONLs + PNGs) for every symbol in one zip.
This script remains for ad-hoc single-symbol deep-dives.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daily_summary import (  # noqa: E402
    DEFAULT_SYMBOLS,
    SymbolStats,
    _iter_jsonl,
    _log_path,
    _read_state,
    _resolve_days,
    _vault_dir,
    parse_log_file,
    render_symbol,
)

from agent.journal.vault import DEFAULT_VAULT_ROOT  # noqa: E402

RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
RE_KILL_SKIP = re.compile(r"Kill switch active\b", re.IGNORECASE)
RE_KILL_ACTIVE_REASON_HEADER = re.compile(
    r"Kill switch (?:ACTIVE|active) at .+?[.:] ?Reason recorded when it was created:"
)
RE_EMERGENCY_CLOSE = re.compile(r"EMERGENCY CLOSE ALL: (?P<reason>.+)")
RE_DD_LIMIT = re.compile(
    r"Daily DD limit reached: (?P<dd>[\d.]+)% >= (?P<limit>[\d.]+)%"
)
RE_AUTOTRADING_DISABLED = re.compile(
    r"agent\.live\.broker: Order rejected: retcode=(?P<code>\d+) "
    r"comment='(?P<comment>[^']+)'"
)
RE_BROKER_DISCONNECTED = re.compile(r"MT5 disconnected")
# Evidence the loop actually evaluated something — used to decide a
# kill-switch downtime window has genuinely ended. Heartbeat / connect /
# healthcheck lines still appear *during* a halt and must NOT close it.
RE_RESUME_EVIDENCE = re.compile(
    r"\[SIGNAL\]|\[TRADE OPENED\]|\[NEAR MISS\]|H4 close .* evaluated|"
    r"Signal loop starting|Startup bar test OK"
)
RE_HEALTHCHECK_FAIL = re.compile(r"Healthcheck ping failed: (?P<detail>.+)")
RE_TELEGRAM_NOT_CONFIGURED = re.compile(r"Telegram not configured")
RE_SOFT_SL_PANIC = re.compile(
    r"\[SOFT SL\] (?P<sym>\S+) ticket=(?P<ticket>\d+) — price (?P<price>[\d.]+) "
    r"blew through soft stop (?P<soft>[\d.]+) by >(?P<mult>[\d.]+)"
)


# ---------------------------------------------------------------------------
# Downtime timeline
# ---------------------------------------------------------------------------
@dataclass
class DowntimeWindow:
    start: datetime
    end: datetime
    reason: str = "unknown"

    @property
    def duration_hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0


@dataclass
class SymbolEvents:
    downtime: list[DowntimeWindow] = field(default_factory=list)
    autotrading_rejects: list[tuple[datetime, str]] = field(default_factory=list)
    dd_halts: list[tuple[datetime, str]] = field(default_factory=list)
    broker_disconnects: int = 0
    healthcheck_fails: list[tuple[datetime, str]] = field(default_factory=list)
    telegram_unconfigured: bool = False
    soft_sl_panics: list[tuple[datetime, str]] = field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None


def _parse_line_ts(line: str) -> datetime | None:
    m = RE_TS.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def scan_downtime_and_incidents(log_paths: list[Path]) -> SymbolEvents:
    """Walk daily log files (chronological) and extract the downtime
    timeline + one-off incident events. Pure text scan — never touches the
    broker or trading state."""
    ev = SymbolEvents()
    in_downtime = False
    cur_start: datetime | None = None
    cur_reason = "unknown"
    pending_reason: str | None = None  # set right after a "Reason recorded" header

    for path in log_paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in lines:
            ts = _parse_line_ts(raw)
            if ts is not None:
                if ev.first_seen is None:
                    ev.first_seen = ts
                ev.last_seen = ts
                line = raw
            else:
                # Continuation line (e.g. the "Auto-kill: ..." reason on its
                # own line right after "...Reason recorded when it was
                # created:"). Attach it if we're expecting one.
                if pending_reason == "":
                    cur_reason = raw.strip() or cur_reason
                    pending_reason = None
                continue

            if RE_KILL_ACTIVE_REASON_HEADER.search(line):
                pending_reason = ""  # next non-timestamped line is the reason
                continue

            m = RE_EMERGENCY_CLOSE.search(line)
            if m:
                reason_text = m.group("reason").strip()
                # "Kill switch activated (kill.txt): ..." is the generic
                # wrapper logged for every halt regardless of cause; prefer
                # whatever more specific reason we already have (e.g. from
                # the "Reason recorded when it was created" header) over it.
                if not reason_text.lower().startswith("kill switch activated"):
                    cur_reason = reason_text

            m = RE_DD_LIMIT.search(line)
            if m:
                ev.dd_halts.append((ts, f"{m.group('dd')}% >= {m.group('limit')}%"))

            m = RE_AUTOTRADING_DISABLED.search(line)
            if m:
                ev.autotrading_rejects.append((ts, m.group("comment")))

            if RE_BROKER_DISCONNECTED.search(line):
                ev.broker_disconnects += 1

            m = RE_HEALTHCHECK_FAIL.search(line)
            if m:
                ev.healthcheck_fails.append((ts, m.group("detail")))

            if RE_TELEGRAM_NOT_CONFIGURED.search(line):
                ev.telegram_unconfigured = True

            m = RE_SOFT_SL_PANIC.search(line)
            if m:
                ev.soft_sl_panics.append(
                    (ts, f"ticket={m.group('ticket')} price={m.group('price')} "
                         f"soft_sl={m.group('soft')} overshoot={m.group('mult')}x")
                )

            if RE_KILL_SKIP.search(line):
                if not in_downtime:
                    in_downtime = True
                    cur_start = ts
                cur_end_candidate = ts
            elif in_downtime and RE_RESUME_EVIDENCE.search(line):
                # Genuine evidence the loop is evaluating again (not just a
                # heartbeat/connect/healthcheck line, which still fire while
                # halted and must not be mistaken for a resume).
                ev.downtime.append(
                    DowntimeWindow(start=cur_start, end=cur_end_candidate,
                                   reason=cur_reason)
                )
                in_downtime = False
                cur_reason = "unknown"

        # Do not close a downtime window just because a daily file ended —
        # it may continue into the next day's file.

    if in_downtime and cur_start is not None:
        ev.downtime.append(
            DowntimeWindow(start=cur_start, end=cur_end_candidate, reason=cur_reason)
        )

    return ev


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_downtime_section(ev: SymbolEvents, window_hours: float) -> list[str]:
    out = ["", "─ Uptime / downtime (kill-switch halts) ─"]
    if not ev.downtime:
        out.append("  No kill-switch halts detected in this window. ✅")
        return out
    total_down = sum(w.duration_hours for w in ev.downtime)
    pct = (total_down / window_hours * 100) if window_hours else 0.0
    out.append(
        f"  ⚠ Halted for {total_down:.1f}h of this ~{window_hours:.0f}h window "
        f"({pct:.0f}% downtime, {len(ev.downtime)} halt period(s))"
    )
    for w in ev.downtime:
        still_open = " — STILL ACTIVE at end of provided logs" if w == ev.downtime[-1] and w.end == ev.last_seen else ""
        out.append(
            f"    · {w.start.strftime('%Y-%m-%d %H:%M')} UTC → "
            f"{w.end.strftime('%Y-%m-%d %H:%M')} UTC "
            f"({w.duration_hours:.1f}h) — reason: {w.reason}{still_open}"
        )
    return out


def render_incidents_section(ev: SymbolEvents) -> list[str]:
    out = ["", "─ Incidents / infra warnings ─"]
    any_incident = False
    if ev.autotrading_rejects:
        any_incident = True
        out.append(f"  ⚠ AutoTrading disabled in MT5 — {len(ev.autotrading_rejects)} "
                    "signal(s) rejected at the terminal (not a code bug — the "
                    "AutoTrading toggle in MT5 was off):")
        for ts, comment in ev.autotrading_rejects:
            out.append(f"    · {ts.strftime('%Y-%m-%d %H:%M')} UTC — {comment}")
    if ev.dd_halts:
        any_incident = True
        out.append(f"  ⚠ Daily drawdown limit breached — {len(ev.dd_halts)} time(s):")
        for ts, detail in ev.dd_halts:
            out.append(f"    · {ts.strftime('%Y-%m-%d %H:%M')} UTC — {detail}")
    if ev.soft_sl_panics:
        any_incident = True
        out.append(f"  ⚠ Soft-SL panic exits (price blew past the soft stop before "
                    f"candle close) — {len(ev.soft_sl_panics)} time(s):")
        for ts, detail in ev.soft_sl_panics:
            out.append(f"    · {ts.strftime('%Y-%m-%d %H:%M')} UTC — {detail}")
    if ev.broker_disconnects:
        any_incident = True
        out.append(f"  · MT5 disconnect/reconnect cycles logged: {ev.broker_disconnects} "
                    "(normal churn unless clustered — see raw logs)")
    if ev.healthcheck_fails:
        any_incident = True
        out.append(f"  ⚠ Healthcheck ping failures (DNS/network) — {len(ev.healthcheck_fails)} time(s):")
        for ts, detail in ev.healthcheck_fails[:5]:
            out.append(f"    · {ts.strftime('%Y-%m-%d %H:%M')} UTC — {detail}")
        if len(ev.healthcheck_fails) > 5:
            out.append(f"    · … and {len(ev.healthcheck_fails) - 5} more")
    if ev.telegram_unconfigured:
        any_incident = True
        out.append("  ⚠ Telegram was NOT configured for at least part of this window "
                    "(halts/notifications would have been silent).")
    if not any_incident:
        out.append("  None detected. ✅")
    return out


# ---------------------------------------------------------------------------
# PNG / evidence copying
# ---------------------------------------------------------------------------
def _date_prefix_in_window(name: str, days: list[date]) -> bool:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_", name)
    if not m:
        return False
    try:
        d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return False
    return d in days


def copy_vault_evidence(symbol_dir: Path, days: list[date], dest: Path) -> dict[str, int]:
    """Copy near-miss/loss PNGs + their JSONL records that fall inside the
    window into ``dest/near_misses`` and ``dest/losses``. Returns counts."""
    counts = {"near_misses": 0, "losses": 0}
    for sub, key in (("near_misses", "near_misses"), ("losses", "losses")):
        src_dir = symbol_dir / sub
        if not src_dir.is_dir():
            continue
        out_dir = dest / sub
        out_dir.mkdir(parents=True, exist_ok=True)
        for png in sorted(src_dir.glob("*.png")):
            if _date_prefix_in_window(png.name, days):
                shutil.copy2(png, out_dir / png.name)
                counts[key] += 1
        jsonl_path = src_dir / "events.jsonl"
        if jsonl_path.exists():
            day_strs = {d.isoformat() for d in days}
            kept = []
            for rec in _iter_jsonl(jsonl_path):
                ts = str(rec.get("ts", ""))
                if ts[:10] in day_strs:
                    kept.append(rec)
            if kept:
                import json
                with (out_dir / "events.jsonl").open("w", encoding="utf-8") as f:
                    for rec in kept:
                        f.write(json.dumps(rec) + "\n")
    return counts


# ---------------------------------------------------------------------------
# Main per-symbol assembly
# ---------------------------------------------------------------------------
def compile_symbol(symbol: str, root: Path, days: list[date], staging: Path) -> str:
    stats = SymbolStats(symbol=symbol)
    symbol_dir = _vault_dir(root, symbol)
    log_paths: list[Path] = []
    if symbol_dir is not None:
        stats.state = _read_state(symbol_dir)
    for day in days:
        log_path = _log_path(root, symbol, day)
        if log_path is None:
            continue
        parse_log_file(log_path, stats)
        log_paths.append(log_path)

    out = [render_symbol(stats, symbol_dir)]

    window_hours = len(days) * 24.0
    if log_paths:
        ev = scan_downtime_and_incidents(log_paths)
        out.extend(render_downtime_section(ev, window_hours))
        out.extend(render_incidents_section(ev))
    else:
        out.append("\n(No log files found for this symbol in the requested window — "
                    "not deployed, or logs live somewhere other than the default path.)")

    # Copy raw evidence into the staging folder for this symbol.
    sym_out = staging / symbol
    logs_out = sym_out / "logs"
    logs_out.mkdir(parents=True, exist_ok=True)
    for lp in log_paths:
        shutil.copy2(lp, logs_out / lp.name)
    if symbol_dir is not None:
        png_counts = copy_vault_evidence(symbol_dir, days, sym_out)
        out.append(
            f"\n(Copied into bundle: {len(log_paths)} log file(s), "
            f"{png_counts['near_misses']} near-miss chart(s), "
            f"{png_counts['losses']} loss chart(s).)"
        )
        state_path = symbol_dir / "state.json"
        if state_path.exists():
            shutil.copy2(state_path, sym_out / "state.json")

    return "\n".join(out)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--symbol", "-s", nargs="+", default=list(DEFAULT_SYMBOLS),
                    help="Symbols to include (default: %(default)s)")
    p.add_argument("--days", "-d", type=int, default=7,
                    help="Number of UTC days back to include (default: 7)")
    p.add_argument("--end-date", default=None,
                    help="Anchor day (YYYY-MM-DD UTC). Default: today UTC.")
    p.add_argument("--log-dir", default=None,
                    help=f"Vault root (default: {DEFAULT_VAULT_ROOT})")
    p.add_argument("--out", default=None,
                    help="Output zip path. Default: "
                         "<log-dir>/reviews/review_<window>.zip")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.log_dir) if args.log_dir else DEFAULT_VAULT_ROOT
    end_day = (datetime.fromisoformat(args.end_date).date()
               if args.end_date else datetime.now(timezone.utc).date())
    days = _resolve_days(end_day, max(1, args.days))
    symbols = [s.strip().upper() for s in args.symbol]

    stamp = (days[0].isoformat() if len(days) == 1
             else f"{days[0].isoformat()}_to_{days[-1].isoformat()}")
    zip_path = Path(args.out) if args.out else root / "reviews" / f"review_{stamp}.zip"
    staging = zip_path.parent / f"_staging_{stamp}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    report_lines = [
        "=" * 80,
        "TRADING AGENT — WEEKLY REVIEW BUNDLE",
        f"Window    : {days[0].isoformat()} -> {days[-1].isoformat()} "
        f"({len(days)} day(s), UTC)",
        f"Symbols   : {', '.join(symbols)}",
        f"Log root  : {root}",
        f"Generated : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "=" * 80,
        "",
        "This bundle is OBSERVATION-ONLY evidence — nothing here changes any",
        "gate or config by itself. Read it top to bottom per symbol: the",
        "'Uptime / downtime' section usually explains a bad week more than",
        "any single trade does.",
        "",
    ]
    for symbol in symbols:
        report_lines.append(compile_symbol(symbol, root, days, staging))
        report_lines.append("")

    report_text = "\n".join(report_lines)
    (staging / "REPORT.md").write_text(report_text, encoding="utf-8")

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in staging.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(staging))
    shutil.rmtree(staging)

    print(report_text)
    print(f"\nBundle written to: {zip_path}")
    print("Attach that one .zip — it contains REPORT.md, the raw daily logs, "
          "and the near-miss/loss chart PNGs for the window above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
