"""Causal HTF demand/supply *draws* for the modular alpha layer (Phase B/C).

The live loop feeds the reaction engine the nearest fresh higher-timeframe zone
price is being pulled toward (a supply band *above* for a long, a demand band
*below* for a short) as the take-profit **draw**. The isolated alphas measured in
Phase B never saw those deeper daily draws — so their *value* was untested.

This module reconstructs them **causally** over an H1 series so the alpha backtest
can measure "does targeting the deeper daily draw help?" symmetrically for both
sides:

* Resample H1 → D1/H4 once.
* On a daily cadence, run `HTFAnalyzer` over only the **closed** D1/H4 bars up to
  that point (no look-ahead) — this preserves the deep `d1_zone_lookback_bars`
  window (≈9 months), which a per-chunk warm-up could never supply.
* For every bar, pick the nearest fresh supply above / demand below using *that
  bar's* close, exactly as `HTFContext.nearest_zone_draw` does live.

The result is keyed by bar **time** so it survives the chunk-slicing the alpha
backtest does (chunk indices are local; times are global).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from agent.config import Config
from agent.context.htf_context import HTFAnalyzer
from agent.types import Bar

# (supply_above_price | None, demand_below_price | None)
DrawPair = tuple[float | None, float | None]


def _bars_to_df(bars: list[Bar]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        },
        index=pd.to_datetime([b.time for b in bars], utc=True),
    )


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df.resample(rule, label="left", closed="left").agg(agg).dropna()


def precompute_htf_draws(
    bars: list[Bar],
    cfg: Config,
    *,
    recompute_every: int = 24,
) -> dict[datetime, DrawPair]:
    """Map each bar's time → (nearest fresh supply above, nearest fresh demand
    below), built causally. Empty for short series."""
    n = len(bars)
    out: dict[datetime, DrawPair] = {}
    if n < 240:
        return out

    df = _bars_to_df(bars)
    d1 = _resample(df, "1D")
    h4 = _resample(df, "4h")
    lookback = getattr(cfg.htf, "d1_zone_lookback_bars", 180)
    analyzer = HTFAnalyzer(d1_zone_lookback_bars=lookback)

    last_zones: list = []
    for i in range(n):
        t = bars[i].time
        if i % recompute_every == 0:
            day = pd.Timestamp(t).normalize()
            # Only CLOSED higher-timeframe bars (the in-progress day/4h excluded).
            d1_slice = d1[d1.index < day]
            h4_slice = h4[h4.index <= pd.Timestamp(t) - timedelta(hours=4)]
            if len(d1_slice) >= 20 and len(h4_slice) >= 30:
                try:
                    last_zones = analyzer.analyze(h4_slice, d1_slice).htf_zones
                except Exception:
                    pass  # keep the previous zone set on a transient failure

        price = bars[i].close
        supply = demand = None
        sup_best = dem_best = None
        for z in last_zones:
            if z.mitigated or z.swept:
                continue
            if z.kind == "supply" and z.bottom > price:
                d = z.bottom - price
                if sup_best is None or d < sup_best:
                    sup_best, supply = d, z.bottom
            elif z.kind == "demand" and z.top < price:
                d = price - z.top
                if dem_best is None or d < dem_best:
                    dem_best, demand = d, z.top
        if supply is not None or demand is not None:
            out[t] = (supply, demand)
    return out
