"""F014 -- Server-Sent Events endpoint for the alerts bus.

`format_event()` renders an event dict as an SSE frame with `id: `,
`event: `, and `data: ` lines (blank line delimits frames per the
spec). `sse_stream_response(handler, initial_history=None,
heartbeat_seconds=15)` writes those frames to a `text/event-stream`
response until the client disconnects.

Concurrent-stream cap (F023, I010): each stream holds a server
thread, so the count is bounded (``[alerts] max_sse_streams``,
default 8). At the cap a NEW stream request is refused with ``429`` +
``Retry-After`` -- refuse, NOT evict: an existing consumer's stream
is never dropped to admit a newcomer. Teardown decrements the counter
finally-guarded, so abrupt disconnects cannot leak slots.

Auth is enforced by the caller (the platform server handler); this
module is transport-only.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from typing import Iterable

from agent.platform import alerts

DEFAULT_HEARTBEAT_SECONDS: float = 15.0

# F023 -- cap on concurrent SSE consumers (refuse-with-429 past it).
DEFAULT_MAX_STREAMS: int = 8
RETRY_AFTER_SECONDS: int = 5

_STREAMS_LOCK = threading.Lock()
_MAX_STREAMS: int = DEFAULT_MAX_STREAMS
_ACTIVE_STREAMS: int = 0


def set_max_streams(n: int) -> None:
    """Configure the concurrent-stream cap (``[alerts]
    max_sse_streams``). Non-positive / non-numeric values are ignored
    -- the cap never silently becomes unbounded."""
    global _MAX_STREAMS
    try:
        n = int(n)
    except (TypeError, ValueError):
        return
    if n > 0:
        with _STREAMS_LOCK:
            _MAX_STREAMS = n


def get_max_streams() -> int:
    """The current concurrent-stream cap (default 8)."""
    with _STREAMS_LOCK:
        return _MAX_STREAMS


def active_stream_count() -> int:
    """How many SSE streams are currently attached."""
    with _STREAMS_LOCK:
        return _ACTIVE_STREAMS


def reset_streams_for_tests() -> None:  # claim-exempt: test-only counter/cap reset, no HTTP surface
    global _MAX_STREAMS, _ACTIVE_STREAMS
    with _STREAMS_LOCK:
        _MAX_STREAMS = DEFAULT_MAX_STREAMS
        _ACTIVE_STREAMS = 0


def _try_acquire_stream() -> bool:
    global _ACTIVE_STREAMS
    with _STREAMS_LOCK:
        if _ACTIVE_STREAMS >= _MAX_STREAMS:
            return False
        _ACTIVE_STREAMS += 1
        return True


def _release_stream() -> None:
    global _ACTIVE_STREAMS
    with _STREAMS_LOCK:
        _ACTIVE_STREAMS = max(0, _ACTIVE_STREAMS - 1)


def _refuse_stream(handler) -> None:
    """429 + Retry-After refusal at the cap. The existing consumers'
    streams are untouched (refuse, not evict)."""
    body = json.dumps({
        "error": "too many concurrent alert streams",
        "hint": "close an existing stream or retry shortly",
        "max_streams": get_max_streams(),
        "retry_after_seconds": RETRY_AFTER_SECONDS,
    }).encode("utf-8")
    handler.send_response(429)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Retry-After", str(RETRY_AFTER_SECONDS))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass


def format_event(event: dict) -> bytes:
    """Render a single event dict as an SSE frame.

    Each frame is:
        id: <event-id>
        event: <event-type>
        data: <json payload>
        <blank line>

    Any missing field falls back to a safe default so malformed
    events on the ring buffer never break the stream."""
    ev_id = str(event.get("id", ""))
    ev_type = str(event.get("type", "message"))
    data = json.dumps({
        "id": ev_id,
        "type": ev_type,
        "ts": event.get("ts"),
        "payload": event.get("payload", {}),
    })
    frame = (
        f"id: {ev_id}\n"
        f"event: {ev_type}\n"
        f"data: {data}\n\n"
    )
    return frame.encode("utf-8")


def _heartbeat_frame() -> bytes:
    return b": heartbeat\n\n"


def sse_stream_response(
    handler,
    initial_history: Iterable[dict] | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    max_seconds: float | None = None,
) -> None:
    """Attach a subscription to the alerts bus and drain frames onto
    the handler's response until the client disconnects.

    Parameters:
      handler -- an `http.server.BaseHTTPRequestHandler` whose
                 `wfile` we'll write to. The caller must NOT have
                 called `handler.end_headers()` yet.
      initial_history -- iterable of events to replay first (used by
                         the ring buffer catch-up on reconnect).
      heartbeat_seconds -- seconds of idle time before we emit a
                          comment frame to keep proxies alive.
      max_seconds -- optional wall-clock cap on the connection
                     lifetime (used by tests).

    F023: at the concurrent-stream cap this refuses with 429 +
    ``Retry-After`` BEFORE subscribing (no eviction of existing
    consumers); the slot is released finally-guarded on any exit path.
    """
    if not _try_acquire_stream():
        _refuse_stream(handler)
        return

    try:
        q: queue.Queue[dict] = queue.Queue()

        def _on_event(ev: dict) -> None:
            q.put(ev)

        sub_id = alerts.subscribe(_on_event)

        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        handler.send_header("X-Accel-Buffering", "no")
        handler.end_headers()

        started = time.time()

        try:
            for ev in list(initial_history or []):
                handler.wfile.write(format_event(ev))
            handler.wfile.flush()

            while True:
                if max_seconds is not None and (time.time() - started) >= max_seconds:
                    break
                try:
                    ev = q.get(timeout=heartbeat_seconds)
                except queue.Empty:
                    try:
                        handler.wfile.write(_heartbeat_frame())
                        handler.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
                    continue
                try:
                    handler.wfile.write(format_event(ev))
                    handler.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
        finally:
            alerts.unsubscribe(sub_id)
    finally:
        _release_stream()


__all__ = [
    "DEFAULT_HEARTBEAT_SECONDS",
    "DEFAULT_MAX_STREAMS",
    "RETRY_AFTER_SECONDS",
    "format_event",
    "sse_stream_response",
    "set_max_streams",
    "get_max_streams",
    "active_stream_count",
]
