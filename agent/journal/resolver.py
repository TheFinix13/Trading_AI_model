"""Near-miss resolution — score the hypothetical outcome of vaulted events.

Given a near-miss event (the hypothetical entry/SL/TP the gate or guard
blocked) and the bar series, walk forward from the event bar and decide
whether the hypothetical trade would have hit SL or TP first. Conservative
tie-break: if BOTH levels fall inside one bar, count it as a stop-out
(intrabar path is unknowable; assume the worst).

This is HYPOTHESIS-GENERATING evidence only. A reason tag with a great
hypothetical win rate is a candidate for the validation pipeline
(ablation → holdout → walk-forward), never a license to loosen a gate
directly.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from agent.types import Bar, Direction

log = logging.getLogger(__name__)

PIP = 10000.0  # same 4-decimal convention as the live loop / monitor


def load_events(path: Path | str) -> list[dict]:
    """Read a vault events.jsonl, skipping unparseable lines (warn only)."""
    path = Path(path)
    events: list[dict] = []
    if not path.exists():
        return events
    with path.open("r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning("%s line %d unparseable, skipped: %s", path, n, e)
    return events


def write_events(path: Path | str, events: Sequence[dict]) -> None:
    """Atomically rewrite a vault events.jsonl."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for evt in events:
                f.write(json.dumps(evt, default=str) + "\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _event_ts(event: dict) -> datetime | None:
    raw = event.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def event_bar_index(event: dict, bars: Sequence[Bar]) -> int | None:
    """Index of the event bar: the first bar at-or-after the event ts."""
    ts = _event_ts(event)
    if ts is None or not bars:
        return None
    for i, b in enumerate(bars):
        if b.time >= ts:
            return i
    return None


def resolve_event(event: dict, bars: Sequence[Bar]) -> dict:
    """Return a copy of ``event`` with outcome fields filled in.

    Walks bars strictly after the event bar. Outcome:
      * ``"loss"``  — SL touched (or both SL and TP inside one bar)
      * ``"win"``   — TP touched before SL
      * ``"open"``  — neither level reached by the end of the series

    Adds: ``outcome``, ``outcome_pips``, ``outcome_r``, ``outcome_time``,
    ``bars_to_outcome``, ``resolved``, ``resolved_at``.
    """
    out = dict(event)
    entry = float(event.get("entry") or 0.0)
    stop = float(event.get("stop") or 0.0)
    tp = float(event.get("take_profit") or 0.0)
    direction = str(event.get("direction") or "")
    is_long = direction == Direction.LONG.value

    stop_pips = abs(entry - stop) * PIP
    idx = event_bar_index(event, bars)

    outcome = "open"
    outcome_pips = 0.0
    outcome_time: str | None = None
    bars_to_outcome: int | None = None

    if idx is not None and entry > 0 and stop > 0 and tp > 0 and stop_pips > 0:
        for j in range(idx + 1, len(bars)):
            b = bars[j]
            if is_long:
                hit_sl = b.low <= stop
                hit_tp = b.high >= tp
            else:
                hit_sl = b.high >= stop
                hit_tp = b.low <= tp
            # SL first when both land in one bar — conservative by contract.
            if hit_sl:
                outcome = "loss"
                outcome_pips = -stop_pips
            elif hit_tp:
                outcome = "win"
                outcome_pips = abs(tp - entry) * PIP
            else:
                continue
            outcome_time = b.time.isoformat()
            bars_to_outcome = j - idx
            break

    out["outcome"] = outcome
    out["outcome_pips"] = round(outcome_pips, 1)
    out["outcome_r"] = round(outcome_pips / stop_pips, 3) if stop_pips > 0 else 0.0
    out["outcome_time"] = outcome_time
    out["bars_to_outcome"] = bars_to_outcome
    out["resolved"] = outcome in ("win", "loss")
    out["resolved_at"] = datetime.now(tz=timezone.utc).isoformat()
    return out


def summarize_by_reason(events: Sequence[dict]) -> list[dict]:
    """Aggregate resolved outcomes per reason tag.

    Returns rows: reason, n, wins, losses, open, win_rate, avg_r (win rate
    and avg R over RESOLVED events only).
    """
    groups: dict[str, list[dict]] = {}
    for evt in events:
        groups.setdefault(str(evt.get("reason", "unknown")), []).append(evt)

    rows = []
    for reason in sorted(groups):
        evts = groups[reason]
        wins = sum(1 for e in evts if e.get("outcome") == "win")
        losses = sum(1 for e in evts if e.get("outcome") == "loss")
        resolved = wins + losses
        sum_r = sum(float(e.get("outcome_r") or 0.0) for e in evts
                    if e.get("outcome") in ("win", "loss"))
        rows.append({
            "reason": reason,
            "n": len(evts),
            "wins": wins,
            "losses": losses,
            "open": len(evts) - resolved,
            "win_rate": round(wins / resolved, 3) if resolved else 0.0,
            "avg_r": round(sum_r / resolved, 3) if resolved else 0.0,
        })
    return rows
