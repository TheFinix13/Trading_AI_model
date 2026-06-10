"""Resolve a symbol's near-miss vault: score each hypothetical and report.

Second pass over ``{vault root}/{SYMBOL}/near_misses/events.jsonl`` (written
live by the alpha hook + SignalLoop, see ``agent/journal/vault.py``):

1. Load the symbol's bars from the parquet cache (BarLoader, same idiom as
   ``scripts/run_cross_pair_frozen.py``).
2. For each unresolved event, walk forward from the event bar: did price hit
   the hypothetical SL or TP first? (Both inside one bar = SL, conservative.)
3. Rewrite the JSONL with outcome / pips / R fields filled in.
4. Re-render each newly resolved event's chart with the aftermath bars and
   the outcome annotated (``*_resolved.png`` next to the original snapshot).
5. Print a per-reason summary table (n / win rate / avg R).

The summary is HYPOTHESIS-GENERATING EVIDENCE ONLY. Gates change exclusively
through the validation pipeline (ablation → holdout → walk-forward).

Usage:
    python scripts/resolve_near_misses.py --symbol EURUSD
    python scripts/resolve_near_misses.py --symbol GBPUSD --log-dir D:\\logs
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.journal.chart_snapshot import render_snapshot
from agent.journal.resolver import (
    load_events,
    resolve_event,
    summarize_by_reason,
    write_events,
)
from agent.journal.vault import DEFAULT_VAULT_ROOT
from agent.types import Bar, Timeframe

logging.basicConfig(level=logging.WARNING)

CAVEAT = (
    "CAVEAT: hypothesis-generating evidence ONLY. These are unvalidated\n"
    "counterfactuals (no spread/slippage costs, conservative SL-first\n"
    "tie-break, no out-of-sample discipline). A promising reason tag earns\n"
    "a pre-registered run through the validation pipeline (ablation ->\n"
    "holdout -> walk-forward); gates are NEVER loosened from this table."
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Resolve near-miss vault events for one symbol.")
    p.add_argument("--symbol", "-s", required=True,
                   help="Symbol whose vault to resolve (e.g. EURUSD)")
    p.add_argument("--log-dir", default=None,
                   help="Vault root (default: ~/Documents/TradingAgentLogs)")
    p.add_argument("--after-bars", type=int, default=40,
                   help="Aftermath bars to include in re-rendered charts "
                        "(default: 40)")
    return p.parse_args()


def _load_bars(symbol: str, tf: str, events: list[dict]) -> list[Bar]:
    """Bars spanning all events on ``tf`` with margin on both sides."""
    times = []
    for e in events:
        try:
            ts = datetime.fromisoformat(str(e.get("ts")))
            times.append(ts.replace(tzinfo=ts.tzinfo or timezone.utc))
        except (ValueError, TypeError):
            continue
    if not times:
        return []
    cfg = load_config()
    loader = BarLoader(cache_root=cfg.data_dir)
    timeframe = Timeframe(tf)
    start = min(times) - timedelta(days=60)
    end = max(times) + timedelta(days=60)
    df = loader.get(symbol, timeframe, start, end, refresh=False)
    return df_to_bars(df, timeframe)


def main() -> None:
    args = parse_args()
    symbol = args.symbol.strip().upper()
    root = Path(args.log_dir) if args.log_dir else DEFAULT_VAULT_ROOT
    vault_dir = root / symbol / "near_misses"
    events_path = vault_dir / "events.jsonl"

    events = load_events(events_path)
    if not events:
        print(f"No near-miss events found at {events_path}")
        return

    by_tf: dict[str, list[Bar]] = {}
    resolved_now = 0
    out_events: list[dict] = []
    for evt in events:
        if evt.get("resolved") is True:
            out_events.append(evt)
            continue
        tf = str(evt.get("tf") or "H4")
        if tf not in by_tf:
            tf_events = [e for e in events if str(e.get("tf") or "H4") == tf]
            by_tf[tf] = _load_bars(symbol, tf, tf_events)
        bars = by_tf[tf]
        resolved = resolve_event(evt, bars)
        out_events.append(resolved)
        if resolved.get("resolved"):
            resolved_now += 1
            try:
                ts = datetime.fromisoformat(str(resolved["ts"]))
            except (ValueError, TypeError):
                ts = None
            stamp = ts.strftime("%Y-%m-%d_%H%M") if ts else "unknown"
            reason = str(resolved.get("reason", "unknown"))
            zone = resolved.get("zone") or {}
            render_snapshot(
                bars,
                vault_dir / f"{stamp}_{reason}_resolved.png",
                title=(f"{symbol} {tf} — {reason} @ {resolved['ts']}  "
                       f"[{resolved['outcome'].upper()} "
                       f"{resolved['outcome_r']:+.2f}R]"),
                event_time=ts,
                entry=resolved.get("entry"),
                stop=resolved.get("stop"),
                take_profit=resolved.get("take_profit"),
                zone_top=zone.get("top"),
                zone_bottom=zone.get("bottom"),
                lookahead=args.after_bars,
            )

    write_events(events_path, out_events)

    print(f"\n{symbol} near-miss vault — {len(out_events)} events, "
          f"{resolved_now} newly resolved")
    print(f"{'reason':<18} {'n':>4} {'wins':>5} {'losses':>7} {'open':>5} "
          f"{'win%':>6} {'avg R':>7}")
    print("-" * 58)
    for row in summarize_by_reason(out_events):
        print(f"{row['reason']:<18} {row['n']:>4} {row['wins']:>5} "
              f"{row['losses']:>7} {row['open']:>5} "
              f"{row['win_rate'] * 100:>5.0f}% {row['avg_r']:>+7.2f}")
    print()
    print(CAVEAT)


if __name__ == "__main__":
    main()
