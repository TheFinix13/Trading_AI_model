"""F022 -- standings assembly from fixture event files.

Acceptance pins:

- Standings equal an independent recomputation from the fixture rows
  for BOTH groupings and every window (equality, not snapshot).
- Deterministic ordering: cumulative R desc, ties on mean TQS, then
  entity for stability; rank is 1-based sequential.
- Insufficient-sample rule SHARED with F021: below
  ``players.MIN_FORM_SAMPLE`` (5) closes the win-rate is None and the
  literal "insufficient sample (n=...)" note rides instead.
- Missing dir / missing file / malformed rows / bogus params degrade
  to the empty payload, never raise (F005 contract).
- Read-only over live_dir.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import leaderboard, players  # noqa: E402

# Fixed "now" for window tests: 2026-07-24T00:00:00Z.
NOW_EPOCH = datetime(2026, 7, 24, tzinfo=timezone.utc).timestamp()

# Close rows across three agents / three pairs with ages relative to
# NOW_EPOCH: OLD (~60d), MID (~20d), FRESH (~2d). Non-close and
# non-numeric-pnl rows must never count.
ROWS = [
    # isagi: 5 closes on EURUSD (win-rate renders: n == MIN_FORM_SAMPLE)
    {"t": "2026-05-25T08:00:00Z", "type": "close", "agent": "isagi_yoichi",
     "symbol": "EURUSD", "pnl_pips": 10.0, "r": 1.0, "tqs": 0.50},
    {"t": "2026-07-04T08:00:00Z", "type": "close", "agent": "isagi_yoichi",
     "symbol": "EURUSD", "pnl_pips": -5.0, "r": -1.0, "tqs": 0.30},
    {"t": "2026-07-04T12:00:00Z", "type": "close", "agent": "isagi_yoichi",
     "symbol": "EURUSD", "pnl_pips": 14.0, "r": 1.4, "tqs": 0.62},
    {"t": "2026-07-22T08:00:00Z", "type": "close", "agent": "isagi_yoichi",
     "symbol": "EURUSD", "pnl_pips": 8.0, "r": 0.8, "tqs": 0.55},
    {"t": "2026-07-22T12:00:00Z", "type": "close", "agent": "isagi_yoichi",
     "symbol": "EURUSD", "pnl_pips": -4.0, "r": -0.8, "tqs": 0.40},
    # bachira: 2 closes on GBPUSD (insufficient sample), one carries
    # no r/tqs (field-variant: agent_id + timestamp).
    {"timestamp": "2026-07-22T16:00:00Z", "type": "close",
     "agent_id": "bachira_meguru", "symbol": "GBPUSD",
     "pnl_pips": 6.0, "r": 1.2, "tqs": 0.70},
    {"t": "2026-07-23T08:00:00Z", "type": "close",
     "agent": "bachira_meguru", "symbol": "GBPUSD", "pnl_pips": -3.0},
    # barou: 1 close on USDCAD, r ties bachira's cum_r (tie-break on
    # mean TQS: barou 0.80 > bachira 0.70).
    {"t": "2026-07-23T12:00:00Z", "type": "close", "agent": "barou_shoei",
     "symbol": "USDCAD", "pnl_pips": 9.0, "r": 1.2, "tqs": 0.80},
    # Rows that must never count toward standings.
    {"t": "2026-07-23T13:00:00Z", "type": "proposal",
     "agent": "isagi_yoichi", "symbol": "EURUSD", "dir": "long"},
    {"t": "2026-07-23T14:00:00Z", "type": "open",
     "agent": "isagi_yoichi", "symbol": "EURUSD", "dir": "long"},
    {"t": "2026-07-23T15:00:00Z", "type": "close",
     "agent": "isagi_yoichi", "symbol": "EURUSD", "pnl_pips": None},
    {"t": "2026-07-23T16:00:00Z", "type": "tick_summary",
     "symbol": "EURUSD", "tick_id": 9},
]


def _write_tape(live: Path, rows: list, extra_lines: list[str] = ()) -> None:
    live.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in rows]
    lines.extend(extra_lines)
    (live / "events.jsonl").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8")


def _seeded(tmp_path: Path) -> Path:
    live = tmp_path / "squad_live"
    _write_tape(live, ROWS)
    return live


def _closes(rows):
    return [r for r in rows if r.get("type") == "close"
            and isinstance(r.get("pnl_pips"), (int, float))]


def _row_by_entity(payload: dict) -> dict:
    return {r["entity"]: r for r in payload["rows"]}


# --------------------------------------------------------------------
# Grouping equality vs independent recomputation
# --------------------------------------------------------------------

class TestAgentGrouping:
    def test_counts_and_sums_match_recomputation(self, tmp_path):
        live = _seeded(tmp_path)
        table = _row_by_entity(leaderboard.standings("agent", live_dir=live))
        closes = _closes(ROWS)
        for key in ("isagi_yoichi", "bachira_meguru", "barou_shoei"):
            mine = [r for r in closes
                    if (r.get("agent") or r.get("agent_id")) == key]
            row = table[key]
            assert row["closed_trades"] == len(mine)
            assert row["wins"] == sum(
                1 for r in mine if r["pnl_pips"] > 0)
            assert row["cum_r"] == round(sum(
                r["r"] for r in mine if isinstance(r.get("r"), float)), 2)
            tqs = [r["tqs"] for r in mine
                   if isinstance(r.get("tqs"), float)]
            expected_tqs = round(sum(tqs) / len(tqs), 3) if tqs else None
            assert row["mean_tqs"] == expected_tqs

    def test_isagi_exact_numbers(self, tmp_path):
        live = _seeded(tmp_path)
        row = _row_by_entity(
            leaderboard.standings("agent", live_dir=live))["isagi_yoichi"]
        assert row["closed_trades"] == 5
        assert row["wins"] == 3
        assert row["cum_r"] == 1.4
        assert row["mean_tqs"] == round((0.50 + 0.30 + 0.62 + 0.55
                                         + 0.40) / 5, 3)
        assert row["win_rate_pct"] == 60.0
        assert row["insufficient_sample"] is False

    def test_display_name_and_player_link(self, tmp_path):
        live = _seeded(tmp_path)
        table = _row_by_entity(leaderboard.standings("agent", live_dir=live))
        assert table["isagi_yoichi"]["name"] == "Isagi"
        assert table["isagi_yoichi"]["player_id"] == "isagi"
        assert table["barou_shoei"]["player_id"] == "barou"

    def test_unknown_agent_key_keeps_raw_name(self, tmp_path):
        live = tmp_path / "squad_live"
        _write_tape(live, [
            {"t": "2026-07-23T08:00:00Z", "type": "close",
             "agent": "mystery_striker", "symbol": "EURUSD",
             "pnl_pips": 3.0, "r": 0.5},
        ])
        row = leaderboard.standings("agent", live_dir=live)["rows"][0]
        assert row["entity"] == row["name"] == "mystery_striker"
        assert row["player_id"] is None

    def test_last_active_is_latest_close_ts(self, tmp_path):
        live = _seeded(tmp_path)
        table = _row_by_entity(leaderboard.standings("agent", live_dir=live))
        assert table["isagi_yoichi"]["last_active"] == "2026-07-22T12:00:00Z"
        assert table["bachira_meguru"]["last_active"] == "2026-07-23T08:00:00Z"


class TestPairGrouping:
    def test_counts_and_sums_match_recomputation(self, tmp_path):
        live = _seeded(tmp_path)
        table = _row_by_entity(leaderboard.standings("pair", live_dir=live))
        closes = _closes(ROWS)
        for sym in ("EURUSD", "GBPUSD", "USDCAD"):
            mine = [r for r in closes if r["symbol"] == sym]
            row = table[sym]
            assert row["closed_trades"] == len(mine)
            assert row["cum_r"] == round(sum(
                r["r"] for r in mine if isinstance(r.get("r"), float)), 2)

    def test_pair_rows_carry_no_player_link(self, tmp_path):
        live = _seeded(tmp_path)
        for row in leaderboard.standings("pair", live_dir=live)["rows"]:
            assert row["player_id"] is None
            assert row["name"] == row["entity"]


# --------------------------------------------------------------------
# Ordering + tie-break
# --------------------------------------------------------------------

class TestOrdering:
    def test_sorted_by_cum_r_desc_with_sequential_rank(self, tmp_path):
        live = _seeded(tmp_path)
        payload = leaderboard.standings("agent", live_dir=live)
        cum_rs = [r["cum_r"] for r in payload["rows"]]
        assert cum_rs == sorted(cum_rs, reverse=True)
        assert [r["rank"] for r in payload["rows"]] == \
            list(range(1, len(payload["rows"]) + 1))

    def test_tie_breaks_on_mean_tqs(self, tmp_path):
        live = _seeded(tmp_path)
        rows = leaderboard.standings("agent", live_dir=live)["rows"]
        # bachira and barou both sit at cum_r == 1.2; barou's mean TQS
        # (0.80) beats bachira's (0.70).
        order = [r["entity"] for r in rows]
        assert order.index("barou_shoei") < order.index("bachira_meguru")

    def test_deterministic_across_calls(self, tmp_path):
        live = _seeded(tmp_path)
        a = leaderboard.standings("agent", live_dir=live)
        b = leaderboard.standings("agent", live_dir=live)
        a.pop("generated_at"), b.pop("generated_at")
        assert a == b


# --------------------------------------------------------------------
# Insufficient-sample rule (shared with F021)
# --------------------------------------------------------------------

class TestInsufficientSampleRule:
    def test_below_min_sample_withholds_percentage(self, tmp_path):
        live = _seeded(tmp_path)
        row = _row_by_entity(
            leaderboard.standings("agent", live_dir=live))["bachira_meguru"]
        assert row["closed_trades"] == 2 < players.MIN_FORM_SAMPLE
        assert row["insufficient_sample"] is True
        assert row["win_rate_pct"] is None
        assert row["note"] == "insufficient sample (n=2)"

    def test_at_min_sample_boundary_renders(self, tmp_path):
        live = _seeded(tmp_path)
        row = _row_by_entity(
            leaderboard.standings("agent", live_dir=live))["isagi_yoichi"]
        assert row["closed_trades"] == players.MIN_FORM_SAMPLE == 5
        assert row["insufficient_sample"] is False
        assert row["win_rate_pct"] == 60.0
        assert row["note"] is None

    def test_min_sample_constant_shared_with_f021(self, tmp_path):
        live = _seeded(tmp_path)
        payload = leaderboard.standings("agent", live_dir=live)
        assert payload["min_sample"] == players.MIN_FORM_SAMPLE


# --------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------

class TestWindows:
    def test_all_history_default(self, tmp_path):
        live = _seeded(tmp_path)
        payload = leaderboard.standings("agent", live_dir=live)
        assert payload["window_days"] is None
        assert payload["window_label"] == "all recorded history"
        assert payload["total_closed"] == len(_closes(ROWS))

    def test_30d_window_drops_old_close(self, tmp_path):
        live = _seeded(tmp_path)
        payload = leaderboard.standings(
            "agent", window_days=30, live_dir=live, now=NOW_EPOCH)
        assert payload["window_label"] == "last 30 days"
        # isagi's 2026-05-25 close (~60d old) falls out; 4 remain.
        row = _row_by_entity(payload)["isagi_yoichi"]
        assert row["closed_trades"] == 4
        assert row["cum_r"] == round(-1.0 + 1.4 + 0.8 - 0.8, 2)

    def test_7d_window_keeps_only_fresh(self, tmp_path):
        live = _seeded(tmp_path)
        payload = leaderboard.standings(
            "pair", window_days=7, live_dir=live, now=NOW_EPOCH)
        table = _row_by_entity(payload)
        # EURUSD keeps the two 07-22 closes; the July-4 pair falls out.
        assert table["EURUSD"]["closed_trades"] == 2
        assert table["GBPUSD"]["closed_trades"] == 2
        assert table["USDCAD"]["closed_trades"] == 1
        assert payload["total_closed"] == 5

    def test_unsupported_window_folds_to_all(self, tmp_path):
        live = _seeded(tmp_path)
        for bad in (3, 90, -1, "banana"):
            payload = leaderboard.standings(
                "agent", window_days=bad, live_dir=live)
            assert payload["window_days"] is None


# --------------------------------------------------------------------
# Degradation (never raise) + read-only + provenance
# --------------------------------------------------------------------

class TestDegradation:
    def test_unknown_grouping_folds_to_agent(self, tmp_path):
        live = _seeded(tmp_path)
        payload = leaderboard.standings("squad!!", live_dir=live)
        assert payload["by"] == "agent"

    def test_missing_live_dir(self):
        payload = leaderboard.standings("agent", live_dir=None)
        assert payload["rows"] == []
        assert payload["total_closed"] == 0

    def test_missing_events_file(self, tmp_path):
        empty = tmp_path / "squad_live"
        empty.mkdir()
        assert leaderboard.standings("agent", live_dir=empty)["rows"] == []

    def test_malformed_rows_skipped(self, tmp_path):
        live = tmp_path / "squad_live"
        _write_tape(live, ROWS, extra_lines=[
            "{not json", '"just a string"', '{"type": "close"}'])
        payload = leaderboard.standings("agent", live_dir=live)
        assert payload["total_closed"] == len(_closes(ROWS))

    def test_unparseable_ts_excluded_from_windowed_view(self, tmp_path):
        live = tmp_path / "squad_live"
        _write_tape(live, [
            {"t": "garbage-ts", "type": "close", "agent": "isagi_yoichi",
             "symbol": "EURUSD", "pnl_pips": 5.0, "r": 0.5},
        ])
        allh = leaderboard.standings("agent", live_dir=live)
        assert allh["total_closed"] == 1
        windowed = leaderboard.standings(
            "agent", window_days=7, live_dir=live, now=NOW_EPOCH)
        assert windowed["total_closed"] == 0

    def test_provenance_in_every_payload(self, tmp_path):
        live = _seeded(tmp_path)
        for payload in (
            leaderboard.standings("agent", live_dir=live),
            leaderboard.standings("pair", live_dir=live),
            leaderboard.standings("agent", live_dir=None),
        ):
            assert payload["provenance"] == leaderboard.PROVENANCE_NOTE
            assert "NOT investment performance" in payload["provenance"]

    def test_read_only_over_live_dir(self, tmp_path):
        live = _seeded(tmp_path)
        before = {str(p): p.stat().st_size for p in live.rglob("*")}
        leaderboard.standings("agent", live_dir=live)
        leaderboard.standings("pair", window_days=7, live_dir=live,
                              now=NOW_EPOCH)
        assert {str(p): p.stat().st_size
                for p in live.rglob("*")} == before

    def test_banned_words_absent_from_module_strings(self):
        source = Path(leaderboard.__file__).read_text(encoding="utf-8")
        for banned in ("ensemble", "aggregator"):
            assert banned not in source.lower()
