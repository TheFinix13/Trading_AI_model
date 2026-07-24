"""Calendar robustness + failure visibility (F5/F6).

Two invisible-failure modes are closed here:

* The news cache path was CWD-relative (``data/news_calendar.json``),
  so a runner launched from the wrong directory silently read/wrote a
  different file. The default is now anchored at the repo root, with a
  read-only legacy fallback for pre-anchoring deployments.
* Calendar fetch failures were console-only ``log.warning`` lines. The
  refresher now emits structured ``system_status`` rows (missing /
  stale cache) through a sink; the live runner appends them to
  ``events.jsonl`` and pages Telegram once per failure streak.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.news import calendar as cal
from agent.news.calendar import (
    DEFAULT_TTL_SECONDS,
    NewsEvent,
    cache_fetched_at,
    load_calendar,
    resolve_cache_path,
)
from agent.platform.event_schema import EVENT_TYPES, validate_event
from agent.platform.squad_events import build_timeline
from agent.squad.news_refresher import NewsFeedRefresher

UTC = timezone.utc

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<weeklyevents>
  <event>
    <title>FOMC Statement</title>
    <country>USD</country>
    <date>07-24-2026</date>
    <time>6:00pm</time>
    <impact>High</impact>
  </event>
</weeklyevents>
"""


def _write_cache(path: Path, *, fetched_at: datetime) -> None:
    events = [NewsEvent(
        time_utc=datetime(2026, 7, 24, 18, 0, tzinfo=UTC),
        currency="USD", impact="High", title="FOMC Statement",
    )]
    cal._write_cache(path, events, fetched_at)


# ---------------------------------------------------------------------------
# 1. Path anchoring + legacy fallback
# ---------------------------------------------------------------------------

def test_default_cache_path_is_anchored_at_repo_root():
    assert cal.DEFAULT_CACHE_PATH.is_absolute()
    assert cal.DEFAULT_CACHE_PATH == (
        Path(cal.__file__).resolve().parents[2] / "data" / "news_calendar.json"
    )


def test_legacy_cwd_relative_cache_read_when_default_missing(
        tmp_path: Path, monkeypatch):
    """Pre-anchoring deployments left the cache in the launch CWD; a
    boot from that CWD must still read it until a fetch migrates it."""
    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "data" / "news_calendar.json"
    legacy.parent.mkdir()
    _write_cache(legacy, fetched_at=datetime.now(tz=UTC))

    anchored = tmp_path / "anchored" / "news_calendar.json"  # absent
    monkeypatch.setattr(cal, "DEFAULT_CACHE_PATH", anchored)

    assert resolve_cache_path(anchored) == cal.LEGACY_CACHE_PATH
    events = load_calendar(anchored)
    assert len(events) == 1
    assert events[0].title == "FOMC Statement"
    assert cache_fetched_at(anchored) is not None


def test_anchored_cache_wins_over_legacy_when_present(
        tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "data" / "news_calendar.json"
    legacy.parent.mkdir()
    _write_cache(legacy, fetched_at=datetime.now(tz=UTC))

    anchored = tmp_path / "anchored" / "news_calendar.json"
    anchored.parent.mkdir()
    _write_cache(anchored, fetched_at=datetime.now(tz=UTC))
    monkeypatch.setattr(cal, "DEFAULT_CACHE_PATH", anchored)

    assert resolve_cache_path(anchored) == anchored


def test_explicit_custom_path_never_redirected(tmp_path: Path, monkeypatch):
    """Caller-supplied paths keep exact-path semantics (tests, custom
    deployments) even when a legacy CWD file exists."""
    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "data" / "news_calendar.json"
    legacy.parent.mkdir()
    _write_cache(legacy, fetched_at=datetime.now(tz=UTC))

    custom = tmp_path / "elsewhere" / "cal.json"  # absent
    assert resolve_cache_path(custom) == custom
    assert load_calendar(custom) == []


def test_fetch_writes_anchored_path_migrating_off_legacy(
        tmp_path: Path, monkeypatch):
    """A successful fetch writes the caller's (anchored) path so the
    legacy fallback stops being consulted afterwards."""
    monkeypatch.chdir(tmp_path)
    anchored = tmp_path / "anchored" / "news_calendar.json"
    monkeypatch.setattr(cal, "DEFAULT_CACHE_PATH", anchored)
    events = cal.fetch_calendar(
        cache_path=anchored, fetcher=lambda _url: SAMPLE_XML,
    )
    assert len(events) == 1
    assert anchored.exists()


# ---------------------------------------------------------------------------
# 2. Failure -> structured system_status rows
# ---------------------------------------------------------------------------

def _failing_fetcher(_url: str) -> str:
    raise ConnectionError("feed down")


def test_missing_cache_emits_system_status_row(tmp_path: Path):
    rows: list[dict] = []
    refresher = NewsFeedRefresher(
        cache_path=tmp_path / "absent.json",
        fetcher=_failing_fetcher,
        status_sink=rows.append,
    )
    refresher.kickoff()
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "system_status"
    assert row["component"] == "news_calendar"
    assert row["status"] == "missing"
    assert row["failure_streak"] == 1
    assert row["cache_age_seconds"] is None


def test_stale_cache_emits_stale_status(tmp_path: Path):
    cache = tmp_path / "cal.json"
    # Older than 2x TTL (default 6 h -> threshold 12 h).
    _write_cache(cache, fetched_at=datetime.now(tz=UTC) - timedelta(hours=13))
    rows: list[dict] = []
    refresher = NewsFeedRefresher(
        cache_path=cache,
        fetcher=_failing_fetcher,
        status_sink=rows.append,
    )
    refresher.kickoff()
    assert len(rows) == 1
    assert rows[0]["status"] == "stale"
    assert rows[0]["cache_age_seconds"] > 2 * DEFAULT_TTL_SECONDS


def test_failure_streak_counts_and_resets(tmp_path: Path):
    cache = tmp_path / "cal.json"
    rows: list[dict] = []
    refresher = NewsFeedRefresher(
        cache_path=cache,
        fetcher=_failing_fetcher,
        status_sink=rows.append,
    )
    refresher.kickoff()
    refresher._refresh_once()
    assert [r["failure_streak"] for r in rows] == [1, 2]

    # Feed recovers -> healthy check resets the streak silently.
    refresher.fetcher = lambda _url: SAMPLE_XML
    refresher._refresh_once()
    assert refresher.failure_streak == 0
    assert len(rows) == 2  # no row on healthy

    # Next outage starts a NEW streak at 1 (rate-limit anchor).
    cache.unlink()
    refresher.fetcher = _failing_fetcher
    refresher._refresh_once()
    assert rows[-1]["failure_streak"] == 1


def test_fresh_cache_emits_nothing(tmp_path: Path):
    cache = tmp_path / "cal.json"
    _write_cache(cache, fetched_at=datetime.now(tz=UTC))
    rows: list[dict] = []
    refresher = NewsFeedRefresher(
        cache_path=cache,
        fetcher=_failing_fetcher,   # fetch fails, but cache is fresh
        status_sink=rows.append,
    )
    refresher.kickoff()
    assert rows == []
    assert refresher.failure_streak == 0


def test_status_sink_errors_fail_open(tmp_path: Path):
    def _exploding_sink(_row: dict) -> None:
        raise RuntimeError("disk full")

    refresher = NewsFeedRefresher(
        cache_path=tmp_path / "absent.json",
        fetcher=_failing_fetcher,
        status_sink=_exploding_sink,
    )
    refresher.kickoff()  # must not raise into the tick loop


# ---------------------------------------------------------------------------
# 3. Runner sink: events.jsonl append + once-per-streak Telegram
# ---------------------------------------------------------------------------

class _FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def notify_system(self, text: str) -> None:
        self.messages.append(text)


def _runner_sink(out_dir: Path, notifier):
    import sys
    repo = Path(__file__).resolve().parents[1]
    if str(repo / "scripts") not in sys.path:
        sys.path.insert(0, str(repo / "scripts"))
    from run_squad_live import make_calendar_status_sink
    return make_calendar_status_sink(out_dir, notifier)


def test_runner_sink_appends_rows_and_rate_limits_telegram(tmp_path: Path):
    notifier = _FakeNotifier()
    sink = _runner_sink(tmp_path, notifier)
    base = {
        "type": "system_status", "component": "news_calendar",
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "status": "missing", "cache_age_seconds": None,
        "message": "news calendar cache missing",
    }
    for streak in (1, 2, 3):
        sink({**base, "failure_streak": streak})
    # New streak after recovery -> pages again.
    sink({**base, "failure_streak": 1})

    rows = [
        json.loads(x)
        for x in (tmp_path / "events.jsonl").read_text().splitlines() if x
    ]
    assert len(rows) == 4, "every failure lands a structured row"
    assert all(r["type"] == "system_status" for r in rows)
    assert len(notifier.messages) == 2, (
        "Telegram pages once per failure streak, not per poll"
    )


def test_runner_sink_silent_without_notifier(tmp_path: Path):
    sink = _runner_sink(tmp_path, None)
    sink({
        "type": "system_status", "component": "news_calendar",
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "status": "missing", "failure_streak": 1,
    })
    assert (tmp_path / "events.jsonl").exists()


# ---------------------------------------------------------------------------
# 4. Contract: parser + schema tolerate the new row type
# ---------------------------------------------------------------------------

def test_system_status_rows_do_not_break_timeline_parser(tmp_path: Path):
    cache_dir = tmp_path / "live"
    cache_dir.mkdir()
    for f in ("proposals_all.jsonl", "proposals_rejected.jsonl",
              "trades.jsonl"):
        (cache_dir / f).touch()
    now = datetime.now(tz=UTC).isoformat()
    (cache_dir / "events.jsonl").write_text(
        json.dumps({
            "type": "tick_summary", "timestamp": now, "symbol": "EURUSD",
            "tick_id": 1, "players_evaluated": [],
            "players_who_proposed": [], "proposal_count": 0,
            "post_sentinel_count": 0, "workspace_thought_count": 0,
            "thoughts_top5": [],
        }) + "\n" + json.dumps({
            "type": "system_status", "timestamp": now,
            "component": "news_calendar", "status": "missing",
            "failure_streak": 1, "cache_age_seconds": None,
        }) + "\n",
    )
    events, _summary = build_timeline(cache_dir)
    # The tick_summary survives; the system_status row is skipped
    # tolerantly (not projected into the playback timeline today).
    assert [e["type"] for e in events] == ["tick_summary"]


def test_event_schema_accepts_system_status_contract():
    assert "system_status" in EVENT_TYPES
    errs = validate_event({
        "t": datetime.now(tz=UTC).isoformat(),
        "type": "system_status",
        "component": "news_calendar",
        "status": "stale",
        "failure_streak": 2,
        "cache_age_seconds": 50000.0,
        "message": "news calendar cache stale",
    })
    assert errs == []
