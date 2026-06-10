"""SQLite journal — agent-side decisions only (v2 reset).

What's kept after the audit:

* ``signals``       — every detected setup, its features, ML score, and the gate
                       verdict (taken / skipped).
* ``trades``        — every taken trade (entry, exit, P&L, MAE/MFE).
* ``equity``        — per-bar account equity for equity-curve plotting.
* ``model_versions``— bookkeeping for the production scorers we ship in v2.

What was burned (per ``docs/audit/redundancy_map.md``): the LLM-extracted
``human_lessons``, ``agent_disagreements``, ``weekly_retrospectives``,
``weekly_logs``, ``agent_corrections``, ``chat_sessions`` /
``chat_messages``, and ``chart_analyses`` tables — all of which were wired
into the BURN ``agent/llm/`` / ``agent/conversation/`` / ``agent/dashboard/``
stack. They can be re-introduced once the learning loop is rebuilt against
the v2 alpha framework.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    take_profit REAL NOT NULL,
    stop_pips REAL NOT NULL,
    rr REAL NOT NULL,
    confluences TEXT NOT NULL,
    confluence_tfs_json TEXT,
    features_json TEXT NOT NULL,
    ml_score REAL,
    decision TEXT NOT NULL,
    decision_reason TEXT,
    lot_size REAL,
    actual_risk_pct REAL,
    entry_confirmation_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER REFERENCES signals(id),
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    tp_price REAL NOT NULL,
    lot_size REAL NOT NULL,
    exit_time TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl REAL,
    pnl_pips REAL,
    commission REAL,
    mode TEXT NOT NULL DEFAULT 'backtest',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    balance REAL NOT NULL,
    equity REAL NOT NULL,
    open_positions INTEGER NOT NULL,
    mode TEXT NOT NULL DEFAULT 'backtest'
);

CREATE TABLE IF NOT EXISTS model_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL,
    trained_at TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    file_path TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(detected_at);
CREATE INDEX IF NOT EXISTS idx_trades_entry ON trades(entry_time);
CREATE INDEX IF NOT EXISTS idx_equity_time ON equity(timestamp);
"""


class Journal:
    def __init__(self, path: Path | str, autocommit: bool = True):
        """``autocommit=False`` defers commits until :meth:`commit` is called
        explicitly. Use ``with journal.batch(): ...`` to bulk-write thousands of
        rows at full speed without paying the fsync cost per row (e.g. during a
        backtest replay)."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.DatabaseError:
            pass
        self._conn.executescript(SCHEMA)
        for migration in (
            "ALTER TABLE signals ADD COLUMN confluence_tfs_json TEXT",
            "ALTER TABLE signals ADD COLUMN entry_confirmation_json TEXT",
        ):
            try:
                self._conn.execute(migration)
            except sqlite3.OperationalError:
                pass
        self._conn.commit()
        self._autocommit = autocommit

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()

    def commit(self) -> None:
        self._conn.commit()

    def batch(self):
        """Context manager: defer commits until exit."""
        journal = self
        class _Batch:
            def __enter__(self):
                journal._autocommit = False
                return journal
            def __exit__(self, *args):
                journal._conn.commit()
                journal._autocommit = True
        return _Batch()

    def _maybe_commit(self) -> None:
        if self._autocommit:
            self._conn.commit()

    # ---------------------------------------------------------- agent decisions

    def log_signal(
        self,
        setup,
        symbol: str,
        decision: str,
        decision_reason: str = "",
        lot_size: float = 0.0,
        actual_risk_pct: float = 0.0,
        ml_score: float | None = None,
    ) -> int:
        confluence_tfs_json = json.dumps(getattr(setup, "confluence_tfs", {}) or {})
        entry_conf_json = (json.dumps(setup.entry_confirmation)
                            if getattr(setup, "entry_confirmation", None) else None)
        cur = self._conn.execute(
            """INSERT INTO signals (detected_at, symbol, timeframe, direction, entry, stop, take_profit,
                                    stop_pips, rr, confluences, confluence_tfs_json,
                                    features_json, ml_score, decision,
                                    decision_reason, lot_size, actual_risk_pct,
                                    entry_confirmation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                setup.detected_at.isoformat(),
                symbol,
                setup.timeframe.value,
                setup.direction.value,
                setup.entry,
                setup.stop,
                setup.take_profit,
                setup.stop_pips,
                setup.rr,
                json.dumps(getattr(setup, "confluences", [])),
                confluence_tfs_json,
                json.dumps(getattr(setup, "features", {})),
                ml_score,
                decision,
                decision_reason,
                lot_size,
                actual_risk_pct,
                entry_conf_json,
            ),
        )
        self._maybe_commit()
        return cur.lastrowid

    def log_trade_open(
        self, signal_id: int, symbol: str, trade, mode: str = "backtest"
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO trades (signal_id, symbol, direction, entry_time, entry_price,
                                   stop_price, tp_price, lot_size, mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id,
                symbol,
                trade.direction.value,
                trade.entry_time.isoformat(),
                trade.entry_price,
                trade.stop_price,
                trade.tp_price,
                trade.lot_size,
                mode,
            ),
        )
        self._maybe_commit()
        return cur.lastrowid

    def log_trade_close(
        self,
        trade_id: int,
        exit_time: datetime,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        pnl_pips: float,
        commission: float = 0.0,
    ) -> None:
        self._conn.execute(
            """UPDATE trades SET exit_time=?, exit_price=?, exit_reason=?, pnl=?, pnl_pips=?, commission=?
               WHERE id=?""",
            (
                exit_time.isoformat(),
                exit_price,
                exit_reason,
                pnl,
                pnl_pips,
                commission,
                trade_id,
            ),
        )
        self._maybe_commit()

    def log_equity(self, ts: datetime, balance: float, equity: float,
                   open_positions: int, mode: str = "backtest") -> None:
        self._conn.execute(
            """INSERT INTO equity (timestamp, balance, equity, open_positions, mode) VALUES (?, ?, ?, ?, ?)""",
            (ts.isoformat(), balance, equity, open_positions, mode),
        )
        self._maybe_commit()

    def register_model(self, version: str, file_path: str, metrics: dict,
                       activate: bool = True) -> int:
        if activate:
            self._conn.execute("UPDATE model_versions SET is_active=0")
        cur = self._conn.execute(
            """INSERT INTO model_versions (version, trained_at, metrics_json, file_path, is_active)
               VALUES (?, ?, ?, ?, ?)""",
            (version, datetime.utcnow().isoformat(), json.dumps(metrics), file_path, int(activate)),
        )
        self._conn.commit()
        return cur.lastrowid

    def active_model(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM model_versions WHERE is_active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def all_trades(self, mode: str | None = None) -> list[dict]:
        if mode:
            rows = self._conn.execute(
                "SELECT * FROM trades WHERE mode=? ORDER BY entry_time", (mode,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM trades ORDER BY entry_time").fetchall()
        return [dict(r) for r in rows]

    def equity_curve(self, mode: str | None = None) -> list[dict]:
        if mode:
            rows = self._conn.execute(
                "SELECT * FROM equity WHERE mode=? ORDER BY timestamp", (mode,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM equity ORDER BY timestamp").fetchall()
        return [dict(r) for r in rows]
