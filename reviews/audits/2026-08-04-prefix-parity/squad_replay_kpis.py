"""Squad batch-replay KPI harness for the causal-zones re-validation.

Runs ``SquadEngine.run_batch`` with the LIVE roster shape (barou v13,
Sae benched, phi41 aggregator) over cached H4 history for the squad's
three symbols, then reduces ``trades.jsonl`` to per-agent KPIs.

Invoked twice from different checkouts (pre-fix HEAD vs the causal
working tree) to measure the performance delta attributable to removing
the detect_zones / structural-TP lookahead (2026-08-04). The tree it
runs in determines the semantics; everything else (data, window, roster)
is pinned identical.

Usage:
    python squad_replay_kpis.py --label causal --start 2019-01-01 \
        --out-dir /tmp/squad_replay_causal
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from agent.data.source import ParquetCache  # noqa: E402
from agent.data.loader import df_to_bars, filter_bars_by_date  # noqa: E402
from agent.squad.engine import SquadEngine  # noqa: E402
from agent.squad.roster import build_roster  # noqa: E402
from agent.types import Timeframe  # noqa: E402

SYMBOLS = ("EURUSD", "GBPUSD", "USDCAD")
CACHE_ROOT = Path("/Users/the1finix/Documents/GitHub/multi-pair-trading-agent/data/parquet")


def _kpis(trades: list[dict]) -> dict:
    n = len(trades)
    wins = [t for t in trades if (t.get("pnl_pips") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl_pips") or 0) <= 0]
    gross_win = sum(t.get("pnl_pips") or 0 for t in wins)
    gross_loss = -sum(t.get("pnl_pips") or 0 for t in losses)
    rs = [t.get("r_multiple") for t in trades if t.get("r_multiple") is not None]
    return {
        "n_trades": n,
        "win_rate": round(len(wins) / n, 4) if n else None,
        "total_pips": round(sum(t.get("pnl_pips") or 0 for t in trades), 1),
        "gross_win_pips": round(gross_win, 1),
        "gross_loss_pips": round(gross_loss, 1),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "mean_r": round(sum(rs) / len(rs), 4) if rs else None,
        "total_r": round(sum(rs), 2) if rs else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()

    cache = ParquetCache(CACHE_ROOT)
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    bars_by_symbol = {}
    for sym in SYMBOLS:
        bars = df_to_bars(cache.load(sym, Timeframe.H4), Timeframe.H4)
        bars = filter_bars_by_date(bars, start=start)
        bars_by_symbol[sym] = bars
        print(f"{sym}: {len(bars)} bars {bars[0].time:%Y-%m-%d} .. {bars[-1].time:%Y-%m-%d}")

    engine = SquadEngine(
        build_roster(),  # live default: barou_v13=True, sae benched
        args.out_dir,
        aggregator_arm="phi41",
        source_label=f"causal_revalidation:{args.label}",
    )
    stats = engine.run_batch(bars_by_symbol)
    print("run_batch stats:", stats)

    trades = []
    tpath = args.out_dir / "trades.jsonl"
    if tpath.exists():
        for line in tpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                trades.append(json.loads(line))

    by_agent: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_agent[t.get("agent_id") or t.get("agent") or "unknown"].append(t)

    out = {
        "label": args.label,
        "window_start": args.start,
        "run_batch": stats,
        "squad": _kpis(trades),
        "per_agent": {k: _kpis(v) for k, v in sorted(by_agent.items())},
    }
    dest = Path(__file__).parent / f"replay_kpis_{args.label}.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out["squad"], indent=2))
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
