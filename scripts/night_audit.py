"""Night Auditor (Ego Jinpachi) -- daily tape audit, observe-and-draft only.

Reads ONE UTC day of the squad's own tape (events.jsonl + proposals +
trades + state.json) and answers the question the liveness watchdog
cannot: "did yesterday MAKE SENSE?". The three P0s of Jul/Aug 2026
(silent week, crash-loop, feed starvation) were all visible on the
tape for days before a human read it -- this is the shift that reads
it every morning.

Hard rules (company/strategy/company-offhours-shifts-proposal.md,
Tier 1):
  * NEVER mutates squad state, config, or git. Writes only under
    <live_dir>/audits/.
  * One page per day maximum, via the existing watchdog_alert ops
    route (no new alert event types).
  * Anomalies become intake STUBS (drafts for the next session's
    triage), never ledger entries.

Usage:
    python scripts/night_audit.py                 # audits yesterday UTC
    python scripts/night_audit.py --date 2026-08-03
    python scripts/night_audit.py --json --no-telegram   # tests / dry runs
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.platform import alerts  # noqa: E402

# H4 close grid observed on the current feed (runbook 7b.9 step 3).
EXPECTED_H4_CLOSES_UTC = (3, 7, 11, 15, 19, 23)
SYMBOLS_DEFAULT = ("EURUSD", "GBPUSD", "USDCAD")

# Weekday -> minimum tick_summary rows per symbol before warn/alarm.
# Fri closes early (no 23 UTC bar), Sun opens late (23 UTC bar only),
# Sat is closed. Floors are deliberately forgiving -- the auditor's
# job is catching ZERO/starved days, not nagging about one lost bar.
_WEEKDAY_FLOORS = {  # (warn_below, alarm_at_or_below)
    0: (5, 0), 1: (5, 0), 2: (5, 0), 3: (5, 0),  # Mon-Thu
    4: (4, 0),                                    # Fri
    5: (0, -1),                                   # Sat: nothing expected
    6: (0, -1),                                   # Sun: 23:00 bar optional
}


def _parse_ts(row: dict) -> datetime | None:
    for key in ("timestamp", "entry_time", "opened_at", "time"):
        v = row.get(key)
        if not v:
            continue
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _read_jsonl_window(path: Path, day_start: datetime,
                       day_end: datetime) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = _parse_ts(row)
        if ts is not None and day_start <= ts < day_end:
            rows.append(row)
    return rows


def audit_day(live_dir: Path, day: datetime,
              symbols: tuple[str, ...] = SYMBOLS_DEFAULT) -> dict:
    """Pure audit pass over one UTC day of tape. Returns the full
    result dict (checks + counts); does no I/O beyond reading."""
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0,
                            tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    events = _read_jsonl_window(live_dir / "events.jsonl", day_start, day_end)
    proposals = _read_jsonl_window(
        live_dir / "proposals_all.jsonl", day_start, day_end)
    trades = _read_jsonl_window(live_dir / "trades.jsonl", day_start, day_end)

    ticks = [r for r in events if r.get("type") == "tick_summary"]
    sys_rows = [r for r in events if r.get("type") == "system_status"]

    checks: list[dict] = []

    # 1) Tape coverage per symbol vs the weekday H4 grid. THE silent-
    #    week catcher: a weekday with zero rows is an alarm on day one.
    warn_below, alarm_at = _WEEKDAY_FLOORS[day_start.weekday()]
    for sym in symbols:
        n = sum(1 for r in ticks if r.get("symbol") == sym)
        if n <= alarm_at:
            status = "alarm"
        elif n < warn_below:
            status = "warn"
        else:
            status = "ok" if warn_below else "na"
        checks.append({
            "id": f"tape_coverage_{sym}", "status": status,
            "detail": f"{n} tick_summary rows (weekday floor {warn_below})",
        })

    # 2) timestamp_miss regression (I024 pin on the tape itself).
    miss = 0
    for r in ticks:
        for t in r.get("thoughts_top5") or []:
            if "timestamp_miss" in str(t.get("narrative", "")):
                miss += 1
                break
    checks.append({
        "id": "timestamp_miss", "status": "alarm" if miss else "ok",
        "detail": f"{miss} tick(s) with timestamp_miss narratives",
    })

    # 3) Feed health from system_status rows (I028 instrumentation).
    stale = [r for r in sys_rows if r.get("status") == "stale"]
    streaks = [int(r.get("failure_streak") or 0) for r in sys_rows
               if r.get("status") == "refresh_error"]
    worst_streak = max(streaks, default=0)
    if stale:
        f_status, f_detail = "alarm", f"{len(stale)} stale event(s)"
    elif worst_streak >= 3:
        f_status = "warn"
        f_detail = f"refresh_error streak reached {worst_streak}"
    else:
        f_status = "ok"
        f_detail = (f"{len(sys_rows)} system_status rows, "
                    f"worst refresh streak {worst_streak}")
    checks.append({"id": "feed_health", "status": f_status,
                   "detail": f_detail})

    # 4) Activity readout (quiet is legal; this is context, not alarm).
    checks.append({
        "id": "activity", "status": "ok",
        "detail": (f"{len(proposals)} proposals, {len(trades)} trades, "
                   f"{len(ticks)} ticks"),
    })

    # 5) state.json cursor readout (realtime freshness belongs to the
    #    5-min watchdog; the auditor just records where the day ended).
    state_detail = "state.json missing"
    try:
        state = json.loads((live_dir / "state.json").read_text())
        lbt = state.get("last_bar_times") or {}
        state_detail = ", ".join(
            f"{s}={str(v)[:16]}" for s, v in sorted(lbt.items())) or "no cursor"
    except (OSError, json.JSONDecodeError):
        pass
    checks.append({"id": "state_cursor", "status": "ok",
                   "detail": state_detail})

    worst = "ok"
    for c in checks:
        if c["status"] == "alarm":
            worst = "alarm"
            break
        if c["status"] == "warn":
            worst = "warn"
    return {
        "audit_day": day_start.date().isoformat(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "overall": worst,
        "checks": checks,
    }


def render_digest(result: dict) -> str:
    lines = [
        f"# Night audit — {result['audit_day']} "
        f"(overall: {result['overall'].upper()})",
        "",
        f"Generated {result['generated_at']} by the Night Auditor "
        "(Ego Jinpachi persona; observe-and-draft only).",
        "",
    ]
    for c in result["checks"]:
        lines.append(f"- [{c['status']:>5}] `{c['id']}` — {c['detail']}")
    return "\n".join(lines) + "\n"


def write_outputs(live_dir: Path, result: dict) -> Path:
    """Digest + intake stubs under <live_dir>/audits/. Returns digest path."""
    audits = live_dir / "audits"
    audits.mkdir(parents=True, exist_ok=True)
    tag = result["audit_day"].replace("-", "")
    digest = audits / f"night_audit_{tag}.md"
    digest.write_text(render_digest(result), encoding="utf-8")

    stubs = audits / "stubs"
    for c in result["checks"]:
        if c["status"] not in ("warn", "alarm"):
            continue
        stubs.mkdir(parents=True, exist_ok=True)
        stub = stubs / f"{tag}_{c['id']}.md"
        stub.write_text(
            f"# DRAFT intake stub — {c['id']} ({c['status']})\n\n"
            f"Audit day: {result['audit_day']}\n"
            f"Detail: {c['detail']}\n\n"
            "Filed automatically by the Night Auditor. Triage in the "
            "next session: confirm, assign an I-number in "
            "company/rd/intake/, or dismiss with a note here.\n",
            encoding="utf-8")
    return digest


def notify(result: dict) -> None:
    """One watchdog_alert bus event per audit (ops Telegram when wired)."""
    anomalies = [c for c in result["checks"]
                 if c["status"] in ("warn", "alarm")]
    if anomalies:
        detail = "; ".join(f"{c['id']}={c['status']}" for c in anomalies)
        text = f"{len(anomalies)} anomalie(s): {detail}"
    else:
        text = "all nominal"
    alerts.publish("watchdog_alert", {
        "check": "night_audit",
        "status": result["overall"],
        "detail": f"tape audit {result['audit_day']}: {text}",
        "recovered": False,
    })


def main(argv: list[str] | None = None) -> int:
    from agent.platform.config import load_config
    cfg = load_config(REPO_ROOT)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live-dir", type=Path, default=cfg["live_dir"])
    ap.add_argument("--date", default=None,
                    help="UTC day to audit (YYYY-MM-DD); default yesterday")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-telegram", action="store_true")
    args = ap.parse_args(argv)

    if args.date:
        day = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)
    else:
        day = datetime.now(tz=timezone.utc) - timedelta(days=1)

    result = audit_day(Path(args.live_dir), day)
    digest = write_outputs(Path(args.live_dir), result)

    if not args.no_telegram:
        from scripts.run_watchdog import _configure_telegram
        _configure_telegram(cfg)
        notify(result)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_digest(result))
        print(f"digest: {digest}")
    return {"ok": 0, "warn": 1, "alarm": 2}.get(result["overall"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
