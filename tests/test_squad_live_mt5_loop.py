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
