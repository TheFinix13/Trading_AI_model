"""Neo Egoist League table (scripts/league_table.py) — pinned scoring.

Pins the D145 v1 rules: 10 HP per R, −3 per overtime trade, the
zero-conversion drain for silent proposers (the Reo rule), advisor
exemption, and the RELEGATION REVIEW flag at HP ≤ 0. The script is
observe-only: score_tape is a pure read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import league_table as lt  # noqa: E402


def _trade(aid: str, r: float, bars: int = 5, pips: float = 10.0) -> dict:
    return {"agent_id": aid, "r_multiple": r, "bars_held": bars,
            "pnl_pips": pips, "symbol": "EURUSD"}


def _tick(evaluated: list[str]) -> dict:
    return {"type": "tick_summary", "players_evaluated": evaluated}


def _write(live_dir: Path, trades: list[dict], ticks: list[dict]) -> None:
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "trades.jsonl").write_text(
        "\n".join(json.dumps(t) for t in trades) + ("\n" if trades else ""))
    (live_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(t) for t in ticks) + ("\n" if ticks else ""))


def _row(result: dict, aid: str) -> dict:
    return next(r for r in result["table"] if r["agent_id"] == aid)


def test_hp_is_ten_per_r(tmp_path):
    _write(tmp_path, [_trade("itoshi_rin", 2.5), _trade("itoshi_rin", -1.0)],
           [_tick(["itoshi_rin"])])
    row = _row(lt.score_tape(tmp_path), "itoshi_rin")
    assert row["hp"] == 100.0 + 10 * (2.5 - 1.0)
    assert row["trades"] == 2 and row["wins"] == 1
    assert not row["relegation_review"]


def test_overtime_trade_costs_extra(tmp_path):
    _write(tmp_path, [_trade("barou_shoei", 1.0, bars=31)], [])
    row = _row(lt.score_tape(tmp_path), "barou_shoei")
    assert row["overtime_trades"] == 1
    assert row["hp"] == 100.0 + 10.0 - 3.0


def test_zero_conversion_drain_and_cap(tmp_path):
    # A silent PROPOSER on 10_000 bars: drain hits the 25 cap.
    _write(tmp_path, [], [_tick(["isagi_yoichi"])] * 10_000)
    row = _row(lt.score_tape(tmp_path), "isagi_yoichi")
    assert row["zero_conversion_drain"] == 25.0
    assert row["hp"] == 75.0


def test_advisors_exempt_from_drain(tmp_path):
    # Karasu (advisor) and Reo (design-time non-scorer, I029) are
    # exempt: their job is not to shoot.
    _write(tmp_path, [], [_tick(["karasu_tabito", "reo_mikage"])] * 10_000)
    for aid in ("karasu_tabito", "reo_mikage"):
        row = _row(lt.score_tape(tmp_path), aid)
        assert row["zero_conversion_drain"] == 0.0
        assert row["hp"] == 100.0


def test_relegation_review_flag_at_zero_hp(tmp_path):
    _write(tmp_path, [_trade("chigiri_hyoma", -1.0)] * 10, [])
    row = _row(lt.score_tape(tmp_path), "chigiri_hyoma")
    assert row["hp"] == 0.0
    assert row["relegation_review"] is True


def test_score_tape_is_pure_read(tmp_path):
    _write(tmp_path, [_trade("itoshi_rin", 1.0)], [_tick(["itoshi_rin"])])
    before = sorted(p.name for p in tmp_path.rglob("*"))
    lt.score_tape(tmp_path)
    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_table_sorted_by_hp_and_renders(tmp_path):
    _write(tmp_path,
           [_trade("itoshi_rin", 2.0), _trade("chigiri_hyoma", -2.0)], [])
    result = lt.score_tape(tmp_path)
    assert [r["agent_id"] for r in result["table"]] == [
        "itoshi_rin", "chigiri_hyoma"]
    out = lt.render(result)
    assert "NEO EGOIST LEAGUE" in out and "itoshi_rin" in out
