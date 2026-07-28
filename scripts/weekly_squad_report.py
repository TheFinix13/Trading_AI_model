"""ONE-COMMAND weekly review bundle for the v2 squad (shadow-paper).

The v2 counterpart of ``scripts/weekly_report.py`` (which reads the v1
zones agent's daily logs). Run ON THE VM once a week:

    python scripts/weekly_squad_report.py --days 7

It reads ``<live_dir>/events.jsonl`` (the same tape every dashboard
surface derives from) and writes ``weekly_squad_report_<start>_to_
<end>.zip`` into ``<live_dir>/reviews/`` -- the v2 twin of the v1
agent's ``<log_root>/reviews`` convention (override with ``--out``).
The zip contains:

* ``REPORT.md`` — executive summary (shots / tackles / goals / net
  pips / net R / mean TQS / bars evaluated), day-by-day match table,
  per-player week table, every resolved shadow trade, Sentinel block
  breakdown, system-health section (calendar/system_status rows,
  no-tape weekdays, warm-up state), and an auto-flagged review
  checklist.
* ``events_window.jsonl`` — the window's raw tape slice.
* ``state.json`` + ``poll_heartbeat.txt`` when present.

OBSERVATION-ONLY: reads files, writes one zip. Missing tape / days
degrade to notes in the report, never a crash. Provenance: shadow
paper activity on a demo data feed — no broker orders, not investment
performance.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agent.platform.config import load_config  # noqa: E402
from agent.platform.highlights import (  # noqa: E402
    _read_events, _row_day, match_report,
)

_WEEKDAY = 5  # Mon..Fri are < 5


def window_days(days: int | None, start: str | None,
                end: str | None) -> list[str]:
    """UTC YYYY-MM-DD strings for the requested window (inclusive)."""
    if start and end:
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
    else:
        d1 = datetime.now(timezone.utc).date()
        d0 = d1 - timedelta(days=(days or 7) - 1)
    if d1 < d0:
        d0, d1 = d1, d0
    out, d = [], d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _num(row: dict, key: str) -> float | None:
    v = row.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def aggregate_week(days: list[str], live_dir: Path) -> dict:
    """Weekly rollup, fully derived from the tape via match_report."""
    per_day, players, totals = [], {}, Counter()
    tqs_vals: list[float] = []
    r_total = 0.0
    r_seen = False
    for day in days:
        rep = match_report(day, live_dir)
        per_day.append(rep)
        ft = rep.get("full_time") or {}
        for k in ("shots", "tackles", "on_target", "resolved", "goals",
                  "misses", "ticks_evaluated"):
            totals[k] += int(ft.get(k) or 0)
        totals["net_pips_x10"] += int(round(float(ft.get("net_pips") or 0.0) * 10))
        if ft.get("net_r") is not None:
            r_total += float(ft["net_r"])
            r_seen = True
        if ft.get("mean_tqs") is not None and ft.get("resolved"):
            tqs_vals.extend([float(ft["mean_tqs"])] * int(ft["resolved"]))
        for p in rep.get("players") or []:
            agg = players.setdefault(p["agent"], {
                "agent": p["agent"], "name": p["name"], "shots": 0,
                "tackled": 0, "opens": 0, "resolved": 0, "goals": 0,
                "net_pips": 0.0,
            })
            for k in ("shots", "tackled", "opens", "resolved", "goals"):
                agg[k] += int(p.get(k) or 0)
            agg["net_pips"] = round(agg["net_pips"]
                                    + float(p.get("net_pips") or 0.0), 1)
    ranked = sorted(players.values(),
                    key=lambda d: (-d["resolved"], -d["shots"], d["agent"]))
    return {
        "per_day": per_day,
        "players": ranked,
        "totals": {
            **{k: totals[k] for k in ("shots", "tackles", "on_target",
                                      "resolved", "goals", "misses",
                                      "ticks_evaluated")},
            "net_pips": totals["net_pips_x10"] / 10.0,
            "net_r": round(r_total, 2) if r_seen else None,
            "mean_tqs": (round(sum(tqs_vals) / len(tqs_vals), 3)
                         if tqs_vals else None),
        },
    }


def issue_scan(rows: list[dict], days: list[str]) -> dict:
    """Auto-flag section inputs: system_status rows, Sentinel blocks,
    resolved trades, and weekday days with no tape at all."""
    day_set = set(days)
    in_window = [r for r in rows if _row_day(r) in day_set]
    sys_rows = [r for r in in_window if r.get("type") == "system_status"]
    sys_summary = Counter(
        (str(r.get("component") or "?"), str(r.get("status") or "?"))
        for r in sys_rows)
    blocks = Counter(
        (str(r.get("by") or "?"), str(r.get("reason") or "?"))
        for r in in_window if r.get("type") == "blocked")
    closes = [r for r in in_window
              if r.get("type") == "close" and _num(r, "pnl_pips") is not None]
    days_on_tape = {_row_day(r) for r in in_window}
    silent_weekdays = [
        d for d in days
        if d not in days_on_tape
        and date.fromisoformat(d).weekday() < _WEEKDAY]
    return {
        "system_status": sys_summary,
        "system_rows": sys_rows[-20:],
        "blocks": blocks,
        "closes": closes,
        "silent_weekdays": silent_weekdays,
    }


def _fmt_opt(v, spec: str = "") -> str:
    return format(v, spec) if v is not None else "—"


def render_report(days: list[str], week: dict, issues: dict,
                  live_dir: Path) -> str:
    t = week["totals"]
    lines = [
        f"# Weekly squad report — {days[0]} to {days[-1]} (v2, shadow paper)",
        "",
        "> PROVENANCE: shadow-paper activity from the v2 squad on a demo",
        "> data feed — no orders sent to any broker, NOT investment",
        "> performance. Past activity is not indicative of future results.",
        "",
        f"Tape: `{live_dir / 'events.jsonl'}`  ·  generated "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "## Executive summary",
        "",
        f"- Shots (proposals): **{t['shots']}**  ·  Sentinel tackles: "
        f"**{t['tackles']}**  ·  on target (opens): **{t['on_target']}**",
        f"- Resolved shadow trades: **{t['resolved']}** "
        f"({t['goals']} goals / {t['misses']} misses)",
        f"- Net: **{t['net_pips']:+.1f} pips**  ·  net R: "
        f"**{_fmt_opt(t['net_r'], '+.2f')}**  ·  mean TQS: "
        f"**{_fmt_opt(t['mean_tqs'])}**",
        f"- Bars evaluated: **{t['ticks_evaluated']}** across "
        f"{sum(1 for d in week['per_day'] if not d['empty'])} day(s) on tape",
        "",
        "## Day by day",
        "",
        "| Day | Headline |",
        "|---|---|",
    ]
    lines += [f"| {d['day']} | {d['headline']} |" for d in week["per_day"]]
    lines += ["", "## Players (week totals)", ""]
    if week["players"]:
        lines += [
            "| Player | Shots | Tackled | Opens | Resolved | Goals | Net pips |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {p['name']} | {p['shots']} | {p['tackled']} | {p['opens']} "
            f"| {p['resolved']} | {p['goals']} | {p['net_pips']:+.1f} |"
            for p in week["players"]
        ]
    else:
        lines.append("_No player activity on tape this window._")
    lines += ["", "## Resolved shadow trades", ""]
    if issues["closes"]:
        lines += [
            "| Time (UTC) | Player | Symbol | Pips | R | Exit |",
            "|---|---|---|---|---|---|",
        ]
        for r in issues["closes"]:
            lines.append(
                f"| {str(r.get('t') or '')[:16]} | {r.get('agent') or '?'} "
                f"| {str(r.get('symbol') or '').upper()} "
                f"| {float(r['pnl_pips']):+.1f} "
                f"| {_fmt_opt(_num(r, 'r'), '+.2f')} "
                f"| {r.get('exit_reason') or '—'} |")
    else:
        lines.append("_No shadow trades resolved this window._")
    lines += ["", "## Sentinel blocks", ""]
    if issues["blocks"]:
        lines += ["| Blocked by | Reason | Count |", "|---|---|---|"]
        lines += [f"| {by} | {reason} | {n} |"
                  for (by, reason), n in issues["blocks"].most_common()]
    else:
        lines.append("_No Sentinel blocks this window._")
    lines += ["", "## System health", ""]
    if issues["system_status"]:
        lines += ["| Component | Status | Rows |", "|---|---|---|"]
        lines += [f"| {c} | {s} | {n} |"
                  for (c, s), n in issues["system_status"].most_common()]
    else:
        lines.append("- No system_status rows — no infrastructure "
                     "complaints on tape.")
    if issues["silent_weekdays"]:
        lines.append(f"- **No tape at all on weekday(s): "
                     f"{', '.join(issues['silent_weekdays'])}** — was the "
                     "runtime down?")
    lines += ["", "## Review checklist", ""]
    flags: list[str] = []
    if issues["silent_weekdays"]:
        flags.append(f"[ ] Explain silent weekday(s) "
                     f"{', '.join(issues['silent_weekdays'])} (runtime "
                     "down / VM off / feed dead?).")
    cal_fail = sum(n for (c, s), n in issues["system_status"].items()
                   if s not in ("ok", "recovered"))
    if cal_fail:
        flags.append(f"[ ] {cal_fail} non-ok system_status row(s) -- check "
                     "the System health table (calendar fetch / cache "
                     "staleness).")
    if t["resolved"] and t["net_pips"] < 0:
        flags.append(f"[ ] Negative week ({t['net_pips']:+.1f}p over "
                     f"{t['resolved']} trades) -- read each close above "
                     "before drawing conclusions (small n).")
    if t["shots"] and not t["on_target"]:
        flags.append(f"[ ] {t['shots']} proposals but zero opens -- "
                     "review Sentinel blocks: over-gating or good defense?")
    if not flags:
        flags.append("[x] Nothing auto-flagged. Quiet weeks are normal on "
                     "an H4 squad.")
    lines += [f"- {f}" for f in flags]
    lines.append("")
    return "\n".join(lines)


def write_bundle(zip_path: Path, report: str, rows: list[dict],
                 days: list[str], live_dir: Path) -> None:
    day_set = set(days)
    window_rows = [r for r in rows if _row_day(r) in day_set]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("REPORT.md", report)
        zf.writestr("events_window.jsonl",
                    "\n".join(json.dumps(r) for r in window_rows))
        for name in ("state.json", "poll_heartbeat.txt"):
            p = live_dir / name
            if p.is_file():
                try:
                    zf.writestr(name, p.read_text(encoding="utf-8"))
                except OSError:
                    pass


def main() -> None:
    cfg = load_config(REPO_ROOT)
    ap = argparse.ArgumentParser(
        description="Weekly v2 squad review bundle (observation-only).")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--start", help="YYYY-MM-DD (with --end)")
    ap.add_argument("--end", help="YYYY-MM-DD (with --start)")
    ap.add_argument("--live-dir", type=Path, default=Path(cfg["live_dir"]))
    ap.add_argument("--out", type=Path, default=None,
                    help="zip path (default: <live_dir>/reviews/"
                         "weekly_squad_report_<start>_to_<end>.zip -- the "
                         "v2 twin of v1's <log_root>/reviews convention)")
    ap.add_argument("--no-zip", action="store_true",
                    help="print REPORT.md to stdout only")
    args = ap.parse_args()

    days = window_days(args.days, args.start, args.end)
    rows = _read_events(args.live_dir)
    week = aggregate_week(days, args.live_dir)
    issues = issue_scan(rows, days)
    report = render_report(days, week, issues, args.live_dir)

    if args.no_zip:
        print(report)
        return
    out = args.out
    if out is None:
        # Default next to the tape it summarizes: <live_dir>/reviews/,
        # the v2 twin of the v1 agent's <log_root>/reviews convention.
        reviews = args.live_dir / "reviews"
        try:
            reviews.mkdir(parents=True, exist_ok=True)
        except OSError:
            reviews = Path(".")  # fall back to CWD rather than crash
        out = reviews / f"weekly_squad_report_{days[0]}_to_{days[-1]}.zip"
    write_bundle(out, report, rows, days, args.live_dir)
    print(f"Wrote {out}  ({out.stat().st_size} bytes)")
    print("Sections: summary, day-by-day, players, trades, Sentinel "
          "blocks, system health, checklist.")


if __name__ == "__main__":
    main()
