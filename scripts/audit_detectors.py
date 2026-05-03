"""Detector precision audit.

Q: Is the bot failing because ICT concepts are wrong, or because it's noisy?

This script answers that empirically by:

  1. Loading every signal the agent journaled in a window.
  2. Joining each signal to its outcome (the trade it produced, if any).
  3. Computing per-confluence-tag and per-confluence-combination win rate,
     average pip P&L, and trade count.
  4. Optionally cross-referencing against the user's discretionary trades
     (`human_lessons` table) to show which detector signatures fired on
     YOUR wins vs the agent's losses.

Output: a CLI table you can copy into the roadmap, plus a JSON sidecar.

Usage:
    PYTHONPATH=. python scripts/audit_detectors.py \
        --agent-db data/agent_week_2026_W18.db \
        --human-db data/journal.db \
        --start 2026-04-27 --end 2026-05-02 \
        --out tmp/weekly_log_2026_W18/audit.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from statistics import mean


def _load_agent_rows(db: Path, start: str | None, end: str | None) -> list[dict]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    sql = (
        "SELECT s.id AS signal_id, s.detected_at, s.timeframe, s.direction, "
        "s.confluences, s.confluence_tfs_json, s.ml_score, s.decision, "
        "t.id AS trade_id, t.entry_price, t.exit_price, t.exit_reason, "
        "t.pnl, t.pnl_pips "
        "FROM signals s INNER JOIN trades t ON t.signal_id = s.id "
        "WHERE 1=1"
    )
    args: list = []
    if start:
        sql += " AND t.entry_time >= ?"; args.append(start)
    if end:
        sql += " AND t.entry_time < ?"; args.append(end)
    sql += " ORDER BY t.entry_time"
    rows = []
    for r in con.execute(sql, args).fetchall():
        d = dict(r)
        try:
            d["confluences_list"] = json.loads(d.get("confluences") or "[]")
        except Exception:
            d["confluences_list"] = []
        try:
            d["confluence_tfs"] = json.loads(d.get("confluence_tfs_json") or "{}")
        except Exception:
            d["confluence_tfs"] = {}
        rows.append(d)
    con.close()
    return rows


def _load_human_rows(db: Path, start: str | None, end: str | None) -> list[dict]:
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    # Some DBs (the agent's per-run journal) won't have the human_lessons table.
    has_table = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='human_lessons'"
    ).fetchone()
    if not has_table:
        con.close()
        return []
    sql = "SELECT * FROM human_lessons"
    args: list = []
    clauses = []
    if start:
        clauses.append("trade_date >= ?"); args.append(start)
    if end:
        clauses.append("trade_date < ?"); args.append(end)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY trade_date, id"
    rows = []
    for r in con.execute(sql, args).fetchall():
        d = dict(r)
        try:
            d["confluences_list"] = [c.get("type") for c in
                                      json.loads(d.get("confluences_json") or "[]")]
        except Exception:
            d["confluences_list"] = []
        rows.append(d)
    con.close()
    return rows


# ---------------------------------------------------------------- analysis ---


def per_tag_stats(rows: list[dict]) -> list[dict]:
    """For every confluence tag, compute fire-count, win-rate, avg pip, total pip."""
    bucket: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for tag in r.get("confluences_list") or []:
            bucket[tag].append(r)
    out: list[dict] = []
    for tag, trades in bucket.items():
        scored = [t for t in trades if t.get("pnl_pips") is not None]
        if not scored:
            continue
        wins = sum(1 for t in scored if (t["pnl_pips"] or 0) > 0)
        out.append({
            "tag": tag,
            "n": len(scored),
            "wins": wins,
            "wr": round(100 * wins / len(scored), 1),
            "avg_pips": round(mean(t["pnl_pips"] for t in scored), 1),
            "total_pips": round(sum(t["pnl_pips"] for t in scored), 1),
        })
    out.sort(key=lambda x: x["total_pips"], reverse=True)
    return out


def per_combo_stats(rows: list[dict], k: int = 2, min_n: int = 2) -> list[dict]:
    """Pairwise/triple confluence combos. Surfaces 'ICT-flavoured signatures'."""
    bucket: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for r in rows:
        tags = sorted(set(r.get("confluences_list") or []))
        for combo in combinations(tags, k):
            bucket[combo].append(r)
    out: list[dict] = []
    for combo, trades in bucket.items():
        scored = [t for t in trades if t.get("pnl_pips") is not None]
        if len(scored) < min_n:
            continue
        wins = sum(1 for t in scored if (t["pnl_pips"] or 0) > 0)
        out.append({
            "combo": list(combo),
            "n": len(scored),
            "wins": wins,
            "wr": round(100 * wins / len(scored), 1),
            "avg_pips": round(mean(t["pnl_pips"] for t in scored), 1),
            "total_pips": round(sum(t["pnl_pips"] for t in scored), 1),
        })
    out.sort(key=lambda x: x["total_pips"], reverse=True)
    return out


def per_hour_stats(rows: list[dict], tz_name: str = "America/New_York") -> list[dict]:
    """Group trades by entry hour in the user's chart timezone (default NY).

    The ICT/SMC framework gives huge weight to specific hours (London 08:00 NY,
    NY 09:30 NY, the 13:30-15:00 ET 'NY lunch fade', etc.). We compute precision
    per hour so we can build a `blocked_hours_ny` config off real evidence.
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        return []
    bucket: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        ts = r.get("entry_time") or r.get("detected_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            local = dt.astimezone(tz)
            bucket[local.hour].append(r)
        except Exception:
            continue
    out: list[dict] = []
    for hour in sorted(bucket):
        trades = bucket[hour]
        scored = [t for t in trades if t.get("pnl_pips") is not None]
        if not scored:
            continue
        wins = sum(1 for t in scored if (t["pnl_pips"] or 0) > 0)
        out.append({
            "hour_ny": hour,
            "n": len(scored),
            "wins": wins,
            "wr": round(100 * wins / len(scored), 1),
            "avg_pips": round(mean(t["pnl_pips"] for t in scored), 1),
            "total_pips": round(sum(t["pnl_pips"] for t in scored), 1),
        })
    return out


def signature_overlap(agent_rows: list[dict], human_rows: list[dict]) -> dict:
    """Return tags that fire on the user's wins. These are the "right" signals
    that the agent should bias toward."""
    agent_tag_freq = Counter()
    for r in agent_rows:
        for t in r.get("confluences_list") or []:
            agent_tag_freq[t] += 1
    human_tag_freq = Counter()
    for r in human_rows:
        for t in r.get("confluences_list") or []:
            human_tag_freq[t] += 1
    return {
        "agent_top": agent_tag_freq.most_common(20),
        "human_top": human_tag_freq.most_common(20),
        "human_only": sorted(set(human_tag_freq) - set(agent_tag_freq)),
        "agent_only": sorted(set(agent_tag_freq) - set(human_tag_freq))[:25],
    }


# ---------------------------------------------------------------- printers ---


def _hr(width: int = 92) -> str:
    return "-" * width


def print_tag_table(rows: list[dict], title: str) -> None:
    print(_hr())
    print(title)
    print(_hr())
    print(f"{'tag':<28s} {'n':>4s} {'wins':>5s} {'wr%':>6s} {'avg_pips':>9s} {'total_pips':>11s}  verdict")
    print(_hr())
    for r in rows[:25]:
        verdict = ""
        if r["n"] >= 3 and r["wr"] >= 60 and r["total_pips"] > 0:
            verdict = "KEEP — high precision"
        elif r["n"] >= 3 and r["wr"] <= 35 and r["total_pips"] < 0:
            verdict = "DROP / gate harder"
        elif r["total_pips"] < -30:
            verdict = "REVIEW — bleeds pips"
        print(f"{r['tag']:<28s} {r['n']:>4d} {r['wins']:>5d} {r['wr']:>6.1f} "
              f"{r['avg_pips']:>+9.1f} {r['total_pips']:>+11.1f}  {verdict}")


def print_combo_table(rows: list[dict], title: str, top: int = 15) -> None:
    print(_hr())
    print(title)
    print(_hr())
    print(f"{'combo':<60s} {'n':>4s} {'wr%':>6s} {'total_pips':>11s}")
    print(_hr())
    for r in rows[:top]:
        combo_s = " + ".join(r["combo"])
        if len(combo_s) > 58:
            combo_s = combo_s[:55] + "..."
        print(f"{combo_s:<60s} {r['n']:>4d} {r['wr']:>6.1f} {r['total_pips']:>+11.1f}")


# ---------------------------------------------------------------- main -------


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--agent-db", required=True)
    p.add_argument("--human-db", default=None)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    agent_rows = _load_agent_rows(Path(args.agent_db), args.start, args.end)
    human_rows = _load_human_rows(Path(args.human_db) if args.human_db else Path("/dev/null"),
                                   args.start, args.end)

    print(f"Loaded {len(agent_rows)} agent trades, {len(human_rows)} human trades.")
    print()

    by_tag = per_tag_stats(agent_rows)
    print_tag_table(by_tag, "AGENT — per-confluence-tag precision (sorted by total pips)")
    print()

    by_pair = per_combo_stats(agent_rows, k=2, min_n=2)
    print_combo_table(by_pair, "AGENT — best 2-tag signatures (combos that actually pay)")
    print()

    by_triple = per_combo_stats(agent_rows, k=3, min_n=2)
    print_combo_table(by_triple, "AGENT — best 3-tag signatures (high-conviction stack)", top=10)
    print()

    by_hour = per_hour_stats(agent_rows)
    if by_hour:
        print(_hr())
        print("AGENT — per-hour-of-day (NY local time)")
        print(_hr())
        print(f"{'hr':>3s}  {'n':>4s} {'wins':>5s} {'wr%':>6s} {'avg_pips':>9s} {'total_pips':>11s}  verdict")
        print(_hr())
        for r in by_hour:
            verdict = ""
            if r["n"] >= 3 and r["wr"] <= 30 and r["total_pips"] < -20:
                verdict = "BLOCK — chop hour"
            elif r["n"] >= 3 and r["wr"] >= 65 and r["total_pips"] > 20:
                verdict = "BOOST — kill zone"
            print(f"{r['hour_ny']:>3d}  {r['n']:>4d} {r['wins']:>5d} {r['wr']:>6.1f} "
                  f"{r['avg_pips']:>+9.1f} {r['total_pips']:>+11.1f}  {verdict}")
        print()

    overlap = signature_overlap(agent_rows, human_rows)
    print(_hr())
    print("SIGNATURE OVERLAP (what the user reads vs what the agent reads)")
    print(_hr())
    print("HUMAN top tags          :", overlap["human_top"])
    print("AGENT top tags (this wk):", overlap["agent_top"][:8])
    print("Tags the HUMAN uses but the agent never fired this week:",
          overlap["human_only"] or "(none)")
    print()

    if args.out:
        out = {
            "agent_trade_count": len(agent_rows),
            "human_trade_count": len(human_rows),
            "per_tag": by_tag,
            "best_pairs": by_pair[:25],
            "best_triples": by_triple[:25],
            "per_hour_ny": by_hour,
            "overlap": overlap,
        }
        Path(args.out).write_text(json.dumps(out, indent=2))
        print(f"JSON written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
