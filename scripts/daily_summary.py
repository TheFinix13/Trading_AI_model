"""Paste-friendly daily / multi-day trading summary.

Walks the live evidence on disk and prints ONE compact report covering every
deployed symbol — designed so you can copy the entire stdout into chat and I
can analyse drift over time.

Per-symbol it parses the structured daily log lines (``[TRADE OPENED]``,
``[TP HIT]`` / ``[SOFT SL]`` / ``[CATASTROPHE SL]`` / ``[BREAKEVEN]`` /
``[PARTIAL TP]``, ``[NEAR MISS]``, ``[POSITION ADOPTED]`` /
``[POSITION RESTORED]`` / ``[SOFT SL ARMED]``, ``[LADDER]``, ``[SIGNAL]``,
``[ORDER REJECTED]``, plus the H4-close and heartbeat lines) for each day in
the window, reads the ``state.json`` sidecar for the current risk-manager /
post-loss-guard snapshot, and rolls cumulative numbers off the vault JSONLs
(``losses/events.jsonl``, ``near_misses/events.jsonl``,
``ladders/events.jsonl``).

Nothing it prints is interpretation — that's my job once you paste the
output back. The script is observation-only.

Usage:
    python scripts/daily_summary.py
    python scripts/daily_summary.py --days 7
    python scripts/daily_summary.py --symbol EURUSD GBPUSD USDCAD --days 1
    python scripts/daily_summary.py --log-dir D:\\TradingAgentLogs
    python scripts/daily_summary.py --out summary.txt --no-stdout

Each run also writes its output to a file under ``{log-dir}/summaries/`` (the
exact path is printed at the end) so you can attach it instead of copying
the whole report into chat. Override the destination with ``--out`` or
disable file output with ``--no-save``.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.journal.vault import DEFAULT_VAULT_ROOT  # noqa: E402

DEFAULT_SYMBOLS = ("EURUSD", "GBPUSD", "USDCAD")
# Live logs use the broker-suffixed name (EURUSDm), but logs are written to a
# folder named with the bare symbol. Try both when searching.
BROKER_SUFFIXES = ("", "m")

# ---------------------------------------------------------------------------
# Regex parsers (one line in the daily log → one structured event)
# ---------------------------------------------------------------------------
RE_TRADE_OPENED = re.compile(
    r"\[TRADE OPENED\] (?P<sym>\S+) (?P<tf>\S+) (?P<alpha>\S+) "
    r"(?P<dir>LONG|SHORT) ticket=(?P<ticket>\d+) entry=(?P<entry>[\d.]+) "
    r"lots=(?P<lots>[\d.]+) "
    r"soft_sl=(?P<soft>[\d.]+) \((?P<soft_p>\d+)p\) "
    r"catastrophe_sl=(?P<cata>[\d.]+) \((?P<cata_p>\d+)p\) "
    r"tp_mech=(?P<tp>[\d.]+) \((?P<tp_r>[\d.]+)R, \+(?P<tp_p>\d+)p\) "
    r"risk=(?P<risk>[\d.]+)%"
)
RE_TRADE_CLOSED = re.compile(
    r"\[(?P<tag>TP HIT|SOFT SL|CATASTROPHE SL|TRADE CLOSED)\] (?P<sym>\S+) "
    r"ticket=(?P<ticket>\d+) (?P<alpha>\S+) (?P<dir>LONG|SHORT) "
    r"exit=(?P<exit>[\d.]+) pnl=(?P<pnl>[+-]?[\d.]+) "
    r"\((?P<pips>[+-]?\d+)p, (?P<r>[+-]?[\d.]+)R\) cause=(?P<cause>\S+)"
)
RE_NEAR_MISS = re.compile(
    r"\[NEAR MISS\] (?P<sym>\S+) (?P<tf>\S+) (?P<alpha>\S+) "
    r"reason=(?P<reason>\S+)(?: — (?P<detail>.+))?"
)
RE_ORDER_REJECTED = re.compile(
    r"\[ORDER REJECTED\] (?P<sym>\S+) (?P<tf>\S+) (?P<alpha>\S+) — (?P<detail>.+)"
)
RE_SIGNAL = re.compile(
    r"\[SIGNAL\] (?P<sym>\S+) (?P<tf>\S+) (?P<alpha>\S+) "
    r"(?P<dir>LONG|SHORT) entry=(?P<entry>[\d.]+) soft_sl=(?P<soft>[\d.]+) "
    r"tp=(?P<tp>[\d.]+) conviction=(?P<conv>[\d.]+)"
)
RE_BREAKEVEN = re.compile(
    r"\[BREAKEVEN\] (?P<sym>\S+) ticket=(?P<ticket>\d+) sl [\d.]+ -> [\d.]+ "
    r"\(at (?P<r>[\d.]+)R\)"
)
RE_PARTIAL = re.compile(
    r"\[PARTIAL TP\] (?P<sym>\S+) ticket=(?P<ticket>\d+) closed "
    r"(?P<closed>[\d.]+) of (?P<total>[\d.]+) lots at (?P<r>[\d.]+)R"
)
RE_ADOPTED = re.compile(
    r"\[POSITION ADOPTED\] (?P<sym>\S+) ticket=(?P<ticket>\d+) "
    r"(?P<dir>LONG|SHORT) (?P<lots>[\d.]+) lots entry=(?P<entry>[\d.]+)"
)
RE_RESTORED = re.compile(
    r"\[POSITION RESTORED\] (?P<sym>\S+) ticket=(?P<ticket>\d+) "
    r"(?P<dir>LONG|SHORT) entry=(?P<entry>[\d.]+)"
)
RE_SOFT_ARMED = re.compile(
    r"\[SOFT SL ARMED\] (?P<sym>\S+) ticket=(?P<ticket>\d+) "
    r"soft_sl=(?P<soft>[\d.]+) source=(?P<source>\S+)"
)
RE_BREACH = re.compile(
    r"\[ADOPTED — SOFT SL ALREADY BREACHED\] (?P<sym>\S+) ticket=(?P<ticket>\d+)"
)
RE_LADDER = re.compile(
    r"\[LADDER\] (?P<sym>\S+) ticket=(?P<ticket>\d+) "
    r"(?:n=(?P<n>\d+)(?: (?P<rungs>.+))?|status=unknown \((?P<reason>[^)]+)\))"
)
RE_H4_NO_SETUP = re.compile(
    r"H4 close (?P<hh>\d{2}:\d{2}) UTC: evaluated, no setup"
)
RE_HEARTBEAT = re.compile(
    r"heartbeat: balance=\$(?P<bal>[\d.]+) equity=\$(?P<eq>[\d.]+) "
    r"open_positions=(?P<n>\d+)"
)


# ---------------------------------------------------------------------------
# Per-symbol bucket
# ---------------------------------------------------------------------------
@dataclass
class SymbolStats:
    symbol: str
    trades_opened: int = 0
    trades_closed_by_cause: Counter = field(default_factory=Counter)
    closed_pnl_usd: float = 0.0
    closed_pnl_pips: float = 0.0
    closed_r: list[float] = field(default_factory=list)
    breakeven_moves: int = 0
    partials: int = 0
    signals: int = 0
    order_rejected: int = 0
    near_misses_by_reason: Counter = field(default_factory=Counter)
    near_miss_total: int = 0
    h4_no_setup: int = 0
    adopted: list[dict] = field(default_factory=list)
    restored: list[dict] = field(default_factory=list)
    soft_armed: list[dict] = field(default_factory=list)
    breached: list[dict] = field(default_factory=list)
    ladders_emitted: int = 0
    ladder_unknown: int = 0
    last_heartbeat: dict | None = None
    state: dict | None = None
    log_files_seen: list[str] = field(default_factory=list)

    @property
    def closed_wins(self) -> int:
        return sum(1 for r in self.closed_r if r > 0)

    @property
    def closed_total(self) -> int:
        return len(self.closed_r)

    @property
    def expectancy_r(self) -> float:
        return statistics.fmean(self.closed_r) if self.closed_r else 0.0


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def _log_path(root: Path, symbol: str, day: date) -> Path | None:
    """Return the daily log file for ``(symbol, day)`` if it exists.

    Tries both the bare symbol folder/filename ("EURUSD") and the broker-
    suffixed one ("EURUSDm") so the script works on any deployment naming.
    """
    iso = day.strftime("%Y-%m-%d")
    for suffix in BROKER_SUFFIXES:
        base = f"{symbol}{suffix}"
        candidate = root / base / f"{base}_{iso}.log"
        if candidate.exists():
            return candidate
        # Folder may be the bare symbol but file may carry the broker suffix.
        candidate = root / symbol / f"{base}_{iso}.log"
        if candidate.exists():
            return candidate
    return None


def _vault_dir(root: Path, symbol: str) -> Path | None:
    for suffix in BROKER_SUFFIXES:
        p = root / f"{symbol}{suffix}"
        if p.exists():
            return p
    return None


def _read_state(symbol_dir: Path) -> dict | None:
    state_path = symbol_dir / "state.json"
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _iter_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------
def parse_log_file(path: Path, stats: SymbolStats) -> None:
    """Aggregate one daily log file's events into ``stats`` in place."""
    stats.log_files_seen.append(path.name)
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.rstrip()

        m = RE_TRADE_OPENED.search(line)
        if m:
            stats.trades_opened += 1
            continue

        m = RE_TRADE_CLOSED.search(line)
        if m:
            cause = m.group("cause")
            stats.trades_closed_by_cause[cause] += 1
            try:
                stats.closed_pnl_usd += float(m.group("pnl"))
                stats.closed_pnl_pips += float(m.group("pips"))
                stats.closed_r.append(float(m.group("r")))
            except ValueError:
                pass
            continue

        m = RE_NEAR_MISS.search(line)
        if m:
            stats.near_miss_total += 1
            stats.near_misses_by_reason[m.group("reason")] += 1
            continue

        m = RE_ORDER_REJECTED.search(line)
        if m:
            stats.order_rejected += 1
            continue

        m = RE_SIGNAL.search(line)
        if m:
            stats.signals += 1
            continue

        if RE_BREAKEVEN.search(line):
            stats.breakeven_moves += 1
            continue
        if RE_PARTIAL.search(line):
            stats.partials += 1
            continue

        m = RE_ADOPTED.search(line)
        if m:
            stats.adopted.append(m.groupdict())
            continue
        m = RE_RESTORED.search(line)
        if m:
            stats.restored.append(m.groupdict())
            continue
        m = RE_SOFT_ARMED.search(line)
        if m:
            stats.soft_armed.append(m.groupdict())
            continue
        m = RE_BREACH.search(line)
        if m:
            stats.breached.append(m.groupdict())
            continue

        m = RE_LADDER.search(line)
        if m:
            if m.group("reason"):
                stats.ladder_unknown += 1
            else:
                stats.ladders_emitted += 1
            continue

        if RE_H4_NO_SETUP.search(line):
            stats.h4_no_setup += 1
            continue

        m = RE_HEARTBEAT.search(line)
        if m:
            stats.last_heartbeat = {
                "ts": line[:19] if line[:4].isdigit() else "",
                "balance": float(m.group("bal")),
                "equity": float(m.group("eq")),
                "open_positions": int(m.group("n")),
            }


# ---------------------------------------------------------------------------
# Cumulative vault aggregates (all-time, not just the window)
# ---------------------------------------------------------------------------
def ladder_reach(symbol_dir: Path) -> tuple[dict[str, dict], int, int]:
    """Cumulative ladder reach rates from ``ladders/events.jsonl``.

    Returns ``(by_source, n_closed, n_with_any_reach)`` so the caller can show
    both the per-source breakdown and the trade-level summary.
    """
    path = symbol_dir / "ladders" / "events.jsonl"
    by_source: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "reached": 0, "reached_rs": []})
    n_closed = 0
    n_with_reach = 0
    for rec in _iter_jsonl(path):
        if rec.get("phase") != "close":
            continue
        n_closed += 1
        any_reached = False
        for rung in rec.get("rungs") or []:
            if "reached" not in rung:
                continue
            src = str(rung.get("source", "unknown"))
            bucket = by_source[src]
            bucket["n"] += 1
            if rung["reached"]:
                bucket["reached"] += 1
                any_reached = True
                try:
                    bucket["reached_rs"].append(float(rung["r_multiple"]))
                except (KeyError, TypeError, ValueError):
                    pass
        if any_reached:
            n_with_reach += 1
    return dict(by_source), n_closed, n_with_reach


def vault_counts(symbol_dir: Path) -> dict[str, int]:
    losses = sum(1 for _ in _iter_jsonl(symbol_dir / "losses" / "events.jsonl"))
    nm_path = symbol_dir / "near_misses" / "events.jsonl"
    nm_total = 0
    nm_by_reason: Counter = Counter()
    nm_resolved_wins = 0
    nm_resolved_total = 0
    for rec in _iter_jsonl(nm_path):
        nm_total += 1
        nm_by_reason[rec.get("reason", "unknown")] += 1
        if rec.get("resolved"):
            nm_resolved_total += 1
            if rec.get("outcome") == "win":
                nm_resolved_wins += 1
    return {
        "losses": losses,
        "near_misses": nm_total,
        "near_miss_by_reason": dict(nm_by_reason),
        "near_miss_resolved": nm_resolved_total,
        "near_miss_resolved_wins": nm_resolved_wins,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _hr(char: str = "=", width: int = 80) -> str:
    return char * width


def _fmt_state(state: dict | None) -> list[str]:
    if not state:
        return ["state.json: not found"]
    rm = state.get("risk_manager", {}) or {}
    plg = state.get("post_loss_guard", {}) or {}
    pm = state.get("position_monitor", {}) or {}
    ents = pm.get("entry_ctx") or {}
    exc = pm.get("excursion") or {}
    open_tickets = sorted(set(ents) | set(exc))
    lines = [
        f"state.json saved_at  : {state.get('saved_at', 'unknown')}",
        f"risk_manager         : day={rm.get('day')} day_pnl=${rm.get('day_pnl', 0):.2f} "
        f"day_open_bal=${rm.get('day_open_balance', 0):.2f} halted={rm.get('halted_today')}",
        f"post_loss_guard      : losses={plg.get('consecutive_losses', 0)} "
        f"halt={plg.get('session_halted', False)} "
        f"size_mult={plg.get('size_multiplier', 1.0):.2f}",
        f"open tickets         : {open_tickets if open_tickets else 'none'}",
    ]
    for t in open_tickets:
        ctx = ents.get(str(t)) or ents.get(t) or {}
        ex = exc.get(str(t)) or exc.get(t) or {}
        bits = []
        if ctx:
            soft = ctx.get("soft_stop")
            soft_str = f"{soft:.5f}" if isinstance(soft, (int, float)) else "—"
            bits.append(f"entry={ctx.get('entry', '—')} soft_sl={soft_str} "
                        f"inferred={ctx.get('inferred', False)}")
        if ex:
            bits.append(f"last_price={ex.get('last_price', '—')} "
                        f"profit=${ex.get('last_profit', 0):.2f} "
                        f"mae={ex.get('mae_pips', 0):.0f}p mfe={ex.get('mfe_pips', 0):.0f}p")
        lines.append(f"  └─ #{t}: " + " | ".join(bits) if bits else f"  └─ #{t}: (no detail)")
    return lines


def render_symbol(stats: SymbolStats, symbol_dir: Path | None) -> str:
    out: list[str] = []
    out.append(f"▌ {stats.symbol}")
    out.append(_hr("-"))
    if stats.log_files_seen:
        out.append(f"Log files parsed     : {', '.join(stats.log_files_seen)}")
    else:
        out.append("Log files parsed     : (none — symbol not deployed or out of window)")

    if stats.last_heartbeat:
        hb = stats.last_heartbeat
        out.append(
            f"Last heartbeat       : balance=${hb['balance']:.2f} "
            f"equity=${hb['equity']:.2f} open_positions={hb['open_positions']}"
        )

    state = stats.state
    if state:
        out.extend(_fmt_state(state))

    out.append("")
    out.append("─ Window activity ─")
    out.append(f"  Signals              : {stats.signals}")
    out.append(f"  Orders rejected      : {stats.order_rejected}")
    out.append(f"  Trades opened        : {stats.trades_opened}")
    if stats.closed_total:
        out.append(
            f"  Trades closed        : {stats.closed_total} "
            f"(wins {stats.closed_wins}, losses {stats.closed_total - stats.closed_wins}) "
            f"| net ${stats.closed_pnl_usd:+.2f} ({stats.closed_pnl_pips:+.0f}p) "
            f"| expectancy {stats.expectancy_r:+.2f}R"
        )
        for cause, n in stats.trades_closed_by_cause.most_common():
            out.append(f"    · {cause}: {n}")
    else:
        out.append("  Trades closed        : 0")
    out.append(f"  Breakeven moves      : {stats.breakeven_moves}")
    out.append(f"  Partial scale-outs   : {stats.partials}")
    if stats.adopted:
        out.append(f"  Positions adopted    : {len(stats.adopted)} "
                   f"(tickets {', '.join(a['ticket'] for a in stats.adopted)})")
    if stats.restored:
        out.append(f"  Positions restored   : {len(stats.restored)} "
                   f"(tickets {', '.join(a['ticket'] for a in stats.restored)})")
    if stats.soft_armed:
        out.append(f"  Soft-SL armed (inferred): {len(stats.soft_armed)}")
    if stats.breached:
        out.append(f"  ⚠ Soft-SL pre-breached at restart: {len(stats.breached)} "
                   "(closed on next tick)")
    out.append(f"  Ladders emitted      : {stats.ladders_emitted}"
               f" (unknown/adopted: {stats.ladder_unknown})")
    out.append(f"  H4 closes — no setup : {stats.h4_no_setup}")
    if stats.near_miss_total:
        out.append(f"  Near-misses          : {stats.near_miss_total}")
        for reason, n in stats.near_misses_by_reason.most_common():
            out.append(f"    · {reason}: {n}")

    if symbol_dir is not None:
        out.append("")
        out.append("─ Cumulative (all-time vault) ─")
        vc = vault_counts(symbol_dir)
        out.append(f"  Losses logged        : {vc['losses']}")
        out.append(
            f"  Near-miss events     : {vc['near_misses']} "
            f"(resolved {vc['near_miss_resolved']}, "
            f"would-have-won {vc['near_miss_resolved_wins']})"
        )
        for reason, n in sorted(vc["near_miss_by_reason"].items(),
                                key=lambda kv: -kv[1]):
            out.append(f"    · {reason}: {n}")

        by_source, n_closed, n_with_reach = ladder_reach(symbol_dir)
        if n_closed:
            out.append(
                f"  Ladder closes scored : {n_closed} "
                f"({n_with_reach} reached ≥1 rung beyond TP)"
            )
            out.append("    source        rungs reached reach%  median R")
            for src in sorted(by_source, key=lambda s: -by_source[s]["n"]):
                b = by_source[src]
                rate = (b["reached"] / b["n"] * 100) if b["n"] else 0.0
                med = (f"{statistics.median(b['reached_rs']):+.2f}"
                       if b["reached_rs"] else "—")
                out.append(
                    f"    {src:<13} {b['n']:>5} {b['reached']:>7} "
                    f"{rate:>5.0f}% {med:>9}"
                )
        else:
            out.append("  Ladder closes scored : 0 (no closed trades yet)")

    out.append("")
    return "\n".join(out)


def render_header(symbols: list[str], days: list[date], log_dir: Path) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    window = (f"{days[0].isoformat()} → {days[-1].isoformat()}"
              if len(days) > 1 else days[0].isoformat())
    return "\n".join([
        _hr("="),
        "TRADING AGENT — DAILY SUMMARY",
        f"Window      : {window} ({len(days)} day{'s' if len(days) != 1 else ''}, UTC)",
        f"Symbols     : {', '.join(symbols)}",
        f"Log root    : {log_dir}",
        f"Generated   : {now}",
        _hr("="),
        "",
    ])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--symbol", "-s", nargs="+", default=list(DEFAULT_SYMBOLS),
        help="Symbols to include (default: %(default)s)",
    )
    p.add_argument(
        "--days", "-d", type=int, default=1,
        help="Number of UTC days back to summarise (default: 1 = today only)",
    )
    p.add_argument(
        "--log-dir", default=None,
        help=f"Vault root (default: {DEFAULT_VAULT_ROOT})",
    )
    p.add_argument(
        "--end-date", default=None,
        help="Anchor day (YYYY-MM-DD UTC). Default: today UTC.",
    )
    p.add_argument(
        "--out", default=None,
        help="Override the output file path. Default: "
             "<log-dir>/summaries/summary_<window>.txt",
    )
    p.add_argument(
        "--no-save", action="store_true",
        help="Do not write the report to a file (stdout only).",
    )
    p.add_argument(
        "--no-stdout", action="store_true",
        help="Suppress stdout (still writes the file unless --no-save).",
    )
    return p.parse_args()


def _default_out_path(root: Path, days: list[date]) -> Path:
    """File destination when ``--out`` is not given.

    Lives next to the per-symbol vault folders so it's easy to find later
    and easy to attach.
    """
    stamp = (days[0].isoformat() if len(days) == 1
             else f"{days[0].isoformat()}_to_{days[-1].isoformat()}")
    return root / "summaries" / f"summary_{stamp}.txt"


def _resolve_days(end: date, n: int) -> list[date]:
    return [end - timedelta(days=i) for i in range(n - 1, -1, -1)]


def main() -> int:
    args = parse_args()
    root = Path(args.log_dir) if args.log_dir else DEFAULT_VAULT_ROOT
    end_day = (datetime.fromisoformat(args.end_date).date()
               if args.end_date else datetime.now(timezone.utc).date())
    days = _resolve_days(end_day, max(1, args.days))
    symbols = [s.strip().upper() for s in args.symbol]

    out = [render_header(symbols, days, root)]
    for symbol in symbols:
        stats = SymbolStats(symbol=symbol)
        symbol_dir = _vault_dir(root, symbol)
        if symbol_dir is not None:
            stats.state = _read_state(symbol_dir)
        for day in days:
            log_path = _log_path(root, symbol, day)
            if log_path is None:
                continue
            parse_log_file(log_path, stats)
        out.append(render_symbol(stats, symbol_dir))

    out.append(_hr("="))
    out.append("NOTE: this report is OBSERVATION-ONLY evidence. Parameter changes")
    out.append("still go through the full validation pipeline (grid → holdout →")
    out.append("walk-forward → cross-pair → sealed). Nothing here moves a gate.")
    out.append(_hr("="))
    report = "\n".join(out)

    saved_to: Path | None = None
    if not args.no_save:
        target = Path(args.out) if args.out else _default_out_path(root, days)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(report + "\n", encoding="utf-8")
            saved_to = target
        except OSError as e:
            print(f"WARN: could not write {target}: {e}", file=sys.stderr)

    if not args.no_stdout:
        print(report)
        if saved_to is not None:
            print(f"\nSaved to: {saved_to}")
    elif saved_to is not None:
        print(saved_to)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
