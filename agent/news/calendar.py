"""ForexFactory weekly calendar fetcher + parser + cache.

The 3-year detector audit (data/agent_3yr_v5_M15H1.db, 2023-05 to 2026-05)
showed NY-time hour 13 bleeding -857 pips on EURUSD; a chunk of that came
from scheduled high-impact USD prints (FOMC, CPI, NFP). The blackout
module (`agent.news.blackout`) consumes events from this calendar to
prevent the rule engine from firing inside a +/-15 min window around any
high-impact USD or EUR release.

Public XML feed (no auth required):
    https://nfs.faireconomy.media/ff_calendar_thisweek.xml

Each <event> looks like:
    <event>
      <title>FOMC Statement</title>
      <country>USD</country>
      <date>05-14-2026</date>
      <time>2:00pm</time>
      <impact>High</impact>
      <forecast></forecast>
      <previous></previous>
    </event>

Times are GMT. Some entries are "All Day" or "Tentative"; we surface
those events with `time_utc=None` so callers can choose to treat them
as full-day blackouts or skip them.

The fetcher caches the parsed calendar to `data/news_calendar.json`
with a TTL (default 6h) so we don't hammer the feed during repeat
backtests. Tests use the offline fixture under
`fixtures/news/ff_calendar_sample.xml` -- CI never hits the network.
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

DEFAULT_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
DEFAULT_CACHE_PATH = Path("data/news_calendar.json")
DEFAULT_TTL_SECONDS = 6 * 60 * 60  # 6 hours

VALID_IMPACTS = {"Low", "Medium", "High", "Holiday", "Non-Economic"}


@dataclass(frozen=True)
class NewsEvent:
    """One scheduled economic event.

    Attributes:
        time_utc:   UTC datetime of the print, or None for "All Day" /
                    "Tentative" entries (which carry no specific time).
        currency:   ISO currency string ("USD", "EUR", ...).
        impact:     "High", "Medium", "Low", "Holiday", or "Non-Economic".
        title:      Human-readable event name (e.g. "FOMC Statement").
        all_day:    True for All-Day / Holiday entries with no time.
    """

    time_utc: datetime | None
    currency: str
    impact: str
    title: str
    all_day: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["time_utc"] = self.time_utc.isoformat() if self.time_utc else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "NewsEvent":
        ts = d.get("time_utc")
        if ts:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = None
        return cls(
            time_utc=dt,
            currency=d.get("currency", ""),
            impact=d.get("impact", ""),
            title=d.get("title", ""),
            all_day=bool(d.get("all_day", False)),
        )


def _parse_event_time(date_str: str, time_str: str) -> tuple[datetime | None, bool]:
    """Parse FF's `date` (MM-DD-YYYY) + `time` (e.g. '2:00pm', 'All Day',
    'Tentative') into a UTC datetime + all-day flag.

    Returns (None, True) for All-Day / Holiday entries, (None, False) for
    unparseable / Tentative entries (treated as not-time-bound), and
    (datetime, False) for normal scheduled prints.
    """
    if not date_str:
        return None, False
    time_clean = (time_str or "").strip()
    is_all_day = time_clean.lower() in ("all day", "")
    is_tentative = time_clean.lower() in ("tentative", "tbd")

    if is_all_day:
        return None, True
    if is_tentative:
        return None, False

    # Date format from the feed is "MM-DD-YYYY".
    for date_fmt in ("%m-%d-%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(date_str.strip(), date_fmt).date()
            break
        except ValueError:
            continue
    else:
        log.debug("Unparseable FF date: %r", date_str)
        return None, False

    # Time format is typically "2:00pm" / "2:00 PM" / "14:00". Normalise
    # the input (uppercase + strip spaces) so a single fmt covers both
    # "2:00pm" and "2:00PM".
    normalised = time_clean.upper().replace(" ", "")
    for time_fmt in ("%I:%M%p", "%H:%M"):
        try:
            t = datetime.strptime(normalised, time_fmt).time()
            break
        except ValueError:
            continue
    else:
        log.debug("Unparseable FF time: %r", time_str)
        return None, False

    # FF feed timestamps are GMT. Tag as UTC.
    return datetime.combine(d, t, tzinfo=timezone.utc), False


def parse_calendar_xml(xml_text: str) -> list[NewsEvent]:
    """Pure parser: XML string -> list[NewsEvent]. No I/O.

    Robust to slightly malformed events: any <event> we can't parse is
    skipped and logged at DEBUG, never raised. Empty / whitespace-only
    input yields []."""
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.warning("Failed to parse FF calendar XML: %s", e)
        return []

    events: list[NewsEvent] = []
    for el in root.findall(".//event"):
        title = (el.findtext("title") or "").strip()
        country = (el.findtext("country") or "").strip().upper()
        impact = (el.findtext("impact") or "").strip()
        date_str = (el.findtext("date") or "").strip()
        time_str = (el.findtext("time") or "").strip()
        if not country or not impact:
            continue
        if impact not in VALID_IMPACTS:
            # tolerate variant casings ("high" -> "High")
            cap = impact.capitalize()
            impact = cap if cap in VALID_IMPACTS else impact
        dt, all_day = _parse_event_time(date_str, time_str)
        events.append(NewsEvent(
            time_utc=dt,
            currency=country,
            impact=impact,
            title=title,
            all_day=all_day,
        ))
    events.sort(key=lambda e: (e.time_utc or datetime.max.replace(tzinfo=timezone.utc), e.currency))
    return events


def _read_cache(cache_path: Path) -> tuple[list[NewsEvent], datetime | None]:
    if not cache_path.exists():
        return [], None
    try:
        payload = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to read news cache %s: %s", cache_path, e)
        return [], None
    fetched_at_str = payload.get("fetched_at")
    fetched_at: datetime | None
    if fetched_at_str:
        try:
            fetched_at = datetime.fromisoformat(fetched_at_str)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        except ValueError:
            fetched_at = None
    else:
        fetched_at = None
    raw_events = payload.get("events", [])
    return [NewsEvent.from_dict(e) for e in raw_events], fetched_at


def _write_cache(cache_path: Path, events: Iterable[NewsEvent], fetched_at: datetime) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": fetched_at.isoformat(),
        "events": [e.to_dict() for e in events],
    }
    cache_path.write_text(json.dumps(payload, indent=2))


def _is_cache_fresh(fetched_at: datetime | None, ttl_seconds: int, now: datetime) -> bool:
    if fetched_at is None:
        return False
    age = (now - fetched_at).total_seconds()
    return 0 <= age < ttl_seconds


def load_calendar(cache_path: Path | str = DEFAULT_CACHE_PATH) -> list[NewsEvent]:
    """Read the cached calendar from disk. Returns [] if missing/corrupt.

    This is the cheap path used by the rule engine / dashboard at decision
    time -- they never block on the network."""
    events, _ = _read_cache(Path(cache_path))
    return events


def fetch_calendar(
    *,
    feed_url: str = DEFAULT_FEED_URL,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    force_refresh: bool = False,
    now: datetime | None = None,
    fetcher=None,
) -> list[NewsEvent]:
    """Return the parsed calendar, refreshing the cache if it's stale.

    Args:
        feed_url:       Public XML endpoint. Override for testing.
        cache_path:     Where to persist the JSON cache.
        ttl_seconds:    Cache freshness window. 6h by default.
        force_refresh:  Skip the freshness check and re-fetch unconditionally.
        now:            Override "current time" for tests.
        fetcher:        Optional callable(url) -> str (XML text). Defaults to
                        a tiny httpx-based fetcher. Inject a stub in tests so
                        CI never hits the live feed.

    Falls back to the cached events if the network call fails."""
    if now is None:
        now = datetime.now(timezone.utc)
    cache_path = Path(cache_path)

    cached_events, fetched_at = _read_cache(cache_path)
    if not force_refresh and _is_cache_fresh(fetched_at, ttl_seconds, now):
        return cached_events

    if fetcher is None:
        fetcher = _default_fetcher

    try:
        xml_text = fetcher(feed_url)
    except Exception as e:
        log.warning("News calendar fetch failed (%s); using cached %d events", e, len(cached_events))
        return cached_events

    events = parse_calendar_xml(xml_text)
    if not events:
        log.warning("News calendar fetch returned 0 events; keeping cache (%d events)", len(cached_events))
        return cached_events

    _write_cache(cache_path, events, now)
    return events


def _default_fetcher(url: str) -> str:
    """Tiny httpx-based fetcher. Imported lazily so the module is usable
    in environments without httpx (e.g. some test runners)."""
    import httpx  # type: ignore

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        resp = client.get(url, headers={"User-Agent": "eurusd-ai-agent/0.1"})
        resp.raise_for_status()
        return resp.text


def filter_events(
    events: list[NewsEvent],
    *,
    currencies: Iterable[str] | None = None,
    impact_levels: Iterable[str] | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
) -> list[NewsEvent]:
    """Convenience filter for downstream consumers (blackout, dashboard).

    Skips all-day / tentative entries when `after` or `before` is set
    (they carry no specific time and can't be windowed)."""
    cur_set = {c.upper() for c in currencies} if currencies else None
    imp_set = set(impact_levels) if impact_levels else None
    out = []
    for e in events:
        if cur_set and e.currency not in cur_set:
            continue
        if imp_set and e.impact not in imp_set:
            continue
        if (after is not None or before is not None) and e.time_utc is None:
            continue
        if after is not None and e.time_utc < after:
            continue
        if before is not None and e.time_utc > before:
            continue
        out.append(e)
    return out


def load_fixture(fixture_path: Path | str) -> list[NewsEvent]:
    """Load + parse the offline test fixture. Used by tests."""
    return parse_calendar_xml(Path(fixture_path).read_text())


# Make `timedelta` available at module level for callers that need
# to express TTLs symbolically.
__all__ = [
    "NewsEvent",
    "fetch_calendar",
    "load_calendar",
    "parse_calendar_xml",
    "filter_events",
    "load_fixture",
    "DEFAULT_FEED_URL",
    "DEFAULT_CACHE_PATH",
    "DEFAULT_TTL_SECONDS",
    "timedelta",
]
