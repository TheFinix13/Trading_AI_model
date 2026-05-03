"""Regression tests for ``scripts/import_backtest_journal.py``.

The dashboard reads ``cfg.journal_db`` (the project-root ``journal.db``) but
backtests write to dedicated ``data/agent_*.db`` files.  When the user wants
those backtest results to show up on http://127.0.0.1:8000/, they run::

    python scripts/import_backtest_journal.py data/agent_3yr_v6_M15H1.db

These tests pin down the contract that script must keep:

  * signals are merged with id-remapping into trades.signal_id
  * a second run of the same source is a no-op (idempotent / dedup works)
  * pre-existing human-side rows (lessons / weekly_logs / chat) are untouched
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from agent.journal.db import Journal
from scripts.import_backtest_journal import merge_journals


def _seed_signal(conn: sqlite3.Connection, **overrides) -> int:
    base = dict(
        detected_at="2025-06-01T10:00:00+00:00",
        symbol="EURUSD",
        timeframe="M15",
        direction="long",
        entry=1.0850,
        stop=1.0830,
        take_profit=1.0890,
        stop_pips=20.0,
        rr=2.0,
        confluences=json.dumps(["zone", "fvg"]),
        confluence_tfs_json=json.dumps({"zone": ["H1"]}),
        features_json=json.dumps({"slope": 0.4}),
        ml_score=0.62,
        decision="approved",
        decision_reason="",
        lot_size=0.10,
        actual_risk_pct=0.01,
        entry_confirmation_json=None,
    )
    base.update(overrides)
    cols = ", ".join(base)
    placeholders = ", ".join(["?"] * len(base))
    cur = conn.execute(
        f"INSERT INTO signals ({cols}) VALUES ({placeholders})",
        tuple(base.values()),
    )
    conn.commit()
    return cur.lastrowid


def _seed_trade(conn: sqlite3.Connection, signal_id: int, **overrides) -> int:
    base = dict(
        signal_id=signal_id,
        symbol="EURUSD",
        direction="long",
        entry_time="2025-06-01T10:15:00+00:00",
        entry_price=1.0852,
        stop_price=1.0830,
        tp_price=1.0890,
        lot_size=0.10,
        exit_time="2025-06-01T13:30:00+00:00",
        exit_price=1.0890,
        exit_reason="tp",
        pnl=38.0,
        pnl_pips=38.0,
        commission=0.7,
        mode="backtest_M15",
    )
    base.update(overrides)
    cols = ", ".join(base)
    placeholders = ", ".join(["?"] * len(base))
    cur = conn.execute(
        f"INSERT INTO trades ({cols}) VALUES ({placeholders})",
        tuple(base.values()),
    )
    conn.commit()
    return cur.lastrowid


def _seed_equity(conn: sqlite3.Connection, ts: str, balance: float, mode: str) -> None:
    conn.execute(
        "INSERT INTO equity (timestamp, balance, equity, open_positions, mode) "
        "VALUES (?, ?, ?, ?, ?)",
        (ts, balance, balance, 0, mode),
    )
    conn.commit()


def _build_source(path: Path) -> dict[int, int]:
    """Create a backtest-shaped source DB with two distinct signals and trades.
    Returns the map of {signal_local_id: trade_local_id}."""
    Journal(path).close()
    conn = sqlite3.connect(path)
    sig_a = _seed_signal(conn, detected_at="2025-06-01T10:00:00+00:00", direction="long")
    sig_b = _seed_signal(
        conn,
        detected_at="2025-06-02T14:00:00+00:00",
        direction="short",
        decision="approved",
        timeframe="H1",
    )
    trade_a = _seed_trade(conn, sig_a)
    trade_b = _seed_trade(
        conn,
        sig_b,
        direction="short",
        entry_time="2025-06-02T14:15:00+00:00",
        exit_time="2025-06-02T18:00:00+00:00",
        mode="backtest_H1",
        pnl=-22.0,
        exit_reason="sl",
    )
    _seed_equity(conn, "2025-06-01T13:30:00+00:00", 10100.0, "backtest_M15")
    _seed_equity(conn, "2025-06-02T18:00:00+00:00", 10078.0, "backtest_H1")
    conn.close()
    return {sig_a: trade_a, sig_b: trade_b}


def _counts(path: Path) -> dict[str, int]:
    c = sqlite3.connect(path)
    out = {}
    for t in ("signals", "trades", "equity", "human_lessons",
              "weekly_logs", "chat_sessions", "chat_messages"):
        out[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    c.close()
    return out


def test_merge_inserts_signals_and_trades(tmp_path: Path):
    src = tmp_path / "backtest.db"
    dst = tmp_path / "journal.db"
    _build_source(src)
    Journal(dst).close()

    stats = merge_journals(src, dst)

    assert stats.signals_inserted == 2
    assert stats.trades_inserted == 2
    assert stats.equity_inserted == 2

    counts = _counts(dst)
    assert counts["signals"] == 2
    assert counts["trades"] == 2
    assert counts["equity"] == 2


def test_merge_is_idempotent(tmp_path: Path):
    src = tmp_path / "backtest.db"
    dst = tmp_path / "journal.db"
    _build_source(src)
    Journal(dst).close()

    merge_journals(src, dst)
    second = merge_journals(src, dst)

    assert second.signals_inserted == 0
    assert second.signals_skipped == 2
    assert second.trades_inserted == 0
    assert second.trades_skipped == 2
    assert second.equity_inserted == 0
    assert second.equity_skipped == 2

    counts = _counts(dst)
    assert counts["signals"] == 2
    assert counts["trades"] == 2
    assert counts["equity"] == 2


def test_merge_remaps_signal_ids(tmp_path: Path):
    """A pre-existing dest row should make the source signal collapse onto it,
    and the merged trade should point at the existing dest signal id (not a
    stale source id)."""
    src = tmp_path / "backtest.db"
    dst = tmp_path / "journal.db"
    _build_source(src)
    # Seed dst with a *different* prior signal so dst auto-increment ids diverge
    # from the source's, then add a row that matches sig_a's natural key.
    Journal(dst).close()
    dst_conn = sqlite3.connect(dst)
    _seed_signal(
        dst_conn,
        detected_at="2024-01-01T00:00:00+00:00",
        direction="short",
        decision="skip_ml",
    )
    pre_existing_a_id = _seed_signal(
        dst_conn,
        detected_at="2025-06-01T10:00:00+00:00",
        direction="long",
        decision="approved",
    )
    dst_conn.close()

    stats = merge_journals(src, dst)

    # Only sig_b is novel, sig_a collapses to the pre-existing row.
    assert stats.signals_inserted == 1
    assert stats.signals_skipped == 1
    # Both trades should have been inserted with proper signal_id remap.
    assert stats.trades_inserted == 2

    c = sqlite3.connect(dst)
    rows = c.execute(
        "SELECT entry_time, signal_id FROM trades ORDER BY entry_time"
    ).fetchall()
    c.close()
    by_entry = {r[0]: r[1] for r in rows}
    # Trade A's signal_id should equal the pre-existing dest signal id, not the
    # source's local id (which was 1).
    assert by_entry["2025-06-01T10:15:00+00:00"] == pre_existing_a_id


def test_merge_preserves_human_side_tables(tmp_path: Path):
    """Lessons, weekly_logs, chat_* must NEVER be touched by the merge."""
    src = tmp_path / "backtest.db"
    dst = tmp_path / "journal.db"
    _build_source(src)

    j = Journal(dst)
    j._conn.execute(
        "INSERT INTO human_lessons (trade_date, symbol, direction, entry_price, "
        "outcome, confluences_json) VALUES (?,?,?,?,?,?)",
        ("2025-06-01", "EURUSD", "long", 1.085, "win", "[]"),
    )
    j._conn.execute(
        "INSERT INTO weekly_logs (week_start, week_end, symbol, standardized_md, "
        "standardized_json) VALUES (?,?,?,?,?)",
        ("2025-05-26", "2025-05-30", "EURUSD", "# week", "{}"),
    )
    j._conn.execute(
        "INSERT INTO chat_sessions (title, last_active) VALUES (?, ?)",
        ("seed chat", datetime.utcnow().isoformat()),
    )
    j._conn.commit()
    j.close()

    pre = _counts(dst)
    merge_journals(src, dst)
    post = _counts(dst)

    for human_table in ("human_lessons", "weekly_logs", "chat_sessions",
                        "chat_messages"):
        assert post[human_table] == pre[human_table], human_table


def test_merge_dry_run_does_not_write(tmp_path: Path):
    src = tmp_path / "backtest.db"
    dst = tmp_path / "journal.db"
    _build_source(src)
    Journal(dst).close()

    stats = merge_journals(src, dst, dry_run=True)
    assert stats.signals_inserted == 2
    assert stats.trades_inserted == 2

    counts = _counts(dst)
    assert counts["signals"] == 0
    assert counts["trades"] == 0
    assert counts["equity"] == 0


def test_merge_mode_suffix_applies_to_trades_and_equity(tmp_path: Path):
    src = tmp_path / "backtest.db"
    dst = tmp_path / "journal.db"
    _build_source(src)
    Journal(dst).close()

    merge_journals(src, dst, mode_suffix="_v6")

    c = sqlite3.connect(dst)
    trade_modes = sorted({r[0] for r in c.execute("SELECT mode FROM trades").fetchall()})
    equity_modes = sorted({r[0] for r in c.execute("SELECT mode FROM equity").fetchall()})
    c.close()
    assert all(m.endswith("_v6") for m in trade_modes), trade_modes
    assert all(m.endswith("_v6") for m in equity_modes), equity_modes


def test_merge_missing_source_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        merge_journals(tmp_path / "nope.db", tmp_path / "j.db")
