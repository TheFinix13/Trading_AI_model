"""F011 -- kill-switch WRITE path (Sprint 2).

Sibling to :mod:`kill_switches` (read-only). Split so a compromised
read-only accessor can never accidentally trip an activate; every
write goes through this module and is audit-logged to
``<config_dir>/kill_events.jsonl``.

Public API
==========

.. code-block:: python

    activate_kill(symbol: str | None = None,
                  reason: str = "",
                  by: str = "user") -> bool
    clear_kill(symbol: str | None = None) -> bool
    recent_events(limit: int = 20) -> list[dict]
    events_log_path() -> Path

Invariants
==========

- Symbol must be ``None`` (global) or a member of
  :data:`kill_switches.SUPPORTED_SYMBOLS`. Anything else raises
  :class:`ValueError`.
- Every write appends a JSON line to the audit log. Bounded reader
  returns the tail via :func:`recent_events`.
- Activate is idempotent: re-activating an already-live scope updates
  the reason (and appends a fresh audit line).
- Clear is idempotent: clearing an already-cleared scope is a no-op
  that still appends an audit line so operators see the click.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from agent.platform import credentials, kill_switches
from agent.platform.kill_switches import (
    GLOBAL_KEY,
    SUPPORTED_SYMBOLS,
)

_MAX_REASON_LEN: int = 200
_AUDIT_FILENAME: str = "kill_events.jsonl"


def events_log_path() -> Path:
    """Return the JSONL audit-log path (``<config_dir>/kill_events.jsonl``)."""
    return credentials._config_dir() / _AUDIT_FILENAME


def _normalise_scope(symbol: str | None) -> str:
    if symbol is None:
        return GLOBAL_KEY
    normalized = str(symbol).upper().strip()
    if normalized == GLOBAL_KEY:
        return GLOBAL_KEY
    if normalized not in SUPPORTED_SYMBOLS:
        raise ValueError(
            f"unknown symbol '{symbol}'; expected one of "
            f"{SUPPORTED_SYMBOLS} or None for global"
        )
    return normalized


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _append_event(action: str, scope: str, reason: str, by: str) -> None:
    path = events_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": _now_iso(),
        "action": action,
        "scope": scope,
        "reason": reason,
        "by": by,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True))
        fh.write("\n")


def activate_kill(symbol: str | None = None,
                  reason: str = "",
                  by: str = "user") -> bool:
    """Create the flag file for ``symbol`` (or global if None).

    Returns True. Raises :class:`ValueError` on unknown symbol. The
    reason is trimmed to :data:`_MAX_REASON_LEN` chars.
    """
    scope = _normalise_scope(symbol)
    clean_reason = str(reason or "").strip()[:_MAX_REASON_LEN]
    clean_by = str(by or "user").strip() or "user"
    directory = kill_switches.kill_dir()
    directory.mkdir(parents=True, exist_ok=True)
    flag_path = directory / f"{scope}.flag"
    body = {
        "reason": clean_reason,
        "activated_at": _now_iso(),
        "by": clean_by,
    }
    flag_path.write_text(
        json.dumps(body, sort_keys=True), encoding="utf-8")
    _bump_mtime(directory)
    _append_event(
        "activate", scope, clean_reason or "(no reason)", clean_by)
    kill_switches.reset_cache_for_tests()
    return True


def clear_kill(symbol: str | None = None) -> bool:
    """Remove the flag for ``symbol`` (or global). Idempotent."""
    scope = _normalise_scope(symbol)
    directory = kill_switches.kill_dir()
    flag_path = directory / f"{scope}.flag"
    existed = flag_path.exists()
    if existed:
        try:
            flag_path.unlink()
        except OSError:
            pass
    if directory.exists():
        _bump_mtime(directory)
    _append_event(
        "clear", scope, "" if existed else "(no-op)", "user")
    kill_switches.reset_cache_for_tests()
    return True


def recent_events(limit: int = 20) -> list[dict]:
    """Return the tail of the audit log (newest LAST -- append order).

    Missing log returns ``[]``. Malformed lines are skipped silently
    (audit read must never raise).
    """
    if limit <= 0:
        return []
    path = events_log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for raw in lines[-limit:]:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _bump_mtime(directory: Path) -> None:
    """Force the directory's mtime forward so the read-path cache
    invalidates immediately (some filesystems don't update dir mtime
    on unlink/write of pre-existing children within the same second)."""
    try:
        now = time.time()
        os.utime(directory, (now, now))
    except OSError:  # pragma: no cover
        pass
