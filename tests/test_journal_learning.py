"""Tests for the enriched learning fields: attribution, counterfactual,
conviction calibration, anticipated-vs-reactive scorecard, and declined setups."""
from datetime import datetime, timezone

from agent.journal.live_journal import (
    LiveJournal,
    calibration_report,
    classify_outcome,
    conviction_band,
    counterfactual,
    scorecard,
)

T = datetime(2024, 4, 1, 10, 0, tzinfo=timezone.utc)


def _journal(tmp_path, scope="live"):
    return LiveJournal(
        root=tmp_path / scope, archive_root=tmp_path / "archive", scope=scope,
    )


# ── Attribution ────────────────────────────────────────────────────────────
def test_classify_outcome_four_categories():
    assert classify_outcome(0.80, 1.5) == "good_setup_won"
    assert classify_outcome(0.55, 1.5) == "marginal_win"
    assert classify_outcome(0.80, -1.0) == "good_setup_failed"
    assert classify_outcome(0.55, -1.0) == "bad_setup"


def test_classify_outcome_handles_missing_conviction():
    # Unknown conviction -> treated as not-high -> marginal/bad.
    assert classify_outcome(None, 1.0) == "marginal_win"
    assert classify_outcome(None, -1.0) == "bad_setup"


def test_conviction_band_thresholds():
    assert conviction_band(0.30) == "low"
    assert conviction_band(0.60) == "med"
    assert conviction_band(0.75) == "high"
    # None defaults to 0.5, which is below BAND_LOW (0.55) -> "low".
    assert conviction_band(None) == "low"
    assert conviction_band(0.5) == "low"


# ── Counterfactual ──────────────────────────────────────────────────────────
def test_counterfactual_loss_with_big_mfe_flags_tp():
    cf = counterfactual(r_multiple=-1.0, mae_pips=20.0, mfe_pips=28.0,
                        stop_pips=20.0, exit_reason="sl")
    assert cf["alt_tp_would_have_helped"] is True
    assert cf["mfe_r"] == 1.4
    assert "TP too far" in cf["note"] or "exit too late" in cf["note"]


def test_counterfactual_loss_never_worked():
    cf = counterfactual(r_multiple=-1.0, mae_pips=20.0, mfe_pips=2.0,
                        stop_pips=20.0, exit_reason="sl")
    assert cf["alt_tp_would_have_helped"] is False
    assert "never worked" in cf["note"]


def test_counterfactual_winner_with_deep_mae_flags_stop():
    cf = counterfactual(r_multiple=2.0, mae_pips=18.0, mfe_pips=40.0,
                        stop_pips=20.0, exit_reason="tp")
    assert cf["alt_stop_would_have_helped"] is True
    assert cf["mae_r"] == 0.9
    assert "entry early" in cf["note"]


def test_counterfactual_winner_gave_back():
    cf = counterfactual(r_multiple=1.0, mae_pips=4.0, mfe_pips=60.0,
                        stop_pips=20.0, exit_reason="manual")
    assert cf["gave_back_r"] == 2.0
    assert "gave back" in cf["note"]


# ── Calibration ─────────────────────────────────────────────────────────────
def test_calibration_flags_miscalibration():
    # High-conviction trades LOSE, low-conviction trades WIN -> miscalibrated.
    records = (
        [{"conviction": 0.80, "r_multiple": -1.0} for _ in range(4)]
        + [{"conviction": 0.40, "r_multiple": 2.0} for _ in range(4)]
    )
    rep = calibration_report(records)
    assert rep["miscalibrated"] is True
    high = next(b for b in rep["buckets"] if b["band"] == "high")
    low = next(b for b in rep["buckets"] if b["band"] == "low")
    assert high["expectancy_r"] < low["expectancy_r"]


def test_calibration_ok_when_high_outperforms():
    records = (
        [{"conviction": 0.80, "r_multiple": 2.0} for _ in range(4)]
        + [{"conviction": 0.40, "r_multiple": -1.0} for _ in range(4)]
    )
    rep = calibration_report(records)
    assert rep["miscalibrated"] is False


def test_calibration_insufficient_samples():
    rep = calibration_report([{"conviction": 0.8, "r_multiple": 1.0}])
    assert rep["miscalibrated"] is False
    assert "insufficient" in rep["message"]


# ── Scorecard ───────────────────────────────────────────────────────────────
def test_scorecard_marked_acted_declined():
    trades = [
        {"source": "reaction", "r_multiple": 2.0},
        {"source": "reaction", "r_multiple": -1.0},
        {"source": "anticipation", "r_multiple": 1.0},
    ]
    declines = [
        {"source": "reaction", "would_have_won": True},
        {"source": "reaction", "would_have_won": False},
    ]
    card = scorecard(trades, declines)
    assert card["reaction"]["acted"] == 2
    assert card["reaction"]["declined"] == 2
    assert card["reaction"]["marked"] == 4
    assert card["reaction"]["declined_would_have_won"] == 1
    assert card["anticipation"]["acted"] == 1
    assert card["best_perspective"] in ("reaction", "anticipation")


def test_scorecard_best_perspective_none_when_no_trades():
    card = scorecard([], [{"source": "reaction", "would_have_won": True}])
    assert card["best_perspective"] == "none"


# ── End-to-end journal behaviour ────────────────────────────────────────────
def test_exit_writes_attribution_and_counterfactual(tmp_path):
    j = _journal(tmp_path)
    j.start_day("2024-04-01")
    j.log_trade_entry(
        ticket=7, time=T, symbol="EURUSD", direction="short", source="reaction",
        strategy="Reaction", signature="Reaction|short|asia|htfNA|reaction",
        entry=1.1000, stop=1.1020, take_profit=1.0960, lot=0.02, conviction=0.80,
    )
    rec = j.log_trade_exit(
        ticket=7, time=T, exit_price=1.1020, exit_reason="sl", pnl=-4.0,
        pnl_pips=-20.0, r_multiple=-1.0, mae_pips=20.0, mfe_pips=28.0,
    )
    assert rec["attribution"] == "good_setup_failed"
    assert rec["alt_tp_would_have_helped"] is True
    assert rec["conviction"] == 0.80  # pulled from stored entry context
    md = (tmp_path / "live" / "2024-04-01.md").read_text()
    assert "Attribution:" in md and "good_setup_failed" in md
    assert "Counterfactual:" in md


def test_declined_logged_to_md_and_jsonl(tmp_path):
    j = _journal(tmp_path)
    j.start_day("2024-04-01")
    j.log_declined(
        "2024-04-01", signature="Reaction|long|london|htfNA|reaction",
        reason="conviction 0.50 < 0.54", source="reaction", conviction=0.50,
        direction="long", would_have_won=True,
        would_have_note="win next 24b (+2.0R/-0.1R)",
    )
    md = (tmp_path / "live" / "2024-04-01.md").read_text()
    assert "declined" in md and "would-have" in md
    jsonl = (tmp_path / "live" / "2024-04-01.jsonl").read_text()
    assert '"event": "declined"' in jsonl
    assert '"would_have_won": true' in jsonl


def test_decline_detail_lines_are_capped(tmp_path):
    j = LiveJournal(root=tmp_path / "live", archive_root=tmp_path / "arch",
                    scope="live", max_decline_detail_per_day=2)
    j.start_day("2024-04-01")
    for k in range(5):
        j.log_declined("2024-04-01", signature=f"sig{k}", reason="low conv",
                       source="reaction", conviction=0.4)
    md = (tmp_path / "live" / "2024-04-01.md").read_text()
    # Only 2 detail lines, but all 5 captured in jsonl + accumulator.
    assert md.count("`declined`") == 2
    jsonl = (tmp_path / "live" / "2024-04-01.jsonl").read_text().splitlines()
    assert sum(1 for line in jsonl if '"event": "declined"' in line) == 5


def test_daily_rollup_writes_calibration_and_scorecard(tmp_path):
    j = _journal(tmp_path)
    day = "2024-04-01"
    j.start_day(day)
    # Two reaction trades (one win, one loss) + a declined that would have won.
    for tk, conv, exitp, pnl, r in [
        (1, 0.80, 1.0960, 4.0, 2.0), (2, 0.80, 1.1020, -4.0, -1.0),
    ]:
        j.log_trade_entry(
            ticket=tk, time=T, symbol="EURUSD", direction="short",
            source="reaction", strategy="Reaction", signature="s", entry=1.1000,
            stop=1.1020, take_profit=1.0960, lot=0.02, conviction=conv,
        )
        j.log_trade_exit(
            ticket=tk, time=T, exit_price=exitp, exit_reason="tp" if pnl > 0 else "sl",
            pnl=pnl, pnl_pips=r * 20, r_multiple=r, mae_pips=5.0, mfe_pips=40.0,
        )
    j.log_declined(day, signature="s2", reason="below threshold", source="reaction",
                   conviction=0.5, would_have_won=True)

    rollup = j.log_daily_rollup(day)
    assert rollup["trades"] == 2
    assert rollup["declined"] == 1
    assert rollup["declined_would_have_won"] == 1
    assert "calibration_today" in rollup and "scorecard" in rollup
    md = (tmp_path / "live" / "2024-04-01.md").read_text()
    assert "Daily Roll-up" in md
    assert "Conviction calibration" in md
    assert "scorecard" in md.lower()

    # Idempotent: a second call writes nothing new.
    assert j.log_daily_rollup(day) == {}
