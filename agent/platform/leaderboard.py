"""F022 -- Public `/leaderboard` data plane: internal squad standings.

Per-agent and per-pair standings computed on read from the same
``<live_dir>/events.jsonl`` tape F001/F002/F020 consume, so the four
surfaces can never disagree about what happened. Single-install scale
only: one install, ranked within itself -- cross-user ranking is
explicitly out of scope until the D115 auth migration ships.

Only ``close`` rows with a numeric ``pnl_pips`` contribute (exactly
the rows ``players._stats_for_agent`` counts as trades). Agent
identifiers ride ``agent`` or ``agent_id``; timestamps ride ``t`` or
``timestamp`` -- both variants accepted, matching
``players._row_agent_key``.

Ranking metrics per entity: closed-trade count, cumulative R, mean
TQS, win rate, last-active timestamp. Sorted by cumulative R
descending; ties break on mean TQS. The insufficient-sample rule is
SHARED with F021 (`players.MIN_FORM_SAMPLE`): below 5 closed trades
no win-rate percentage is ever rendered -- the payload carries
``win_rate_pct=None`` plus the literal "insufficient sample (n=...)"
note.

Read-only invariant: nothing under ``live_dir`` is written to.
Malformed rows and missing files degrade to empty payloads, never an
exception (F005 contract). Deterministic: the same tape always yields
the same rows (``generated_at`` aside).

Provenance: every number this module emits is a shadow-paper
activity/quality ranking from the v2 squad's demo feed -- NOT
investment performance. See :data:`PROVENANCE_NOTE`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.platform import players

# Rendered verbatim on the /leaderboard page banner and echoed in
# every payload, same provenance-labelling posture as /performance.
PROVENANCE_NOTE = (
    "Internal squad standings on a demo feed -- shadow-paper activity "
    "and quality metrics from the v2 squad (no orders sent to any "
    "broker), NOT investment performance. No comparison against any "
    "external benchmark is implied. Past activity is not indicative "
    "of future results."
)

# Supported groupings and rolling windows (None = all recorded
# history). Anything else folds to the default -- never-raise.
GROUPINGS: tuple[str, ...] = ("agent", "pair")
WINDOWS_SUPPORTED: tuple[int | None, ...] = (None, 7, 30)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")


def _row_ts(row: dict) -> str:
    return str(row.get("t") or row.get("timestamp") or "")


def _ts_epoch(ts: str) -> float | None:
    """ISO-8601 string -> UTC epoch; None on failure."""
    text = str(ts or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


_META_BY_KEY: dict[str, dict] = {
    r["agent_key"]: r for r in players.roster_meta()
}


def _num(row: dict, key: str) -> float | None:
    v = row.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def _closes(live_dir: Path | str | None) -> list[dict]:
    """Time-ordered close rows with numeric pnl_pips -- the same rows
    every other surface counts as resolved trades."""
    live = Path(live_dir) if live_dir is not None else None
    rows = players._read_events(live)
    closes = [
        r for r in rows
        if r.get("type") == "close"
        and isinstance(r.get("pnl_pips"), (int, float))
    ]
    closes.sort(key=_row_ts)
    return closes


def _entity_key(row: dict, by: str) -> str:
    if by == "pair":
        return str(row.get("symbol") or "").upper()
    return players._row_agent_key(row)


def _sort_key(row: dict) -> tuple:
    # Cumulative R descending, mean TQS descending (absent TQS sorts
    # last among ties), then entity ascending for determinism.
    mean_tqs = row["mean_tqs"]
    return (-row["cum_r"],
            -(mean_tqs if mean_tqs is not None else float("-inf")),
            row["entity"])


def standings(
    by: str = "agent",
    window_days: int | None = None,
    live_dir: Path | str | None = None,
    now: float | None = None,
) -> dict:
    """Standings table payload for one grouping and window.

    ``by`` is ``"agent"`` or ``"pair"`` (anything else folds to
    ``"agent"``). ``window_days`` is ``None`` (all recorded history),
    7, or 30; unsupported values fold to ``None``. ``now`` is an
    injectable UTC epoch for the window cutoff (tests pin it;
    production leaves it None = wall clock).

    Entities appear once they have >= 1 resolved close on tape; an
    empty/missing tape yields ``rows=[]`` (F005 empty state upstream).
    Never raises.
    """
    by = str(by or "").strip().lower()
    if by not in GROUPINGS:
        by = "agent"
    try:
        window_days = int(window_days) if window_days is not None else None
    except (TypeError, ValueError):
        window_days = None
    if window_days not in WINDOWS_SUPPORTED:
        window_days = None

    closes = _closes(live_dir)
    if window_days is not None:
        now_e = float(now) if now is not None \
            else datetime.now(timezone.utc).timestamp()
        cutoff = now_e - timedelta(days=window_days).total_seconds()
        closes = [r for r in closes
                  if (e := _ts_epoch(_row_ts(r))) is not None
                  and e >= cutoff]

    per: dict[str, dict] = {}
    for r in closes:
        key = _entity_key(r, by)
        if not key:
            continue
        d = per.setdefault(key, {
            "closed": 0, "wins": 0, "cum_r": 0.0,
            "tqs_vals": [], "last_active": "",
        })
        d["closed"] += 1
        if float(r["pnl_pips"]) > 0:
            d["wins"] += 1
        r_val = _num(r, "r")
        if r_val is not None:
            d["cum_r"] += r_val
        tqs = _num(r, "tqs")
        if tqs is not None:
            d["tqs_vals"].append(tqs)
        ts = _row_ts(r)
        if ts > d["last_active"]:
            d["last_active"] = ts

    min_sample = players.MIN_FORM_SAMPLE
    rows: list[dict] = []
    for entity, d in per.items():
        n = d["closed"]
        insufficient = n < min_sample
        meta = _META_BY_KEY.get(entity) if by == "agent" else None
        rows.append({
            "entity": entity,
            "name": (meta["name"] if meta else entity),
            "player_id": (meta["id"] if meta else None),
            "closed_trades": n,
            "wins": d["wins"],
            "cum_r": round(d["cum_r"], 2),
            "mean_tqs": (round(sum(d["tqs_vals"]) / len(d["tqs_vals"]), 3)
                         if d["tqs_vals"] else None),
            "insufficient_sample": insufficient,
            "win_rate_pct": (None if insufficient
                             else round(100.0 * d["wins"] / n, 1)),
            "note": (f"insufficient sample (n={n})"
                     if insufficient else None),
            "last_active": d["last_active"] or None,
        })
    rows.sort(key=_sort_key)
    for i, row in enumerate(rows, start=1):
        row["rank"] = i

    return {
        "by": by,
        "window_days": window_days,
        "window_label": ("all recorded history" if window_days is None
                         else f"last {window_days} days"),
        "rows": rows,
        "total_closed": len(closes),
        "min_sample": min_sample,
        "provenance": PROVENANCE_NOTE,
        "generated_at": _now_iso(),
    }


__all__ = [
    "PROVENANCE_NOTE",
    "GROUPINGS",
    "WINDOWS_SUPPORTED",
    "standings",
]
