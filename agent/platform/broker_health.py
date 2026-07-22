"""F012 -- broker connection health probe (Sprint 2).

Wraps :mod:`broker_connection` with a 30-second in-memory cache so
:func:`/risk` can poll continuously without blowing the F007 rate
limit (5 test_connection calls / minute / process).

Public API
==========

.. code-block:: python

    CACHE_TTL_SECONDS: float = 30.0

    check_broker_health(user_alias, cache_ttl=None) -> dict
    is_broker_alive(user_alias) -> bool
    clear_cache() -> None
    list_health_states() -> list[dict]

Return shape of :func:`check_broker_health`::

    {
      "alive": bool,
      "reason": str,                # "ok" | "no credentials" | "..."
      "account_type": str | None,
      "server": str | None,
      "checked_at": iso8601 str,
      "cached": bool,               # True if cache-hit
    }

The password is **never** returned even accidentally -- only the
alias + connection metadata surface. This module never imports from
``agent/live/*``, ``agent/risk/*``, or ``agent/squad/*``.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from agent.platform import broker_connection

CACHE_TTL_SECONDS: float = 30.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _sanitise_result(alias: str, raw: dict, checked_at: str) -> dict:
    """Whitelist metadata; never let a password leak."""
    return {
        "alias": alias,
        "alive": bool(raw.get("success", False)),
        "reason": (raw.get("error_message")
                   or ("ok" if raw.get("success") else "unknown")),
        "account_type": raw.get("account_type"),
        "server": raw.get("server"),
        "checked_at": checked_at,
        "cached": False,
    }


def _unreachable(alias: str, reason: str, checked_at: str) -> dict:
    return {
        "alias": alias,
        "alive": False,
        "reason": reason,
        "account_type": None,
        "server": None,
        "checked_at": checked_at,
        "cached": False,
    }


def check_broker_health(user_alias: str,
                        cache_ttl: float | None = None) -> dict:
    """Return the health payload for ``user_alias``.

    - Reads the in-memory cache first. Fresh entries (age < ``cache_ttl``)
      are returned with ``cached=True`` and no ``broker_connection``
      call is made.
    - On cache miss, loads credentials via
      :func:`broker_connection.load_credentials`. Missing credentials
      short-circuit to ``alive=False, reason="no credentials"``.
    - Otherwise runs :func:`broker_connection.test_connection` and
      caches the sanitised result. The raw password never appears in
      the return.
    """
    ttl = float(CACHE_TTL_SECONDS if cache_ttl is None else cache_ttl)
    now = time.monotonic()
    with _lock:
        entry = _cache.get(user_alias)
        if entry is not None:
            ts, cached_payload = entry
            if (now - ts) <= ttl:
                out = dict(cached_payload)
                out["cached"] = True
                return out

    creds: dict | None
    try:
        creds = broker_connection.load_credentials(user_alias)
    except Exception:  # pragma: no cover
        creds = None
    checked_at = _now_iso()
    if creds is None:
        payload = _unreachable(user_alias, "no credentials", checked_at)
    else:
        try:
            raw = broker_connection.test_connection(
                login=creds.get("login"),
                password=creds.get("password", ""),
                server=creds.get("server", ""))
        except Exception as exc:  # pragma: no cover
            payload = _unreachable(user_alias, f"probe raised: {exc!s}",
                                   checked_at)
        else:
            payload = _sanitise_result(user_alias, raw, checked_at)

    with _lock:
        _cache[user_alias] = (now, payload)

    out = dict(payload)
    out["cached"] = False
    return out


def is_broker_alive(user_alias: str) -> bool:
    """Convenience wrapper returning just the ``alive`` bool."""
    return bool(check_broker_health(user_alias).get("alive", False))


def clear_cache() -> None:  # claim-exempt: test-only cache reset, no HTTP surface
    """Wipe the health cache. Test helper."""
    with _lock:
        _cache.clear()


def list_health_states() -> list[dict]:
    """Return one payload per configured broker alias.

    Aliases are read from :func:`broker_connection.list_aliases`. Each
    entry is the same shape as :func:`check_broker_health`. Aliases
    with no probe result yet are surfaced with ``alive=False,
    reason="not yet probed"`` -- consumers can trigger a probe by
    calling :func:`check_broker_health(alias)` explicitly.
    """
    out: list[dict] = []
    for alias_row in broker_connection.list_aliases():
        alias = alias_row.get("alias")
        if not alias:
            continue
        with _lock:
            entry = _cache.get(alias)
        if entry is None:
            out.append({
                "alias": alias,
                "alive": False,
                "reason": "not yet probed",
                "account_type": alias_row.get("account_type"),
                "server": alias_row.get("server"),
                "checked_at": None,
                "cached": False,
            })
        else:
            _, payload = entry
            row = dict(payload)
            row["cached"] = True
            out.append(row)
    return out
