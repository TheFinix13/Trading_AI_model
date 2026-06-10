# 2026-06-10: Frozen test on similar pairs — AUDUSD moderate, NZDUSD weak

## Setup

Same protocol as the GBPUSD/USDCAD frozen test
(`docs/reviews/2026-06-10_cross_pair_frozen.md`): the deployed EURUSD
strategy (`zone_d1_against`: H4 supply/demand zone touch faded against
the D1 trend, htf_lookback=10, htf_min_move_pips=60) run
**byte-for-byte, zero re-tuning** on the two remaining
EURUSD-correlated anti-USD majors: AUDUSD and NZDUSD.

No parameter was ever fit to these pairs, so the entire 2015→2025
history is out-of-sample. Costs scaled UP to realistic retail spreads
(AUDUSD ×1.4, NZDUSD ×1.8 vs EURUSD). 2026 data stays sealed.

Script: `scripts/run_cross_pair_frozen.py` (SYMBOLS extended; only the
new pairs were re-run).

## Results — H4 (the deployed timeframe)

| Pair | Config | n | Exp/trade | Sharpe | p | Positive years |
|---|---|---|---|---|---|---|
| AUDUSD | zone_d1_against | 695 | +3.45 | 1.15 | 0.032 | 8/11 |
| AUDUSD | zone (baseline) | 1,034 | +9.54 | 2.81 | 0.001 | **11/11** |
| NZDUSD | zone_d1_against | 681 | +2.47 | 0.85 | 0.096 | 6/11 |
| NZDUSD | zone (baseline) | 1,059 | +5.19 | 1.63 | 0.005 | **10/11** |

For reference, prior frozen results on the deployed config (H4
zone_d1_against): GBPUSD +10.24/trade, 11/11 years; USDCAD +4.63,
10/11. EURUSD reference: +11.34 median OOS.

## Results — D1 (the candidate timeframe)

| Pair | Config | n | Exp/trade | Sharpe | p | Positive years |
|---|---|---|---|---|---|---|
| AUDUSD | zone_d1_against | 301 | +15.01 | 2.54 | 0.002 | 10/11 |
| AUDUSD | zone (baseline) | 293 | +13.18 | 1.72 | 0.025 | 7/11 |
| NZDUSD | zone_d1_against | 292 | +1.38 | 0.26 | 0.369 | 6/11 |
| NZDUSD | zone (baseline) | 308 | +9.87 | 1.38 | 0.059 | 7/11 |

## Verdict (rubric applied to the deployed config: zone_d1_against / H4)

Rubric: STRONG = p≤0.05 AND ≥9/11 positive years AND positive
expectancy; MODERATE = positive expectancy and ≥7/11 years but missing
another gate; WEAK = anything else.

| Pair | Verdict | Reason |
|---|---|---|
| AUDUSD | **MODERATE** | exp +3.45 ✓, p=0.032 ✓, but 8/11 years misses the ≥9/11 gate. Negative years 2018/2020/2022; 2025 (+37.7) rests on only 25 trades. |
| NZDUSD | **WEAK** | exp +2.47 is positive but p=0.096 fails and 6/11 positive years fails both year gates. |

**The deployed edge transfers weakly to the antipodean pairs.** The
cross-pair ranking is now: GBPUSD (11/11) > USDCAD (10/11) > AUDUSD
(8/11) > NZDUSD (6/11) — a clean monotonic decay that tracks neither
correlation with EURUSD nor cost multipliers, suggesting the D1-trend
fade interacts with pair-specific trend character. Neither new pair
earns a deployment slot under the frozen protocol; the proposed
three-slot portfolio (EURUSD/GBPUSD/USDCAD) stands unchanged.

## Notable observation (no action taken)

On both new pairs the **baseline** zone config is much stronger than
the deployed against-D1 variant (AUDUSD 11/11 years p=0.001; NZDUSD
10/11 p=0.005) — the reverse of EURUSD. The same was partially true on
USDCAD (baseline 9/11 with higher expectancy). AUDUSD D1
zone_d1_against also looks strong (10/11, p=0.002). Both are
*observations from a frozen test*, not validated candidates — acting
on them would be selecting the best post-hoc cell, exactly what the
frozen discipline exists to prevent. If pursued, either would need its
own pre-registered walk-forward.

## Data quality

Fresh Dukascopy downloads, 2015-01-01 → 2026-06-09 UTC: AUDUSD
H4 18,421 / D1 3,577 bars; NZDUSD H4 18,418 / D1 3,574 bars. Checks:
no calendar gaps > 3.5 days (i.e. nothing beyond normal weekends +
holidays), zero nulls, zero inverted (high < low) bars on any of the
four series. No anomalies — unlike the GBPUSD baseline zero-trade
window flagged in the prior review, both configs traded every year on
both new pairs.
