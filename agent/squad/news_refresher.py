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
from typing import Callable, Optional

from agent.news.calendar import (
    DEFAULT_CACHE_PATH,
    DEFAULT_FEED_URL,
    DEFAULT_TTL_SECONDS,
    NewsEvent,
    cache_fetched_at,
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
        sae:              Sae instance to re-hydrate alongside Karasu.
                          Optional (backward compat with karasu-only
                          call sites). Hydration is cheap and harmless
                          when Sae is disabled -- he simply holds the
                          event list without ever proposing.
        cache_path:       Where the JSON cache lives.
        feed_url:         Upstream feed.
        ttl_seconds:      Passed to ``fetch_calendar``.
        interval_seconds: Sleep between refresh attempts on the
                          background thread. Default 3600 (1 h).
        fetcher:          Optional injectable fetcher(url)->xml_text
                          for tests.
        status_sink:      Optional callable(row: dict) invoked after
                          every refresh attempt that finds the cache
                          MISSING or STALE (older than 2x TTL). The
                          row is a structured ``system_status`` event
                          carrying ``failure_streak`` so the caller
                          can rate-limit operator pages (notify on
                          streak==1, i.e. once per failure streak,
                          not per poll). Never invoked on healthy
                          checks; the streak resets to 0 there.
    """

    def __init__(
        self,
        *,
        karasu: Optional[A8KarasuV1] = None,
        sae=None,
        cache_path: Path | str = DEFAULT_CACHE_PATH,
        feed_url: str = DEFAULT_FEED_URL,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        interval_seconds: float = 3600.0,
        fetcher=None,
        status_sink: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.karasu = karasu
        self.sae = sae
        self.cache_path = Path(cache_path)
        self.feed_url = feed_url
        self.ttl_seconds = int(ttl_seconds)
        self.interval_seconds = float(interval_seconds)
        self.fetcher = fetcher
        self.status_sink = status_sink
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_refresh: datetime | None = None
        self._last_event_count: int = 0
        self._failure_streak: int = 0

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
        self._hydrate_sae()
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

    @property
    def failure_streak(self) -> int:
        return int(self._failure_streak)

    def cache_health(self) -> dict:
        """Freshness verdict on the on-disk cache.

        ``status`` is ``"ok"`` / ``"stale"`` (fetched_at older than
        2x TTL -- the fetch path has been failing for a while) /
        ``"missing"`` (no readable cache at all). ``fetch_calendar``
        swallows network failures by design (fail-open on the cached
        events), so the cache's own fetched_at age is the only honest
        health signal available here.
        """
        now = datetime.now(tz=timezone.utc)
        fetched_at = cache_fetched_at(self.cache_path)
        stale_after = 2.0 * float(self.ttl_seconds)
        if fetched_at is None:
            return {
                "status": "missing",
                "fetched_age_seconds": None,
                "stale_after_seconds": stale_after,
            }
        age = (now - fetched_at).total_seconds()
        return {
            "status": "ok" if age <= stale_after else "stale",
            "fetched_age_seconds": age,
            "stale_after_seconds": stale_after,
        }

    def _check_cache_health(self) -> None:
        health = self.cache_health()
        if health["status"] == "ok":
            self._failure_streak = 0
            return
        self._failure_streak += 1
        age = health["fetched_age_seconds"]
        log.warning(
            "news calendar cache %s (age=%s, streak=%d) -- Karasu/Sae "
            "advisories may be running blind",
            health["status"],
            f"{age:.0f}s" if age is not None else "n/a",
            self._failure_streak,
        )
        if self.status_sink is None:
            return
        row = {
            "type": "system_status",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "component": "news_calendar",
            "status": health["status"],
            "failure_streak": int(self._failure_streak),
            "cache_age_seconds": (
                round(age, 1) if age is not None else None
            ),
            "message": (
                f"news calendar cache {health['status']} "
                f"(threshold {health['stale_after_seconds']:.0f}s)"
            ),
        }
        try:
            self.status_sink(row)
        except Exception as exc:   # noqa: BLE001
            log.warning("NewsFeedRefresher: status sink failed (%s)", exc)

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
            self._check_cache_health()
            return 0
        self._last_refresh = datetime.now(tz=timezone.utc)
        self._last_event_count = len(events)
        log.info(
            "NewsFeedRefresher: %d events cached at %s",
            self._last_event_count, self.cache_path,
        )
        # fetch_calendar fails open (returns stale cache on network
        # errors), so success of the call above is NOT proof of a
        # fresh feed -- verify the cache stamp itself.
        self._check_cache_health()
        return self._last_event_count

    def _hydrate_sae(self) -> None:
        """Re-hydrate Sae from the on-disk cache. Fail-open like Karasu."""
        if self.sae is None:
            return
        try:
            self.sae.load_calendar(cache_path=self.cache_path)
        except Exception as exc:   # noqa: BLE001
            log.warning(
                "NewsFeedRefresher: Sae hydration failed (%s)", exc,
            )

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
                    self._hydrate_sae()
                    continue
            self._hydrate_sae()
            log.debug(
                "NewsFeedRefresher tick: %d events, karasu=%s sae=%s",
                n, "yes" if self.karasu else "no",
                "yes" if self.sae else "no",
            )


__all__ = ["NewsFeedRefresher"]
