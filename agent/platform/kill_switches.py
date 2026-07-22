"""F011 -- kill-switch READ path (Sprint 2).

File-existence-based kill primitive, patterned on the v1 zones agent's
``agent/utils.kill_switch_active`` but scoped under
``<config_dir>/kill/`` and dimensioned per-symbol so a live-pathway
integration can decide "halt EURUSD only" versus "halt everything".

The write path lives in :mod:`kill_switch_admin` -- this module is
intentionally read-only so a compromised admin bug can't ship an
accidental kill from a request that only meant to *check* state.

Public API
==========

.. code-block:: python

    KILL_DIR_ENV: str = "BLUELOCK_KILL_DIR"
    DEFAULT_KILL_DIRNAME: str = "kill"
    SUPPORTED_SYMBOLS: tuple[str, ...] = (
        "EURUSD", "GBPUSD", "USDCAD", "USDJPY", "USDCHF",
    )
    GLOBAL_KEY: str = "GLOBAL"

    kill_dir() -> Path
    is_killed(symbol: str | None = None) -> bool
    list_killed() -> list[dict]
    reset_cache_for_tests() -> None

Live-mode-off gate contract
===========================

F011 provides :func:`is_killed`; the future integration wires it as
the SECOND gate in the 4-check live-order pathway:

.. code-block:: python

    if not live_mode_enabled():           # F013
        return
    if kill_switches.is_killed(symbol):   # F011 -- THIS SPRINT
        return
    if not risk_budget.can_send_order(symbol, worst_case): return  # F012
    if not approval_queue.can_send_order(id): return               # F013

This module MUST NOT import from ``agent/live/*``, ``agent/risk/*``,
or ``agent/squad/*`` (D065 invariant). It mirrors the shape of the v1
protocol without touching it.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from agent.platform import credentials  # for the config-dir default

KILL_DIR_ENV: str = "BLUELOCK_KILL_DIR"
DEFAULT_KILL_DIRNAME: str = "kill"
SUPPORTED_SYMBOLS: tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDCAD", "USDJPY", "USDCHF",
)
GLOBAL_KEY: str = "GLOBAL"


@dataclass
class _CacheEntry:
    mtime_ns: int
    killed_scopes: frozenset[str]
    payloads: dict[str, dict]  # scope -> parsed flag body


_lock = threading.Lock()
_cache: _CacheEntry | None = None
_cache_dir: Path | None = None


def kill_dir() -> Path:
    """Return the current kill-flag directory.

    Resolution order:

    1. ``BLUELOCK_KILL_DIR`` env var, if set.
    2. ``<credentials._config_dir()>/kill`` -- the platform config dir.

    The directory is created on-demand by the admin write path; this
    module never mutates the filesystem.
    """
    override = os.environ.get(KILL_DIR_ENV)
    if override:
        return Path(override)
    return credentials._config_dir() / DEFAULT_KILL_DIRNAME


def _scan(directory: Path) -> _CacheEntry:
    scopes: set[str] = set()
    payloads: dict[str, dict] = {}
    mtime = 0
    if directory.is_dir():
        try:
            mtime = directory.stat().st_mtime_ns
        except OSError:
            mtime = 0
        for entry in directory.iterdir():
            if not entry.is_file() or not entry.name.endswith(".flag"):
                continue
            scope = entry.name[:-len(".flag")]
            if scope != GLOBAL_KEY and scope not in SUPPORTED_SYMBOLS:
                continue
            scopes.add(scope)
            try:
                body = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                body = {}
            if not isinstance(body, dict):
                body = {}
            payloads[scope] = body
    return _CacheEntry(mtime_ns=mtime, killed_scopes=frozenset(scopes),
                       payloads=payloads)


def _read_state() -> _CacheEntry:
    """Return a fresh :class:`_CacheEntry`; hot-reload via mtime cache."""
    global _cache, _cache_dir
    directory = kill_dir()
    try:
        cur_mtime = directory.stat().st_mtime_ns if directory.is_dir() else 0
    except OSError:
        cur_mtime = 0
    with _lock:
        if _cache is not None and _cache_dir == directory and _cache.mtime_ns == cur_mtime:
            return _cache
        entry = _scan(directory)
        _cache = entry
        _cache_dir = directory
        return entry


def is_killed(symbol: str | None = None) -> bool:
    """Return True iff a matching kill flag exists.

    - ``symbol=None`` -- returns True iff the global kill flag exists.
    - ``symbol="EURUSD"`` -- returns True iff EURUSD's flag OR the
      global flag exists.
    - Unknown symbol -- returns False (validated only in the admin
      write path; the read path never raises).
    """
    entry = _read_state()
    if GLOBAL_KEY in entry.killed_scopes:
        return True
    if symbol is None:
        return False
    sym = symbol.upper().strip()
    if sym not in SUPPORTED_SYMBOLS:
        return False
    return sym in entry.killed_scopes


def list_killed() -> list[dict]:
    """Return one dict per active kill scope.

    Shape: ``[{"scope": "EURUSD", "reason": "...", "activated_at":
    "iso8601", "by": "user"}, ...]``. Order: global first, then
    supported symbols in :data:`SUPPORTED_SYMBOLS` order.
    """
    entry = _read_state()
    ordered: list[str] = []
    if GLOBAL_KEY in entry.killed_scopes:
        ordered.append(GLOBAL_KEY)
    for sym in SUPPORTED_SYMBOLS:
        if sym in entry.killed_scopes:
            ordered.append(sym)
    out: list[dict] = []
    for scope in ordered:
        payload = entry.payloads.get(scope, {})
        out.append({
            "scope": scope,
            "reason": str(payload.get("reason", "")),
            "activated_at": str(payload.get("activated_at", "")),
            "by": str(payload.get("by", "user")),
        })
    return out


def reset_cache_for_tests() -> None:  # claim-exempt: test-only cache reset, no HTTP surface
    """Invalidate the mtime cache. Test-only."""
    global _cache, _cache_dir
    with _lock:
        _cache = None
        _cache_dir = None
