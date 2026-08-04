"""End-to-end mt5-path regression for the 2026-08-04 live fixes.

Replays the exact failure shape of the Jul 28 - Aug 3 live week
through the REAL ``run_loop`` + ``Mt5Feed`` (only the broker is fake):

* startup hydrates ``prepare()`` from broker history,
* the first poll emits the newest already-closed bar (catch-up),
* a later poll delivers a bar that closed AFTER startup.

Before the fixes, that post-startup bar (and every bar after it,
forever) was invisible to all bar-based agents: it missed their frozen
``index_by_ts`` and the whole roster abstained with ``timestamp_miss``
at confidence 0.00 -- an entire week with 0 proposals. The runner also
mixed the feed's sliding-window bar indices into the engine's
append-only history, overwriting historical bars.

Pinned here: the live loop processes both bars, no ``timestamp_miss``
ever lands on the tape, and state advances to the newest bar.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_squad_live  # noqa: E402

from agent.types import Bar, Timeframe  # noqa: E402

UTC = timezone.utc
START = datetime(2024, 1, 2, tzinfo=UTC)


def _bar(t: datetime) -> Bar:
    return Bar(time=t, open=1.10, high=1.11, low=1.09, close=1.105,
               volume=100.0, timeframe=Timeframe.H4)


def _series(n: int, start: datetime = START) -> list[Bar]:
    return [_bar(start + timedelta(hours=4 * i)) for i in range(n)]


class _ScriptedMt5Broker:
    """Read-only broker double: history at boot, one new close later.

    ``get_latest_bars`` returns closed bars PLUS the forming bar, like
    the real MT5 adapter. From the ``grow_after``-th H4 refresh call
    onward the series has grown by one closed bar -- i.e. an H4 bar
    closed while the loop was polling.
    """

    def __init__(self, hist: list[Bar], grow_after: int = 2):
        self._hist = list(hist)
        self._grow_after = int(grow_after)
        self._h4_calls = 0
        last = hist[-1].time
        self._new_closed = _bar(last + timedelta(hours=4))
        self._forming_1 = _bar(last + timedelta(hours=4))
        self._forming_2 = _bar(last + timedelta(hours=8))

    async def get_latest_bars(self, symbol: str, timeframe: str, count: int = 0):
        if timeframe != "H4":
            return []
        self._h4_calls += 1
        if self._h4_calls <= self._grow_after:
            return self._hist + [self._forming_1]
        return self._hist + [self._new_closed, self._forming_2]

    async def disconnect(self):
        return None


def _args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        feed="mt5",
        aggregator="phi41",
        symbols=["EURUSD"],
        poll=0.01,
        cache_bars_per_poll=1,
        out_dir=tmp_path / "squad_live",
        max_steps=2,
        feed_stale_hours=9.0,
        reset=False,
        no_telegram=True,
        parity_mode=False,
        enable_sae=False,
        burn_in_bars=0,
        refresh_news=False,
        no_news_refresh=True,
        news_refresh_seconds=3600,
        verbose=False,
    )


def test_run_loop_mt5_sees_post_startup_bars(tmp_path, monkeypatch):
    hist = _series(210)
    broker = _ScriptedMt5Broker(hist)

    async def _fake_connect(cfg_live=None):  # noqa: ARG001
        return broker

    monkeypatch.setattr(run_squad_live, "_connect_mt5", _fake_connect)

    outcome = run_squad_live.run_loop(_args(tmp_path), cfg={})
    assert outcome == "max_steps"

    out_dir = tmp_path / "squad_live"
    tape = (out_dir / "events.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(x) for x in tape.splitlines() if x]
    summaries = [r for r in rows if r.get("type") == "tick_summary"]

    # Both the catch-up bar (hist[-1]) and the post-startup close made
    # it onto the tape...
    times = {r["timestamp"] for r in summaries}
    assert hist[-1].time.isoformat() in times
    assert broker._new_closed.time.isoformat() in times

    # ...and NOTHING on the tape is a timestamp_miss abstain. This is
    # the exact regression: last week's tape had 160 of them.
    assert "timestamp_miss" not in tape

    # State advanced to the newest closed bar (resume cursor correct).
    state = json.loads((out_dir / "state.json").read_text(encoding="utf-8"))
    assert state["last_bar_times"]["EURUSD"] == (
        broker._new_closed.time.isoformat()
    )


# ---------------------------------------------------------------------------
# Feed-outage resilience (2026-08-04 hardening)
# ---------------------------------------------------------------------------


class _FlakyMt5Broker(_ScriptedMt5Broker):
    """Scripted broker whose H4 reads raise on selected refresh attempts.

    The Aug 3 DNS outage shape: reads start failing mid-session, then the
    network comes back. Before the hardening, the first raise escaped
    ``run_loop`` and killed the process.
    """

    def __init__(self, hist: list[Bar], fail_on: set[int], grow_after: int = 2):
        super().__init__(hist, grow_after=grow_after)
        self._fail_on = set(fail_on)

    async def get_latest_bars(self, symbol: str, timeframe: str, count: int = 0):
        if timeframe == "H4" and (self._h4_calls + 1) in self._fail_on:
            self._h4_calls += 1
            raise ConnectionError("simulated MT5 IPC read failure")
        return await super().get_latest_bars(symbol, timeframe, count)


def _patch_sleep(monkeypatch, hook=None) -> list[float]:
    """No-op ``time.sleep`` inside run_squad_live (records durations)."""
    slept: list[float] = []

    def _sleep(seconds: float) -> None:
        slept.append(float(seconds))
        if hook is not None:
            hook()

    monkeypatch.setattr(
        run_squad_live, "time", SimpleNamespace(sleep=_sleep),
    )
    return slept


def test_run_loop_survives_transient_refresh_errors(tmp_path, monkeypatch):
    hist = _series(210)
    # H4 read #1 = startup, #2 = first loop poll (emits the catch-up
    # bar), #3 and #4 raise mid-session, #5 recovers with a new close.
    broker = _FlakyMt5Broker(hist, fail_on={3, 4}, grow_after=4)

    async def _fake_connect(cfg_live=None):  # noqa: ARG001
        return broker

    monkeypatch.setattr(run_squad_live, "_connect_mt5", _fake_connect)
    slept = _patch_sleep(monkeypatch)

    outcome = run_squad_live.run_loop(_args(tmp_path), cfg={})
    assert outcome == "max_steps", (
        "a transient feed read error must not kill the loop"
    )

    tape = (tmp_path / "squad_live" / "events.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(x) for x in tape.splitlines() if x]
    feed_rows = [
        r for r in rows
        if r.get("type") == "system_status"
        and r.get("component") == "market_feed"
    ]
    statuses = [r["status"] for r in feed_rows]
    assert statuses.count("refresh_error") == 2, statuses
    assert "recovered" in statuses, (
        "recovery must be visible on the tape, not just in the log"
    )
    streaks = [r["failure_streak"] for r in feed_rows
               if r["status"] == "refresh_error"]
    assert streaks == [1, 2]
    # Bounded exponential backoff was applied (60s then 120s).
    assert 60.0 in slept and 120.0 in slept

    # The post-outage closed bar was still processed (catch-up worked).
    assert broker._new_closed.time.isoformat() in tape


def test_run_loop_tapes_feed_staleness(tmp_path, monkeypatch):
    hist = _series(210)
    broker = _ScriptedMt5Broker(hist, grow_after=10_000)  # feed starves

    async def _fake_connect(cfg_live=None):  # noqa: ARG001
        return broker

    monkeypatch.setattr(run_squad_live, "_connect_mt5", _fake_connect)

    class _FixedNow(datetime):
        """Pin 'now' to a Tuesday so the weekend gap can't suppress."""

        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 4, 12, 0, tzinfo=tz)

    monkeypatch.setattr(run_squad_live, "datetime", _FixedNow)

    out_dir = tmp_path / "squad_live"
    kill = out_dir / "kill.txt"

    def _stop_once_stale() -> None:
        events = out_dir / "events.jsonl"
        if events.exists() and '"stale"' in events.read_text(encoding="utf-8"):
            kill.write_text("test-stop", encoding="utf-8")

    _patch_sleep(monkeypatch, hook=_stop_once_stale)

    args = _args(tmp_path)
    args.max_steps = None  # let the loop idle so staleness can trigger
    outcome = run_squad_live.run_loop(args, cfg={})
    assert outcome == "killed"

    rows = [
        json.loads(x)
        for x in (out_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if x
    ]
    stale = [
        r for r in rows
        if r.get("type") == "system_status"
        and r.get("component") == "market_feed"
        and r.get("status") == "stale"
    ]
    assert len(stale) == 1, "staleness must be taped exactly once per episode"
    assert stale[0]["threshold_hours"] == 9.0
    assert stale[0]["age_hours"] > 9.0


def test_weekend_gap_window():
    gap = run_squad_live._in_weekend_gap
    UTC_ = timezone.utc
    assert gap(datetime(2026, 8, 1, 12, 0, tzinfo=UTC_))       # Saturday
    assert gap(datetime(2026, 7, 31, 20, 30, tzinfo=UTC_))     # late Friday
    assert gap(datetime(2026, 8, 2, 21, 0, tzinfo=UTC_))       # Sunday pre-open
    assert not gap(datetime(2026, 8, 2, 22, 30, tzinfo=UTC_))  # Sunday open
    assert not gap(datetime(2026, 7, 31, 12, 0, tzinfo=UTC_))  # Friday midday
    assert not gap(datetime(2026, 8, 4, 12, 0, tzinfo=UTC_))   # Tuesday
