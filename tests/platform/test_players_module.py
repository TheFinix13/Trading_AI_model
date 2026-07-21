"""Unit tests for agent/platform/players.py -- F002 data plane.

Cover the four surfaces:

* ID normalisation (case, trailing slash, canon_player, unknown).
* Bio markdown parsing (playstyle prose, evolution list, signature
  blurb from the header meta, missing / partial file).
* Live events ingestion + per-agent stats (proposals, wins, best
  pair, best/worst trade, days active, empty case).
* `get_player` + `list_players` full contract (retired / standby
  source hints, ten valid IDs, read-only invariant).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent.platform import players


# --------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_bio_cache():
    players._reset_bio_cache()
    yield
    players._reset_bio_cache()


@pytest.fixture()
def tmp_bio_dir(tmp_path: Path) -> Path:
    d = tmp_path / "roster"
    d.mkdir()
    return d


@pytest.fixture()
def tmp_live_dir(tmp_path: Path) -> Path:
    d = tmp_path / "squad_live"
    d.mkdir()
    return d


def _write_events(live_dir: Path, rows: list[dict]) -> None:
    with (live_dir / "events.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _fs_snapshot(root: Path) -> dict[str, int]:
    snap: dict[str, int] = {}
    for p in root.rglob("*"):
        if p.is_file():
            snap[str(p.relative_to(root))] = p.stat().st_size
    return snap


# --------------------------------------------------------------------
# ID normalisation
# --------------------------------------------------------------------

def test_normalize_id_direct_slug():
    assert players.normalize_id("isagi") == "isagi"
    assert players.normalize_id("kunigami") == "kunigami"


def test_normalize_id_case_insensitive():
    assert players.normalize_id("Isagi") == "isagi"
    assert players.normalize_id("RIN") == "rin"


def test_normalize_id_trailing_slash():
    assert players.normalize_id("isagi/") == "isagi"
    assert players.normalize_id("/rin/") == "rin"


def test_normalize_id_canon_player_variant():
    assert players.normalize_id("isagi_yoichi") == "isagi"
    assert players.normalize_id("itoshi_rin") == "rin"
    assert players.normalize_id("kunigami_rensuke") == "kunigami"


def test_normalize_id_suffix_variant():
    assert players.normalize_id("isagi-v1") == "isagi"
    assert players.normalize_id("Rin v2") == "rin"


def test_normalize_id_unknown_returns_none():
    assert players.normalize_id("unknown") is None
    assert players.normalize_id("") is None
    assert players.normalize_id(None) is None
    assert players.normalize_id("   ") is None


def test_valid_ids_is_ten_and_ordered():
    ids = players.valid_ids()
    assert len(ids) == 10
    assert ids[0] == "isagi"
    assert ids[-1] == "kunigami"
    assert set(ids) == {
        "isagi", "bachira", "rin", "chigiri", "reo", "nagi",
        "barou", "karasu", "sae", "kunigami",
    }


# --------------------------------------------------------------------
# Bio markdown parsing
# --------------------------------------------------------------------

BIO_TEMPLATE = """# Isagi -- Yoichi Isagi

- **id:** `isagi`
- **canon_player:** `isagi_yoichi`
- **status:** active
- **signature_blurb:** Isagi is the striker who sees the whole field. He fades zones against the daily trend.

## Playstyle prose

First paragraph of playstyle prose.

Second paragraph explaining the mechanic.

## Signature setup

```
    zone touch -> counter-trend fade
```

## Evolution history

- v1.0 landed 2026-06-24.
- v1.1 (2026-07-14) -- F20 provenance stamping added.
"""


def test_parse_bio_all_sections(tmp_bio_dir: Path):
    (tmp_bio_dir / "isagi.md").write_text(BIO_TEMPLATE, encoding="utf-8")
    bio = players._load_bio("isagi", bio_dir=tmp_bio_dir)
    assert "First paragraph" in bio["playstyle_prose"]
    assert "Second paragraph" in bio["playstyle_prose"]
    assert "counter-trend fade" in bio["signature_setup"]
    assert bio["signature_blurb"].startswith("Isagi is the striker")
    assert len(bio["evolution"]) == 2
    assert bio["evolution"][0]["note"].startswith("v1.0 landed")


def test_parse_bio_missing_file_returns_empty(tmp_bio_dir: Path):
    bio = players._load_bio("isagi", bio_dir=tmp_bio_dir)
    assert bio == {
        "playstyle_prose": "",
        "signature_setup": "",
        "evolution": [],
        "signature_blurb": "",
    }


def test_parse_bio_partial_file(tmp_bio_dir: Path):
    only_header = (
        "# Isagi\n\n"
        "- **id:** `isagi`\n"
        "- **signature_blurb:** Header only bio.\n"
    )
    (tmp_bio_dir / "isagi.md").write_text(only_header, encoding="utf-8")
    bio = players._load_bio("isagi", bio_dir=tmp_bio_dir)
    assert bio["signature_blurb"].startswith("Header only bio")
    assert bio["playstyle_prose"] == ""
    assert bio["evolution"] == []


# --------------------------------------------------------------------
# Live events + per-agent stats
# --------------------------------------------------------------------

def test_stats_empty_rows_yield_zeros():
    stats = players._stats_for_agent("isagi_yoichi", [])
    assert stats["proposals"] == 0
    assert stats["trades"] == 0
    assert stats["wins"] == 0
    assert stats["net_pips"] == 0.0
    assert stats["avg_pips"] == 0.0
    assert stats["best_pair"] is None
    assert stats["best_trade_pips"] == 0.0
    assert stats["worst_trade_pips"] == 0.0
    assert stats["days_active"] == 0


def test_stats_counts_proposals_and_closes():
    rows = [
        {"t": "2026-07-15T09:00:00Z", "type": "propose", "agent": "isagi_yoichi"},
        {"t": "2026-07-15T13:00:00Z", "type": "propose", "agent": "isagi_yoichi"},
        {"t": "2026-07-15T21:00:00Z", "type": "close",
         "agent": "isagi_yoichi", "symbol": "EURUSD", "pnl_pips": 12.5},
        {"t": "2026-07-16T09:00:00Z", "type": "close",
         "agent": "isagi_yoichi", "symbol": "GBPUSD", "pnl_pips": -8.0},
        {"t": "2026-07-16T09:00:00Z", "type": "close",
         "agent": "bachira_meguru", "symbol": "EURUSD", "pnl_pips": 5.0},
    ]
    stats = players._stats_for_agent("isagi_yoichi", rows)
    assert stats["proposals"] == 2
    assert stats["trades"] == 2
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["net_pips"] == 4.5
    assert stats["best_pair"] == "EURUSD"
    assert stats["best_trade_pips"] == 12.5
    assert stats["worst_trade_pips"] == -8.0
    assert stats["days_active"] == 2
    assert stats["win_rate_pct"] == 50.0


def test_stats_ignores_non_numeric_pnl():
    rows = [
        {"t": "2026-07-15T21:00:00Z", "type": "close",
         "agent": "isagi_yoichi", "symbol": "EURUSD", "pnl_pips": "not-a-number"},
        {"t": "2026-07-15T22:00:00Z", "type": "close",
         "agent": "isagi_yoichi", "symbol": "EURUSD", "pnl_pips": None},
    ]
    stats = players._stats_for_agent("isagi_yoichi", rows)
    assert stats["trades"] == 0
    assert stats["net_pips"] == 0.0


def test_stats_accepts_agent_id_field_variant():
    rows = [
        {"t": "2026-07-15T09:00:00Z", "type": "close",
         "agent_id": "isagi_yoichi", "symbol": "EURUSD", "pnl_pips": 4.0},
    ]
    stats = players._stats_for_agent("isagi_yoichi", rows)
    assert stats["trades"] == 1
    assert stats["net_pips"] == 4.0


def test_recent_activity_returns_newest_first():
    rows = [
        {"t": "2026-07-15T09:00:00Z", "type": "propose", "agent": "isagi_yoichi", "symbol": "EURUSD"},
        {"t": "2026-07-15T21:00:00Z", "type": "close", "agent": "isagi_yoichi",
         "symbol": "EURUSD", "pnl_pips": 12.5},
        {"t": "2026-07-16T09:00:00Z", "type": "propose", "agent": "isagi_yoichi", "symbol": "GBPUSD"},
    ]
    activity = players._recent_activity("isagi_yoichi", rows, n=2)
    assert len(activity) == 2
    assert activity[0]["t"] == "2026-07-16T09:00:00Z"
    assert activity[1]["t"] == "2026-07-15T21:00:00Z"
    assert activity[1]["pnl_pips"] == 12.5


def test_read_events_missing_file(tmp_live_dir: Path):
    assert players._read_events(tmp_live_dir) == []


def test_read_events_skips_malformed(tmp_live_dir: Path):
    (tmp_live_dir / "events.jsonl").write_text(
        '{"type":"propose","agent":"isagi_yoichi"}\n'
        'not-json\n'
        '{"type":"close","agent":"isagi_yoichi","pnl_pips":3.0}\n',
        encoding="utf-8",
    )
    rows = players._read_events(tmp_live_dir)
    assert len(rows) == 2


# --------------------------------------------------------------------
# get_player / list_players full contract
# --------------------------------------------------------------------

def test_get_player_unknown_id_returns_none():
    assert players.get_player("obi-wan") is None
    assert players.get_player(None) is None


def test_get_player_all_ten_ids_return_payload(tmp_bio_dir: Path, tmp_live_dir: Path):
    # empty bio dir + empty live dir -> module still returns a full
    # shape for every canonical id; empty state is degradable-ish.
    for id_ in players.valid_ids():
        payload = players.get_player(id_, live_dir=tmp_live_dir, bio_dir=tmp_bio_dir)
        assert payload is not None
        assert payload["id"] == id_
        assert isinstance(payload["stats"], dict)
        assert isinstance(payload["recent_activity"], list)
        assert "source_hint" in payload
        assert "generated_at" in payload
        assert payload["symbols"] and isinstance(payload["symbols"], list)


def test_get_player_status_field_matches_roster(tmp_live_dir: Path):
    payload = players.get_player("isagi", live_dir=tmp_live_dir)
    assert payload["status"] == "active"
    ret = players.get_player("kunigami", live_dir=tmp_live_dir)
    assert ret["status"] == "retired"
    sae = players.get_player("sae", live_dir=tmp_live_dir)
    assert sae["status"] == "standby"


def test_get_player_source_hint_retired():
    ret = players.get_player("kunigami")
    assert "Retired" in ret["source_hint"] or "retired" in ret["source_hint"]


def test_get_player_source_hint_standby_no_rows(tmp_live_dir: Path):
    sae = players.get_player("sae", live_dir=tmp_live_dir)
    assert "standby" in sae["source_hint"].lower()


def test_get_player_source_hint_active_no_rows(tmp_live_dir: Path):
    isagi = players.get_player("isagi", live_dir=tmp_live_dir)
    assert "No shadow-paper" in isagi["source_hint"]


def test_get_player_source_hint_active_with_rows(tmp_bio_dir: Path, tmp_live_dir: Path):
    _write_events(tmp_live_dir, [
        {"t": "2026-07-15T09:00:00Z", "type": "propose", "agent": "isagi_yoichi"},
        {"t": "2026-07-15T13:00:00Z", "type": "close",
         "agent": "isagi_yoichi", "symbol": "EURUSD", "pnl_pips": 12.5},
    ])
    isagi = players.get_player("isagi", live_dir=tmp_live_dir, bio_dir=tmp_bio_dir)
    assert "2" in isagi["source_hint"]
    assert isagi["stats"]["proposals"] == 1
    assert isagi["stats"]["net_pips"] == 12.5


def test_list_players_returns_ten_in_canonical_order(tmp_bio_dir: Path, tmp_live_dir: Path):
    rows = players.list_players(live_dir=tmp_live_dir, bio_dir=tmp_bio_dir)
    assert len(rows) == 10
    assert rows[0]["id"] == "isagi"
    assert rows[-1]["id"] == "kunigami"
    # all rows carry the top-line stats keys
    for row in rows:
        assert set(row).issuperset({
            "id", "name", "playstyle_tag", "status", "tier",
            "symbols", "signature_blurb",
            "proposals", "wins", "net_pips",
        })


def test_list_state_envelope(tmp_bio_dir: Path, tmp_live_dir: Path):
    st = players.list_state(live_dir=tmp_live_dir, bio_dir=tmp_bio_dir)
    assert st["total"] == 10
    assert len(st["players"]) == 10
    assert "generated_at" in st


# --------------------------------------------------------------------
# Read-only invariant
# --------------------------------------------------------------------

def test_read_only_invariant(tmp_bio_dir: Path, tmp_live_dir: Path):
    # write one baseline event so the parser has something to do.
    _write_events(tmp_live_dir, [
        {"t": "2026-07-15T09:00:00Z", "type": "propose", "agent": "isagi_yoichi"},
    ])
    before_bio = _fs_snapshot(tmp_bio_dir)
    before_live = _fs_snapshot(tmp_live_dir)
    for id_ in players.valid_ids():
        players.get_player(id_, live_dir=tmp_live_dir, bio_dir=tmp_bio_dir)
    players.list_players(live_dir=tmp_live_dir, bio_dir=tmp_bio_dir)
    players.list_state(live_dir=tmp_live_dir, bio_dir=tmp_bio_dir)
    assert _fs_snapshot(tmp_bio_dir) == before_bio
    assert _fs_snapshot(tmp_live_dir) == before_live


# --------------------------------------------------------------------
# Default bio dir wires up to company/roster/players/
# --------------------------------------------------------------------

def test_default_bio_dir_reads_shipped_bios():
    # These files are shipped in this commit; the smoke test asserts
    # the parser wires up to them by default.
    payload = players.get_player("isagi")
    assert payload["playstyle_prose"]
    assert payload["signature_blurb"]
    assert payload["evolution"]


def test_default_bio_dir_covers_all_ten_shipped():
    for id_ in players.valid_ids():
        payload = players.get_player(id_)
        assert payload["playstyle_prose"], f"missing prose for {id_}"
        assert payload["evolution"], f"missing evolution for {id_}"
