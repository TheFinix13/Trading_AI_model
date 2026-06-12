"""Report extension-ladder reach rates for one symbol.

Reads ``{vault root}/{SYMBOL}/ladders/events.jsonl`` (written live by
``SignalLoop`` — entry-phase opinions plus close-phase records whose rungs are
already scored against the trade's realised MFE) and prints, per rung source
(swing / zone_edge / trendline / fib_ext / daily_level):

    how many rungs were published, how many price actually reached, the reach
    rate, and the median R of the reached rungs.

This is the empirical answer to "are our mechanical 1.5R take-profits leaving
money on the table?" — measured, not eyeballed off winning charts.

The table is HYPOTHESIS-GENERATING EVIDENCE ONLY. A persistent high reach
rate earns ``target_rr`` / ``target_via_structure`` a pre-registered run
through the validation pipeline (grid -> holdout -> walk-forward); the live
TP is NEVER moved from this table.

Usage:
    python scripts/report_target_ladders.py --symbol EURUSD
    python scripts/report_target_ladders.py --symbol GBPUSD --log-dir D:\\logs
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.journal.vault import DEFAULT_VAULT_ROOT

CAVEAT = (
    "CAVEAT: hypothesis-generating evidence ONLY. Reach rates ignore costs\n"
    "and assume the position could have been held to each rung. A promising\n"
    "source earns a pre-registered target_rr / structural-TP study through\n"
    "the validation pipeline; the live TP is never moved from this table."
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Summarize extension-ladder reach rates for one symbol.")
    p.add_argument("--symbol", "-s", required=True,
                   help="Symbol whose ladder vault to report (e.g. EURUSD)")
    p.add_argument("--log-dir", default=None,
                   help="Vault root (default: ~/Documents/TradingAgentLogs)")
    return p.parse_args()


def load_close_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("phase") == "close":
            records.append(rec)
    return records


def main() -> None:
    args = parse_args()
    symbol = args.symbol.strip().upper()
    root = Path(args.log_dir) if args.log_dir else DEFAULT_VAULT_ROOT
    events_path = root / symbol / "ladders" / "events.jsonl"

    closes = load_close_records(events_path)
    if not closes:
        print(f"No resolved (close-phase) ladder events at {events_path}")
        return

    by_source: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "reached": 0, "reached_rs": []})
    trades_with_reach = 0
    for rec in closes:
        any_reached = False
        for rung in rec.get("rungs") or []:
            if "reached" not in rung:
                continue
            src = str(rung.get("source", "unknown"))
            stats = by_source[src]
            stats["n"] += 1
            if rung["reached"]:
                stats["reached"] += 1
                any_reached = True
                try:
                    stats["reached_rs"].append(float(rung["r_multiple"]))
                except (KeyError, TypeError, ValueError):
                    pass
        if any_reached:
            trades_with_reach += 1

    print(f"\n{symbol} extension ladders — {len(closes)} closed trades, "
          f"{trades_with_reach} reached at least one rung beyond TP")
    print(f"{'source':<14} {'rungs':>6} {'reached':>8} {'reach%':>7} "
          f"{'median R (reached)':>19}")
    print("-" * 58)
    for src in sorted(by_source, key=lambda s: -by_source[s]["n"]):
        stats = by_source[src]
        rate = stats["reached"] / stats["n"] if stats["n"] else 0.0
        med = (f"{statistics.median(stats['reached_rs']):+.2f}"
               if stats["reached_rs"] else "—")
        print(f"{src:<14} {stats['n']:>6} {stats['reached']:>8} "
              f"{rate * 100:>6.0f}% {med:>19}")
    print()
    print(CAVEAT)


if __name__ == "__main__":
    main()
