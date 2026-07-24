"""F021 -- form guide, gate status, recent decisions (Sprint 3).

Covers the three new read-only accessors in agent/platform/players.py:

* ``form_guide``   : rolling window mechanics, the insufficient-sample
  rule (win-rate withheld below MIN_FORM_SAMPLE closes), zero-history
  empty state, TQS series extraction, window clamping.
* ``gate_status``  : benched resolution against the CPO publication
  manifest (published fail/dead only), honest standby fallbacks,
  retired/active passthrough.
* ``recent_decisions`` : outcome + exit_reason enrichment on closes.

Plus the payload integration (get_player / list_players) and the
read-only invariant. Numbers are equality-tested against independent
recomputations from the fixture rows, not snapshotted.
"""
from __future__ import annotations

import json
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
def tmp_live_dir(tmp_path: Path) -> Path:
    d = tmp_path / "squad_live"
    d.mkdir()
    return d


def _write_events(live_dir: Path, rows: list[dict]) -> None:
    with (live_dir / "events.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _close(i: int, pnl: float, agent: str = "isagi_yoichi",
           tqs: float | None = None, **extra) -> dict:
    row = {
        "t": f"2026-07-{(i % 28) + 1:02d}T{i % 24:02d}:00:00Z",
        "type": "close",
        "agent": agent,
        "symbol": "EURUSD",
        "pnl_pips": pnl,
    }
    if tqs is not None:
        row["tqs"] = tqs
    row.update(extra)
    return row


def _manifest(tmp_path: Path, *, publish: bool = True,
              verdict_kind: str = "fail",
              verdict_label: str = "Fails pre-registered AE2 quality criterion",
              headline_stat: str = "OOS mean TQS 0.097") -> Path:
    path = tmp_path / "publication_manifest.json"
    path.write_text(json.dumps({
        "cpo_signoff_by": "cpo",
        "cpo_signoff_at": "2026-07-24T00:00:00Z",
        "entries": [{
            "campaign_id": "phase_ae_sae_event_specialist",
            "publish": publish,
            "verdict_kind": verdict_kind,
            "verdict_label": verdict_label,
            "brand_summary": "x",
            "headline_stat": headline_stat,
        }],
    }), encoding="utf-8")
    return path


# --------------------------------------------------------------------
# form_guide -- window mechanics
# --------------------------------------------------------------------

def test_form_guide_unknown_id_returns_none(tmp_live_dir: Path):
    assert players.form_guide("not-a-striker", live_dir=tmp_live_dir) is None


def test_form_guide_zero_history_empty_state(tmp_live_dir: Path):
    _write_events(tmp_live_dir, [])
    fg = players.form_guide("isagi", live_dir=tmp_live_dir)
    assert fg["sample_size"] == 0
    assert fg["win_rate_pct"] is None
    assert fg["insufficient_sample"] is True
    assert fg["note"] == "insufficient sample (n=0)"
    assert fg["form"] is None
    assert fg["results"] == []
    assert fg["tqs_series"] == []
    assert fg["net_pips_window"] == 0.0


def test_form_guide_rolling_window_takes_the_tail(tmp_live_dir: Path):
    # 25 closes; first 5 are large wins that must fall OUT of a 20-window.
    rows = [_close(i, 100.0) for i in range(5)]
    rows += [_close(i + 5, -1.0 if i % 2 else 2.0) for i in range(20)]
    _write_events(tmp_live_dir, rows)
    fg = players.form_guide("isagi", live_dir=tmp_live_dir, n=20)
    assert fg["sample_size"] == 20
    # Independent recomputation over the last 20 rows only.
    tail = rows[-20:]
    wins = sum(1 for r in tail if r["pnl_pips"] > 0)
    assert fg["win_rate_pct"] == round(100.0 * wins / 20, 1)
    assert fg["net_pips_window"] == round(sum(r["pnl_pips"] for r in tail), 1)
    assert 100.0 not in [0.0]  # guard: big early wins excluded
    assert fg["window_label"] == "last 20 closed shadow-paper trades"


def test_form_guide_results_and_form_strip(tmp_live_dir: Path):
    pnls = [1.0, -2.0, 3.0, 4.0, -5.0, 6.0]
    _write_events(tmp_live_dir, [_close(i, p) for i, p in enumerate(pnls)])
    fg = players.form_guide("isagi", live_dir=tmp_live_dir)
    assert fg["results"] == ["W", "L", "W", "W", "L", "W"]
    assert fg["form"] == "L-W-W-L-W"  # last five only


def test_form_guide_insufficient_sample_withholds_win_rate(tmp_live_dir: Path):
    _write_events(tmp_live_dir, [_close(i, 5.0) for i in range(3)])
    fg = players.form_guide("isagi", live_dir=tmp_live_dir)
    assert fg["sample_size"] == 3
    assert fg["insufficient_sample"] is True
    assert fg["win_rate_pct"] is None
    assert fg["note"] == "insufficient sample (n=3)"
    # The rails themselves stay visible.
    assert fg["results"] == ["W", "W", "W"]
    assert fg["min_sample"] == players.MIN_FORM_SAMPLE == 5


def test_form_guide_exactly_min_sample_renders_percentage(tmp_live_dir: Path):
    _write_events(
        tmp_live_dir,
        [_close(i, 1.0 if i < 3 else -1.0) for i in range(5)])
    fg = players.form_guide("isagi", live_dir=tmp_live_dir)
    assert fg["sample_size"] == 5
    assert fg["insufficient_sample"] is False
    assert fg["win_rate_pct"] == 60.0
    assert fg["note"] is None


def test_form_guide_tqs_series_numeric_rows_only(tmp_live_dir: Path):
    rows = [
        _close(0, 1.0, tqs=0.41),
        _close(1, -1.0),                    # no tqs -> excluded
        _close(2, 2.0, tqs="bad"),          # non-numeric -> excluded
        _close(3, 3.0, tqs=0.6789),
    ]
    _write_events(tmp_live_dir, rows)
    fg = players.form_guide("isagi", live_dir=tmp_live_dir)
    assert [p["tqs"] for p in fg["tqs_series"]] == [0.41, 0.679]
    assert fg["sample_size"] == 4  # tqs gaps don't shrink the window


def test_form_guide_ignores_non_close_and_non_numeric_rows(tmp_live_dir: Path):
    rows = [
        {"t": "2026-07-01T00:00:00Z", "type": "propose",
         "agent": "isagi_yoichi", "symbol": "EURUSD"},
        _close(1, "not-a-number"),
        _close(2, 7.5),
        _close(3, -1.5, agent="bachira_meguru"),
    ]
    _write_events(tmp_live_dir, rows)
    fg = players.form_guide("isagi", live_dir=tmp_live_dir)
    assert fg["sample_size"] == 1
    assert fg["net_pips_window"] == 7.5


def test_form_guide_window_clamped_to_200(tmp_live_dir: Path):
    _write_events(tmp_live_dir, [_close(i, 1.0) for i in range(210)])
    fg = players.form_guide("isagi", live_dir=tmp_live_dir, n=5000)
    assert fg["window"] == 200
    assert fg["sample_size"] == 200


# --------------------------------------------------------------------
# gate_status
# --------------------------------------------------------------------

def test_gate_status_unknown_id_returns_none():
    assert players.gate_status("nobody") is None


def test_gate_status_active_agent_passthrough(tmp_path: Path):
    out = players.gate_status("isagi", manifest_path=_manifest(tmp_path))
    assert out["status"] == "active"
    assert out["finding_url"] is None


def test_gate_status_retired_agent(tmp_path: Path):
    out = players.gate_status("kunigami", manifest_path=_manifest(tmp_path))
    assert out["status"] == "retired"
    assert out["reason"]  # playstyle tag, non-empty
    assert out["finding_url"] is None


def test_gate_status_sae_benched_from_published_fail(tmp_path: Path):
    out = players.gate_status("sae", manifest_path=_manifest(tmp_path))
    assert out["status"] == "benched"
    assert out["reason"] == "Fails pre-registered AE2 quality criterion"
    assert out["finding_url"] == "/research#phase_ae_sae_event_specialist"
    assert out["headline_stat"] == "OOS mean TQS 0.097"


def test_gate_status_manifest_missing_falls_back_to_standby(tmp_path: Path):
    out = players.gate_status(
        "sae", manifest_path=tmp_path / "does-not-exist.json")
    assert out["status"] == "standby"
    assert out["finding_url"] is None


def test_gate_status_unpublished_finding_stays_standby(tmp_path: Path):
    out = players.gate_status(
        "sae", manifest_path=_manifest(tmp_path, publish=False))
    assert out["status"] == "standby"


def test_gate_status_non_fail_verdict_stays_standby(tmp_path: Path):
    out = players.gate_status(
        "sae", manifest_path=_manifest(tmp_path, verdict_kind="alive_survivor"))
    assert out["status"] == "standby"


def test_gate_status_sae_benched_on_the_shipped_manifest():
    """Pins the real product behaviour: the repo's own manifest
    (D112) publishes the Phase AE FAIL, so Sae renders benched."""
    out = players.gate_status("sae")
    assert out["status"] == "benched"
    assert out["finding_url"] == "/research#phase_ae_sae_event_specialist"


# --------------------------------------------------------------------
# recent_decisions
# --------------------------------------------------------------------

def test_recent_decisions_unknown_id_returns_none(tmp_live_dir: Path):
    assert players.recent_decisions("nobody", live_dir=tmp_live_dir) is None


def test_recent_decisions_outcome_and_exit_reason(tmp_live_dir: Path):
    rows = [
        {"t": "2026-07-01T00:00:00Z", "type": "propose",
         "agent": "isagi_yoichi", "symbol": "EURUSD", "dir": "buy"},
        _close(1, 12.5, exit_reason="tp"),
        _close(2, -4.0, exit_reason="sl"),
        _close(3, 3.0),
    ]
    _write_events(tmp_live_dir, rows)
    out = players.recent_decisions("isagi", live_dir=tmp_live_dir, n=5)
    closes = [r for r in out if r["type"] == "close"]
    # Newest first (the F002 recent-activity contract).
    assert [r["outcome"] for r in closes] == ["win", "loss", "win"]
    assert "exit_reason" not in closes[0]          # _close(3) had none
    assert closes[1]["exit_reason"] == "sl"
    assert closes[2]["exit_reason"] == "tp"
    proposes = [r for r in out if r["type"] != "close"]
    assert all("outcome" not in r for r in proposes)


# --------------------------------------------------------------------
# payload integration + read-only invariant
# --------------------------------------------------------------------

def test_get_player_payload_carries_f021_fields(tmp_live_dir: Path):
    _write_events(tmp_live_dir, [_close(i, 2.0) for i in range(6)])
    payload = players.get_player("isagi", live_dir=tmp_live_dir)
    assert payload["form_guide"]["sample_size"] == 6
    assert payload["form_guide"]["win_rate_pct"] == 100.0
    assert payload["gate_status"]["status"] == "active"
    assert isinstance(payload["recent_decisions"], list)


def test_list_players_cards_carry_form_and_gate(tmp_live_dir: Path):
    _write_events(tmp_live_dir, [_close(i, 1.0 if i % 2 else -1.0)
                                 for i in range(8)])
    cards = {p["id"]: p for p in players.list_players(live_dir=tmp_live_dir)}
    assert cards["isagi"]["form"] is not None
    assert set(cards["isagi"]["form"].split("-")) <= {"W", "L"}
    # Sae rides the shipped manifest -> benched on the index card too.
    assert cards["sae"]["gate"] == "benched"
    assert cards["kunigami"]["gate"] == "retired"


def test_f021_accessors_are_read_only(tmp_live_dir: Path, tmp_path: Path):
    _write_events(tmp_live_dir, [_close(i, 1.0) for i in range(6)])
    manifest = _manifest(tmp_path)

    def _snap(root: Path) -> dict[str, int]:
        return {str(p): p.stat().st_size
                for p in root.rglob("*") if p.is_file()}

    before = {**_snap(tmp_live_dir), **_snap(tmp_path)}
    players.form_guide("isagi", live_dir=tmp_live_dir)
    players.gate_status("sae", manifest_path=manifest)
    players.recent_decisions("isagi", live_dir=tmp_live_dir)
    assert {**_snap(tmp_live_dir), **_snap(tmp_path)} == before
