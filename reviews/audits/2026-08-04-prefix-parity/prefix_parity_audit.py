"""Prefix-vs-full prepare parity audit (2026-08-04).

Question being settled: after the I024 fix, the LIVE squad re-prepares the
roster on every new bar, so agents compute detector context from history-
so-far only ("prefix" semantics). The validated research replays prepared
once on the ENTIRE series ("full" semantics). The causality audit found
exactly two channels where full-series prepare can see the future:

  1. ``detect_zones``: impulse validity uses a rolling median of candle
     bodies CENTERED on the impulse bar (median_window=200, so +/-100
     bars). Near the series head the forward half is truncated, which can
     admit/reject a zone differently than the full-series run.
  2. ``detect_swings``: a fractal swing needs ``lookback`` (5) bars on
     BOTH sides, so the last 5 bars of a prefix carry no confirmed swings.
     Swings feed only ``_structural_tp`` (take-profit selection) in the
     squad's zone alpha path.

Everything else the five bar-based agents consume (fresh_zones/mitigation
filters, ATR, HTF bias, Bachira's rebel scan, all of Chigiri) is strictly
index-causal and provably identical between the two prepare shapes.

This harness measures how often those two channels actually change a
SIGNAL on real cached H4 data: for each decision bar i in the audit
window, compare ``alpha.signal(ctx_full, i)`` against
``alpha.signal(ctx_prefix_i, i)`` where ``ctx_prefix_i = precompute(
bars[:i+1])`` — the exact live shape. Compared per agent param set:
fired/not-fired, direction, entry, stop, take-profit.

Run (from the product worktree, repo venv):

    python reviews/audits/2026-08-04-prefix-parity/prefix_parity_audit.py

Writes results JSON next to this file.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from agent.alphas.base import AlphaContext  # noqa: E402
from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha  # noqa: E402
from agent.config import load_config  # noqa: E402
from agent.data.source import ParquetCache  # noqa: E402
from agent.data.loader import df_to_bars  # noqa: E402
from agent.rules.engine import precompute  # noqa: E402
from agent.squad.agents.a01_isagi import ISAGI_V1_PARAMS  # noqa: E402
from agent.squad.agents.a02_bachira import BACHIRA_V1_PARAMS  # noqa: E402
from agent.squad.agents.a03_rin import RIN_V1_PARAMS  # noqa: E402
from agent.squad.agents.a07_barou import BAROU_V1_PARAMS, BAROU_V13_PARAMS  # noqa: E402
from agent.types import Timeframe  # noqa: E402

SYMBOLS = ("EURUSD", "GBPUSD", "USDCAD")
# The main checkout carries the full 2014->2026 H4 parquet cache; the
# product worktree only has a partial one. Data content is identical.
CACHE_ROOT = Path("/Users/the1finix/Documents/GitHub/multi-pair-trading-agent/data/parquet")
HISTORY_BARS = 2500      # matches the live feed's startup lookback
DECISION_BARS = 600      # ~4.5 months of H4 decisions per symbol
PRICE_TOL = 1e-9

AGENT_PARAMS = {
    "isagi": ISAGI_V1_PARAMS,
    "bachira": BACHIRA_V1_PARAMS,
    "rin": RIN_V1_PARAMS,
    "barou_v1": BAROU_V1_PARAMS,
    "barou_v13": BAROU_V13_PARAMS,
}


def _sig_tuple(sig):
    if sig is None:
        return None
    return (sig.direction.value, round(sig.entry, 9), round(sig.stop, 9),
            round(sig.take_profit, 9), sig.reason)


def main() -> None:
    cfg = load_config()
    cache = ParquetCache(CACHE_ROOT)
    alphas = {k: SupplyDemandAlpha(cfg=cfg, **p) for k, p in AGENT_PARAMS.items()}

    results: dict = {"config": {"history_bars": HISTORY_BARS,
                                "decision_bars": DECISION_BARS,
                                "symbols": list(SYMBOLS)},
                     "per_symbol": {}}

    for sym in SYMBOLS:
        df = cache.load(sym, Timeframe.H4)
        bars = df_to_bars(df, Timeframe.H4)
        n = HISTORY_BARS + DECISION_BARS
        if len(bars) < n:
            print(f"{sym}: only {len(bars)} bars, skipping")
            continue
        window = bars[-n:]
        t0 = time.time()
        ctx_full = precompute(window, cfg)
        actx_full = AlphaContext(bars=window, ctx=ctx_full, cfg=cfg)
        full_cost = time.time() - t0

        stats = {k: {"full_fired": 0, "prefix_fired": 0, "match": 0,
                     "only_full": [], "only_prefix": [], "field_diff": []}
                 for k in alphas}

        t_start = time.time()
        for i in range(HISTORY_BARS, n):
            prefix = window[:i + 1]
            ctx_prefix = precompute(prefix, cfg)
            actx_prefix = AlphaContext(bars=prefix, ctx=ctx_prefix, cfg=cfg)
            ts = window[i].time.isoformat()
            for name, alpha in alphas.items():
                sf = _sig_tuple(alpha.signal(actx_full, i))
                sp = _sig_tuple(alpha.signal(actx_prefix, i))
                st = stats[name]
                if sf is not None:
                    st["full_fired"] += 1
                if sp is not None:
                    st["prefix_fired"] += 1
                if sf == sp:
                    if sf is not None:
                        st["match"] += 1
                    continue
                if sf is not None and sp is None:
                    st["only_full"].append({"ts": ts, "full": sf})
                elif sf is None and sp is not None:
                    st["only_prefix"].append({"ts": ts, "prefix": sp})
                else:
                    st["field_diff"].append({"ts": ts, "full": sf, "prefix": sp})
        elapsed = time.time() - t_start

        results["per_symbol"][sym] = {
            "n_decisions": DECISION_BARS,
            "precompute_full_seconds": round(full_cost, 3),
            "audit_seconds": round(elapsed, 1),
            "agents": stats,
        }
        print(f"\n=== {sym} ({DECISION_BARS} decision bars, {elapsed:.0f}s) ===")
        for name, st in stats.items():
            div = len(st["only_full"]) + len(st["only_prefix"]) + len(st["field_diff"])
            print(f"  {name:10s} full={st['full_fired']:3d} prefix={st['prefix_fired']:3d} "
                  f"identical={st['match']:3d} divergent={div}"
                  f" (only_full={len(st['only_full'])}, only_prefix={len(st['only_prefix'])},"
                  f" field_diff={len(st['field_diff'])})")

    out = Path(__file__).parent / "results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
