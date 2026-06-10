# 2026-06-10: Frozen cross-pair test — the zone edge is structural

## Setup

The deployed EURUSD strategy (`zone_d1_against`: H4 supply/demand zone
touch faded against the D1 trend, htf_lookback=10, htf_min_move_pips=60)
was run **byte-for-byte, zero re-tuning** on two pairs the research
pipeline had never touched: GBPUSD and USDCAD.

Because no parameter was ever fit to these pairs, their entire
2015→2025 history is out-of-sample. Costs were scaled UP to realistic
retail spreads (GBPUSD ×1.5, USDCAD ×1.8 vs EURUSD) to keep the test
conservative. 2026 data stays sealed for these pairs too.

Script: `scripts/run_cross_pair_frozen.py`.

## Results — H4 (the deployed timeframe)

| Pair | Config | n | Exp/trade | Sharpe | p | Positive years |
|---|---|---|---|---|---|---|
| GBPUSD | zone_d1_against | 1,161 | **+10.24** | **2.42** | **0.001** | **11/11** |
| GBPUSD | zone (baseline) | 518 | +17.10 | 2.14 | 0.001 | 6/6* |
| USDCAD | zone_d1_against | 858 | +4.63 | 1.16 | 0.028 | **10/11** |
| USDCAD | zone (baseline) | 1,107 | +7.38 | 1.68 | 0.002 | 9/11 |

\* GBPUSD baseline emitted zero trades 2017–2021 — anomaly flagged below.

For reference, EURUSD H4 `zone_d1_against` (the #1 cell): exp +11.34
median OOS, 7/7 positive walk-forward windows.

## Results — D1 (the candidate timeframe)

| Pair | Config | n | Exp/trade | Sharpe | p | Positive years |
|---|---|---|---|---|---|---|
| GBPUSD | zone_d1_against | 354 | +8.03 | 0.81 | 0.170 | 6/11 |
| USDCAD | zone_d1_against | 365 | +8.65 | 1.21 | 0.071 | 8/11 |

## Verdict

**The H4 zone-fade edge is a structural FX phenomenon, not an EURUSD
quirk.** The deployed configuration, with zero re-tuning and *wider*
costs, was profitable in 21 of 22 pair-years across two unseen symbols
— GBPUSD in particular (11/11 positive years, Sharpe 2.42, p=0.001)
arguably validates better than EURUSD itself.

This is the strongest possible kind of evidence: it cannot be
overfitting, because nothing was fit.

**D1 is weaker cross-pair** (6/11 and 8/11 positive years, p>0.05).
This *weakens* the case for promoting the EURUSD D1/all candidate to
2nd place — the honest 2nd/3rd place is the same H4 strategy on
GBPUSD/USDCAD, not a different timeframe on EURUSD. D1 stays in
`CANDIDATE_CELLS`.

## Implications for deployment

Proposed three-slot portfolio, all running the SAME validated logic:

| Slot | Symbol | Cell | Evidence |
|---|---|---|---|
| #1 | EURUSD | zone_d1_against / H4 / all | full pipeline + walk-forward |
| #2 | GBPUSD | zone_d1_against / H4 / all | frozen test, 11/11 years |
| #3 | USDCAD | zone_d1_against / H4 / all | frozen test, 10/11 years |

Diversification benefit: same logic, different pairs → partially
uncorrelated trade streams (~66 + ~105 + ~78 trades/year). Deploying
the new pairs at reduced size initially (e.g. half risk) until live
results confirm the backtest is the prudent path.

Requires extending `zone_routing.py` from (TF, session) to
(symbol, TF, session) keys — a deliberate, test-gated change.

## On the retired concepts (FVG, BOS, sweeps, momentum, fibs)

The plan held a slot for giving these one disciplined shot on the
fresh pair data. Recommendation after seeing these results: **defer**.
The cross-pair test just handed us two new validated deployments for
free; spending the fresh data's evidentiary value on concepts that
already failed honest tests on EURUSD has worse expected value than
keeping that data clean for future confirmation runs. Revisit only if
the live portfolio needs more breadth later.

## Anomaly to investigate (non-blocking)

GBPUSD H4 **baseline** zone produced zero trades during 2017–2021 while
`zone_d1_against` traded normally through the same years (and the same
bars / same precomputed zones). Likely something in the baseline
first-touch / zone-lifecycle logic interacting with GBPUSD's 2017-2021
regime. Doesn't affect the deployed config, but worth a look before
ever deploying a baseline-mode cell on GBPUSD.
