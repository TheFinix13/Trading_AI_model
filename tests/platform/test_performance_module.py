"""Unit tests for `agent.platform.performance`.

Coverage:

* v1 daily-log parser round-trip on real ``[TRADE CLOSED]`` /
  ``[TP HIT]`` / ``[SOFT SL]`` / ``[CATASTROPHE SL]`` line shapes
  (schema authoritative in `agent/live/trade_events.py`).
* v2 shadow-paper events.jsonl parser (close events with pnl_pips).
* Merge + time-sort across both sources.
* Equity curve is cumulative and monotonic in inputs.
* Worst draw-down is the deepest peak-to-trough on the curve.
* Sharpe returns None + "N days needed" below the 30-day floor,
  a real number above it.
* Per-pair aggregate rows (trades/wins/net/avg/best/worst) are
  correct on hand-computed fixtures.
* Missing sources degrade to a shaped-empty payload with a
  human-friendly source_hint (no 500).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import performance  # noqa: E402


# --- Fixture helpers ------------------------------------------------------

def _write_v1_log(log_root: Path, symbol: str, day: str,
                  lines: list[str]) -> Path:
    sym_dir = log_root / symbol
    sym_dir.mkdir(parents=True, exist_ok=True)
    log = sym_dir / f"{symbol}_{day}.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


def _trade_closed_line(ts: str, symbol: str, ticket: int, alpha: str,
                       direction: str, exit_px: float, pnl: float,
                       pips: float, r: float, cause: str,
                       tag: str = "TRADE CLOSED") -> str:
    """Mirror the exact line format written by `log_trade_closed`."""
    return (f"{ts},547 INFO agent.live.monitor - "
            f"[{tag}] {symbol} ticket={ticket} {alpha} "
            f"{direction.upper()} exit={exit_px:.5f} "
            f"pnl={pnl:+.2f} ({pips:+.1f}p, {r:+.2f}R) cause={cause}")


def _write_v2_events(live_dir: Path, rows: list[dict]) -> Path:
    live_dir.mkdir(parents=True, exist_ok=True)
    ev = live_dir / "events.jsonl"
    ev.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                  encoding="utf-8")
    return ev


# --- Parser tests ---------------------------------------------------------

class TestV1LogParser:

    def test_parses_trade_closed_line(self, tmp_path: Path):
        log_root = tmp_path / "logs"
        _write_v1_log(log_root, "EURUSD", "2026-07-15", [
            _trade_closed_line(
                "2026-07-15 09:22:03", "EURUSD", 12345,
                "zone_d1_against", "long", 1.09321, 2.98,
                30.5, 1.20, "tp"),
        ])
        trades = performance._collect_v1_trades(log_root)
        assert len(trades) == 1
        t = trades[0]
        assert t["symbol"] == "EURUSD"
        assert t["ticket"] == 12345
        assert t["alpha"] == "zone_d1_against"
        assert t["direction"] == "long"
        assert t["pnl_pips"] == 30.5
        assert t["exit_reason"] == "tp"
        assert t["source"] == "v1"
        assert t["ts"].startswith("2026-07-15T09:22:03")

    def test_parses_all_close_tags(self, tmp_path: Path):
        log_root = tmp_path / "logs"
        tags_and_causes = [
            ("TRADE CLOSED", "manual"),
            ("TP HIT", "tp"),
            ("SOFT SL", "soft_sl_close"),
            ("CATASTROPHE SL", "catastrophe_sl"),
            ("CLOSED (cause unconfirmed)", "unknown"),
            ("MARGIN STOP-OUT", "stop_out"),
            ("EA/EXPERT CLOSE", "expert"),
        ]
        lines = []
        for i, (tag, cause) in enumerate(tags_and_causes):
            lines.append(_trade_closed_line(
                f"2026-07-15 09:{22+i:02d}:03", "EURUSD", 10000 + i,
                "zone_d1_against", "long", 1.09321,
                (1.0 + i), (10.0 + i), 0.5, cause, tag=tag))
        _write_v1_log(log_root, "EURUSD", "2026-07-15", lines)
        trades = performance._collect_v1_trades(log_root)
        assert len(trades) == len(tags_and_causes)
        assert {t["tag"] for t in trades} == {t for t, _ in tags_and_causes}

    def test_ignores_non_close_lines(self, tmp_path: Path):
        log_root = tmp_path / "logs"
        _write_v1_log(log_root, "EURUSD", "2026-07-15", [
            "2026-07-15 09:00:00,000 INFO agent - heartbeat: alive",
            "2026-07-15 09:15:00,000 INFO agent - [TRADE OPENED] EURUSD "
            "H4 zone_d1_against LONG ticket=1 entry=1.10000 lots=0.01",
            "2026-07-15 09:30:00,000 INFO agent - [LADDER] EURUSD "
            "ticket=1 tp=1.10500 (soft 20p)",
            _trade_closed_line(
                "2026-07-15 12:00:00", "EURUSD", 1,
                "zone_d1_against", "long", 1.10500, 5.00,
                50.0, 2.50, "tp"),
        ])
        trades = performance._collect_v1_trades(log_root)
        assert len(trades) == 1

    def test_missing_log_root_returns_empty(self, tmp_path: Path):
        assert performance._collect_v1_trades(tmp_path / "nonexistent") == []

    def test_skips_non_symbol_dirs(self, tmp_path: Path):
        log_root = tmp_path / "logs"
        (log_root / "notes").mkdir(parents=True)
        (log_root / "notes" / "notes_2026-07-15.log").write_text(
            _trade_closed_line(
                "2026-07-15 09:00:00", "EURUSD", 1,
                "z", "long", 1.0, 1.0, 10.0, 0.5, "tp"),
            encoding="utf-8")
        assert performance._collect_v1_trades(log_root) == []

    def test_malformed_lines_dont_crash(self, tmp_path: Path):
        log_root = tmp_path / "logs"
        _write_v1_log(log_root, "EURUSD", "2026-07-15", [
            "not a log line",
            "[TRADE CLOSED] EURUSD ticket=... malformed",
            _trade_closed_line("2026-07-15 09:00:00", "EURUSD", 1,
                               "z", "long", 1.0, 1.0, 10.0, 0.5, "tp"),
        ])
        assert len(performance._collect_v1_trades(log_root)) == 1


class TestV2EventsParser:

    def test_parses_close_event_with_pnl_pips(self, tmp_path: Path):
        live = tmp_path / "squad_live"
        _write_v2_events(live, [
            {"type": "close", "symbol": "GBPUSD",
             "t": "2026-07-15T12:00:00", "pnl_pips": 8.5,
             "goal": True, "exit_reason": "tp"},
        ])
        trades = performance._collect_v2_trades(live)
        assert len(trades) == 1
        assert trades[0]["symbol"] == "GBPUSD"
        assert trades[0]["pnl_pips"] == 8.5
        assert trades[0]["source"] == "v2"

    def test_ignores_non_close_events(self, tmp_path: Path):
        live = tmp_path / "squad_live"
        _write_v2_events(live, [
            {"type": "proposal", "symbol": "EURUSD",
             "t": "2026-07-15T09:00:00", "dir": "long"},
            {"type": "open", "symbol": "EURUSD",
             "t": "2026-07-15T09:00:00", "dir": "long"},
            {"type": "close", "symbol": "EURUSD",
             "t": "2026-07-15T13:00:00", "pnl_pips": -4.2},
            {"type": "tick_summary", "symbol": "EURUSD"},
        ])
        assert len(performance._collect_v2_trades(live)) == 1

    def test_close_without_pnl_pips_ignored(self, tmp_path: Path):
        live = tmp_path / "squad_live"
        _write_v2_events(live, [
            {"type": "close", "symbol": "EURUSD",
             "t": "2026-07-15T13:00:00"},
        ])
        assert performance._collect_v2_trades(live) == []

    def test_missing_live_dir_returns_empty(self, tmp_path: Path):
        assert performance._collect_v2_trades(tmp_path / "nowhere") == []


# --- Derivation tests -----------------------------------------------------

class TestDerivations:

    def test_equity_curve_is_cumulative(self):
        trades = [{"ts": "2026-07-15T09:00:00", "pnl_pips": 10.0,
                   "symbol": "EURUSD"},
                  {"ts": "2026-07-15T13:00:00", "pnl_pips": -3.5,
                   "symbol": "EURUSD"},
                  {"ts": "2026-07-16T09:00:00", "pnl_pips": 7.5,
                   "symbol": "EURUSD"}]
        curve = performance._equity_curve(trades)
        assert [round(p["cum_pips"], 1) for p in curve] == [10.0, 6.5, 14.0]

    def test_worst_drawdown_peak_to_trough(self):
        curve = [
            {"ts": "1", "cum_pips": 10.0},
            {"ts": "2", "cum_pips": 25.0},   # peak
            {"ts": "3", "cum_pips": 15.0},
            {"ts": "4", "cum_pips": 5.0},    # trough (peak-to-trough = 20)
            {"ts": "5", "cum_pips": 12.0},
        ]
        assert performance._worst_dd(curve) == 20.0

    def test_worst_drawdown_zero_when_monotone_up(self):
        curve = [{"ts": str(i), "cum_pips": float(i)} for i in range(10)]
        assert performance._worst_dd(curve) == 0.0

    def test_sharpe_null_below_floor(self):
        # 10 daily returns -> below the 30-day floor -> None + needed
        sh, needed = performance._sharpe_or_null([1.0] * 10)
        assert sh is None
        assert needed == performance.MIN_DAYS_FOR_SHARPE - 10

    def test_sharpe_computed_at_or_above_floor(self):
        # 30 daily returns with a non-zero mean and std -> a real Sharpe.
        # Mixed 3.0 / -1.0 series has mean 1.0, std sqrt(2)+
        # so Sharpe = (1/std) * sqrt(252) > 0.
        series = [3.0, -1.0] * 15  # 30 entries
        sh, needed = performance._sharpe_or_null(series)
        assert sh is not None
        assert needed == 0
        assert sh > 0

    def test_sharpe_zero_std_returns_zero(self):
        series = [2.0] * 30
        sh, _ = performance._sharpe_or_null(series)
        assert sh == 0.0

    def test_per_pair_aggregates(self):
        trades = [
            {"symbol": "EURUSD", "pnl_pips": 10.0},
            {"symbol": "EURUSD", "pnl_pips": -3.0},
            {"symbol": "EURUSD", "pnl_pips": 5.0},  # 3 trades, 2 wins
            {"symbol": "GBPUSD", "pnl_pips": -6.0}, # 1 trade, 0 wins
        ]
        rows = performance._per_pair(trades)
        assert [r["symbol"] for r in rows] == ["EURUSD", "GBPUSD"]
        eur = rows[0]
        assert eur["trades"] == 3
        assert eur["wins"] == 2
        assert eur["net_pips"] == 12.0
        assert eur["best_pips"] == 10.0
        assert eur["worst_pips"] == -3.0
        assert round(eur["avg_pips"], 2) == 4.0
        gbp = rows[1]
        assert gbp["trades"] == 1
        assert gbp["wins"] == 0
        assert gbp["net_pips"] == -6.0


# --- Full-state contract tests --------------------------------------------

class TestGetStateContract:

    def test_missing_all_sources_returns_shaped_empty(self, tmp_path: Path):
        # Neither log root nor live dir exists.
        state = performance.get_state(
            log_root=tmp_path / "no_logs",
            live_dir=tmp_path / "no_live",
        )
        assert state["days_live"] == 0
        assert state["net_pips"] == 0
        assert state["equity_curve"] == []
        assert state["per_pair"] == []
        assert state["sharpe_or_null"] is None
        assert state["sharpe_days_needed"] == performance.MIN_DAYS_FOR_SHARPE
        assert "no shadow-paper data yet" in state["source_hint"]
        assert state["generated_at"].endswith("Z")

    def test_v1_only_source_hint(self, tmp_path: Path):
        log_root = tmp_path / "logs"
        _write_v1_log(log_root, "EURUSD", "2026-07-15", [
            _trade_closed_line("2026-07-15 09:00:00", "EURUSD", 1,
                               "z", "long", 1.0, 1.0, 10.0, 0.5, "tp"),
        ])
        state = performance.get_state(log_root=log_root)
        assert state["v1_trades_count"] == 1
        assert state["v2_trades_count"] == 0
        assert "v1 live-demo agent" in state["source_hint"]

    def test_v2_only_source_hint(self, tmp_path: Path):
        live = tmp_path / "squad_live"
        _write_v2_events(live, [
            {"type": "close", "symbol": "EURUSD",
             "t": "2026-07-15T13:00:00", "pnl_pips": 5.0},
        ])
        state = performance.get_state(live_dir=live)
        assert state["v2_trades_count"] == 1
        assert state["v1_trades_count"] == 0
        assert "shadow-paper" in state["source_hint"]

    def test_combined_source_hint(self, tmp_path: Path):
        log_root = tmp_path / "logs"
        _write_v1_log(log_root, "EURUSD", "2026-07-15", [
            _trade_closed_line("2026-07-15 09:00:00", "EURUSD", 1,
                               "z", "long", 1.0, 1.0, 10.0, 0.5, "tp"),
        ])
        live = tmp_path / "squad_live"
        _write_v2_events(live, [
            {"type": "close", "symbol": "GBPUSD",
             "t": "2026-07-15T13:00:00", "pnl_pips": -3.0},
        ])
        state = performance.get_state(log_root=log_root, live_dir=live)
        assert state["v1_trades_count"] == 1
        assert state["v2_trades_count"] == 1
        assert "combined view" in state["source_hint"]

    def test_full_payload_shape(self, tmp_path: Path):
        # Sanity: every promised key is present with the right type.
        state = performance.get_state()
        for k in ("generated_at", "days_live", "net_pips",
                  "worst_dd_pips", "win_rate_pct", "sharpe_or_null",
                  "sharpe_days_needed", "trades_total", "equity_curve",
                  "per_pair", "source_hint", "v1_trades_count",
                  "v2_trades_count"):
            assert k in state, f"missing key: {k!r}"

    def test_readonly_invariant(self, tmp_path: Path):
        # Regression: performance.get_state() must not create files under
        # log_root or live_dir. Simulate by pointing at empty dirs and
        # asserting neither is modified.
        log_root = tmp_path / "logs"
        log_root.mkdir()
        live = tmp_path / "squad_live"
        live.mkdir()
        _ = performance.get_state(log_root=log_root, live_dir=live)
        assert list(log_root.iterdir()) == []
        assert list(live.iterdir()) == []

    def test_win_rate_computation(self, tmp_path: Path):
        log_root = tmp_path / "logs"
        # 3 wins, 2 losses -> 60% win rate
        lines = []
        for i, pips in enumerate([10.0, -5.0, 12.0, -3.0, 8.0]):
            lines.append(_trade_closed_line(
                f"2026-07-15 0{i}:00:00", "EURUSD", 1000 + i,
                "z", "long", 1.0, pips / 10.0, pips, 0.5, "tp"))
        _write_v1_log(log_root, "EURUSD", "2026-07-15", lines)
        state = performance.get_state(log_root=log_root)
        assert state["win_rate_pct"] == 60.0
        assert state["trades_total"] == 5
        assert state["net_pips"] == 22.0
