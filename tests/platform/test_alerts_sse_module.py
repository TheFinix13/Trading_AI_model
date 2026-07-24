"""F014 -- alerts_sse module unit tests (spec asked 5).

F023 extends this file with the concurrent-stream cap cases: refusal
at the cap (429 + Retry-After, refuse NOT evict), teardown decrement,
abrupt-close leak check, and the default cap value.
"""
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
    alerts_sse.reset_streams_for_tests()
    yield
    alerts.reset()
    alerts_sse.reset_streams_for_tests()


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


class _BrokenPipeHandler(_FakeHandler):
    """Simulates a client that vanished: every body write raises."""

    class _BrokenFile(io.BytesIO):
        def write(self, *_a, **_k):  # type: ignore[override]
            raise BrokenPipeError("client gone")

    def __init__(self):
        super().__init__()
        self.wfile = self._BrokenFile()


def _stream_in_thread(handler, max_seconds=0.5):
    # Short heartbeat so the loop re-checks max_seconds promptly and
    # the thread winds down inside the join window.
    t = threading.Thread(target=lambda: alerts_sse.sse_stream_response(
        handler, heartbeat_seconds=0.1, max_seconds=max_seconds))
    t.start()
    return t


class TestStreamCap:
    def test_default_cap_is_eight(self) -> None:
        assert alerts_sse.DEFAULT_MAX_STREAMS == 8
        assert alerts_sse.get_max_streams() == 8

    def test_set_max_streams_ignores_nonpositive(self) -> None:
        alerts_sse.set_max_streams(3)
        assert alerts_sse.get_max_streams() == 3
        for bad in (0, -1, "many", None):
            alerts_sse.set_max_streams(bad)
            assert alerts_sse.get_max_streams() == 3

    def test_stream_past_cap_gets_429_with_retry_after(self) -> None:
        alerts_sse.set_max_streams(1)
        first = _FakeHandler()
        t = _stream_in_thread(first, max_seconds=0.5)
        time.sleep(0.05)
        assert alerts_sse.active_stream_count() == 1
        # Stream N+1 is refused -- and the FIRST stream stays attached
        # (refuse, not evict).
        refused = _FakeHandler()
        alerts_sse.sse_stream_response(refused, max_seconds=0.05)
        assert refused.status == 429
        headers = dict(refused.headers_sent)
        assert headers["Retry-After"] == str(
            alerts_sse.RETRY_AFTER_SECONDS)
        payload = json.loads(refused.wfile.getvalue().decode())
        assert payload["max_streams"] == 1
        assert alerts_sse.active_stream_count() == 1  # not evicted
        t.join(timeout=1.0)

    def test_closing_a_stream_admits_the_next(self) -> None:
        alerts_sse.set_max_streams(1)
        first = _FakeHandler()
        alerts_sse.sse_stream_response(first, max_seconds=0.05)
        assert alerts_sse.active_stream_count() == 0
        second = _FakeHandler()
        alerts_sse.sse_stream_response(second, max_seconds=0.05)
        assert second.status == 200

    def test_teardown_decrements_counter(self) -> None:
        handler = _FakeHandler()
        alerts_sse.sse_stream_response(handler, max_seconds=0.05)
        assert alerts_sse.active_stream_count() == 0

    def test_abrupt_disconnect_never_leaks_a_slot(self) -> None:
        # The client dies mid-stream: the first write raises
        # BrokenPipeError (which propagates to the server handler,
        # same as F014 -- serve_platform catches it). The slot must
        # still be released AND the bus subscription cleaned up.
        handler = _BrokenPipeHandler()
        with pytest.raises(BrokenPipeError):
            alerts_sse.sse_stream_response(
                handler,
                initial_history=[{"id": "evt_x", "type": "trade_fill",
                                  "ts": "t", "payload": {}}],
                max_seconds=0.05)
        assert alerts_sse.active_stream_count() == 0
        received: list[dict] = []
        alerts.subscribe(lambda ev: received.append(ev))
        alerts.publish("trade_fill", {})
        assert len(received) == 1  # no orphaned stream subscriber

    def test_refusal_does_not_touch_the_bus(self) -> None:
        alerts_sse.set_max_streams(1)
        t = _stream_in_thread(_FakeHandler(), max_seconds=0.4)
        time.sleep(0.05)
        alerts_sse.sse_stream_response(_FakeHandler(), max_seconds=0.05)
        # The refused request never subscribed: exactly one consumer
        # (the live stream) receives the event.
        published = alerts.publish("stop_hit", {})
        assert published["type"] == "stop_hit"
        t.join(timeout=2.0)
        assert not t.is_alive()
        assert alerts_sse.active_stream_count() == 0
