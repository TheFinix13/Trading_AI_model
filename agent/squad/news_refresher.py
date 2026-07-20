"""Non-blocking news-calendar refresher for the live squad runtime.

The tick loop in ``scripts/run_squad_live.py`` must never block on
network I/O. Karasu's advisories depend on the ForexFactory cache
(``data/news_calendar.json`` by default); the refresher spins a small
background thread that periodically calls
:func:`agent.news.calendar.refresh_cache_if_stale` and, on success,
re-hydrates any registered Karasu instances via ``load_calendar()``.

Failures are logged (``log.warning``) but never raised into the tick
loop -- Karasu's fail-open contract keeps R7 pass-through when the
cache is empty / stale.

Typical wiring::

    refresher = NewsFeedRefresher(
        karasu=roster.karasu,
        cache_path=news_cfg.cache_path,
        feed_url=news_cfg.feed_url,
        ttl_seconds=news_cfg.cache_ttl_seconds,
        interval_seconds=3600,   # once per hour
    )
    refresher.kickoff()          # one immediate refresh + hydrate
    refresher.start()            # background thread every interval

    ... tick loop ...

    refresher.stop()             # graceful shutdown

The refresher is a daemon thread; if the main process exits without
calling ``stop()`` it will not block shutdown.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent.news.calendar import (
    DEFAULT_FEED_URL,
    DEFAULT_TTL_SECONDS,
    NewsEvent,
    refresh_cache_if_stale,
)
from agent.squad.agents.a08_karasu import A8KarasuV1


log = logging.getLogger(__name__)


class NewsFeedRefresher:
    """Background refresher for the news calendar cache.

    Attributes:
        karasu:           Karasu instance to re-hydrate on each
                          successful refresh. Optional -- when None,
                          the refresher only writes to the on-disk
                          cache and callers can pull it themselves.
        cache_path:       Where the JSON cache lives.
        feed_url:         Upstream feed.
        ttl_seconds:      Passed to ``fetch_calendar``.
        interval_seconds: Sleep between refresh attempts on the
                          background thread. Default 3600 (1 h).
        fetcher:          Optional injectable fetcher(url)->xml_text
                          for tests.
    """

    def __init__(
        self,
        *,
        karasu: Optional[A8KarasuV1] = None,
        cache_path: Path | str = "data/news_calendar.json",
        feed_url: str = DEFAULT_FEED_URL,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        interval_seconds: float = 3600.0,
        fetcher=None,
    ) -> None:
        self.karasu = karasu
        self.cache_path = Path(cache_path)
        self.feed_url = feed_url
        self.ttl_seconds = int(ttl_seconds)
        self.interval_seconds = float(interval_seconds)
        self.fetcher = fetcher
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_refresh: datetime | None = None
        self._last_event_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def kickoff(self) -> int:
        """One synchronous refresh + Karasu hydration.

        Called BEFORE ``start()`` so Karasu has data on the very
        first tick without waiting for the interval to elapse.
        Returns the number of events loaded (may be 0 if the fetch
        fails and no cache exists yet -- Karasu is fail-open).
        """
        n = self._refresh_once()
        if self.karasu is not None:
            self.karasu.load_calendar(
                cache_path=self.cache_path,
                cache_fetched_at=self._last_refresh,
            )
        return n

    def start(self) -> None:
        """Spawn the daemon background thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="NewsFeedRefresher",
            daemon=True,
        )
        self._thread.start()

    def stop(self, join_timeout: float = 5.0) -> None:
        """Signal the thread to exit and join briefly."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=join_timeout)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_refresh(self) -> datetime | None:
        return self._last_refresh

    @property
    def last_event_count(self) -> int:
        return int(self._last_event_count)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _refresh_once(self) -> int:
        try:
            events: list[NewsEvent] = refresh_cache_if_stale(
                feed_url=self.feed_url,
                cache_path=self.cache_path,
                ttl_seconds=self.ttl_seconds,
                fetcher=self.fetcher,
            )
        except Exception as exc:   # noqa: BLE001
            log.warning(
                "NewsFeedRefresher: refresh failed (%s); Karasu will"
                " read the cache as-is.", exc,
            )
            return 0
        self._last_refresh = datetime.now(tz=timezone.utc)
        self._last_event_count = len(events)
        log.info(
            "NewsFeedRefresher: %d events cached at %s",
            self._last_event_count, self.cache_path,
        )
        return self._last_event_count

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._stop.wait(timeout=self.interval_seconds):
                return
            n = self._refresh_once()
            if self.karasu is not None:
                try:
                    self.karasu.load_calendar(
                        cache_path=self.cache_path,
                        cache_fetched_at=self._last_refresh,
                    )
                except Exception as exc:   # noqa: BLE001
                    log.warning(
                        "NewsFeedRefresher: Karasu hydration failed (%s)",
                        exc,
                    )
                    continue
            log.debug(
                "NewsFeedRefresher tick: %d events, karasu=%s",
                n, "yes" if self.karasu else "no",
            )


__all__ = ["NewsFeedRefresher"]
