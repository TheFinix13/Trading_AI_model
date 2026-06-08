"""Tests for the fresh, present-time live journal."""
from datetime import datetime, timezone

from agent.journal.live_journal import LiveJournal

T = datetime(2024, 3, 1, 9, 0, tzinfo=timezone.utc)


def _journal(tmp_path, scope="live"):
    return LiveJournal(
        root=tmp_path / "live", archive_root=tmp_path / "archive", scope=scope,
    )


def test_start_day_is_idempotent(tmp_path):
    j = _journal(tmp_path)
    j.start_day("2024-03-01", htf_bias="BULLISH", mode="hybrid")
    j.start_day("2024-03-01", htf_bias="BEARISH")  # second call ignored
    md = (tmp_path / "live" / "2024-03-01.md").read_text()
    assert md.count("# Live Trading Journal") == 1
    assert "BULLISH" in md
    assert "BEARISH" not in md


def test_trade_entry_and_exit_written(tmp_path):
    j = _journal(tmp_path)
    j.start_day("2024-03-01", htf_bias="BULLISH")
    j.log_trade_entry(
        ticket=1, time=T, symbol="EURUSD", direction="long", source="reaction",
        strategy="Reaction", signature="Reaction|long|london|htfNA|reaction",
        entry=1.1000, stop=1.0980, take_profit=1.1040, lot=0.05, conviction=0.72,
        sizing_summary="balance=$100 risk=1%", rationale="BUY reaction",
        features={"atr": 0.002}, reaction_components={"displacement": 0.8},
    )
    j.log_trade_exit(
        ticket=1, time=T, exit_price=1.1040, exit_reason="tp", pnl=20.0,
        pnl_pips=40.0, r_multiple=2.0, mae_pips=4.0, mfe_pips=42.0,
        signature="Reaction|long|london|htfNA|reaction",
    )
    md = (tmp_path / "live" / "2024-03-01.md").read_text()
    assert "Trade #1" in md
    assert "WIN" in md
    assert "Lesson:" in md
    # JSONL sidecar carries the feature snapshot for retraining.
    jsonl = (tmp_path / "live" / "2024-03-01.jsonl").read_text().splitlines()
    events = [line for line in jsonl if line.strip()]
    assert any('"event": "trade_entry"' in e and '"displacement": 0.8' in e for e in events)
    assert any('"event": "trade_exit"' in e for e in events)


def test_loss_reflection_for_premature_entry(tmp_path):
    j = _journal(tmp_path)
    # Loss straight to stop with almost no favourable excursion.
    lesson = j._reflection(pnl=-10.0, r=-1.0, mae=20.0, mfe=1.0, exit_reason="sl")
    assert "premature" in lesson or "momentum" in lesson


def test_loss_reflection_for_gave_back_winner(tmp_path):
    j = _journal(tmp_path)
    lesson = j._reflection(pnl=-10.0, r=-1.0, mae=20.0, mfe=15.0, exit_reason="sl")
    assert "reversed" in lesson or "break-even" in lesson


def test_archive_existing_moves_files(tmp_path):
    j = _journal(tmp_path)
    j.start_day("2024-03-01", htf_bias="BULLISH")
    assert (tmp_path / "live" / "2024-03-01.md").exists()

    dest = j.archive_existing()
    assert dest is not None
    assert not (tmp_path / "live" / "2024-03-01.md").exists()
    assert (dest / "2024-03-01.md").exists()


def test_archive_returns_none_when_empty(tmp_path):
    j = _journal(tmp_path)
    assert j.archive_existing() is None


def test_note_appends_intraday(tmp_path):
    j = _journal(tmp_path)
    j.start_day("2024-03-01")
    j.note("2024-03-01", "PDH swept, momentum flipping", kind="level")
    md = (tmp_path / "live" / "2024-03-01.md").read_text()
    assert "PDH swept" in md
