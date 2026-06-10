# 2026-06-09: Walk-forward validation overturns single-cell deployment

## TL;DR

- Holdout validation (single 2015-2022 IS / 2023-2025 OOS split) named
  `zone_d1_against / H4 / asia` as the one and only OOS-validated cell.
- Walk-forward (7 rolling 4-yr-IS / 1-yr-OOS windows) shows the
  **Asia-only restriction was selection bias from that single window**.
- The same alpha on H4 across **all sessions** has identical per-trade
  edge, 4× more trades per year, and 3× more OOS-significant windows.
- Router updated: deploy `zone_d1_against / H4 / all` as the primary
  cell. Drop `H4 / asia` (now a redundant subset). H4/Asia coverage
  unchanged in practice — `H4 / all` includes Asia plus London, NY, and
  the overlap.

## Walk-forward summary table

Cells with positive OOS expectancy in 100% of windows:

| Cell | trades/win | Median OOS exp | OOS p≤.05 hit | IS p≤.05 hit |
|---|---|---|---|---|
| **zone_d1_against / H4 / all** | 66 | **+11.34** | **43%** (3/7) | 71% (5/7) |
| zone_d1_against / H4 / asia | 15 | +11.36 | 14% (1/7) | 71% (5/7) |
| zone / H4 / all | 99 | +8.52 | 14% (1/7) | 57% (4/7) |

86% of windows positive:

| Cell | trades/win | Median OOS exp | OOS p≤.05 hit |
|---|---|---|---|
| zone / D1 / all | 31 | +14.43 | 0% |
| zone / D1 / asia | 31 | +14.43 | 0% |
| zone / H4 / asia | 21 | +8.44 | 14% |
| zone / H4 / ny | 33 | +7.61 | 14% |

71% positive (candidate territory):

| Cell | trades/win | Median OOS exp |
|---|---|---|
| zone_d1_against / D1 / all | 30 | +6.90 |
| zone_d1_against / H1 / all | 79 | +0.61 (too thin) |
| zone / M15 / london_ny_overlap | 56 | +3.18 |

## Why per-window OOS p ≤ 0.05 isn't the right gate

A single year of OOS trading for an H4-Asia cell gives ~10-17 trades.
Even a real +11/trade edge with reasonable variance can't reliably hit
p ≤ 0.05 on a 15-trade sample (bootstrap power is low).

So we relied on **consistent positive expectancy across windows** as
the robustness signal — `zone_d1_against/H4/all` shows positive OOS in
7/7 windows, which is the kind of behaviour we want from a real edge.
The 43% per-window OOS-significance rate is gravy.

## What the user asked, and the answer

> "Will the agent be able to trade outside H4/Asia?"

Yes. Post-update the agent trades H4 across London, NY, Asia, overlap
— ~66 trades/year. Asia-only deployment was an artifact of the single
2023-2025 OOS window, not a real session-specific edge.

> "Will it capture moves on other days when big opportunities arise?"

It will trade any H4 candle close that touches a daily zone counter to
D1 trend. That can happen on any session, any day of the week.

> "Considering Asia is sideways, does it ever trend?"

Irrelevant — we're no longer restricted to Asia. The edge is the D1
counter-trend zone touch, not the session.

> "Will the agent learn more outside this?"

`zone_d1_against` generalizes across TFs (D1, H4 confirmed; H1 thin).
Future research directions:

1. **D1 cell** is the next candidate to promote (71% positive OOS, +6.90
   median exp). Needs ~2 more years of OOS evidence to clear the
   IS-BH-consistency gate.
2. **Cross-TF portfolio** of H4/all + D1/all would diversify trade
   timing without adding correlation risk (zones are on different TFs).
3. **More market regimes** — EURUSD-only is one symbol. Repeating the
   walk-forward on GBPUSD / USDJPY / XAUUSD would either confirm the
   edge is general (a market-structure phenomenon) or symbol-specific
   (might indicate noise).

## Changes shipped this session

- `agent/alphas/zone_routing.py` — router now deploys `H4/all` instead
  of `H4/asia`. `CANDIDATE_CELLS` updated to track `D1/all`.
- `tests/test_zone_routing.py` — contract test redesigned to validate
  walk-forward gates (IS-BH-pass-rate, OOS-significance-rate, median
  OOS expectancy, average sample size) instead of single-window p-values.
- `scripts/run_walk_forward.py` — refactored IS path to filter
  pre-computed full-series trades instead of re-running `run_grid`
  per window (~10× faster), and added disk caching for the alpha walks
  via `.cache/walk_forward_trades.pkl`.
- `scripts/analyze_walk_forward.py` — new script that surfaces cells
  by positive-OOS-expectancy stability from the JSON dump.
- `docs/reviews/walk_forward_raw.json` — full per-window evidence for
  every cell, used by `analyze_walk_forward.py`.
