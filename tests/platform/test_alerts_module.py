"""F014 -- alerts event bus unit tests (spec asked 7)."""
from __future__ import annotations

import threading

import pytest

from agent.platform import alerts


@pytest.fixture(autouse=True)
def _clean():
    alerts.reset()
    yield
    alerts.reset()


class TestPublishSubscribe:
    def test_subscriber_receives_event(self) -> None:
        received: list[dict] = []
        alerts.subscribe(lambda ev: received.append(ev))
        published = alerts.publish("trade_fill", {"symbol": "EURUSD"})
        assert len(received) == 1
        assert received[0]["type"] == "trade_fill"
        assert received[0]["payload"]["symbol"] == "EURUSD"
        assert received[0]["id"] == published["id"]

    def test_multiple_subscribers_all_receive(self) -> None:
        counts = [0, 0, 0]

        def make(i):
            def cb(ev):
                counts[i] += 1
            return cb

        for i in range(3):
            alerts.subscribe(make(i))
        alerts.publish("stop_hit", {})
        alerts.publish("stop_hit", {})
        assert counts == [2, 2, 2]

    def test_unsubscribe_stops_delivery(self) -> None:
        received: list[dict] = []
        sub_id = alerts.subscribe(lambda ev: received.append(ev))
        alerts.publish("trade_fill", {})
        assert alerts.unsubscribe(sub_id) is True
        alerts.publish("trade_fill", {})
        assert len(received) == 1


class TestEventTypeValidation:
    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown event_type"):
            alerts.publish("nope", {})

    def test_non_dict_payload_raises(self) -> None:
        with pytest.raises(ValueError, match="payload"):
            alerts.publish("trade_fill", ["not", "a", "dict"])  # type: ignore[arg-type]


class TestExceptionIsolation:
    def test_raising_subscriber_does_not_break_others(self) -> None:
        received: list[dict] = []
        alerts.subscribe(lambda ev: (_ for _ in ()).throw(RuntimeError("boom")))
        alerts.subscribe(lambda ev: received.append(ev))
        alerts.publish("trade_fill", {})
        assert len(received) == 1


class TestRingBuffer:
    def test_recent_returns_newest_first(self) -> None:
        for i in range(3):
            alerts.publish("trade_fill", {"i": i})
        rows = alerts.recent(3)
        assert [r["payload"]["i"] for r in rows] == [2, 1, 0]

    def test_ring_buffer_is_bounded(self) -> None:
        # Publish more than capacity; oldest events fall off.
        cap = alerts.RING_BUFFER_CAPACITY
        for i in range(cap + 15):
            alerts.publish("trade_fill", {"i": i})
        rows = alerts.recent(cap + 20)
        # Only `cap` rows retained.
        assert len(rows) == cap
        # Newest first: highest i first, and oldest 15 dropped.
        assert rows[0]["payload"]["i"] == cap + 14
        assert rows[-1]["payload"]["i"] == 15


class TestReset:
    def test_reset_clears_subscribers_and_buffer(self) -> None:
        received: list[dict] = []
        alerts.subscribe(lambda ev: received.append(ev))
        alerts.publish("trade_fill", {})
        assert len(received) == 1
        alerts.reset()
        alerts.publish("trade_fill", {})
        # Subscription was cleared by reset -- second publish should
        # not fire the pre-reset callback.
        assert len(received) == 1
        # Ring buffer starts empty from the reset; only the post-reset
        # event is retained.
        assert len(alerts.recent()) == 1


class TestThreadSafety:
    def test_concurrent_publishers_all_land(self) -> None:
        def worker():
            for _ in range(50):
                alerts.publish("trade_fill", {})

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 200 events published but ring buffer caps at RING_BUFFER_CAPACITY.
        assert len(alerts.recent(500)) == alerts.RING_BUFFER_CAPACITY
