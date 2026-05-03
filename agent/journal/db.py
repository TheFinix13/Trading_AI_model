"""SQLite journal: every signal (taken or skipped), feature vector, model score, outcome.

This file owns ALL persistence for the agent + the human-side learning loop:

  * `signals` / `trades` / `equity` / `model_versions`
        — the agent's own decisions and outcomes (untouched).
  * `human_lessons`
        — what the user actually traded and the reasoning they gave us
        (extracted by the LLM from a free-form paragraph).
  * `agent_disagreements`
        — for each lesson, what the agent would have done at that timestamp.
        This is the *training signal* for closing the gap between human and
        agent reads.
  * `weekly_retrospectives`
        — auto-generated Friday reports clustering the week's mistakes.
  * `chat_sessions` / `chat_messages`
        — conversation history shared by `scripts/ask.py` and the dashboard
        `/chat` page.
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

-- Human-side learning surface. Distinct from `trades` (which holds the agent's
-- simulated/live decisions). Every row is a discretionary trade or a "would-have"
-- that the user typed/spoke into teach.py.
CREATE TABLE IF NOT EXISTS human_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL,
    tp_price REAL,
    outcome TEXT NOT NULL DEFAULT 'open',
    pnl_pips REAL,
    pnl_usd REAL,
    daily_bias TEXT,
    confluences_json TEXT NOT NULL,
    session TEXT,
    emotion TEXT,
    notes TEXT,
    raw_text TEXT,
    extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    source TEXT DEFAULT 'teach.py'
);

CREATE TABLE IF NOT EXISTS agent_disagreements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id INTEGER NOT NULL REFERENCES human_lessons(id) ON DELETE CASCADE,
    agreement TEXT NOT NULL,
    agent_direction TEXT,
    agent_entry REAL,
    agent_stop REAL,
    agent_tp REAL,
    agent_confluences_json TEXT,
    agent_ml_score REAL,
    diff_summary TEXT,
    detected_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weekly_retrospectives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    n_trades INTEGER NOT NULL,
    n_wins INTEGER NOT NULL,
    n_losses INTEGER NOT NULL,
    total_pips REAL,
    total_usd REAL,
    failure_clusters_json TEXT,
    lessons_learned TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_active TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    context_json TEXT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

-- A whole-week trading review (the user's Word docs land here). Each row holds
-- the standardized markdown + a JSON dump of the WeeklyTradingLog object so the
-- dashboard / chat agent can re-load patterns, observations, predictions.
CREATE TABLE IF NOT EXISTS weekly_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    symbol TEXT NOT NULL,
    standardized_md TEXT NOT NULL,
    standardized_json TEXT NOT NULL,
    n_trades INTEGER NOT NULL DEFAULT 0,
    total_pips REAL,
    total_usd REAL,
    source_path TEXT,
    source_kind TEXT DEFAULT 'docx',
    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(detected_at);
CREATE INDEX IF NOT EXISTS idx_trades_entry ON trades(entry_time);
CREATE INDEX IF NOT EXISTS idx_equity_time ON equity(timestamp);
CREATE INDEX IF NOT EXISTS idx_lessons_date ON human_lessons(trade_date);
CREATE INDEX IF NOT EXISTS idx_disagreements_lesson ON agent_disagreements(lesson_id);
CREATE INDEX IF NOT EXISTS idx_chat_msg_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_weekly_logs_start ON weekly_logs(week_start);
"""


class Journal:
    def __init__(self, path: Path | str, autocommit: bool = True):
        """`autocommit=False` defers commits until `commit()` is called explicitly.
        Use `with journal.batch(): ...` to bulk-write thousands of rows at full speed
        without paying the fsync cost per row (e.g., during a backtest replay)."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL gives us much better write throughput; safe for the single-writer
        # backtest workload and for the live trader.
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.DatabaseError:
            pass
        self._conn.executescript(SCHEMA)
        # Migrate older journals. ALTER TABLE … ADD COLUMN is idempotent enough
        # if we swallow "duplicate column" errors. New tables are handled by
        # CREATE TABLE IF NOT EXISTS in SCHEMA above.
        for migration in (
            "ALTER TABLE signals ADD COLUMN confluence_tfs_json TEXT",
            "ALTER TABLE signals ADD COLUMN entry_confirmation_json TEXT",
            "ALTER TABLE human_lessons ADD COLUMN weekly_log_id INTEGER",
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
        """Context manager: defer commits until exit. Use for high-throughput writes."""
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
                json.dumps(setup.confluences),
                confluence_tfs_json,
                json.dumps(setup.features),
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

    def log_equity(self, ts: datetime, balance: float, equity: float, open_positions: int, mode: str = "backtest") -> None:
        self._conn.execute(
            """INSERT INTO equity (timestamp, balance, equity, open_positions, mode) VALUES (?, ?, ?, ?, ?)""",
            (ts.isoformat(), balance, equity, open_positions, mode),
        )
        self._maybe_commit()

    def register_model(self, version: str, file_path: str, metrics: dict, activate: bool = True) -> int:
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
            rows = self._conn.execute("SELECT * FROM trades WHERE mode=? ORDER BY entry_time", (mode,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM trades ORDER BY entry_time").fetchall()
        return [dict(r) for r in rows]

    def equity_curve(self, mode: str | None = None) -> list[dict]:
        if mode:
            rows = self._conn.execute("SELECT * FROM equity WHERE mode=? ORDER BY timestamp", (mode,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM equity ORDER BY timestamp").fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------- human lessons

    def log_human_lesson(
        self,
        lesson,
        source: str = "teach.py",
        weekly_log_id: int | None = None,
    ) -> int:
        """Persist a :class:`agent.llm.extractor.TradeLesson` into ``human_lessons``.

        ``lesson`` is duck-typed: either a TradeLesson (Pydantic) or anything with
        the same attribute names. Returns the new ``id``.

        ``weekly_log_id`` ties this lesson back to a row in ``weekly_logs`` when
        it came from a multi-day ingest (e.g. ``scripts/ingest_docx.py``)."""
        confluences = []
        for c in getattr(lesson, "confluences", []) or []:
            if hasattr(c, "model_dump"):
                confluences.append(c.model_dump())
            elif hasattr(c, "__dict__"):
                confluences.append({k: v for k, v in c.__dict__.items() if not k.startswith("_")})
            else:
                confluences.append(dict(c))
        td = lesson.trade_date
        td_str = td.isoformat() if hasattr(td, "isoformat") else str(td)
        cur = self._conn.execute(
            """INSERT INTO human_lessons (trade_date, symbol, direction, entry_price,
                                          stop_price, tp_price, outcome, pnl_pips, pnl_usd,
                                          daily_bias, confluences_json, session, emotion,
                                          notes, raw_text, source, weekly_log_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                td_str,
                lesson.symbol,
                lesson.direction,
                lesson.entry_price,
                lesson.stop_price,
                lesson.tp_price,
                lesson.outcome,
                lesson.pnl_pips,
                lesson.pnl_usd,
                lesson.daily_bias,
                json.dumps(confluences),
                lesson.session,
                lesson.emotion,
                lesson.notes,
                lesson.raw_text,
                source,
                weekly_log_id,
            ),
        )
        self._maybe_commit()
        return cur.lastrowid

    # ---------------------------------------------------------- weekly logs

    def log_weekly_log(self, weekly) -> int:
        """Persist a :class:`agent.llm.weekly.WeeklyTradingLog` into ``weekly_logs``.
        Returns the new id so individual lessons can FK back to it."""
        from agent.llm.weekly import WeeklyTradingLog
        if not isinstance(weekly, WeeklyTradingLog):
            raise TypeError(f"expected WeeklyTradingLog, got {type(weekly).__name__}")
        cur = self._conn.execute(
            """INSERT INTO weekly_logs (week_start, week_end, symbol,
                                        standardized_md, standardized_json,
                                        n_trades, total_pips, total_usd,
                                        source_path, source_kind)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                weekly.week_start.isoformat(),
                weekly.week_end.isoformat(),
                weekly.symbol,
                weekly.to_markdown(),
                weekly.model_dump_json(),
                weekly.n_trades,
                weekly.total_pips,
                weekly.total_usd,
                weekly.source_path,
                weekly.source_kind,
            ),
        )
        self._maybe_commit()
        return cur.lastrowid

    def all_weekly_logs(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, week_start, week_end, symbol, n_trades, total_pips, total_usd, "
            "source_path, ingested_at FROM weekly_logs ORDER BY week_start DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_weekly_log(self, weekly_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM weekly_logs WHERE id=?", (weekly_id,)
        ).fetchone()
        return dict(row) if row else None

    def all_lessons(self,
                     start_date: str | None = None,
                     end_date: str | None = None) -> list[dict]:
        sql = "SELECT * FROM human_lessons"
        clauses, args = [], []
        if start_date:
            clauses.append("trade_date >= ?")
            args.append(start_date)
        if end_date:
            clauses.append("trade_date <= ?")
            args.append(end_date)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY trade_date, id"
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def get_lesson(self, lesson_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM human_lessons WHERE id=?", (lesson_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_lesson(self, lesson_id: int) -> None:
        self._conn.execute("DELETE FROM human_lessons WHERE id=?", (lesson_id,))
        self._maybe_commit()

    # ---------------------------------------------------------- disagreements

    def log_disagreement(
        self,
        lesson_id: int,
        agreement: str,
        agent_direction: str | None = None,
        agent_entry: float | None = None,
        agent_stop: float | None = None,
        agent_tp: float | None = None,
        agent_confluences: list | None = None,
        agent_ml_score: float | None = None,
        diff_summary: str = "",
        detected_at: datetime | str | None = None,
    ) -> int:
        det_str = (
            detected_at.isoformat() if isinstance(detected_at, datetime)
            else (detected_at or None)
        )
        cur = self._conn.execute(
            """INSERT INTO agent_disagreements (lesson_id, agreement, agent_direction,
                                                agent_entry, agent_stop, agent_tp,
                                                agent_confluences_json, agent_ml_score,
                                                diff_summary, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                lesson_id,
                agreement,
                agent_direction,
                agent_entry,
                agent_stop,
                agent_tp,
                json.dumps(agent_confluences or []),
                agent_ml_score,
                diff_summary,
                det_str,
            ),
        )
        self._maybe_commit()
        return cur.lastrowid

    def disagreements_for_lesson(self, lesson_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM agent_disagreements WHERE lesson_id=? ORDER BY id", (lesson_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------- retrospectives

    def log_retrospective(
        self,
        week_start: str,
        week_end: str,
        n_trades: int,
        n_wins: int,
        n_losses: int,
        total_pips: float,
        total_usd: float,
        failure_clusters: list,
        lessons_learned: str,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO weekly_retrospectives (week_start, week_end, n_trades, n_wins,
                                                  n_losses, total_pips, total_usd,
                                                  failure_clusters_json, lessons_learned)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (week_start, week_end, n_trades, n_wins, n_losses, total_pips, total_usd,
             json.dumps(failure_clusters), lessons_learned),
        )
        self._maybe_commit()
        return cur.lastrowid

    def all_retrospectives(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM weekly_retrospectives ORDER BY week_start DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------- chat

    def create_chat_session(self, title: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO chat_sessions (title, last_active) VALUES (?, ?)",
            (title, datetime.utcnow().isoformat()),
        )
        self._maybe_commit()
        return cur.lastrowid

    def append_chat_message(
        self,
        session_id: int,
        role: str,
        content: str,
        context: dict | None = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO chat_messages (session_id, role, content, context_json)
               VALUES (?, ?, ?, ?)""",
            (session_id, role, content, json.dumps(context) if context else None),
        )
        self._conn.execute(
            "UPDATE chat_sessions SET last_active=? WHERE id=?",
            (datetime.utcnow().isoformat(), session_id),
        )
        self._maybe_commit()
        return cur.lastrowid

    def chat_history(self, session_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM chat_messages WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def list_chat_sessions(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM chat_sessions ORDER BY last_active DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
