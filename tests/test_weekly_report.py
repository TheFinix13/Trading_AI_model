"""Tests for ``scripts/weekly_report.py`` — the one-command weekly bundle.

Small synthetic log/vault fixtures cover the contract the reviewer relies
on: multi-symbol aggregation into one REPORT.md + zip, external-equity-move
flagging on the merged account timeline, downtime-window extraction,
rejection-reason breakdown, vault evidence filtering by window, and
graceful degradation when days / symbols / vault dirs are missing.
"""
from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts import weekly_report as wr  # noqa: E402
from scripts.compile_review_bundle import DowntimeWindow  # noqa: E402

DAY = "2026-07-06"
DAY2 = "2026-07-07"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------
EURUSD_LOG = f"""\
{DAY} 08:00:01 INFO     agent.live.signal_loop: Signal loop starting (v2 scaffold)
{DAY} 09:00:00 INFO     agent.live.signal_loop: heartbeat: balance=$1000.00 equity=$1000.00 open_positions=0 | next H4 close ~12:00 UTC
{DAY} 09:00:18 INFO     agent.live.signal_loop: H4 close 08:00 UTC: evaluated, no setup (alphas checked: zone_h4_all)
{DAY} 12:00:00 INFO     agent.live.signal_loop: [SIGNAL] EURUSDm H4 zone_h4_all LONG entry=1.15151 soft_sl=1.14661 tp=1.15432 conviction=0.65
{DAY} 12:00:00 INFO     agent.live.signal_loop: [TRADE OPENED] EURUSDm H4 zone_h4_all LONG ticket=111 entry=1.15151 lots=0.07 soft_sl=1.14661 (49p) catastrophe_sl=1.14400 (75p) tp_mech=1.15432 (1.5R, +28p) risk=1.00%
{DAY} 13:00:02 INFO     agent.live.signal_loop: [NEAR MISS] EURUSDm H4 zone_h4_all reason=risk_manager — skip_max_positions: open=1
{DAY} 13:30:00 INFO     agent.live.signal_loop: [NEAR MISS] EURUSDm H4 zone_h4_all reason=htf_gate — htf_bias up vs zone supply
{DAY} 14:00:00 INFO     agent.live.monitor: [TP HIT] EURUSDm ticket=111 zone_h4_all LONG exit=1.15432 pnl=+28.10 (+28p, +1.50R) cause=tp
{DAY} 15:00:00 INFO     agent.live.signal_loop: heartbeat: balance=$978.10 equity=$978.10 open_positions=0 | next H4 close ~16:00 UTC
"""

# GBPUSD: an unexplained balance drop between flat heartbeats (manual/external
# trade) and a kill-switch halt with a recorded reason, later resumed.
GBPUSD_LOG = f"""\
{DAY} 08:00:01 INFO     agent.live.signal_loop: Signal loop starting (v2 scaffold)
{DAY} 10:00:00 INFO     agent.live.signal_loop: heartbeat: balance=$1000.00 equity=$1000.00 open_positions=0 | next H4 close ~12:00 UTC
{DAY} 12:00:00 INFO     agent.live.signal_loop: heartbeat: balance=$950.00 equity=$950.00 open_positions=0 | next H4 close ~16:00 UTC
{DAY} 12:30:00 ERROR    agent.live.broker: [ORDER REJECTED] GBPUSDm H4 zone_h4_all — retcode=10027 AutoTrading disabled by client
{DAY} 12:30:00 ERROR    agent.live.broker: Order rejected: retcode=10027 comment='AutoTrading disabled by client'
{DAY} 16:00:00 WARNING  agent.live.signal_loop: EMERGENCY CLOSE ALL: Daily DD limit reached: 5.00% >= 3.00%
{DAY} 16:00:05 INFO     agent.live.signal_loop: Kill switch active — skipping iteration
{DAY} 20:00:00 INFO     agent.live.signal_loop: Kill switch active — skipping iteration
{DAY2} 08:00:00 INFO     agent.live.signal_loop: Signal loop starting (v2 scaffold)
{DAY2} 09:00:00 INFO     agent.live.signal_loop: heartbeat: balance=$978.10 equity=$978.10 open_positions=0 | next H4 close ~12:00 UTC
"""

NEAR_MISS_RECORDS = [
    {
        "ts": f"{DAY}T13:30:00+00:00", "tf": "H4", "reason": "htf_gate",
        "direction": "short", "entry": 1.15100, "stop": 1.15500,
        "take_profit": 1.14300, "conviction": 0.65,
        "zone": {"direction": "supply", "top": 1.1550, "bottom": 1.1510,
                 "created_at": f"{DAY}T01:30:00+00:00", "impulse_pips": 42.0},
        "symbol": "EURUSDm",
    },
    {   # outside the window — must be filtered out of the bundle
        "ts": "2026-06-01T13:30:00+00:00", "tf": "H4", "reason": "htf_gate",
        "direction": "long", "entry": 1.10, "stop": 1.09,
        "take_profit": 1.12, "symbol": "EURUSDm",
    },
]


def _write_root(tmp_path: Path, *, gbp_kill_txt: bool = True) -> Path:
    root = tmp_path / "TradingAgentLogs"

    eur = root / "EURUSDm"
    eur.mkdir(parents=True)
    (eur / f"EURUSDm_{DAY}.log").write_text(EURUSD_LOG, encoding="utf-8")
    (eur / "state.json").write_text(json.dumps({
        "saved_at": f"{DAY2}T00:00:00+00:00",
        "risk_manager": {"day": DAY, "day_pnl": 28.10, "halted_today": False},
        "post_loss_guard": {"consecutive_losses": 0, "session_halted": False,
                            "size_multiplier": 1.0},
    }), encoding="utf-8")
    nm_dir = eur / "near_misses"
    nm_dir.mkdir()
    (nm_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in NEAR_MISS_RECORDS) + "\n",
        encoding="utf-8")
    (nm_dir / f"{DAY}_1330_htf_gate.png").write_bytes(b"\x89PNG fake")
    (nm_dir / "2026-06-01_1330_htf_gate.png").write_bytes(b"\x89PNG old")

    gbp = root / "GBPUSDm"
    gbp.mkdir(parents=True)
    (gbp / f"GBPUSDm_{DAY}.log").write_text(GBPUSD_LOG, encoding="utf-8")
    if gbp_kill_txt:
        (gbp / "kill.txt").write_text(
            "Auto-kill: daily drawdown limit", encoding="utf-8")
    # No vault subdirs for GBPUSD on purpose (graceful-missing coverage).
    return root


def _weeks(root: Path, symbols=("EURUSD", "GBPUSD", "USDCAD")):
    days = wr._resolve_days(datetime.fromisoformat(DAY2).date(), 2)
    return {s: wr.parse_symbol_week(s, root, days) for s in symbols}, days


# ---------------------------------------------------------------------------
# Parsing / aggregation
# ---------------------------------------------------------------------------
def test_trade_table_joins_open_and_close(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    weeks, _ = _weeks(root)
    trades = weeks["EURUSD"].trades
    assert set(trades) == {"111"}
    t = trades["111"]
    assert t.direction == "LONG"
    assert t.lots == pytest.approx(0.07)
    assert t.entry == pytest.approx(1.15151)
    assert t.exit == pytest.approx(1.15432)
    assert t.risk_pct == pytest.approx(1.00)
    assert t.pnl == pytest.approx(28.10)
    assert t.r == pytest.approx(1.50)
    assert t.exit_tag == "TP HIT"
    assert t.cause == "tp"
    assert t.opened_ts is not None and t.closed_ts is not None


def test_rejection_breakdown_splits_max_positions(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    weeks, _ = _weeks(root)
    breakdown = weeks["EURUSD"].rejection_breakdown
    # risk_manager near-miss whose detail says skip_max_positions is
    # re-bucketed as max_positions.
    assert breakdown["max_positions"] == 1
    assert breakdown["htf_gate"] == 1
    assert "risk_manager" not in breakdown
    assert weeks["GBPUSD"].rejection_breakdown["broker_reject_line"] == 1


def test_vault_near_misses_filtered_by_window(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    weeks, _ = _weeks(root)
    recs = weeks["EURUSD"].vault_near_misses
    assert len(recs) == 1          # the 2026-06-01 record is out of window
    assert recs[0]["reason"] == "htf_gate"


# ---------------------------------------------------------------------------
# Downtime windows
# ---------------------------------------------------------------------------
def test_downtime_window_extracted_with_reason(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    weeks, _ = _weeks(root)
    ev = weeks["GBPUSD"].events
    assert ev is not None
    assert len(ev.downtime) == 1
    w = ev.downtime[0]
    assert w.start == datetime(2026, 7, 6, 16, 0, 5, tzinfo=timezone.utc)
    assert w.end == datetime(2026, 7, 6, 20, 0, 0, tzinfo=timezone.utc)
    assert "Daily DD limit" in w.reason
    assert weeks["GBPUSD"].kill_txt == "Auto-kill: daily drawdown limit"


# ---------------------------------------------------------------------------
# Cross-symbol account view
# ---------------------------------------------------------------------------
def test_external_equity_move_flagged(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    weeks, _ = _weeks(root)
    view = wr.build_account_view(weeks)

    # The GBPUSD 10:00 -> 12:00 drop of -50 has no agent close inside the
    # gap and every known symbol was flat: external move.
    assert len(view.external_moves) == 1
    mv = view.external_moves[0]
    assert mv["delta"] == pytest.approx(-50.0)
    assert mv["agent_explained"] == pytest.approx(0.0)
    assert mv["residual"] == pytest.approx(-50.0)
    assert mv["all_agent_flat"] is True

    # The 12:00 -> 15:00 +28.10 change IS explained by the EURUSD TP at
    # 14:00, so it must NOT be flagged.
    assert view.agent_pnl == pytest.approx(28.10)
    assert view.account_delta == pytest.approx(-21.90)         # 978.10 - 1000


def test_agent_vs_external_pnl_split(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    weeks, _ = _weeks(root)
    view = wr.build_account_view(weeks)
    # First balance 1000 (EURUSD 09:00), last 978.10 (GBPUSD day 2 09:00):
    # account delta -21.90 = agent +28.10 (TP) + external -50 (manual drop).
    assert view.account_delta == pytest.approx(-21.90)
    assert view.external_pnl == pytest.approx(-50.0)


def test_kill_cascade_detection() -> None:
    t0 = datetime(2026, 7, 6, 16, 0, tzinfo=timezone.utc)
    wk_a = wr.SymbolWeek(symbol="EURUSD")
    wk_a.events = wr.SymbolEvents()
    wk_a.events.downtime.append(
        DowntimeWindow(start=t0, end=t0.replace(hour=20), reason="x"))
    wk_b = wr.SymbolWeek(symbol="GBPUSD")
    wk_b.events = wr.SymbolEvents()
    wk_b.events.downtime.append(
        DowntimeWindow(start=t0.replace(minute=10), end=t0.replace(hour=21),
                       reason="y"))
    cascades = wr._kill_cascades({"EURUSD": wk_a, "GBPUSD": wk_b})
    assert len(cascades) == 1
    assert {s for s, _ in cascades[0]} == {"EURUSD", "GBPUSD"}


# ---------------------------------------------------------------------------
# Report + checklist
# ---------------------------------------------------------------------------
def test_report_contains_all_sections_and_missing_notes(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    weeks, days = _weeks(root)
    view = wr.build_account_view(weeks)
    report = wr.render_report(weeks, view, days, root)

    assert "## Executive summary" in report
    assert "## EURUSD" in report
    assert "## GBPUSD" in report
    assert "## USDCAD" in report
    assert "## Cross-symbol account view" in report
    assert "## Parameter snapshot" in report
    assert "## Review checklist" in report
    # USDCAD has no logs at all: graceful MISSING, not a crash.
    assert "MISSING: no daily log files found" in report
    # Trade row rendered with exit tag.
    assert "TP HIT" in report
    assert "external/manual equity move" in report.lower() \
        or "external / manual equity moves" in report.lower()


def test_checklist_flags(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    weeks, _ = _weeks(root)
    view = wr.build_account_view(weeks)
    flags = wr.build_checklist(weeks, view)
    text = "\n".join(flags)
    assert "[USDCAD] NO LOG FILES" in text
    assert "kill.txt PRESENT" in text
    assert "external/manual equity move" in text
    assert "AutoTrading disabled" in text
    # GBPUSD is missing DAY2's log? No — it has day2 lines in the same file?
    # The fixture writes one file per day per symbol; GBPUSD only has DAY's
    # file, so DAY2 must be reported missing.
    assert f"[GBPUSD] missing daily log(s): {DAY2}" in text


# ---------------------------------------------------------------------------
# End-to-end CLI + bundle contents
# ---------------------------------------------------------------------------
def test_main_writes_zip_with_expected_members(tmp_path: Path,
                                               capsys: pytest.CaptureFixture) -> None:
    root = _write_root(tmp_path)
    rc = wr.main([
        "--log-root", str(root),
        "--start", DAY, "--end", DAY2,
        "--symbols", "EURUSD,GBPUSD,USDCAD",
    ])
    assert rc == 0
    zip_path = root / "reviews" / f"weekly_report_{DAY}_to_{DAY2}.zip"
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "REPORT.md" in names
        assert f"EURUSD/logs/EURUSDm_{DAY}.log" in names
        assert f"GBPUSD/logs/GBPUSDm_{DAY}.log" in names
        assert "EURUSD/state.json" in names
        assert "GBPUSD/kill.txt" in names
        # In-window PNG bundled, out-of-window PNG excluded.
        assert f"EURUSD/near_misses/{DAY}_1330_htf_gate.png" in names
        assert "EURUSD/near_misses/2026-06-01_1330_htf_gate.png" not in names
        # Filtered events.jsonl only carries the in-window record.
        nm_body = zf.read("EURUSD/near_misses/events.jsonl").decode("utf-8")
        recs = [json.loads(l) for l in nm_body.splitlines() if l.strip()]
        assert len(recs) == 1
        assert recs[0]["ts"].startswith(DAY)
        report = zf.read("REPORT.md").decode("utf-8")
        assert "Weekly trading agent report" in report

    out = capsys.readouterr().out
    assert "Bundle written to:" in out
    assert out.isascii()  # cp1252-safe console output


def test_main_days_window_and_symbol_discovery(tmp_path: Path,
                                               capsys: pytest.CaptureFixture) -> None:
    root = _write_root(tmp_path)
    rc = wr.main(["--log-root", str(root), "--days", "2", "--end", DAY2])
    assert rc == 0
    out = capsys.readouterr().out
    # Symbols auto-discovered from the broker-suffixed folders.
    assert "EURUSD" in out and "GBPUSD" in out
    assert (root / "reviews" / f"weekly_report_{DAY}_to_{DAY2}.zip").exists()


def test_main_survives_empty_root(tmp_path: Path,
                                  capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    rc = wr.main(["--log-root", str(root), "--days", "7", "--end", DAY2])
    assert rc == 0
    zips = list((root / "reviews").glob("weekly_report_*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        report = zf.read("REPORT.md").decode("utf-8")
    assert "MISSING" in report


def test_discover_symbols_strips_broker_suffix(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    assert wr.discover_symbols(root) == ["EURUSD", "GBPUSD"]
    # Empty root falls back to the deployed default trio.
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert wr.discover_symbols(empty) == list(wr.DEFAULT_SYMBOLS)
