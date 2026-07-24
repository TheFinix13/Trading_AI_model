"""Tests for the I002 "make silence legible" pass on /v2 (2026-07-24).

Covers the four surfaces the pass added:

1. **Roster** — ``sae_itoshi`` and ``karasu_tabito`` join the /v2 pitch
   ROSTER (Sae as the event-specialist striker, Karasu as a defender).
2. **upcoming_events collector** — read-only view over the news cache:
   USD + High + future-only, Sae-window tagging, fetched-at age, and
   honest degradation when the cache is missing.
3. **live_status additive fields** — ``warmup`` / ``sae_enabled`` /
   ``calendar_fetched_age_seconds`` / ``quiet_reason``, including the
   quiet_reason priority order (dead > kill > warming > burn-in > quiet).
4. **Page smoke** — the /v2 template ships the quiet line, the events
   panel, and the JS wire-up for both.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import paper_loop, squad_events  # noqa: E402
from agent.platform.pages import V2_PAGE  # noqa: E402

UTC = timezone.utc


# ---------------------------------------------------------------------------
# 1) Roster additions
# ---------------------------------------------------------------------------

class TestRosterAdditions:

    def test_sae_and_karasu_on_the_pitch(self):
        assert "sae_itoshi" in squad_events.ROSTER
        assert "karasu_tabito" in squad_events.ROSTER

    def test_positions_make_sense(self):
        sae = squad_events.ROSTER["sae_itoshi"]
        karasu = squad_events.ROSTER["karasu_tabito"]
        # Sae is the event-specialist striker: most advanced player on
        # the pitch (roster y grows toward the goal).
        others = [r["y"] for aid, r in squad_events.ROSTER.items()
                  if aid != "sae_itoshi"]
        assert sae["y"] > max(others)
        # Karasu defends: back line, below every proposer.
        proposer_ys = [r["y"] for aid, r in squad_events.ROSTER.items()
                       if aid not in ("karasu_tabito", "kunigami_rensuke")]
        assert karasu["y"] < min(proposer_ys)

    def test_required_render_fields_present(self):
        for aid in ("sae_itoshi", "karasu_tabito"):
            r = squad_events.ROSTER[aid]
            for field in ("name", "num", "x", "y", "color", "role"):
                assert field in r, f"{aid} missing {field!r}"

    def test_summary_roster_carries_new_players(self, tmp_path):
        # build_timeline embeds ROSTER in every summary — the pitch is
        # drawn from that payload, so the new players must ride along.
        (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
        (tmp_path / "run_meta.json").write_text("{}", encoding="utf-8")
        _, summary = squad_events.build_timeline(tmp_path)
        assert "sae_itoshi" in summary["roster"]
        assert "karasu_tabito" in summary["roster"]


# ---------------------------------------------------------------------------
# 2) upcoming_events collector
# ---------------------------------------------------------------------------

def _write_cache(path: Path, events: list[dict],
                 fetched_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "fetched_at": fetched_at.isoformat(),
        "events": events,
    }), encoding="utf-8")


def _ev(t: datetime | None, title: str, currency: str = "USD",
        impact: str = "High") -> dict:
    return {
        "time_utc": t.isoformat() if t else None,
        "currency": currency,
        "impact": impact,
        "title": title,
        "all_day": t is None,
    }


class TestUpcomingEvents:

    NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)

    def test_missing_cache_degrades_honestly(self, tmp_path):
        out = paper_loop.upcoming_events(tmp_path / "nope.json",
                                         now=self.NOW)
        assert out["exists"] is False
        assert out["fetched_at"] is None
        assert out["fetched_age_seconds"] is None
        assert out["events"] == []

    def test_filters_usd_high_future_only(self, tmp_path):
        cache = tmp_path / "cal.json"
        _write_cache(cache, [
            _ev(self.NOW + timedelta(hours=2), "NFP"),                # keep
            _ev(self.NOW - timedelta(hours=1), "old CPI"),            # past
            _ev(self.NOW + timedelta(hours=3), "ECB rate", "EUR"),    # not USD
            _ev(self.NOW + timedelta(hours=4), "retail", impact="Medium"),
            _ev(None, "Bank Holiday"),                                # all-day
        ], fetched_at=self.NOW - timedelta(minutes=30))
        out = paper_loop.upcoming_events(cache, now=self.NOW)
        assert [e["title"] for e in out["events"]] == ["NFP"]
        row = out["events"][0]
        assert row["currency"] == "USD"
        assert row["impact"] == "High"
        assert row["minutes_to_event"] == 120
        assert out["fetched_age_seconds"] == 1800.0
        assert out["exists"] is True

    def test_sae_window_tagging(self, tmp_path):
        # Sae's firing window is [T-30m, T+60m]. With after=now the only
        # taggable events are those starting within the next 30 minutes.
        cache = tmp_path / "cal.json"
        _write_cache(cache, [
            _ev(self.NOW + timedelta(minutes=20), "FOMC soon"),
            _ev(self.NOW + timedelta(minutes=90), "CPI later"),
        ], fetched_at=self.NOW)
        out = paper_loop.upcoming_events(cache, now=self.NOW)
        by_title = {e["title"]: e for e in out["events"]}
        assert by_title["FOMC soon"]["in_sae_window"] is True
        assert by_title["CPI later"]["in_sae_window"] is False

    def test_events_sorted_soonest_first(self, tmp_path):
        cache = tmp_path / "cal.json"
        _write_cache(cache, [
            _ev(self.NOW + timedelta(hours=5), "later"),
            _ev(self.NOW + timedelta(hours=1), "sooner"),
        ], fetched_at=self.NOW)
        out = paper_loop.upcoming_events(cache, now=self.NOW)
        mins = [e["minutes_to_event"] for e in out["events"]]
        assert mins == sorted(mins)


# ---------------------------------------------------------------------------
# 3) live_status additive fields + quiet_reason priority
# ---------------------------------------------------------------------------

def _touch_fresh(out_dir: Path, state: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / paper_loop.STATE_FILE).write_text(
        json.dumps(state), encoding="utf-8")
    (out_dir / paper_loop.POLL_HEARTBEAT_FILE).write_text(
        str(time.time()), encoding="utf-8")


def _warm(bars_seen: int, warmup_bars: int = 200,
          burn_in: int = 0) -> dict:
    return {"bars_seen": bars_seen, "warmup_bars": warmup_bars,
            "burn_in_remaining": burn_in, "seeded_bars": 0}


class TestLiveStatusAdditiveFields:

    def test_additive_fields_present_and_none_safe(self, tmp_path):
        # Pre-Sae / pre-seeding state file: the new keys exist but are
        # None — old dashboards keep working, new ones stay honest.
        _touch_fresh(tmp_path, {"source": "live_market:mt5"})
        st = paper_loop.live_status(
            tmp_path, calendar_cache_path=tmp_path / "no_cal.json")
        assert st["warmup"] is None
        assert st["sae_enabled"] is None
        assert st["calendar_fetched_age_seconds"] is None
        assert isinstance(st["quiet_reason"], str)
        # Pre-existing keys unchanged.
        assert st["running"] is True
        assert st["source"] == "live_market:mt5"

    def test_warmup_and_sae_passthrough(self, tmp_path):
        _touch_fresh(tmp_path, {
            "warmup": {"EURUSD": _warm(150)},
            "sae_enabled": False,
        })
        st = paper_loop.live_status(
            tmp_path, calendar_cache_path=tmp_path / "no_cal.json")
        assert st["warmup"]["EURUSD"]["bars_seen"] == 150
        assert st["sae_enabled"] is False

    def test_calendar_age_from_cache(self, tmp_path):
        cache = tmp_path / "cal.json"
        _write_cache(cache, [],
                     fetched_at=datetime.now(tz=UTC) - timedelta(hours=1))
        _touch_fresh(tmp_path, {})
        st = paper_loop.live_status(tmp_path, calendar_cache_path=cache)
        assert st["calendar_fetched_age_seconds"] is not None
        assert 3500 < st["calendar_fetched_age_seconds"] < 3700


class TestQuietReasonPriority:
    """dead/stalled > kill file > warming up > burn-in > quiet market."""

    def test_dead_beats_everything(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / paper_loop.STATE_FILE).write_text(
            json.dumps({"warmup": {"EURUSD": _warm(10)}}), encoding="utf-8")
        # No heartbeat, and force the state file to look old.
        old = time.time() - 3600
        import os
        os.utime(tmp_path / paper_loop.STATE_FILE, (old, old))
        st = paper_loop.live_status(
            tmp_path, calendar_cache_path=tmp_path / "no_cal.json")
        assert st["running"] is False
        assert "dead or stalled" in st["quiet_reason"]

    def test_kill_beats_warming(self, tmp_path):
        _touch_fresh(tmp_path, {"warmup": {"EURUSD": _warm(10)}})
        (tmp_path / paper_loop.KILL_FILE).write_text(
            "daily loss cap", encoding="utf-8")
        st = paper_loop.live_status(
            tmp_path, calendar_cache_path=tmp_path / "no_cal.json")
        assert st["quiet_reason"] == "halted by kill file: daily loss cap"

    def test_warming_beats_burn_in(self, tmp_path):
        _touch_fresh(tmp_path, {"warmup": {
            "EURUSD": _warm(150, burn_in=2),
            "GBPUSD": _warm(201),
        }})
        st = paper_loop.live_status(
            tmp_path, calendar_cache_path=tmp_path / "no_cal.json")
        assert st["quiet_reason"].startswith("warming up:")
        assert "EURUSD 150/200" in st["quiet_reason"]
        # GBPUSD is past the gate (201 > 200) so it must not be listed.
        assert "GBPUSD" not in st["quiet_reason"]

    def test_burn_in_when_warm(self, tmp_path):
        _touch_fresh(tmp_path, {"warmup": {
            "EURUSD": _warm(205, burn_in=2),
        }})
        st = paper_loop.live_status(
            tmp_path, calendar_cache_path=tmp_path / "no_cal.json")
        assert "burn-in" in st["quiet_reason"]
        assert "2 bars left" in st["quiet_reason"]

    def test_quiet_market_fallthrough(self, tmp_path):
        _touch_fresh(tmp_path, {"warmup": {"EURUSD": _warm(205)}})
        st = paper_loop.live_status(
            tmp_path, calendar_cache_path=tmp_path / "no_cal.json")
        assert "evaluating quietly" in st["quiet_reason"]

    def test_no_warmup_payload_falls_through(self, tmp_path):
        # Old state files (no warmup dict) must not claim "warming up".
        _touch_fresh(tmp_path, {})
        st = paper_loop.live_status(
            tmp_path, calendar_cache_path=tmp_path / "no_cal.json")
        assert "evaluating quietly" in st["quiet_reason"]


# ---------------------------------------------------------------------------
# 4) /v2 page smoke — quiet line + events panel + JS wire-up
# ---------------------------------------------------------------------------

class TestV2PageQuietSurfaces:

    def test_quiet_line_markup(self):
        assert 'id="quiet-line"' in V2_PAGE
        assert 'id="quiet-reason"' in V2_PAGE
        assert "why quiet" in V2_PAGE

    def test_events_panel_markup(self):
        for marker in ('id="events-card"', 'id="events-list"',
                       'id="events-empty"', 'id="events-meta"',
                       "Upcoming USD events", "this week only"):
            assert marker in V2_PAGE, f"missing events-panel piece: {marker!r}"

    def test_events_panel_empty_state_mentions_weekly_feed(self):
        # The FF feed is this-week-only; the empty state must say so,
        # otherwise an empty list looks like a broken feed.
        assert "current week" in V2_PAGE

    def test_js_wires_new_endpoint_and_fields(self):
        assert "/api/v2/live/upcoming_events" in V2_PAGE
        assert "quiet_reason" in V2_PAGE
        assert "in_sae_window" in V2_PAGE
        assert "calendar_fetched_age_seconds" in V2_PAGE

    def test_sae_disabled_visual_state(self):
        # Dim class + the benched label + the applier function.
        assert ".player-off" in V2_PAGE
        assert "Sae (off)" in V2_PAGE
        assert "applySaeState" in V2_PAGE

    def test_sae_window_tag_style(self):
        assert "sae-tag" in V2_PAGE


# ---------------------------------------------------------------------------
# 5) HTTP — the endpoint is routed and answers before any live dir exists
# ---------------------------------------------------------------------------

class TestUpcomingEventsEndpoint:

    def test_endpoint_routed_and_cold_start_safe(self, tmp_path):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        from scripts.serve_platform import make_handler

        reviews = tmp_path / "reviews"
        reviews.mkdir()
        log_root = tmp_path / "logs"
        log_root.mkdir()
        handler = make_handler(log_root, tmp_path, reviews,
                               live_dir=tmp_path / "squad_live")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = (f"http://127.0.0.1:{srv.server_address[1]}"
                   "/api/v2/live/upcoming_events")
            with urllib.request.urlopen(url) as resp:
                assert resp.status == 200
                body = json.loads(resp.read())
            # Shape contract: present even with no cache on this box
            # (the repo-anchored default may or may not exist here, so
            # only pin the keys, not the values).
            for key in ("exists", "fetched_at", "fetched_age_seconds",
                        "events"):
                assert key in body
            assert isinstance(body["events"], list)
        finally:
            srv.shutdown()
