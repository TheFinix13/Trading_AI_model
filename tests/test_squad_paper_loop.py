"""Tests for the shadow-only squad paper loop (agent/platform/paper_loop.py).

The loop replays a source replay cache into a live output dir in the
same three-JSONL schema. Hard guarantees under test: kill.txt stops it,
state.json lets it resume without double-appending, a full replay
parses to the byte-identical event stream as the source cache (the
sim-vs-paper parity contract, see also test_platform_contract.py), and
cache selection follows the documented precedence (CLI > toml >
g7retry1 auto-pick > any-g7 auto-pick) so a fresh G7 second attempt
lands on /v2 LIVE by default.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.platform import squad_events  # noqa: E402
from agent.platform.paper_loop import (  # noqa: E402
    AGGREGATORS,
    PaperLoop,
    live_status,
    select_source_cache,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


@pytest.fixture()
def source_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "g7_replay_cache_source"
    cache.mkdir()
    _write_jsonl(cache / "proposals_all.jsonl", [
        {"agent_id": "isagi_yoichi", "timestamp": "2024-01-01T00:00:00+00:00",
         "symbol": "EURUSD", "direction": "long", "conviction": 0.75,
         "rationale": {"signal_reason": "zone_demand"}},
        {"agent_id": "barou_shoei", "timestamp": "2024-01-01T04:00:00+00:00",
         "symbol": "USDCAD", "direction": "short", "conviction": 0.7},
    ])
    _write_jsonl(cache / "proposals_rejected.jsonl", [
        {"tick_id": 1, "symbol": "USDCAD",
         "timestamp": "2024-01-01T04:00:00+00:00",
         "winner_agent_id": "isagi_yoichi", "loser_agent_id": "barou_shoei",
         "rejection_reason": "lower_conviction_same_symbol"},
    ])
    _write_jsonl(cache / "trades.jsonl", [
        {"agent_id": "isagi_yoichi", "symbol": "EURUSD",
         "entry_time": "2024-01-01 00:00:00+00:00",
         "exit_time": "2024-01-01 12:00:00+00:00",
         "direction": "long", "exit_reason": "tp", "pnl_pips": 42.5,
         "r_multiple": 1.5, "tqs_components": {"tqs": 0.61}},
    ])
    (cache / "workspace_counts.json").write_text(
        json.dumps({"publish": {"isagi_yoichi": 2}}), encoding="utf-8")
    return cache


def _run_to_completion(loop: PaperLoop) -> str:
    return loop.run(sleep=lambda s: None, log=lambda *a, **k: None)


class TestPaperLoop:

    def test_full_replay_emits_everything(self, source_cache, tmp_path):
        out = tmp_path / "squad_live"
        loop = PaperLoop(source_cache, out, tick_seconds=0)
        assert _run_to_completion(loop) == "done"
        for fname in ("proposals_all.jsonl", "proposals_rejected.jsonl",
                      "trades.jsonl", "workspace_counts.json", "state.json"):
            assert (out / fname).exists(), fname
        assert loop.remaining() == 0

    def test_rows_are_appended_verbatim(self, source_cache, tmp_path):
        out = tmp_path / "squad_live"
        _run_to_completion(PaperLoop(source_cache, out, tick_seconds=0))
        for fname in ("proposals_all.jsonl", "proposals_rejected.jsonl",
                      "trades.jsonl"):
            src_rows = [json.loads(x) for x in
                        (source_cache / fname).read_text().splitlines() if x]
            out_rows = [json.loads(x) for x in
                        (out / fname).read_text().splitlines() if x]
            assert out_rows == src_rows, fname

    def test_kill_txt_stops_the_loop(self, source_cache, tmp_path):
        out = tmp_path / "squad_live"
        out.mkdir()
        (out / "kill.txt").write_text("halt for review", encoding="utf-8")
        loop = PaperLoop(source_cache, out, tick_seconds=0)
        assert _run_to_completion(loop) == "killed"
        # Nothing was emitted.
        assert (out / "proposals_all.jsonl").read_text() == ""

    def test_max_steps_and_resume_without_double_append(
            self, source_cache, tmp_path):
        out = tmp_path / "squad_live"
        loop1 = PaperLoop(source_cache, out, tick_seconds=0)
        assert loop1.run(max_steps=2, sleep=lambda s: None,
                         log=lambda *a, **k: None) == "max_steps"
        # A fresh loop instance resumes from state.json.
        loop2 = PaperLoop(source_cache, out, tick_seconds=0)
        assert _run_to_completion(loop2) == "done"
        total_rows = sum(
            len((out / f).read_text().splitlines())
            for f in ("proposals_all.jsonl", "proposals_rejected.jsonl",
                      "trades.jsonl"))
        assert total_rows == 4  # 2 proposals + 1 reject + 1 trade, no dupes

    def test_state_reset_on_different_source(self, source_cache, tmp_path):
        out = tmp_path / "squad_live"
        loop1 = PaperLoop(source_cache, out, tick_seconds=0)
        loop1.run(max_steps=1, sleep=lambda s: None, log=lambda *a, **k: None)
        # Same out dir, different source path -> cursors start at 0.
        other = tmp_path / "g7_replay_cache_other"
        other.mkdir()
        loop2 = PaperLoop(other, out, tick_seconds=0)
        loop2.load_state()
        assert all(c == 0 for c in loop2.cursors.values())

    def test_emitted_stream_parses_like_the_source(
            self, source_cache, tmp_path):
        """Parity: parsed(paper output) == parsed(source), byte-for-byte."""
        out = tmp_path / "squad_live"
        _run_to_completion(PaperLoop(source_cache, out, tick_seconds=0))
        src_events, src_summary = squad_events.build_timeline(source_cache)
        out_events, out_summary = squad_events.build_timeline(out)
        assert json.dumps(out_events, sort_keys=True) == \
            json.dumps(src_events, sort_keys=True)
        assert out_summary["per_agent"] == src_summary["per_agent"]


class TestLiveStatus:

    def test_missing_dir(self, tmp_path):
        st = live_status(tmp_path / "nope")
        assert st["exists"] is False
        assert st["running"] is False

    def test_running_fresh_state(self, source_cache, tmp_path):
        out = tmp_path / "squad_live"
        loop = PaperLoop(source_cache, out, tick_seconds=0)
        loop.run(max_steps=1, sleep=lambda s: None, log=lambda *a, **k: None)
        st = live_status(out)
        assert st["exists"] is True
        assert st["running"] is True  # state.json written milliseconds ago
        assert st["last_event_time"].startswith("2024-01-01")
        assert st["source_cache"] == str(source_cache)

    def test_kill_marks_not_running(self, source_cache, tmp_path):
        out = tmp_path / "squad_live"
        loop = PaperLoop(source_cache, out, tick_seconds=0)
        loop.run(max_steps=1, sleep=lambda s: None, log=lambda *a, **k: None)
        (out / "kill.txt").write_text("stop", encoding="utf-8")
        st = live_status(out)
        assert st["running"] is False
        assert st["kill"] == "stop"


def _mk_cache(root: Path, name: str, mtime: float | None = None) -> Path:
    """A minimal-but-valid cache dir (has all three JSONL artifacts)."""
    cache = root / name
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "proposals_all.jsonl").write_text("", encoding="utf-8")
    (cache / "proposals_rejected.jsonl").write_text("", encoding="utf-8")
    (cache / "trades.jsonl").write_text("", encoding="utf-8")
    if mtime is not None:
        os.utime(cache, (mtime, mtime))
    return cache


class TestSelectSourceCache:
    """Cache-selection precedence: CLI > config > g7retry1 auto > any-g7 auto.

    These pin the default the operator sees on /v2 LIVE when they run
    ``scripts/run_squad_paper.py`` with no flags. The user asked for
    the newest g7retry1 arm to be the default so a fresh G7 second
    attempt (all 7 v1 players active) shows up automatically.
    """

    def test_explicit_cache_wins(self, tmp_path):
        reviews = tmp_path / "reviews"
        _mk_cache(reviews, "g7_replay_cache_g7retry1-phi41", mtime=1_000)
        picked = _mk_cache(reviews, "g7_replay_cache_special", mtime=500)
        p, reason = select_source_cache(
            reviews, cache="g7_replay_cache_special")
        assert p == picked
        assert reason == "explicit"

    def test_explicit_absolute_path(self, tmp_path):
        reviews = tmp_path / "reviews"
        elsewhere = _mk_cache(tmp_path / "elsewhere",
                              "g7_replay_cache_manual", mtime=100)
        p, reason = select_source_cache(reviews, cache=str(elsewhere))
        assert p == elsewhere
        assert reason == "explicit"

    def test_explicit_missing_raises(self, tmp_path):
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        with pytest.raises(FileNotFoundError):
            select_source_cache(reviews, cache="g7_replay_cache_nope")

    def test_aggregator_resolves_to_g7retry1(self, tmp_path):
        reviews = tmp_path / "reviews"
        phi = _mk_cache(reviews, "g7_replay_cache_g7retry1-phi41", mtime=100)
        _mk_cache(reviews, "g7_replay_cache_g7retry1-arm4", mtime=200)
        p, reason = select_source_cache(reviews, aggregator="phi41")
        assert p == phi
        assert reason == "aggregator=phi41"

    def test_aggregator_arm4(self, tmp_path):
        reviews = tmp_path / "reviews"
        _mk_cache(reviews, "g7_replay_cache_g7retry1-phi41", mtime=100)
        arm = _mk_cache(reviews, "g7_replay_cache_g7retry1-arm4", mtime=200)
        p, reason = select_source_cache(reviews, aggregator="arm4")
        assert p == arm
        assert reason == "aggregator=arm4"

    def test_cache_wins_over_aggregator(self, tmp_path):
        reviews = tmp_path / "reviews"
        _mk_cache(reviews, "g7_replay_cache_g7retry1-phi41", mtime=100)
        specific = _mk_cache(reviews, "g7_replay_cache_g7retry1-arm4",
                             mtime=200)
        p, reason = select_source_cache(
            reviews, cache="g7_replay_cache_g7retry1-arm4",
            aggregator="phi41")
        assert p == specific
        assert reason == "explicit"

    def test_aggregator_missing_raises(self, tmp_path):
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        with pytest.raises(FileNotFoundError):
            select_source_cache(reviews, aggregator="phi41")

    def test_aggregator_unknown_raises(self, tmp_path):
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        with pytest.raises(ValueError):
            select_source_cache(reviews, aggregator="not_a_real_arm")

    def test_auto_picks_newest_g7retry1(self, tmp_path):
        reviews = tmp_path / "reviews"
        _mk_cache(reviews, "g7_replay_cache_g7retry1-arm4", mtime=100)
        newer = _mk_cache(reviews, "g7_replay_cache_g7retry1-phi41",
                          mtime=200)
        # A newer non-g7retry1 cache is present but shouldn't win —
        # the g7retry1 prefix outranks other g7_replay_cache_* dirs by
        # design (that's how a fresh G7 second attempt reaches /v2
        # LIVE without config edits).
        _mk_cache(reviews, "g7_replay_cache_walk-forward-post-X",
                  mtime=999)
        p, reason = select_source_cache(reviews)
        assert p == newer
        assert reason == "newest g7retry1"

    def test_falls_back_to_any_g7_replay_cache(self, tmp_path):
        reviews = tmp_path / "reviews"
        older = _mk_cache(reviews, "g7_replay_cache_walk-forward-baseline",
                          mtime=100)
        newer = _mk_cache(reviews, "g7_replay_cache_phi5-arm4-post-kunigami",
                          mtime=200)
        p, reason = select_source_cache(reviews)
        assert p == newer
        assert reason == "newest replay cache"
        assert older != newer  # tie-break sanity

    def test_empty_reviews_dir_raises(self, tmp_path):
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        with pytest.raises(FileNotFoundError):
            select_source_cache(reviews)

    def test_missing_reviews_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            select_source_cache(tmp_path / "does-not-exist")

    def test_ignores_dirs_missing_required_files(self, tmp_path):
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        # Half-baked cache (missing trades.jsonl): must not be picked.
        broken = reviews / "g7_replay_cache_g7retry1-phi41"
        broken.mkdir()
        (broken / "proposals_all.jsonl").write_text("", encoding="utf-8")
        (broken / "proposals_rejected.jsonl").write_text(
            "", encoding="utf-8")
        with pytest.raises(FileNotFoundError):
            select_source_cache(reviews, aggregator="phi41")
        # And auto-pick also skips it, falling through to no-g7retry1
        # then no-any-g7 -> raises.
        with pytest.raises(FileNotFoundError):
            select_source_cache(reviews)

    def test_aggregators_constant_covers_both_arms(self):
        # If the research repo grows a new aggregator arm, this
        # constant needs updating alongside select_source_cache /
        # runbook 7b.5 — locking here so it doesn't drift silently.
        assert set(AGGREGATORS) == {"phi41", "arm4"}
