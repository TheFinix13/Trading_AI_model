"""Shared helpers: pip math, time helpers, atomic file ops."""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PIP_SIZE = 0.0001  # for EURUSD-style 5-digit pairs (1 pip = 0.0001)


def to_pips(price_diff: float, pip_size: float = PIP_SIZE) -> float:
    return price_diff / pip_size


def from_pips(pips: float, pip_size: float = PIP_SIZE) -> float:
    return pips * pip_size


def round_lot(lot: float, step: float = 0.01, minimum: float = 0.01) -> float:
    """Round down to the nearest broker lot step, enforcing the minimum."""
    if lot < minimum:
        return 0.0  # too small to trade; caller decides whether to skip or escalate to min
    rounded = round(int(lot / step) * step, 2)
    return max(rounded, minimum)


def in_time_window(now: datetime, start: str, end: str, tz: str) -> bool:
    """Check if `now` falls within [start, end] interpreted in `tz`."""
    local = now.astimezone(ZoneInfo(tz)) if now.tzinfo else now.replace(tzinfo=ZoneInfo(tz))
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    s = time(sh, sm)
    e = time(eh, em)
    t = local.time()
    return s <= t <= e


def atomic_write(path: Path | str, content: bytes | str) -> None:
    """Write file atomically by writing to temp then renaming."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    with tempfile.NamedTemporaryFile(mode=mode, delete=False, dir=path.parent) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def kill_switch_active(path: Path | str) -> bool:
    # Global override for local runs/tests.
    # If set, the process ignores all kill switch files.
    if str(os.getenv("SKIP_KILL_SWITCH", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return False
    return Path(path).exists()


def kill_switch_reason(path: Path | str) -> str | None:
    """Return the kill file's own content (the reason it was created,
    written by ``_emergency_close_all``) if the file exists, else ``None``.

    The kill switch itself already carries this — previously callers only
    ever logged "kill switch active", forcing the operator to go dig up the
    file by hand (or, worse, never notice it and just keep restarting).
    """
    if str(os.getenv("SKIP_KILL_SWITCH", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or "(empty kill file)"
    except OSError:
        return "(kill file exists but could not be read)"


# ---------------------------------------------------------------------------
# Daily-DD auto-kill classification + creation date (self-recovery support)
#
# A daily-DD circuit-breaker halt writes a per-symbol kill.txt whose FIRST
# line is exactly ``Auto-kill: Daily DD halt: <pct>% (limit <pct>%)`` (see
# PositionMonitor._emergency_close_all). Because that limit is literally a
# "% PER DAY" budget that RiskManager.on_new_day resets at the UTC date
# change, this specific halt class is safe to auto-clear at the next UTC
# midnight — re-arming evaluation without a human deleting the file.
#
# EVERYTHING ELSE stays sticky: the master kill_switch_file, a manually
# created kill.txt, and any auto-kill whose reason is NOT a clean daily-DD
# halt (consecutive-error / catastrophe / broker-misread paths). Human stop
# and non-DD safety halts always win — this classifier is deliberately
# narrow and fails safe (returns False / None on anything ambiguous).
# ---------------------------------------------------------------------------


def is_daily_dd_auto_kill(reason: str | None) -> bool:
    """True iff a kill file's recorded reason marks it as an *automatic
    daily-drawdown* halt — the ONLY halt class eligible for auto-clear.

    Requires BOTH the ``Auto-kill:`` prefix (agent-written, never a human
    file) AND the ``Daily DD halt`` marker. Consecutive-error, catastrophe
    and manual kill files therefore stay sticky.
    """
    if not reason:
        return False
    text = reason.strip().lower()
    return text.startswith("auto-kill:") and "daily dd halt" in text


def kill_file_creation_utc_date(path: Path | str) -> date | None:
    """Best-effort UTC calendar date on which a kill file was created.

    Prefers the ISO timestamp ``_emergency_close_all`` writes on the second
    line; falls back to the file's mtime. Returns ``None`` when the file is
    missing or no date can be established — callers must fail safe (stay
    halted) on ``None`` rather than guess a rollover.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    # Skip the reason (line 0); look for an ISO timestamp on later lines.
    for line in lines[1:]:
        stamp = line.strip()
        if not stamp:
            continue
        try:
            ts = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).date()
    try:
        return datetime.fromtimestamp(
            p.stat().st_mtime, tz=timezone.utc
        ).date()
    except OSError:
        return None
