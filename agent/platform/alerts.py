"""F014 -- in-process event bus for platform alerts.

Thread-safe pub/sub with a bounded ring buffer of the most recent
events. Callbacks are invoked synchronously; a raised exception in
one subscriber is swallowed so it never breaks the others.

This is deliberately in-process (single-user install per D052 -- no
Redis, no message broker). SSE consumers register a queue-drain
callback in `agent.platform.alerts_sse`; Telegram bridge registers
a `httpx.post` callback in `agent.platform.alerts_telegram`.

Durability boundary (F023, I010): by default the ring buffer is the
ONLY copy of recent events this bus holds -- a process restart drops
it (the Telegram bridge and the per-module JSONL audits are the
mitigations). Opt-in via ``[alerts] jsonl_sink = true`` in
platform.toml, every ``publish()`` additionally appends the event to
``<config_dir>/alerts_log.jsonl`` (:func:`configure_sink`). Sink
failures NEVER block or fail ``publish()`` -- bus semantics are
unchanged either way; a failed sink write logs one warning per
process. No retention/rotation policy: the sink file is
operator-managed.

Sprint 2 ships the bus + wiring but no Sprint 2 pathway publishes
events from a live-order code path (D065 SCAFFOLDING invariant).
Publishers exist only inside tests + the test-alert API.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

EVENT_TYPES: tuple[str, ...] = (
    "trade_fill",
    "stop_hit",
    "kill_switch_trip",
    "risk_budget_breach",
    "approval_submitted",
    "platform_down",
    # F017 (Sprint 2b) -- ops-watchdog state transitions. Added under
    # the F014 Legal rolling constraint with an inline Legal re-review
    # on tape at company/legal/F017-review.md (D100).
    "watchdog_alert",
)

RING_BUFFER_CAPACITY: int = 100

# F023 (I010) -- optional durable sink, default OFF (opt-in only).
SINK_FILENAME: str = "alerts_log.jsonl"

_LOG = logging.getLogger(__name__)

_LOCK = threading.RLock()
_SUBSCRIBERS: dict[str, Callable[[dict], None]] = {}
_RECENT: deque[dict] = deque(maxlen=RING_BUFFER_CAPACITY)

_SINK_ENABLED: bool = False
_SINK_PATH_OVERRIDE: Path | None = None
_SINK_WARNED: bool = False


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def configure_sink(enabled: bool, path: Path | str | None = None) -> None:
    """F023 -- toggle the optional JSONL sink.

    ``enabled`` defaults to False module-wide (opt-in only; the server
    wires it from ``[alerts] jsonl_sink``). ``path`` overrides the
    default ``<config_dir>/alerts_log.jsonl`` (tests inject a tmp
    path). Reconfiguring re-arms the once-per-process failure warning.
    """
    global _SINK_ENABLED, _SINK_PATH_OVERRIDE, _SINK_WARNED
    with _LOCK:
        _SINK_ENABLED = enabled is True
        _SINK_PATH_OVERRIDE = Path(path) if path is not None else None
        _SINK_WARNED = False


def sink_is_enabled() -> bool:
    """Whether the F023 JSONL sink is currently on (default False)."""
    with _LOCK:
        return _SINK_ENABLED


def sink_path() -> Path:
    """Where the sink appends: the configured override, else
    ``<config_dir>/alerts_log.jsonl`` (same relocation seam as every
    other piece of platform state)."""
    with _LOCK:
        override = _SINK_PATH_OVERRIDE
    if override is not None:
        return override
    from agent.platform import credentials
    return credentials._config_dir() / SINK_FILENAME


def _sink_write(event: dict) -> None:
    """Append one event to the sink. NEVER raises into ``publish()``;
    the first failure logs a warning, later failures stay quiet until
    the sink is reconfigured (no log spam on a read-only disk)."""
    global _SINK_WARNED
    try:
        path = sink_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    except Exception:
        with _LOCK:
            if _SINK_WARNED:
                return
            _SINK_WARNED = True
        _LOG.warning("alerts JSONL sink write failed; bus delivery "
                     "unaffected (further sink failures stay quiet)",
                     exc_info=True)


def publish(event_type: str, payload: dict,
            ts: float | None = None) -> dict:
    """Push an event onto the bus. Returns the event dict so callers can
    inspect the assigned id / timestamp."""
    if event_type not in EVENT_TYPES:
        raise ValueError(
            f"unknown event_type {event_type!r}; "
            f"expected one of {EVENT_TYPES}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    now = ts if ts is not None else time.time()
    event = {
        "id": "evt_" + uuid.uuid4().hex[:16],
        "type": event_type,
        "ts": _iso(now),
        "ts_epoch": now,
        "payload": dict(payload),
    }
    with _LOCK:
        _RECENT.append(event)
        callbacks = list(_SUBSCRIBERS.values())
        sink_on = _SINK_ENABLED
    if sink_on:
        # Durable copy first, consumers second -- and a sink failure
        # never blocks either (F023).
        _sink_write(event)
    for cb in callbacks:
        try:
            cb(event)
        except Exception:  # pragma: no cover - defensive; logged
            _LOG.exception("alerts subscriber raised; swallowed")
    return event


def subscribe(callback: Callable[[dict], None]) -> str:
    """Register a callback. Returns the subscription id."""
    if not callable(callback):
        raise TypeError("callback must be callable")
    sub_id = "sub_" + uuid.uuid4().hex[:12]
    with _LOCK:
        _SUBSCRIBERS[sub_id] = callback
    return sub_id


def unsubscribe(subscription_id: str) -> bool:
    with _LOCK:
        return _SUBSCRIBERS.pop(subscription_id, None) is not None


def recent(limit: int = 100) -> list[dict]:
    """Return the last `limit` events, newest first."""
    with _LOCK:
        rows = list(_RECENT)
    rows.reverse()
    if limit <= 0:
        return []
    return [dict(r) for r in rows[:limit]]


def reset() -> None:  # claim-exempt: test-only
    """Clear subscribers, the ring buffer, and the sink config (the
    sink FILE, if any, is deliberately left on disk -- that is the
    durability property under test)."""
    global _SINK_ENABLED, _SINK_PATH_OVERRIDE, _SINK_WARNED
    with _LOCK:
        _SUBSCRIBERS.clear()
        _RECENT.clear()
        _SINK_ENABLED = False
        _SINK_PATH_OVERRIDE = None
        _SINK_WARNED = False


__all__ = [
    "EVENT_TYPES",
    "RING_BUFFER_CAPACITY",
    "SINK_FILENAME",
    "publish",
    "subscribe",
    "unsubscribe",
    "recent",
    "configure_sink",
    "sink_is_enabled",
    "sink_path",
    "reset",
]
