"""F020 -- Public `/highlights` data plane: match reports from the tape.

Retells the squad's recorded shadow-paper activity as daily "match
reports". Every line is derived from rows already on tape in
``<live_dir>/events.jsonl`` -- the same file the F001 performance
module and F002 players module read, so the three surfaces can never
disagree about what happened.

Row types consumed (same schema family as ``squad_events`` emits and
F001/F002 parse; unknown types are ignored so the file can grow):

* ``propose`` / ``proposal`` -- an agent published a trade intent.
* ``blocked``                -- a proposal was tackled by a peer or
                                turned away by a Sentinel rule.
* ``open``                   -- a proposal was executed (shadow fill).
* ``close``                  -- the trade resolved; carries pnl_pips,
                                r, tqs, exit_reason.
* ``tick_summary``           -- one row per evaluated H4 bar; proof of
                                life on quiet days.

Agent identifiers ride ``agent`` (live-loop dumps) or ``agent_id``
(older caches); timestamps ride ``t`` or ``timestamp`` -- both
variants are accepted, matching ``players._row_agent_key``.

Narrative strings are deterministic template assembly ONLY -- no LLM,
no external calls. The Blue Lock metaphor voice is used; the Brand
banned words ("ensemble", "aggregator") never appear in any template.

Read-only invariant: nothing under ``live_dir`` is written to.
Malformed rows and missing files degrade to empty payloads, never an
exception (F005 contract).

Provenance: every number this module emits is a shadow-paper
activity/quality metric from the v2 squad's demo feed -- NOT profit
performance. See :data:`PROVENANCE_NOTE`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from agent.platform import players

# Rendered verbatim on the /highlights page banner and echoed in every
# payload, same provenance-labelling posture as /performance.
PROVENANCE_NOTE = (
    "Shadow-paper activity and quality metrics from the v2 squad "
    "(demo data feed, no orders sent to any broker) -- NOT profit "
    "performance. Past activity is not indicative of future results."
)

# I002 quiet-reason vocabulary (mirrors paper_loop._quiet_reason's
# no-setup line) so a quiet match day reads the same as the /v2 badge.
QUIET_VOCAB = (
    "no scheduled events in window and no fresh setups -- "
    "evaluating quietly"
)

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PROPOSAL_TYPES = ("propose", "proposal")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")


def _read_events(live_dir: Path | str | None) -> list[dict]:
    """Every parseable row of ``<live_dir>/events.jsonl``.

    Missing dir/file -> ``[]``; malformed JSON rows are skipped
    defensively (same posture as ``players._read_events``).
    """
    if live_dir is None:
        return []
    live = Path(live_dir)
    events_file = live / "events.jsonl"
    if not live.is_dir() or not events_file.is_file():
        return []
    rows: list[dict] = []
    try:
        with events_file.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def _row_ts(row: dict) -> str:
    return str(row.get("t") or row.get("timestamp") or "")


def _row_day(row: dict) -> str:
    return _row_ts(row)[:10]


def _row_agent(row: dict) -> str:
    return str(row.get("agent") or row.get("agent_id") or "").strip()


_NAME_BY_KEY: dict[str, str] = {
    r["agent_key"]: r["name"] for r in players.roster_meta()
}


def _display_name(agent_key: str) -> str:
    return _NAME_BY_KEY.get(agent_key, agent_key or "Unknown")


def _clock(ts: str) -> str:
    """``HH:MM`` UTC wall-clock label for a timeline line -- honest
    timestamps rather than invented match minutes."""
    return ts[11:16] if len(ts) >= 16 else "--:--"


def _num(row: dict, key: str) -> float | None:
    v = row.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def _fmt_r(r: float | None) -> str:
    return f"{r:+.2f}R" if r is not None else "R n/a"


def trade_id_for(close_row: dict) -> str:
    """Deterministic id for one close row: ``<agent>-<ts-compact>-<sym>``.

    Derived purely from recorded fields so the same tape always yields
    the same ids (click-through stays stable across restarts).
    """
    ts = _row_ts(close_row).replace(":", "").replace("-", "")
    sym = str(close_row.get("symbol") or "").upper()
    return f"{_row_agent(close_row)}-{ts}-{sym}"


def _day_rows(rows: list[dict], day: str) -> list[dict]:
    picked = [r for r in rows if _row_day(r) == day]
    picked.sort(key=_row_ts)
    return picked


# ---------------------------------------------------------------------
# Narrative templating (deterministic; Brand-swept -- no banned words)
# ---------------------------------------------------------------------

def _line_for(row: dict) -> str | None:
    """One narrative line per event row; None for rows the report skips
    (tick_summary rows are summarised, not itemised)."""
    kind = row.get("type")
    clock = _clock(_row_ts(row))
    name = _display_name(_row_agent(row))
    sym = str(row.get("symbol") or "?").upper()
    if kind in _PROPOSAL_TYPES:
        direction = str(row.get("dir") or row.get("direction") or "?").lower()
        conv = _num(row, "conviction")
        conv_txt = f" (conviction {conv:.2f})" if conv is not None else ""
        return (f"{clock}' {name} spots a {direction} opening on "
                f"{sym}{conv_txt}.")
    if kind == "blocked":
        reason = str(row.get("reason") or "?")
        if row.get("rule"):
            return (f"{clock}' The wall holds -- Sentinel turns away "
                    f"{name}'s {sym} attempt ({reason}).")
        winner = _display_name(str(row.get("by") or "?"))
        return (f"{clock}' {winner} tackles {name} -- one ball, one "
                f"shooter on {sym}.")
    if kind == "open":
        direction = str(row.get("dir") or row.get("direction") or "?").lower()
        return f"{clock}' Shot on target -- {name} goes {direction} on {sym}."
    if kind == "close":
        pips = _num(row, "pnl_pips")
        r = _num(row, "r")
        reason = str(row.get("exit_reason") or "?")
        pips_txt = f"{pips:+.1f}p" if pips is not None else "pips n/a"
        if pips is not None and pips > 0:
            return (f"{clock}' GOAL! {name}'s {sym} run banks {pips_txt} "
                    f"({_fmt_r(r)}, {reason}).")
        return (f"{clock}' Saved -- {name}'s {sym} shot closes {pips_txt} "
                f"({_fmt_r(r)}, {reason}).")
    return None


def _full_time(day_rows: list[dict]) -> dict:
    """Recomputable full-time stat line for one day's rows."""
    proposals = [r for r in day_rows if r.get("type") in _PROPOSAL_TYPES]
    tackles = [r for r in day_rows if r.get("type") == "blocked"]
    opens = [r for r in day_rows if r.get("type") == "open"]
    closes = [r for r in day_rows if r.get("type") == "close"
              and _num(r, "pnl_pips") is not None]
    ticks = [r for r in day_rows if r.get("type") == "tick_summary"]
    goals = sum(1 for r in closes if float(r["pnl_pips"]) > 0)
    net_pips = round(sum(float(r["pnl_pips"]) for r in closes), 1)
    r_vals = [v for r in closes if (v := _num(r, "r")) is not None]
    tqs_vals = [v for r in closes if (v := _num(r, "tqs")) is not None]
    return {
        "shots": len(proposals),
        "tackles": len(tackles),
        "on_target": len(opens),
        "resolved": len(closes),
        "goals": goals,
        "misses": len(closes) - goals,
        "net_pips": net_pips,
        "net_r": round(sum(r_vals), 2) if r_vals else None,
        "mean_tqs": (round(sum(tqs_vals) / len(tqs_vals), 3)
                     if tqs_vals else None),
        "ticks_evaluated": len(ticks),
    }


def _headline(day: str, ft: dict, quiet: bool) -> str:
    if quiet:
        return (f"{day}: quiet match -- {ft['ticks_evaluated']} bars "
                f"evaluated, no shots taken.")
    goal_word = "goal" if ft["goals"] == 1 else "goals"
    pips_txt = (f"{ft['net_pips']:+.1f}p net" if ft["resolved"]
                else "no trades resolved")
    return (f"{day}: {ft['shots']} shots, {ft['on_target']} on target, "
            f"{ft['goals']} {goal_word} -- {pips_txt}.")


def _players_involved(day_rows: list[dict]) -> list[dict]:
    per: dict[str, dict] = {}

    def rec(key: str) -> dict:
        return per.setdefault(key, {
            "agent": key, "name": _display_name(key),
            "shots": 0, "tackled": 0, "opens": 0,
            "resolved": 0, "goals": 0, "net_pips": 0.0,
        })

    for r in day_rows:
        kind = r.get("type")
        key = _row_agent(r)
        if not key:
            continue
        if kind in _PROPOSAL_TYPES:
            rec(key)["shots"] += 1
        elif kind == "blocked":
            rec(key)["tackled"] += 1
        elif kind == "open":
            rec(key)["opens"] += 1
        elif kind == "close" and _num(r, "pnl_pips") is not None:
            d = rec(key)
            d["resolved"] += 1
            d["net_pips"] += float(r["pnl_pips"])
            if float(r["pnl_pips"]) > 0:
                d["goals"] += 1
    out = sorted(per.values(), key=lambda d: (-d["resolved"], -d["shots"],
                                              d["agent"]))
    for d in out:
        d["net_pips"] = round(d["net_pips"], 1)
    return out


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def match_report(day: str, live_dir: Path | str | None = None) -> dict:
    """One day's narrative match report, fully derived from the tape.

    ``day`` is a UTC ``YYYY-MM-DD`` string. Unknown/invalid days and a
    missing tape degrade to an ``empty=True`` payload -- never raise.
    """
    day = str(day or "").strip()
    if not _DAY_RE.match(day):
        return {
            "day": day, "empty": True, "quiet": False,
            "headline": "That's not a match day -- use YYYY-MM-DD.",
            "timeline": [], "full_time": None, "players": [],
            "provenance": PROVENANCE_NOTE, "generated_at": _now_iso(),
        }
    rows = _day_rows(_read_events(live_dir), day)
    if not rows:
        return {
            "day": day, "empty": True, "quiet": False,
            "headline": f"{day}: no tape on record for this day.",
            "timeline": [], "full_time": None, "players": [],
            "provenance": PROVENANCE_NOTE, "generated_at": _now_iso(),
        }
    ft = _full_time(rows)
    quiet = (ft["shots"] == 0 and ft["on_target"] == 0
             and ft["resolved"] == 0)
    timeline: list[dict] = []
    for r in rows:
        line = _line_for(r)
        if line is None:
            continue
        item = {
            "t": _row_ts(r),
            "type": ("proposal" if r.get("type") in _PROPOSAL_TYPES
                     else str(r.get("type"))),
            "agent": _row_agent(r),
            "symbol": str(r.get("symbol") or "").upper() or None,
            "line": line,
        }
        if r.get("type") == "close":
            item["trade_id"] = trade_id_for(r)
            if _num(r, "pnl_pips") is not None:
                item["pnl_pips"] = round(float(r["pnl_pips"]), 1)
            if _num(r, "r") is not None:
                item["r"] = float(r["r"])
        timeline.append(item)
    quiet_note = None
    if quiet:
        syms = sorted({str(r.get("symbol") or "").upper()
                       for r in rows if r.get("symbol")})
        quiet_note = (
            f"{ft['ticks_evaluated']} bars evaluated"
            + (f" across {', '.join(syms)}" if syms else "")
            + f" -- {QUIET_VOCAB}."
        )
    return {
        "day": day,
        "empty": False,
        "quiet": quiet,
        "quiet_note": quiet_note,
        "headline": _headline(day, ft, quiet),
        "timeline": timeline,
        "full_time": ft,
        "players": _players_involved(rows),
        "provenance": PROVENANCE_NOTE,
        "generated_at": _now_iso(),
    }


def list_reports(n: int = 14, live_dir: Path | str | None = None) -> list[dict]:
    """Newest-first index of match days present on tape.

    Each entry carries the day, the one-line headline, and the key
    full-time stats -- enough for the index cards without a per-day
    fetch. ``n`` is clamped to [1, 60].
    """
    n = max(1, min(int(n), 60))
    rows = _read_events(live_dir)
    days = sorted({d for r in rows if (d := _row_day(r))}, reverse=True)
    out: list[dict] = []
    for day in days[:n]:
        day_rows = _day_rows(rows, day)
        ft = _full_time(day_rows)
        quiet = (ft["shots"] == 0 and ft["on_target"] == 0
                 and ft["resolved"] == 0)
        out.append({
            "day": day,
            "quiet": quiet,
            "headline": _headline(day, ft, quiet),
            "shots": ft["shots"],
            "goals": ft["goals"],
            "resolved": ft["resolved"],
            "net_pips": ft["net_pips"],
        })
    return out


def trade_story(trade_id: str, live_dir: Path | str | None = None) -> dict | None:
    """Retell one closed trade: opening seen -> gate path -> outcome.

    ``trade_id`` is the deterministic id :func:`trade_id_for` derives
    from a close row. Unknown id -> ``None`` (route 404s). Chapters
    are stitched from the latest same-agent same-symbol proposal and
    open rows at or before the close -- all recorded evidence, no
    invention.
    """
    rows = _read_events(live_dir)
    rows.sort(key=_row_ts)
    close = next(
        (r for r in rows
         if r.get("type") == "close" and trade_id_for(r) == str(trade_id)),
        None,
    )
    if close is None:
        return None
    agent = _row_agent(close)
    sym = str(close.get("symbol") or "").upper()
    close_ts = _row_ts(close)

    def _latest(kind_test) -> dict | None:
        prior = [r for r in rows
                 if kind_test(r.get("type")) and _row_agent(r) == agent
                 and str(r.get("symbol") or "").upper() == sym
                 and _row_ts(r) <= close_ts]
        return prior[-1] if prior else None

    proposal = _latest(lambda k: k in _PROPOSAL_TYPES)
    opened = _latest(lambda k: k == "open")
    chapters: list[dict] = []
    for label, row in (("the opening", proposal), ("the shot", opened),
                       ("full time", close)):
        if row is None:
            continue
        chapters.append({
            "label": label,
            "t": _row_ts(row),
            "line": _line_for(row),
        })
    pips = _num(close, "pnl_pips")
    return {
        "trade_id": str(trade_id),
        "agent": agent,
        "name": _display_name(agent),
        "symbol": sym,
        "goal": bool(pips is not None and pips > 0),
        "pnl_pips": round(pips, 1) if pips is not None else None,
        "r": _num(close, "r"),
        "tqs": _num(close, "tqs"),
        "exit_reason": close.get("exit_reason"),
        "chapters": chapters,
        "provenance": PROVENANCE_NOTE,
        "generated_at": _now_iso(),
    }
