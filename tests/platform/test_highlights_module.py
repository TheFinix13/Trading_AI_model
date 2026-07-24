"""F020 -- match-report assembly from fixture event files.

Acceptance pins:

- An active day's every number matches an independent recomputation
  from the raw ``events.jsonl`` rows (equality, not snapshot).
- A quiet day renders an honest quiet report reusing the I002
  quiet-reason vocabulary -- not an empty page.
- Missing dir / missing file / malformed rows / bogus day strings all
  degrade to the empty state, never raise (F005 contract).
- Narrative templates never contain the Brand banned words.
- Read-only: no request writes anything under live_dir.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import highlights  # noqa: E402

ACTIVE_DAY = "2026-07-20"
QUIET_DAY = "2026-07-21"

ACTIVE_ROWS = [
    {"t": f"{ACTIVE_DAY}T04:00:00Z", "type": "tick_summary",
     "symbol": "EURUSD", "tick_id": 1, "proposal_count": 0},
    {"t": f"{ACTIVE_DAY}T04:00:00Z", "type": "tick_summary",
     "symbol": "GBPUSD", "tick_id": 2, "proposal_count": 0},
    {"t": f"{ACTIVE_DAY}T08:00:00Z", "type": "proposal",
     "agent": "isagi_yoichi", "symbol": "EURUSD", "dir": "long",
     "conviction": 0.62},
    {"t": f"{ACTIVE_DAY}T08:00:00Z", "type": "propose",
     "agent": "bachira_meguru", "symbol": "GBPUSD", "dir": "short",
     "conviction": 0.55},
    {"t": f"{ACTIVE_DAY}T08:00:05Z", "type": "blocked",
     "agent": "bachira_meguru", "symbol": "GBPUSD", "by": "SENTINEL",
     "rule": True, "reason": "r1_daily_cap"},
    {"t": f"{ACTIVE_DAY}T08:00:05Z", "type": "blocked",
     "agent": "reo_mikage", "symbol": "EURUSD", "by": "isagi_yoichi",
     "rule": False, "reason": "lower_conviction"},
    {"t": f"{ACTIVE_DAY}T12:00:00Z", "type": "open",
     "agent": "isagi_yoichi", "symbol": "EURUSD", "dir": "long"},
    # Field-variant row: agent_id + timestamp (older-cache schema).
    {"timestamp": f"{ACTIVE_DAY}T16:00:00Z", "type": "close",
     "agent_id": "chigiri_hyoma", "symbol": "GBPUSD",
     "pnl_pips": -6.0, "r": -1.0, "exit_reason": "sl"},
    {"t": f"{ACTIVE_DAY}T20:00:00Z", "type": "close",
     "agent": "isagi_yoichi", "symbol": "EURUSD",
     "pnl_pips": 14.0, "r": 1.4, "tqs": 0.62, "exit_reason": "tp"},
    {"t": f"{ACTIVE_DAY}T20:00:00Z", "type": "tick_summary",
     "symbol": "EURUSD", "tick_id": 3, "proposal_count": 1},
]

QUIET_ROWS = [
    {"t": f"{QUIET_DAY}T04:00:00Z", "type": "tick_summary",
     "symbol": "EURUSD", "tick_id": 4, "proposal_count": 0},
    {"t": f"{QUIET_DAY}T08:00:00Z", "type": "tick_summary",
     "symbol": "EURUSD", "tick_id": 5, "proposal_count": 0},
]


def _write_tape(live: Path, rows: list, extra_lines: list[str] = ()) -> None:
    live.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in rows]
    lines.extend(extra_lines)
    (live / "events.jsonl").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8")


def _seeded(tmp_path: Path) -> Path:
    live = tmp_path / "squad_live"
    _write_tape(live, ACTIVE_ROWS + QUIET_ROWS)
    return live


def _fs_snapshot(root: Path) -> dict[str, int]:
    return {str(p.relative_to(root)): p.stat().st_size
            for p in root.rglob("*") if p.is_file()}


# --------------------------------------------------------------------
# Active day: every number == independent recomputation
# --------------------------------------------------------------------

class TestActiveDayNumbers:
    def test_full_time_matches_recomputation(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        # Independent recomputation from the raw fixture rows.
        day = [r for r in ACTIVE_ROWS]
        proposals = [r for r in day if r["type"] in ("propose", "proposal")]
        blocked = [r for r in day if r["type"] == "blocked"]
        opens = [r for r in day if r["type"] == "open"]
        closes = [r for r in day if r["type"] == "close"]
        ticks = [r for r in day if r["type"] == "tick_summary"]
        goals = sum(1 for r in closes if r["pnl_pips"] > 0)
        ft = report["full_time"]
        assert ft["shots"] == len(proposals) == 2
        assert ft["tackles"] == len(blocked) == 2
        assert ft["on_target"] == len(opens) == 1
        assert ft["resolved"] == len(closes) == 2
        assert ft["goals"] == goals == 1
        assert ft["misses"] == len(closes) - goals == 1
        assert ft["net_pips"] == round(
            sum(r["pnl_pips"] for r in closes), 1) == 8.0
        assert ft["net_r"] == round(
            sum(r["r"] for r in closes), 2) == 0.4
        assert ft["mean_tqs"] == 0.62  # single close carries tqs
        assert ft["ticks_evaluated"] == len(ticks) == 3

    def test_headline_reflects_counts(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        assert report["headline"] == (
            f"{ACTIVE_DAY}: 2 shots, 1 on target, 1 goal -- +8.0p net.")
        assert report["empty"] is False
        assert report["quiet"] is False

    def test_players_involvement_matches_recomputation(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        by_agent = {p["agent"]: p for p in report["players"]}
        isagi = by_agent["isagi_yoichi"]
        assert (isagi["shots"], isagi["opens"], isagi["resolved"],
                isagi["goals"], isagi["net_pips"]) == (1, 1, 1, 1, 14.0)
        chigiri = by_agent["chigiri_hyoma"]
        assert (chigiri["resolved"], chigiri["goals"],
                chigiri["net_pips"]) == (1, 0, -6.0)
        assert by_agent["bachira_meguru"]["tackled"] == 1
        assert by_agent["reo_mikage"]["tackled"] == 1
        # Roster display names ride along.
        assert isagi["name"] == "Isagi"

    def test_players_sorted_most_involved_first(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        agents = [p["agent"] for p in report["players"]]
        assert agents[:2] == ["chigiri_hyoma", "isagi_yoichi"] or \
            agents[:2] == ["isagi_yoichi", "chigiri_hyoma"]
        assert agents.index("isagi_yoichi") < agents.index("bachira_meguru")


class TestTimelineNarrative:
    def test_goal_and_miss_language(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        lines = [item["line"] for item in report["timeline"]]
        assert any("GOAL!" in ln and "Isagi" in ln and "+14.0p" in ln
                   and "+1.40R" in ln for ln in lines)
        assert any("Saved" in ln and "Chigiri" in ln and "-6.0p" in ln
                   for ln in lines)

    def test_tackle_and_wall_language(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        lines = [item["line"] for item in report["timeline"]]
        assert any("The wall holds" in ln and "Bachira" in ln
                   and "r1_daily_cap" in ln for ln in lines)
        assert any("Isagi tackles Reo" in ln for ln in lines)

    def test_close_items_carry_trade_id_and_numbers(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        closes = [i for i in report["timeline"] if i["type"] == "close"]
        assert len(closes) == 2
        for item in closes:
            assert item["trade_id"]
            assert isinstance(item["pnl_pips"], float)

    def test_tick_summaries_not_itemised(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        assert all(i["type"] != "tick_summary" for i in report["timeline"])

    def test_clock_labels_are_utc_hhmm(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        first = report["timeline"][0]
        assert first["line"].startswith("08:00'")

    def test_no_banned_words_in_narratives(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        blob = json.dumps(report).lower()
        assert "ensemble" not in blob
        assert "aggregator" not in blob


# --------------------------------------------------------------------
# Quiet day
# --------------------------------------------------------------------

class TestQuietDay:
    def test_quiet_report_not_empty(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(QUIET_DAY, live_dir=live)
        assert report["empty"] is False
        assert report["quiet"] is True

    def test_quiet_note_reuses_i002_vocabulary(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(QUIET_DAY, live_dir=live)
        assert highlights.QUIET_VOCAB in report["quiet_note"]
        assert "2 bars evaluated" in report["quiet_note"]
        assert "EURUSD" in report["quiet_note"]

    def test_quiet_headline(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report(QUIET_DAY, live_dir=live)
        assert report["headline"] == (
            f"{QUIET_DAY}: quiet match -- 2 bars evaluated, "
            "no shots taken.")


# --------------------------------------------------------------------
# Degradation (F005 contract)
# --------------------------------------------------------------------

class TestDegradation:
    def test_missing_dir_empty_state(self, tmp_path):
        report = highlights.match_report(
            ACTIVE_DAY, live_dir=tmp_path / "nope")
        assert report["empty"] is True
        assert report["timeline"] == []

    def test_none_live_dir_empty_state(self):
        assert highlights.match_report(ACTIVE_DAY, live_dir=None)["empty"]
        assert highlights.list_reports(5, live_dir=None) == []

    def test_missing_file_empty_state(self, tmp_path):
        live = tmp_path / "squad_live"
        live.mkdir()
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        assert report["empty"] is True

    def test_unknown_day_empty_state(self, tmp_path):
        live = _seeded(tmp_path)
        report = highlights.match_report("2001-01-01", live_dir=live)
        assert report["empty"] is True
        assert "no tape" in report["headline"]

    def test_invalid_day_string_never_raises(self, tmp_path):
        live = _seeded(tmp_path)
        for bogus in ("garbage", "", None, "2026-7-2", "20260720"):
            report = highlights.match_report(bogus, live_dir=live)
            assert report["empty"] is True

    def test_malformed_rows_skipped(self, tmp_path):
        live = tmp_path / "squad_live"
        _write_tape(live, ACTIVE_ROWS,
                    extra_lines=["not json at all", "[1, 2, 3]", "{}"])
        report = highlights.match_report(ACTIVE_DAY, live_dir=live)
        assert report["full_time"]["resolved"] == 2  # unchanged


# --------------------------------------------------------------------
# Index
# --------------------------------------------------------------------

class TestListReports:
    def test_newest_first_with_key_stats(self, tmp_path):
        live = _seeded(tmp_path)
        reports = highlights.list_reports(14, live_dir=live)
        assert [r["day"] for r in reports] == [QUIET_DAY, ACTIVE_DAY]
        assert reports[0]["quiet"] is True
        active = reports[1]
        assert (active["shots"], active["goals"], active["resolved"],
                active["net_pips"]) == (2, 1, 2, 8.0)

    def test_n_clamped(self, tmp_path):
        live = _seeded(tmp_path)
        assert len(highlights.list_reports(1, live_dir=live)) == 1
        assert len(highlights.list_reports(0, live_dir=live)) == 1
        assert len(highlights.list_reports(9999, live_dir=live)) == 2


# --------------------------------------------------------------------
# Trade stories
# --------------------------------------------------------------------

class TestTradeStory:
    def _goal_id(self) -> str:
        close = ACTIVE_ROWS[-2]
        return highlights.trade_id_for(close)

    def test_trade_id_deterministic(self):
        close = ACTIVE_ROWS[-2]
        assert (highlights.trade_id_for(close)
                == highlights.trade_id_for(dict(close))
                == "isagi_yoichi-20260720T200000Z-EURUSD")

    def test_story_stitches_three_chapters(self, tmp_path):
        live = _seeded(tmp_path)
        story = highlights.trade_story(self._goal_id(), live_dir=live)
        labels = [c["label"] for c in story["chapters"]]
        assert labels == ["the opening", "the shot", "full time"]

    def test_story_numbers_match_close_row(self, tmp_path):
        live = _seeded(tmp_path)
        story = highlights.trade_story(self._goal_id(), live_dir=live)
        assert story["goal"] is True
        assert story["pnl_pips"] == 14.0
        assert story["r"] == 1.4
        assert story["tqs"] == 0.62
        assert story["exit_reason"] == "tp"
        assert story["name"] == "Isagi"

    def test_unknown_trade_id_returns_none(self, tmp_path):
        live = _seeded(tmp_path)
        assert highlights.trade_story("nope-123", live_dir=live) is None

    def test_story_with_partial_evidence(self, tmp_path):
        # A close with no matching proposal/open still tells a
        # one-chapter story (recorded evidence only, no invention).
        live = tmp_path / "squad_live"
        close = {"t": f"{ACTIVE_DAY}T16:00:00Z", "type": "close",
                 "agent": "barou_shoei", "symbol": "USDCAD",
                 "pnl_pips": 3.0, "r": 0.3, "exit_reason": "tp"}
        _write_tape(live, [close])
        story = highlights.trade_story(
            highlights.trade_id_for(close), live_dir=live)
        assert [c["label"] for c in story["chapters"]] == ["full time"]


# --------------------------------------------------------------------
# Read-only + provenance
# --------------------------------------------------------------------

class TestInvariants:
    def test_read_only_over_live_dir(self, tmp_path):
        live = _seeded(tmp_path)
        before = _fs_snapshot(live)
        highlights.match_report(ACTIVE_DAY, live_dir=live)
        highlights.list_reports(14, live_dir=live)
        highlights.trade_story("whatever", live_dir=live)
        assert _fs_snapshot(live) == before

    def test_provenance_note_in_every_payload(self, tmp_path):
        live = _seeded(tmp_path)
        assert highlights.match_report(
            ACTIVE_DAY, live_dir=live)["provenance"] == \
            highlights.PROVENANCE_NOTE
        goal_id = "isagi_yoichi-20260720T200000Z-EURUSD"
        assert highlights.trade_story(
            goal_id, live_dir=live)["provenance"] == \
            highlights.PROVENANCE_NOTE
        assert "NOT profit performance" in highlights.PROVENANCE_NOTE
