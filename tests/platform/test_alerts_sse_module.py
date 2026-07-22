"""F014 -- alerts_sse module unit tests (spec asked 5)."""
from __future__ import annotations

import io
import json
import threading
import time

import pytest

from agent.platform import alerts, alerts_sse


@pytest.fixture(autouse=True)
def _clean():
    alerts.reset()
    yield
    alerts.reset()


class _FakeHandler:
    """Minimal duck-typed BaseHTTPRequestHandler stand-in."""

    def __init__(self):
        self.status: int | None = None
        self.headers_sent: list[tuple[str, str]] = []
        self.headers_ended: bool = False
        self.wfile = io.BytesIO()

    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, key: str, value: str) -> None:
        self.headers_sent.append((key, value))

    def end_headers(self) -> None:
        self.headers_ended = True


class TestFormatEvent:
    def test_frame_shape(self) -> None:
        ev = {"id": "evt_a", "type": "trade_fill",
              "ts": "2026-07-22T00:00:00Z",
              "payload": {"symbol": "EURUSD"}}
        frame = alerts_sse.format_event(ev).decode("utf-8")
        assert frame.startswith("id: evt_a\n")
        assert "event: trade_fill\n" in frame
        assert "data: " in frame
        assert frame.endswith("\n\n")

    def test_data_line_is_json(self) -> None:
        ev = {"id": "evt_b", "type": "stop_hit",
              "ts": "t", "payload": {"foo": 1}}
        frame = alerts_sse.format_event(ev).decode("utf-8")
        data_line = [l for l in frame.split("\n")
                     if l.startswith("data: ")][0]
        parsed = json.loads(data_line[len("data: "):])
        assert parsed["type"] == "stop_hit"
        assert parsed["payload"] == {"foo": 1}


class TestStreamResponse:
    def test_headers_and_history_replayed(self) -> None:
        handler = _FakeHandler()
        history = [
            {"id": "evt_1", "type": "trade_fill",
             "ts": "t1", "payload": {}},
            {"id": "evt_2", "type": "stop_hit",
             "ts": "t2", "payload": {}},
        ]
        # max_seconds=0.05 forces a quick exit even with no live events.
        alerts_sse.sse_stream_response(
            handler, initial_history=history,
            heartbeat_seconds=1.0, max_seconds=0.05)
        assert handler.status == 200
        # SSE required headers all present.
        header_keys = {k for k, _ in handler.headers_sent}
        assert "Content-Type" in header_keys
        assert dict(handler.headers_sent)["Content-Type"] == "text/event-stream"
        # Both history events landed on the wire.
        body = handler.wfile.getvalue().decode()
        assert "id: evt_1" in body
        assert "id: evt_2" in body

    def test_disconnect_cleans_subscriber(self) -> None:
        handler = _FakeHandler()
        alerts_sse.sse_stream_response(
            handler, heartbeat_seconds=1.0, max_seconds=0.05)
        # After stream exits, subscriber list is empty.
        received: list[dict] = []
        alerts.subscribe(lambda ev: received.append(ev))
        alerts.publish("trade_fill", {})
        # Only the freshly registered subscriber should have fired.
        assert len(received) == 1


class TestLiveDelivery:
    def test_publish_delivers_to_stream(self) -> None:
        handler = _FakeHandler()

        def run():
            alerts_sse.sse_stream_response(
                handler, heartbeat_seconds=1.0, max_seconds=0.3)

        t = threading.Thread(target=run)
        t.start()
        # Give the subscription a chance to attach.
        time.sleep(0.05)
        alerts.publish("kill_switch_trip", {"symbol": "EURUSD"})
        t.join(timeout=1.0)
        body = handler.wfile.getvalue().decode()
        assert "event: kill_switch_trip" in body
        assert "EURUSD" in body
