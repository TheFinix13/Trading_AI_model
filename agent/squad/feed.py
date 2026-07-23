"""Market feed abstraction for the squad live paper runtime.

Ported concerns — no research analogue (research harness loads bars
from the parquet cache via ``_load_production_bars``). Feeds:

* ``cache`` — replay historical H4 bars from ``agent.data.loader.BarLoader``
  (default on non-Windows). Accelerated for local testing.
* ``mt5``   — pull latest H4 bars via the existing read-only broker
  adapter (``agent.live.broker``). Shadow-only: never places orders.
  Default on Windows.
* ``fake``  — synthetic bars for unit / e2e tests.

All feeds yield closed bars only. The live runtime is responsible for
detecting "new closed H4" and calling ``SquadEngine.on_bar(...)``.
"""
from __future__ import annotations

import platform
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Sequence

from agent.config import load_config
from agent.data.loader import BarLoader
from agent.types import Bar, Timeframe

DEFAULT_SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDCAD")


def default_feed_name() -> str:
    """``mt5`` on Windows (where MT5 lives); ``cache`` elsewhere."""
    return "mt5" if sys.platform.startswith("win") else "cache"


@dataclass(frozen=True)
class FeedBar:
    """One closed bar tagged with its symbol."""

    symbol: str
    bar: Bar
    bar_index: int  # index within that symbol's series (for next-bar open)


class MarketFeed(ABC):
    """Abstract closed-bar source."""

    @abstractmethod
    def warmup_bars(self) -> dict[str, list[Bar]]:
        """Full history needed for ``agent.prepare()`` (all symbols)."""
        ...

    @abstractmethod
    def poll_new_closed(self) -> list[FeedBar]:
        """Return newly closed H4 bars since last poll (may be empty)."""
        ...

    def close(self) -> None:
        """Optional cleanup."""
        return None


class CacheFeed(MarketFeed):
    """Replay parquet-cached H4 bars chronologically.

    On each ``poll_new_closed`` call, emits the next N interleaved
    closed bars (default 1 wall-tick -> 1 global bar) so the live
    loop can sleep between polls for accelerated local testing.
    """

    def __init__(
        self,
        *,
        symbols: Sequence[str] = DEFAULT_SYMBOLS,
        start: datetime | None = None,
        end: datetime | None = None,
        cache_root: Path | None = None,
        bars_per_poll: int = 1,
        warmup: int = 200,
    ) -> None:
        self.symbols = tuple(symbols)
        self.bars_per_poll = max(1, int(bars_per_poll))
        self.warmup = int(warmup)
        cfg = load_config()
        root = cache_root or cfg.data_dir
        loader = BarLoader(cache_root=root)
        end = end or datetime.now(tz=timezone.utc)
        start = start or (end - timedelta(days=365 * 11))
        self._bars: dict[str, list[Bar]] = {}
        for sym in self.symbols:
            self._bars[sym] = loader.get_bars(sym, Timeframe.H4, start, end)
        # Interleaved stream by (time, symbol), skipping first ``warmup``.
        flat: list[FeedBar] = []
        for sym, bars in self._bars.items():
            for i, b in enumerate(bars):
                if i < self.warmup:
                    continue
                if i >= len(bars) - 1:
                    continue  # need a next bar to open
                flat.append(FeedBar(symbol=sym, bar=b, bar_index=i))
        flat.sort(key=lambda fb: (fb.bar.time, fb.symbol))
        self._stream = flat
        self._cursor = 0
        self._emitted_keys: set[tuple[str, datetime]] = set()

    def warmup_bars(self) -> dict[str, list[Bar]]:
        return {sym: list(bars) for sym, bars in self._bars.items()}

    def poll_new_closed(self) -> list[FeedBar]:
        out: list[FeedBar] = []
        while self._cursor < len(self._stream) and len(out) < self.bars_per_poll:
            fb = self._stream[self._cursor]
            self._cursor += 1
            key = (fb.symbol, fb.bar.time)
            if key in self._emitted_keys:
                continue
            self._emitted_keys.add(key)
            out.append(fb)
        return out

    def seek(self, cursor: int) -> None:
        """Resume support -- set the interleaved stream cursor."""
        self._cursor = max(0, min(int(cursor), len(self._stream)))

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def remaining(self) -> int:
        return max(0, len(self._stream) - self._cursor)


class FakeFeed(MarketFeed):
    """Push-driven synthetic feed for unit / e2e tests."""

    def __init__(
        self,
        bars_by_symbol: dict[str, list[Bar]] | None = None,
        *,
        warmup: int = 0,
    ) -> None:
        self._bars = {s: list(b) for s, b in (bars_by_symbol or {}).items()}
        self.warmup = int(warmup)
        self._queue: list[FeedBar] = []
        self._indices: dict[str, int] = {s: 0 for s in self._bars}

    def warmup_bars(self) -> dict[str, list[Bar]]:
        return {s: list(b) for s, b in self._bars.items()}

    def push(self, symbol: str, bar: Bar) -> None:
        """Append a closed bar for ``symbol`` and queue it for the next poll."""
        series = self._bars.setdefault(symbol, [])
        series.append(bar)
        idx = len(series) - 1
        self._indices[symbol] = idx
        if idx >= self.warmup:
            self._queue.append(FeedBar(symbol=symbol, bar=bar, bar_index=idx))

    def poll_new_closed(self) -> list[FeedBar]:
        out = list(self._queue)
        self._queue.clear()
        return out

    def seed(self, bars_by_symbol: dict[str, list[Bar]]) -> None:
        """Replace the internal series (does not auto-queue)."""
        self._bars = {s: list(b) for s, b in bars_by_symbol.items()}
        self._indices = {s: max(0, len(b) - 1) for s, b in self._bars.items()}
        self._queue.clear()


class Mt5Feed(MarketFeed):
    """Read-only H4 pull via the existing broker adapter.

    Requires a connected ``BrokerConnection``. Never calls
    ``place_order`` / ``close_position`` / ``modify_position``.
    """

    def __init__(
        self,
        broker,
        *,
        symbols: Sequence[str] = DEFAULT_SYMBOLS,
        history_bars: int = 500,
        lookback_for_prepare: int = 2500,
        m15_symbols: Sequence[str] = (),
        m15_lookback: int = 64,
    ) -> None:
        self.broker = broker
        self.symbols = tuple(symbols)
        self.history_bars = int(history_bars)
        self.lookback_for_prepare = int(lookback_for_prepare)
        # Symbols for which refresh() also pulls a small M15 window
        # (read-only) so Sae's event mechanics have intra-H4 bars.
        # Empty by default -- the extra pull is opt-in per symbol.
        self.m15_symbols = tuple(m15_symbols)
        self.m15_lookback = int(m15_lookback)
        self._last_closed: dict[str, datetime] = {}
        self._cache: dict[str, list[Bar]] = {s: [] for s in self.symbols}
        self._m15_cache: dict[str, list[Bar]] = {s: [] for s in self.m15_symbols}
        # Forming (in-progress) bar per symbol — used as the fill bar
        # (next open) when a newly closed H4 is processed live.
        self._forming: dict[str, Bar | None] = {s: None for s in self.symbols}

    def warmup_bars(self) -> dict[str, list[Bar]]:
        # Synchronous helper: caller should have an event loop. We keep
        # a sync facade that expects the broker already populated the
        # cache via ``await refresh()``; otherwise we fall through to
        # the parquet cache so local Macs without MT5 don't blow up.
        if any(self._cache.values()):
            return {s: list(b) for s, b in self._cache.items()}
        # Fallback: parquet cache under the trading-repo data dir.
        fallback = CacheFeed(symbols=self.symbols)
        return fallback.warmup_bars()

    async def refresh(self) -> None:
        """Pull latest bars for every symbol into the local cache."""
        for sym in self.symbols:
            bars = await self.broker.get_latest_bars(
                sym, "H4", count=self.lookback_for_prepare,
            )
            if not bars:
                continue
            if len(bars) >= 2:
                self._cache[sym] = list(bars[:-1])
                self._forming[sym] = bars[-1]
            else:
                self._cache[sym] = list(bars)
                self._forming[sym] = None
        for sym in self.m15_symbols:
            m15 = await self.broker.get_latest_bars(
                sym, "M15", count=self.m15_lookback,
            )
            if m15:
                self._m15_cache[sym] = list(m15)

    def m15_bars(self, symbol: str, start_utc: datetime, end_utc: datetime) -> list[Bar]:
        """Sae ``BarsProvider`` contract: M15 bars whose open time falls
        in ``[start_utc, end_utc]``, ascending. Read-only view over the
        cache populated by ``refresh()`` -- never a broker round-trip,
        so it is safe to call from the synchronous ``intend()`` path.
        Returns [] for symbols outside ``m15_symbols`` (Sae fail-open)."""
        def _utc(dt: datetime) -> datetime:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        start_utc = _utc(start_utc)
        end_utc = _utc(end_utc)
        out = [
            b for b in self._m15_cache.get(symbol, ())
            if start_utc <= _utc(b.time) <= end_utc
        ]
        out.sort(key=lambda b: b.time)
        return out

    def forming_bar(self, symbol: str) -> Bar | None:
        """In-progress H4 bar (fill proxy for the just-closed bar)."""
        return self._forming.get(symbol)

    def poll_new_closed(self) -> list[FeedBar]:
        out: list[FeedBar] = []
        for sym in self.symbols:
            series = self._cache.get(sym) or []
            if len(series) < 2:
                continue
            last = series[-1]
            prev = self._last_closed.get(sym)
            if prev is not None and last.time <= prev:
                continue
            self._last_closed[sym] = last.time
            out.append(FeedBar(symbol=sym, bar=last, bar_index=len(series) - 1))
        out.sort(key=lambda fb: (fb.bar.time, fb.symbol))
        return out

    def mark_seen(self, symbol: str, when: datetime) -> None:
        """Resume support -- don't re-emit bars at or before ``when``."""
        self._last_closed[symbol] = when


def make_feed(
    name: str | None = None,
    *,
    symbols: Sequence[str] = DEFAULT_SYMBOLS,
    broker=None,
    **kwargs,
) -> MarketFeed:
    """Factory. ``name=None`` picks the platform default."""
    name = (name or default_feed_name()).lower()
    if name == "cache":
        return CacheFeed(symbols=symbols, **kwargs)
    if name == "fake":
        return FakeFeed(**kwargs)
    if name == "mt5":
        if broker is None:
            raise ValueError("Mt5Feed requires a connected broker instance")
        return Mt5Feed(broker, symbols=symbols, **{
            k: v for k, v in kwargs.items()
            if k in ("history_bars", "lookback_for_prepare",
                     "m15_symbols", "m15_lookback")
        })
    raise ValueError(f"unknown feed: {name!r} (expected cache|mt5|fake)")


__all__ = [
    "CacheFeed",
    "DEFAULT_SYMBOLS",
    "FakeFeed",
    "FeedBar",
    "MarketFeed",
    "Mt5Feed",
    "default_feed_name",
    "make_feed",
]
