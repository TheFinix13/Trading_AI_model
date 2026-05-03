"""Merge a stand-alone backtest journal into the dashboard's main journal.

Why this exists
---------------
``scripts/run_multitf.py`` writes each backtest run to its own SQLite file under
``data/`` (e.g. ``data/agent_3yr_v6_M15H1.db``) so concurrent runs don't trample
each other and a bad run can be thrown away cheaply.  The FastAPI dashboard
(``agent/dashboard/app.py``) reads ``cfg.journal_db`` (default
``journal.db`` in the project root), so those backtest trades never appear on
the dashboard until they're copied over.

This script merges ``signals``, ``trades`` (and optionally ``equity``) from a
source DB into the destination DB **without touching** the human-side tables
(``human_lessons``, ``weekly_logs``, ``agent_disagreements``,
``weekly_retrospectives``, ``chat_sessions``, ``chat_messages``,
``model_versions``).

It is idempotent.  Re-running with the same source is a no-op:

* signals are deduped on ``(detected_at, symbol, timeframe, direction,
  decision)`` — the natural identity of a setup as logged by
  ``Journal.log_signal``.
* trades are deduped on ``(entry_time, symbol, direction, mode)`` — there is at
  most one open trade per (mode, symbol) at a time in the engine, so this is
  unique in practice.
* equity rows are deduped on ``(timestamp, mode)``.

Usage::

    # Default: merge into the journal the dashboard reads
    PYTHONPATH=. .venv/bin/python scripts/import_backtest_journal.py \
        data/agent_3yr_v6_M15H1.db

    # Custom destination (e.g. a copy for inspection)
    python scripts/import_backtest_journal.py SRC.db --dest /tmp/merged.db

    # Preview without writing
    python scripts/import_backtest_journal.py SRC.db --dry-run

    # Tag every imported trade with a suffix so they can be filtered later
    python scripts/import_backtest_journal.py SRC.db --mode-suffix _3yrV6
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.config import load_config
from agent.journal.db import Journal


SIGNAL_COLS: tuple[str, ...] = (
    "detected_at",
    "symbol",
    "timeframe",
    "direction",
    "entry",
    "stop",
    "take_profit",
    "stop_pips",
    "rr",
    "confluences",
    "confluence_tfs_json",
    "features_json",
    "ml_score",
    "decision",
    "decision_reason",
    "lot_size",
    "actual_risk_pct",
    "entry_confirmation_json",
    "created_at",
)

TRADE_COLS: tuple[str, ...] = (
    "signal_id",
    "symbol",
    "direction",
    "entry_time",
    "entry_price",
    "stop_price",
    "tp_price",
    "lot_size",
    "exit_time",
    "exit_price",
    "exit_reason",
    "pnl",
    "pnl_pips",
    "commission",
    "mode",
    "created_at",
)

EQUITY_COLS: tuple[str, ...] = (
    "timestamp",
    "balance",
    "equity",
    "open_positions",
    "mode",
)


@dataclass
class MergeStats:
    signals_seen: int = 0
    signals_inserted: int = 0
    signals_skipped: int = 0
    trades_seen: int = 0
    trades_inserted: int = 0
    trades_skipped: int = 0
    equity_seen: int = 0
    equity_inserted: int = 0
    equity_skipped: int = 0

    def render(self) -> str:
        return (
            f"  signals: {self.signals_inserted} new / {self.signals_skipped} dup "
            f"(of {self.signals_seen})\n"
            f"  trades:  {self.trades_inserted} new / {self.trades_skipped} dup "
            f"(of {self.trades_seen})\n"
            f"  equity:  {self.equity_inserted} new / {self.equity_skipped} dup "
            f"(of {self.equity_seen})"
        )


def _row_dict(cur: sqlite3.Cursor, row: sqlite3.Row | tuple) -> dict[str, Any]:
    return {d[0]: row[i] for i, d in enumerate(cur.description)}


def _fetch_existing_signal_index(dst: sqlite3.Connection) -> dict[tuple, int]:
    """Build {(detected_at, symbol, timeframe, direction, decision): id} for the
    destination's existing signals so dedup is O(1) per source row."""
    index: dict[tuple, int] = {}
    cur = dst.execute(
        "SELECT id, detected_at, symbol, timeframe, direction, decision FROM signals"
    )
    for row in cur.fetchall():
        key = (row[1], row[2], row[3], row[4], row[5])
        index[key] = row[0]
    return index


def _fetch_existing_trade_keys(dst: sqlite3.Connection) -> set[tuple]:
    keys: set[tuple] = set()
    cur = dst.execute("SELECT entry_time, symbol, direction, mode FROM trades")
    for row in cur.fetchall():
        keys.add((row[0], row[1], row[2], row[3]))
    return keys


def _fetch_existing_equity_keys(dst: sqlite3.Connection) -> set[tuple]:
    keys: set[tuple] = set()
    cur = dst.execute("SELECT timestamp, mode FROM equity")
    for row in cur.fetchall():
        keys.add((row[0], row[1]))
    return keys


def _projected_select(table: str, cols: tuple[str, ...]) -> str:
    return f"SELECT id, {', '.join(cols)} FROM {table} ORDER BY id"


def _placeholders(n: int) -> str:
    return ", ".join(["?"] * n)


def merge_journals(
    src_path: Path,
    dst_path: Path,
    *,
    mode_suffix: str = "",
    dry_run: bool = False,
    include_equity: bool = True,
) -> MergeStats:
    """Merge ``signals`` + ``trades`` (+ optionally ``equity``) from ``src_path``
    into ``dst_path``.  Dedup keys are documented at the top of this module.

    Returns counts so callers / tests can assert on the result.

    ``mode_suffix`` is appended to every imported trade's ``mode`` column, e.g.
    use ``"_3yrV6"`` to keep imports clearly identified after merge.  Default is
    empty string (preserve source mode verbatim)."""
    src_path = Path(src_path)
    dst_path = Path(dst_path)
    if not src_path.exists():
        raise FileNotFoundError(f"source DB not found: {src_path}")

    # Touching Journal() at dst_path makes sure schema + migrations exist before
    # we start INSERTing — important for fresh / older journals.
    Journal(dst_path).close()

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(dst_path)
    dst.row_factory = sqlite3.Row

    stats = MergeStats()
    try:
        signal_index = _fetch_existing_signal_index(dst)
        trade_keys = _fetch_existing_trade_keys(dst)
        equity_keys = _fetch_existing_equity_keys(dst) if include_equity else set()

        # ----- signals: build src_id -> dst_id map ---------------------------
        sig_id_map: dict[int, int] = {}
        sig_cur = src.execute(_projected_select("signals", SIGNAL_COLS))
        sig_insert_sql = (
            f"INSERT INTO signals ({', '.join(SIGNAL_COLS)}) "
            f"VALUES ({_placeholders(len(SIGNAL_COLS))})"
        )
        for row in sig_cur.fetchall():
            stats.signals_seen += 1
            d = dict(row)
            src_id = d["id"]
            key = (
                d["detected_at"],
                d["symbol"],
                d["timeframe"],
                d["direction"],
                d["decision"],
            )
            if key in signal_index:
                sig_id_map[src_id] = signal_index[key]
                stats.signals_skipped += 1
                continue
            if dry_run:
                # Reserve a synthetic id so the trade pass still resolves.
                sig_id_map[src_id] = -src_id
            else:
                vals = tuple(d[c] for c in SIGNAL_COLS)
                cur = dst.execute(sig_insert_sql, vals)
                new_id = cur.lastrowid
                sig_id_map[src_id] = new_id
                signal_index[key] = new_id
            stats.signals_inserted += 1

        # ----- trades --------------------------------------------------------
        trade_cur = src.execute(_projected_select("trades", TRADE_COLS))
        trade_insert_sql = (
            f"INSERT INTO trades ({', '.join(TRADE_COLS)}) "
            f"VALUES ({_placeholders(len(TRADE_COLS))})"
        )
        for row in trade_cur.fetchall():
            stats.trades_seen += 1
            d = dict(row)
            mapped_signal_id = sig_id_map.get(d["signal_id"])
            mode_val = (d["mode"] or "backtest") + mode_suffix
            d["mode"] = mode_val
            d["signal_id"] = mapped_signal_id
            tkey = (d["entry_time"], d["symbol"], d["direction"], mode_val)
            if tkey in trade_keys:
                stats.trades_skipped += 1
                continue
            if not dry_run:
                vals = tuple(d[c] for c in TRADE_COLS)
                dst.execute(trade_insert_sql, vals)
            trade_keys.add(tkey)
            stats.trades_inserted += 1

        # ----- equity (optional) --------------------------------------------
        if include_equity:
            try:
                eq_cur = src.execute(_projected_select("equity", EQUITY_COLS))
            except sqlite3.OperationalError:
                eq_cur = None
            if eq_cur is not None:
                eq_insert_sql = (
                    f"INSERT INTO equity ({', '.join(EQUITY_COLS)}) "
                    f"VALUES ({_placeholders(len(EQUITY_COLS))})"
                )
                for row in eq_cur.fetchall():
                    stats.equity_seen += 1
                    d = dict(row)
                    mode_val = (d["mode"] or "backtest") + mode_suffix
                    d["mode"] = mode_val
                    ekey = (d["timestamp"], mode_val)
                    if ekey in equity_keys:
                        stats.equity_skipped += 1
                        continue
                    if not dry_run:
                        vals = tuple(d[c] for c in EQUITY_COLS)
                        dst.execute(eq_insert_sql, vals)
                    equity_keys.add(ekey)
                    stats.equity_inserted += 1

        if not dry_run:
            dst.commit()
    finally:
        src.close()
        dst.close()
    return stats


def _default_dest() -> Path:
    return load_config().journal_db


def main() -> int:
    p = argparse.ArgumentParser(
        description="Merge a backtest journal SQLite into the dashboard journal.",
    )
    p.add_argument("source", type=Path, help="path to the source backtest .db")
    p.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="destination DB (default: cfg.journal_db, usually project-root/journal.db)",
    )
    p.add_argument(
        "--mode-suffix",
        default="",
        help="suffix appended to trade/equity 'mode' values for tracking imports",
    )
    p.add_argument(
        "--no-equity",
        action="store_true",
        help="skip the equity table (useful when source is signals/trades-only)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be merged without writing",
    )
    args = p.parse_args()

    dest = args.dest or _default_dest()
    print(f"merging {args.source} -> {dest}{' (dry run)' if args.dry_run else ''}")
    stats = merge_journals(
        args.source,
        dest,
        mode_suffix=args.mode_suffix,
        dry_run=args.dry_run,
        include_equity=not args.no_equity,
    )
    print(stats.render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
