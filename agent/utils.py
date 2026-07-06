"""Shared helpers: pip math, time helpers, atomic file ops."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, time
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
