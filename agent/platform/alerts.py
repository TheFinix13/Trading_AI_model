"""F014 -- in-process event bus for platform alerts.

Thread-safe pub/sub with a bounded ring buffer of the most recent
events. Callbacks are invoked synchronously; a raised exception in
one subscriber is swallowed so it never breaks the others.

This is deliberately in-process (single-user install per D052 -- no
Redis, no message broker). SSE consumers register a queue-drain
callback in `agent.platform.alerts_sse`; Telegram bridge registers
a `httpx.post` callback in `agent.platform.alerts_telegram`.

Sprint 2 ships the bus + wiring but no Sprint 2 pathway publishes
events from a live-order code path (D065 SCAFFOLDING invariant).
Publishers exist only inside tests + the test-alert API.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
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

_LOG = logging.getLogger(__name__)

_LOCK = threading.RLock()
_SUBSCRIBERS: dict[str, Callable[[dict], None]] = {}
_RECENT: deque[dict] = deque(maxlen=RING_BUFFER_CAPACITY)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


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
    """Clear subscribers and the ring buffer."""
    with _LOCK:
        _SUBSCRIBERS.clear()
        _RECENT.clear()


__all__ = [
    "EVENT_TYPES",
    "RING_BUFFER_CAPACITY",
    "publish",
    "subscribe",
    "unsubscribe",
    "recent",
    "reset",
]
