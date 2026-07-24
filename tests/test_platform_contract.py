"""Contract tests: every squad-event producer conforms to one schema.

``agent/platform/event_schema.py`` is the sim-vs-paper contract. These
tests validate (a) events parsed straight from a replay cache and
(b) events parsed from a paper-loop-emitted live dir against it, plus
the parity guarantee that both streams are byte-equivalent. When the
real squad graduates in as a third producer, pointing these tests at
its output dir is the whole acceptance check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.platform import squad_events  # noqa: E402
from agent.platform.event_schema import (  # noqa: E402
    EVENT_TYPES, validate_event, validate_events)
from agent.platform.paper_loop import PaperLoop  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


@pytest.fixture()
def source_cache(tmp_path: Path) -> Path:
    """A synthetic cache exercising every event type incl. thoughts."""
    cache = tmp_path / "g7_replay_cache_contract"
    cache.mkdir()
    _write_jsonl(cache / "proposals_all.jsonl", [
        {"agent_id": "isagi_yoichi", "timestamp": "2024-01-01T00:00:00+00:00",
         "symbol": "EURUSD", "direction": "long", "conviction": 0.75,
         "rationale": {"signal_reason": "zone_demand",
                       "base_conviction": 0.65, "final_conviction": 0.75}},
        {"agent_id": "barou_shoei", "timestamp": "2024-01-01T04:00:00+00:00",
         "symbol": "USDCAD", "direction": "short", "conviction": 0.7},
    ])
    _write_jsonl(cache / "proposals_rejected.jsonl", [
        {"tick_id": 1, "symbol": "USDCAD",
         "timestamp": "2024-01-01T04:00:00+00:00",
         "winner_agent_id": "isagi_yoichi", "loser_agent_id": "barou_shoei",
         "rejection_reason": "lower_conviction_same_symbol"},
        {"tick_id": 2, "symbol": "EURUSD",
         "timestamp": "2024-01-01T08:00:00+00:00",
         "winner_agent_id": "isagi_yoichi", "loser_agent_id": "isagi_yoichi",
         "rejection_reason": "r6_per_symbol_risk_cap"},
    ])
    _write_jsonl(cache / "trades.jsonl", [
        {"agent_id": "isagi_yoichi", "symbol": "EURUSD",
         "entry_time": "2024-01-01 00:00:00+00:00",
         "exit_time": "2024-01-01 12:00:00+00:00",
         "direction": "long", "exit_reason": "tp", "pnl_pips": 42.5,
         "mae_pips": 5.0, "mfe_pips": 50.0,
         "r_multiple": 1.5, "tqs_components": {"tqs": 0.61}},
    ])
    _write_jsonl(cache / "thoughts.jsonl", [
        {"agent_id": "isagi_yoichi",
         "timestamp": "2024-01-01T02:00:00+00:00",
         "symbol": "EURUSD", "text": "the field is opening up"},
    ])
    (cache / "workspace_counts.json").write_text("{}", encoding="utf-8")
    return cache


class TestSchemaValidator:

    def test_valid_events_of_every_type_pass(self):
        samples = [
            {"t": "2024-01-01T00:00:00+00:00", "type": "proposal",
             "agent": "isagi_yoichi", "symbol": "EURUSD", "dir": "long",
             "conviction": 0.75},
            {"t": "2024-01-01T00:00:00+00:00", "type": "blocked",
             "agent": "barou_shoei", "symbol": "USDCAD", "by": "SENTINEL",
             "rule": True, "reason": "r6_per_symbol_risk_cap"},
            {"t": "2024-01-01T00:00:00+00:00", "type": "open",
             "agent": "isagi_yoichi", "symbol": "EURUSD", "dir": "long"},
            {"t": "2024-01-01T00:00:00+00:00", "type": "close",
             "agent": "isagi_yoichi", "symbol": "EURUSD", "goal": True,
             "pnl_pips": 42.5, "exit_reason": "tp", "tqs": 0.61, "r": 1.5},
            {"t": "2024-01-01T00:00:00+00:00", "type": "thought",
             "agent": "isagi_yoichi", "symbol": None, "text": "hm"},
            # tick_summary is a proof-of-life footer with no agent
            # attribution — the validator recognises it as
            # agent-optional; see event_schema._AGENT_OPTIONAL_TYPES.
            {"t": "2024-01-01T00:00:00+00:00", "type": "tick_summary",
             "symbol": "EURUSD", "tick_id": 42,
             "players_evaluated": ["isagi_yoichi", "barou_shoei"],
             "players_who_proposed": [],
             "proposal_count": 0, "post_sentinel_count": 0,
             "workspace_thought_count": 3},
            # system_status is an infrastructure-health row (news feed
            # dead / cache stale) — agent-optional like tick_summary.
            {"t": "2024-01-01T00:00:00+00:00", "type": "system_status",
             "component": "news_calendar", "status": "stale",
             "failure_streak": 1, "cache_age_seconds": 50000.0,
             "message": "news calendar cache stale"},
        ]
        assert {s["type"] for s in samples} == set(EVENT_TYPES)
        for s in samples:
            assert validate_event(s) == [], s["type"]

    def test_rejects_unknown_type(self):
        errs = validate_event({"t": "2024-01-01T00:00:00+00:00",
                               "type": "own_goal", "agent": "x"})
        assert errs and "own_goal" in errs[0]

    def test_rejects_missing_required_field(self):
        errs = validate_event({"t": "2024-01-01T00:00:00+00:00",
                               "type": "close", "agent": "isagi_yoichi",
                               "symbol": "EURUSD", "goal": True,
                               "pnl_pips": 1.0})  # no exit_reason
        assert any("exit_reason" in e for e in errs)

    def test_rejects_wrong_types(self):
        errs = validate_event({"t": "not-a-date", "type": "proposal",
                               "agent": "", "symbol": 7, "dir": "long",
                               "conviction": "high"})
        assert any("ISO-8601" in e for e in errs)
        assert any("agent" in e for e in errs)
        assert any("symbol" in e for e in errs)
        assert any("conviction" in e for e in errs)

    def test_rejects_bool_where_number_expected(self):
        errs = validate_event({"t": "2024-01-01T00:00:00+00:00",
                               "type": "close", "agent": "a", "symbol": "S",
                               "goal": True, "pnl_pips": True,
                               "exit_reason": "tp"})
        assert any("pnl_pips" in e for e in errs)


class TestProducerContracts:

    def test_replay_parsed_events_conform(self, source_cache):
        events, _ = squad_events.build_timeline(source_cache)
        assert len(events) >= 7  # 2 props + 2 blocks + open/close + thought
        assert validate_events(events) == []

    def test_paper_loop_emitted_events_conform(self, source_cache, tmp_path):
        out = tmp_path / "squad_live"
        # thoughts.jsonl is not part of the paper loop's three-file
        # schema; the replay side of this dir simply won't have it.
        PaperLoop(source_cache, out, tick_seconds=0).run(
            sleep=lambda s: None, log=lambda *a, **k: None)
        events, _ = squad_events.build_timeline(out)
        assert events
        assert validate_events(events) == []

    def test_sim_vs_paper_parity(self, source_cache, tmp_path):
        """The future acceptance gate: a full paper replay of a cache is
        byte-equivalent (as an event stream) to parsing the cache."""
        out = tmp_path / "squad_live"
        PaperLoop(source_cache, out, tick_seconds=0).run(
            sleep=lambda s: None, log=lambda *a, **k: None)
        src_events, _ = squad_events.build_timeline(source_cache)
        # The paper loop replays the three trading files, not thoughts.
        src_events = [e for e in src_events if e["type"] != "thought"]
        out_events, _ = squad_events.build_timeline(out)
        assert json.dumps(out_events, sort_keys=True) == \
            json.dumps(src_events, sort_keys=True)

    def test_api_paged_events_conform_minus_detail(self, source_cache):
        page = squad_events.get_events(source_cache, cursor=0, limit=1000)
        assert page["events"]
        assert validate_events(page["events"]) == []
