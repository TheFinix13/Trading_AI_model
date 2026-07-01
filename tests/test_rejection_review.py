"""Tests for the weekly rejection-review digest generator (Wave 2.1).

Covers three concerns:

1. Stop-bucket labelling matches the E011 pre-registered boundaries.
2. Aggregation groups events correctly by (symbol, reason, bucket) and
   filters by time window.
3. Markdown rendering produces a stable snapshot with the caveat block.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.reports import rejection_review as rr


def _make_event(
    ts: datetime,
    reason: str,
    entry: float,
    stop: float,
    tp: float,
    direction: str = "LONG",
    resolved: bool = False,
    outcome: str = "open",
    outcome_r: float = 0.0,
    forward_bars_available: int = 30,
) -> dict:
    return {
        "ts": ts.isoformat(),
        "symbol": "EURUSD",
        "tf": "H4",
        "reason": reason,
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "take_profit": tp,
        "resolved": resolved,
        "outcome": outcome,
        "outcome_r": outcome_r,
        "forward_bars_available": forward_bars_available,
    }


def test_stop_bucket_labels_match_e011_boundaries():
    assert rr._stop_bucket_label(0.0) == "0-10p"
    assert rr._stop_bucket_label(9.99) == "0-10p"
    assert rr._stop_bucket_label(10.0) == "10-20p"
    assert rr._stop_bucket_label(19.99) == "10-20p"
    assert rr._stop_bucket_label(20.0) == "20-40p"
    assert rr._stop_bucket_label(39.99) == "20-40p"
    assert rr._stop_bucket_label(40.0) == "40-80p"
    assert rr._stop_bucket_label(79.99) == "40-80p"
    assert rr._stop_bucket_label(80.0) == "80p+"
    assert rr._stop_bucket_label(500.0) == "80p+"


def test_event_stop_pips_returns_none_for_missing_fields():
    assert rr._event_stop_pips({"entry": 0, "stop": 1.10}) is None
    assert rr._event_stop_pips({"entry": 1.10, "stop": 0}) is None
    assert rr._event_stop_pips({"entry": 1.10}) is None


def test_event_stop_pips_rounds_correctly():
    # 20 pip stop on EURUSD
    e = {"entry": 1.10000, "stop": 1.09800}
    assert rr._event_stop_pips(e) == pytest.approx(20.0, abs=1e-6)


def test_within_window_none_since_accepts_all():
    e = _make_event(datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "sizing_skip", 1.10, 1.098, 1.104)
    assert rr._within_window(e, None) is True


def test_within_window_filters_by_since():
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    old = _make_event(now - timedelta(days=30),
                      "sizing_skip", 1.10, 1.098, 1.104)
    recent = _make_event(now - timedelta(days=3),
                         "sizing_skip", 1.10, 1.098, 1.104)
    since = now - timedelta(days=7)
    assert rr._within_window(old, since) is False
    assert rr._within_window(recent, since) is True


def test_aggregate_groups_correctly():
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = [
        _make_event(now - timedelta(hours=1), "sizing_skip",
                    1.10000, 1.09880, 1.10240,  # 12 pip -> 10-20p bucket
                    resolved=True, outcome="win", outcome_r=1.5),
        _make_event(now - timedelta(hours=2), "sizing_skip",
                    1.10000, 1.09850, 1.10300,  # 15 pip -> 10-20p bucket
                    resolved=True, outcome="loss", outcome_r=-1.0),
        _make_event(now - timedelta(hours=3), "sizing_skip",
                    1.10000, 1.09500, 1.11000,  # 50 pip -> 40-80p bucket
                    resolved=True, outcome="win", outcome_r=1.5),
        _make_event(now - timedelta(days=100), "sizing_skip",
                    1.10000, 1.09880, 1.10240,  # OUT OF WINDOW
                    resolved=True, outcome="win", outcome_r=1.5),
    ]
    load = rr.SymbolLoad(
        symbol="EURUSD", path=Path("/tmp/fake"), events=events,
    )
    since = now - timedelta(days=7)
    rows = rr.aggregate([load], since)

    # Should have 2 buckets: 10-20p (n=2) and 40-80p (n=1)
    assert len(rows) == 2
    by_bucket = {r.bucket: r for r in rows}
    assert by_bucket["10-20p"].n == 2
    assert by_bucket["10-20p"].wins == 1
    assert by_bucket["10-20p"].losses == 1
    assert by_bucket["40-80p"].n == 1
    assert by_bucket["40-80p"].wins == 1
    assert by_bucket["40-80p"].win_rate == 1.0


def test_render_markdown_includes_caveat_and_headers():
    now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    events = [
        _make_event(now - timedelta(hours=6), "post_loss_guard",
                    1.10000, 1.09850, 1.10225,
                    resolved=True, outcome="win", outcome_r=1.5),
    ]
    load = rr.SymbolLoad("EURUSD", Path("/tmp/fake"), events, resolved_now=1)
    since = now - timedelta(days=7)
    rows = rr.aggregate([load], since)
    md = rr.render_markdown(
        rows, days=7, since=since, generated_at=now, loads=[load],
    )
    assert "Weekly rejection-review" in md
    assert "HYPOTHESIS-GENERATING EVIDENCE ONLY" in md
    assert "post_loss_guard" in md
    assert "By (symbol · reason · stop bucket)" in md


def test_render_markdown_empty_rows_prints_placeholder():
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    load = rr.SymbolLoad("EURUSD", Path("/tmp/fake"), [], 0)
    since = now - timedelta(days=7)
    md = rr.render_markdown([], days=7, since=since, generated_at=now,
                             loads=[load])
    assert "No events in window" in md
    assert "HYPOTHESIS-GENERATING EVIDENCE ONLY" in md


def test_write_csv_produces_stable_columns(tmp_path):
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = [
        _make_event(now - timedelta(hours=1), "sizing_skip",
                    1.10000, 1.09880, 1.10240,  # 12 pip -> 10-20p
                    resolved=True, outcome="win", outcome_r=1.5),
    ]
    load = rr.SymbolLoad("EURUSD", Path("/tmp/fake"), events)
    rows = rr.aggregate([load], since=now - timedelta(days=1))
    csv_path = tmp_path / "digest.csv"
    rr.write_csv(rows, csv_path)
    content = csv_path.read_text()
    header = content.splitlines()[0]
    assert header == (
        "symbol,reason,bucket,n,wins,losses,open,stale,"
        "win_rate,avg_r,median_r,median_stop_pips"
    )
    # One data row
    assert "EURUSD,sizing_skip,10-20p,1,1,0" in content


def test_load_symbol_missing_vault_returns_empty(tmp_path):
    load = rr.load_symbol("EURUSD", tmp_path)
    assert load.events == []
    assert load.resolved_now == 0


def test_load_symbol_reads_prewritten_events_without_resolving(tmp_path):
    """When --no-resolve is used, load_symbol should not attempt bar
    lookups and should return the raw events."""
    vault_dir = tmp_path / "EURUSD" / "near_misses"
    vault_dir.mkdir(parents=True)
    events_path = vault_dir / "events.jsonl"
    e = _make_event(
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        "sizing_skip", 1.10000, 1.09800, 1.10400,
        resolved=True, outcome="win", outcome_r=1.5,
    )
    events_path.write_text(json.dumps(e) + "\n")

    load = rr.load_symbol("EURUSD", tmp_path, resolve=False)
    assert len(load.events) == 1
    assert load.events[0]["reason"] == "sizing_skip"
    assert load.resolved_now == 0
