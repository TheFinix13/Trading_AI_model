"""Parser round-trip for ``tick_summary`` events in ``events.jsonl``.

The live squad engine writes proof-of-life rows to ``events.jsonl``.
:mod:`agent.platform.squad_events` must:

1. Include those rows as ``type="tick_summary"`` events in
   :func:`build_timeline`.
2. NOT count them toward the per-agent trade / goal / proposal /
   blocked tallies in the summary (they are footers, not events with
   an agent attribution).
3. Return them through :func:`get_events` alongside real match events.
4. Validate against :func:`agent.platform.event_schema.validate_event`
   as agent-optional.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.platform import squad_events
from agent.platform.event_schema import validate_event, validate_events


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


def _make_cache(tmp_path: Path, *, with_tick_summary: bool = True) -> Path:
    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    _write_jsonl(cache / "proposals_all.jsonl", [
        {"agent_id": "isagi_yoichi",
         "timestamp": "2024-01-01T04:00:00+00:00",
         "symbol": "EURUSD", "direction": "long", "conviction": 0.75,
         "rationale": {"signal_reason": "zone_demand"}},
    ])
    _write_jsonl(cache / "proposals_rejected.jsonl", [])
    _write_jsonl(cache / "trades.jsonl", [
        {"agent_id": "isagi_yoichi", "symbol": "EURUSD",
         "entry_time": "2024-01-01 04:00:00+00:00",
         "exit_time": "2024-01-01 16:00:00+00:00",
         "direction": "long", "exit_reason": "tp", "pnl_pips": 42.5,
         "r_multiple": 1.5},
    ])
    if with_tick_summary:
        _write_jsonl(cache / "events.jsonl", [
            {"type": "tick_summary",
             "timestamp": "2024-01-01T00:00:00+00:00",
             "symbol": "EURUSD", "tick_id": 1,
             "players_evaluated": ["isagi_yoichi", "barou_shoei"],
             "players_who_proposed": [],
             "proposal_count": 0, "post_sentinel_count": 0,
             "workspace_thought_count": 0},
            {"type": "tick_summary",
             "timestamp": "2024-01-01T04:00:00+00:00",
             "symbol": "EURUSD", "tick_id": 2,
             "players_evaluated": ["isagi_yoichi", "barou_shoei"],
             "players_who_proposed": ["isagi_yoichi"],
             "proposal_count": 1, "post_sentinel_count": 1,
             "workspace_thought_count": 2},
        ])
    return cache


def test_build_timeline_includes_tick_summary(tmp_path: Path) -> None:
    cache = _make_cache(tmp_path, with_tick_summary=True)
    events, _ = squad_events.build_timeline(cache)
    ticks = [e for e in events if e["type"] == "tick_summary"]
    assert len(ticks) == 2
    quiet, active = ticks
    assert quiet["symbol"] == "EURUSD"
    assert quiet["tick_id"] == 1
    assert quiet["proposal_count"] == 0
    assert quiet["post_sentinel_count"] == 0
    assert quiet["players_who_proposed"] == []
    assert active["proposal_count"] == 1
    assert active["post_sentinel_count"] == 1
    assert active["players_who_proposed"] == ["isagi_yoichi"]


def test_tick_summary_events_time_sort_with_real_events(tmp_path: Path):
    """Timeline is time-sorted; tick_summary rows interleave naturally
    with proposals / trades based on their timestamp."""
    cache = _make_cache(tmp_path, with_tick_summary=True)
    events, _ = squad_events.build_timeline(cache)
    # Timestamps in the fixture: the two tick_summary rows are at
    # 00:00 and 04:00; the proposal + open are at 04:00; close at 16:00.
    # Sort by parsed timestamp -> tick_summary(00:00) is first.
    assert events[0]["type"] == "tick_summary"
    assert events[0]["tick_id"] == 1


def test_tick_summary_does_not_count_toward_trade_tally(tmp_path: Path):
    """The Bug B guarantee: per-agent counts are unchanged whether or
    not events.jsonl is present."""
    without_ts = _make_cache(tmp_path / "a", with_tick_summary=False)
    with_ts = _make_cache(tmp_path / "b", with_tick_summary=True)

    _, sum_without = squad_events.build_timeline(without_ts)
    _, sum_with = squad_events.build_timeline(with_ts)

    # Isolate per-agent counts; other fields (n_events, t_start,
    # t_end) will legitimately differ because tick_summary rows do
    # count as timeline events.
    assert sum_without["per_agent"] == sum_with["per_agent"], (
        "tick_summary rows must NOT bleed into per-agent tallies"
    )
    # Sanity: the isagi row exists in both and shows 1 proposal + 1
    # trade + 1 goal (pnl>0), unchanged by tick_summary presence.
    isagi = sum_with["per_agent"]["isagi_yoichi"]
    assert isagi["proposals"] == 1
    assert isagi["trades"] == 1
    assert isagi["goals"] == 1


def test_get_events_returns_tick_summary_in_paged_slice(tmp_path: Path):
    """The paged /api/v2/.../events endpoint returns tick_summary rows
    alongside real events (they render as muted rows in the ticker)."""
    cache = _make_cache(tmp_path, with_tick_summary=True)
    page = squad_events.get_events(cache, cursor=0, limit=1000)
    types = [e["type"] for e in page["events"]]
    assert "tick_summary" in types
    assert page["total"] == len(page["events"])


def test_tick_summary_events_validate_against_contract(tmp_path: Path):
    """The whole timeline must pass event_schema.validate_events —
    tick_summary is recognised as agent-optional."""
    cache = _make_cache(tmp_path, with_tick_summary=True)
    events, _ = squad_events.build_timeline(cache)
    # validate_events prefixes each problem with the index; empty list
    # means the whole stream conforms.
    errs = validate_events(events)
    assert errs == [], errs
    # Explicit per-event check: tick_summary rows validate without
    # an agent field.
    for e in events:
        if e["type"] == "tick_summary":
            assert "agent" not in e
            assert validate_event(e) == []


def test_missing_events_jsonl_is_still_valid(tmp_path: Path):
    """Older caches without events.jsonl parse cleanly (backwards
    compat)."""
    cache = _make_cache(tmp_path, with_tick_summary=False)
    events, summary = squad_events.build_timeline(cache)
    assert not any(e["type"] == "tick_summary" for e in events)
    assert summary["per_agent"]["isagi_yoichi"]["trades"] == 1
