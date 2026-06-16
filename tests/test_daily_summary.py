"""Tests for ``scripts/daily_summary.py``.

The script is a passive reporter — its only job is to parse the structured
``[TAG]`` lines emitted by ``agent/live/trade_events.py`` (plus heartbeats and
``H4 close`` evaluations) and aggregate counts / pnl / R buckets without
mis-attributing anything. These tests pin the regex contract against real
fixtures so a future tweak to a log line shape can't silently break the report.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import daily_summary as ds  # noqa: E402


# ---------------------------------------------------------------------------
# Realistic log fixture mirroring lines shipped by trade_events.py
# ---------------------------------------------------------------------------
SAMPLE_LOG = """\
2026-06-16 04:12:21 INFO     agent.live.monitor: [POSITION ADOPTED] USDCADm ticket=2842973741 SHORT 0.03 lots entry=1.39715 broker_sl=1.40292 (58p) tp=1.39382 (33p) soft_sl=1.39946 (23p, inferred) profit=-5.66 (opened before this process started)
2026-06-16 04:12:21 INFO     agent.live.monitor: [LADDER] USDCADm ticket=2842973741 status=unknown (adopted)
2026-06-16 04:12:21 INFO     agent.live.monitor: [SOFT SL ARMED] USDCADm ticket=2842973741 soft_sl=1.39946 source=inferred
2026-06-16 04:12:21 WARNING  agent.live.monitor: [ADOPTED — SOFT SL ALREADY BREACHED] USDCADm ticket=2842973741 price=1.39979 past inferred soft_sl=1.39946 — will close on next monitor tick
2026-06-16 04:12:27 INFO     agent.live.monitor: [SOFT SL] USDCADm ticket=2842973741 zone_h4_all SHORT exit=1.39979 pnl=-26.10 (-26p, -1.13R) cause=soft_sl_inferred_overshoot
2026-06-16 09:00:18 INFO     agent.live.signal_loop: H4 close 08:00 UTC: evaluated, no setup (alphas checked: zone_h4_all)
2026-06-16 09:02:18 INFO     agent.live.signal_loop: heartbeat: balance=$1005.78 equity=$1004.66 open_positions=0 | next H4 close ~12:00 UTC
2026-06-16 13:00:02 INFO     agent.live.signal_loop: [NEAR MISS] USDCADm H4 zone_h4_all reason=risk_manager — skip_max_positions: open=1
2026-06-16 17:00:03 INFO     agent.live.signal_loop: [NEAR MISS] USDCADm H4 zone_h4_all reason=htf_gate — htf_bias up vs zone supply
2026-06-16 12:00:00 INFO     agent.live.signal_loop: [SIGNAL] EURUSDm H4 zone_h4_all LONG entry=1.15151 soft_sl=1.14661 tp=1.15432 conviction=0.65
2026-06-16 12:00:00 INFO     agent.live.signal_loop: [TRADE OPENED] EURUSDm H4 zone_h4_all LONG ticket=19664710 entry=1.15151 lots=0.07 soft_sl=1.14661 (49p) catastrophe_sl=1.14400 (75p) tp_mech=1.15432 (1.5R, +28p) risk=1.00%
2026-06-16 12:00:01 INFO     agent.live.signal_loop: [LADDER] EURUSDm ticket=19664710 n=3 swing=1.15700(55p,1.1R) zone_edge=1.15780(63p,1.3R) trendline=1.15850(70p,1.4R)
2026-06-16 13:32:51 INFO     agent.live.monitor: [BREAKEVEN] EURUSDm ticket=19664710 sl 1.14661 -> 1.15151 (at 1.0R)
2026-06-16 13:45:00 INFO     agent.live.monitor: [TP HIT] EURUSDm ticket=19664710 zone_h4_all LONG exit=1.15432 pnl=+28.10 (+28p, +1.50R) cause=tp
2026-06-16 01:00:10 ERROR    agent.live.broker: [ORDER REJECTED] GBPUSDm H4 zone_h4_all — retcode=10027 AutoTrading disabled by client
"""


@pytest.fixture()
def parsed(tmp_path: Path) -> ds.SymbolStats:
    log = tmp_path / "USDCAD_2026-06-16.log"
    log.write_text(SAMPLE_LOG, encoding="utf-8")
    stats = ds.SymbolStats(symbol="USDCAD")
    ds.parse_log_file(log, stats)
    return stats


def test_trade_events_counted(parsed: ds.SymbolStats) -> None:
    assert parsed.trades_opened == 1
    assert parsed.signals == 1
    assert parsed.order_rejected == 1
    assert parsed.breakeven_moves == 1


def test_close_lines_aggregate_pnl_and_r(parsed: ds.SymbolStats) -> None:
    assert parsed.closed_total == 2  # SOFT SL overshoot + TP HIT
    assert parsed.closed_wins == 1
    assert parsed.closed_pnl_usd == pytest.approx(28.10 - 26.10, abs=1e-6)
    assert parsed.closed_pnl_pips == pytest.approx(28 - 26)
    assert parsed.expectancy_r == pytest.approx((1.50 + -1.13) / 2, abs=1e-6)
    assert parsed.trades_closed_by_cause["tp"] == 1
    assert parsed.trades_closed_by_cause["soft_sl_inferred_overshoot"] == 1


def test_near_misses_bucketed(parsed: ds.SymbolStats) -> None:
    assert parsed.near_miss_total == 2
    assert parsed.near_misses_by_reason["risk_manager"] == 1
    assert parsed.near_misses_by_reason["htf_gate"] == 1


def test_adopted_and_armed_and_breached(parsed: ds.SymbolStats) -> None:
    assert len(parsed.adopted) == 1
    assert parsed.adopted[0]["ticket"] == "2842973741"
    assert len(parsed.soft_armed) == 1
    assert parsed.soft_armed[0]["source"] == "inferred"
    assert len(parsed.breached) == 1


def test_ladder_lines_classified(parsed: ds.SymbolStats) -> None:
    # One real ladder (EURUSD) and one "status=unknown (adopted)" (USDCAD).
    assert parsed.ladders_emitted == 1
    assert parsed.ladder_unknown == 1


def test_heartbeat_and_no_setup_counts(parsed: ds.SymbolStats) -> None:
    assert parsed.h4_no_setup == 1
    assert parsed.last_heartbeat is not None
    assert parsed.last_heartbeat["balance"] == pytest.approx(1005.78)
    assert parsed.last_heartbeat["open_positions"] == 0


# ---------------------------------------------------------------------------
# Cumulative ladder + vault aggregates
# ---------------------------------------------------------------------------
def test_ladder_reach_rates(tmp_path: Path) -> None:
    """`ladder_reach` must compute per-source rung counts and reach % the same
    way the human report does, and only look at ``phase=close`` records."""
    sym_dir = tmp_path / "EURUSDm"
    (sym_dir / "ladders").mkdir(parents=True)
    events = [
        {"phase": "entry", "rungs": [{"source": "swing", "price": 1.16,
                                      "r_multiple": 2.0}]},
        {"phase": "close", "rungs": [
            {"source": "swing", "price": 1.16, "r_multiple": 2.0,
             "reached": True},
            {"source": "zone_edge", "price": 1.17, "r_multiple": 3.0,
             "reached": False},
        ]},
        {"phase": "close", "rungs": [
            {"source": "swing", "price": 1.165, "r_multiple": 2.5,
             "reached": True},
            {"source": "swing", "price": 1.18, "r_multiple": 4.0,
             "reached": False},
        ]},
    ]
    path = sym_dir / "ladders" / "events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n",
                    encoding="utf-8")

    by_source, n_closed, n_with_reach = ds.ladder_reach(sym_dir)
    assert n_closed == 2
    assert n_with_reach == 2  # each close had at least one reached rung
    assert by_source["swing"]["n"] == 3
    assert by_source["swing"]["reached"] == 2
    assert by_source["zone_edge"]["n"] == 1
    assert by_source["zone_edge"]["reached"] == 0


def test_vault_counts(tmp_path: Path) -> None:
    sym_dir = tmp_path / "EURUSDm"
    (sym_dir / "losses").mkdir(parents=True)
    (sym_dir / "near_misses").mkdir(parents=True)
    (sym_dir / "losses" / "events.jsonl").write_text(
        json.dumps({"pnl": -10}) + "\n", encoding="utf-8")
    nm_events = [
        {"reason": "htf_gate", "resolved": True, "outcome": "win"},
        {"reason": "htf_gate", "resolved": True, "outcome": "loss"},
        {"reason": "risk_manager", "resolved": False, "outcome": "open"},
    ]
    (sym_dir / "near_misses" / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in nm_events) + "\n",
        encoding="utf-8")

    vc = ds.vault_counts(sym_dir)
    assert vc["losses"] == 1
    assert vc["near_misses"] == 3
    assert vc["near_miss_resolved"] == 2
    assert vc["near_miss_resolved_wins"] == 1
    assert vc["near_miss_by_reason"] == {"htf_gate": 2, "risk_manager": 1}


# ---------------------------------------------------------------------------
# End-to-end CLI smoke
# ---------------------------------------------------------------------------
def test_log_path_discovers_broker_suffixed_file(tmp_path: Path) -> None:
    """The runner writes ``USDCADm/USDCADm_*.log`` even when the user types
    ``--symbol USDCAD``. ``_log_path`` must find both layouts."""
    (tmp_path / "USDCADm").mkdir()
    target = tmp_path / "USDCADm" / "USDCADm_2026-06-16.log"
    target.write_text(SAMPLE_LOG, encoding="utf-8")
    found = ds._log_path(tmp_path, "USDCAD", date(2026, 6, 16))
    assert found == target


def test_main_runs_and_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    sym_dir = tmp_path / "EURUSDm"
    (sym_dir / "ladders").mkdir(parents=True)
    log = sym_dir / "EURUSDm_2026-06-16.log"
    log.write_text(SAMPLE_LOG, encoding="utf-8")
    (sym_dir / "state.json").write_text(json.dumps({
        "symbol": "EURUSDm",
        "saved_at": "2026-06-16T00:00:00+00:00",
        "risk_manager": {"day": "2026-06-16", "day_pnl": 28.10,
                         "day_open_balance": 1005.78, "halted_today": False},
        "post_loss_guard": {"day": "2026-06-16", "consecutive_losses": 0,
                            "session_halted": False, "size_multiplier": 1.0},
        "position_monitor": {"entry_ctx": {}, "excursion": {}},
        "signal_loop": {"last_bar_times": {}},
    }), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [
        "daily_summary.py", "--symbol", "EURUSD",
        "--log-dir", str(tmp_path), "--end-date", "2026-06-16",
    ])
    rc = ds.main()
    assert rc == 0
    captured = capsys.readouterr().out
    assert "EURUSD" in captured
    assert "Trades opened        : 1" in captured
    assert "TP HIT" not in captured  # cause is lowercase in the close line
    assert "tp" in captured  # cause=tp is shown in the per-cause list
    assert "day_pnl=$28.10" in captured
