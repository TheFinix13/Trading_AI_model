"""F014 -- Server-Sent Events endpoint for the alerts bus.

`format_event()` renders an event dict as an SSE frame with `id: `,
`event: `, and `data: ` lines (blank line delimits frames per the
spec). `sse_stream_response(handler, initial_history=None,
heartbeat_seconds=15)` writes those frames to a `text/event-stream`
response until the client disconnects.

Auth is enforced by the caller (the platform server handler); this
module is transport-only.
"""
from __future__ import annotations

import json
import queue
import time
from typing import Iterable

from agent.platform import alerts

DEFAULT_HEARTBEAT_SECONDS: float = 15.0


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
    """
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


__all__ = [
    "DEFAULT_HEARTBEAT_SECONDS",
    "format_event",
    "sse_stream_response",
]
