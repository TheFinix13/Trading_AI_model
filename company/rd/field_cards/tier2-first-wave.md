# Field cards — Tier-2 first wave (D148 / I030)

Created 2026-08-04. One card per instrument BEFORE any study relies on
its semantics (D148 doctrine). Source of the spec tables in
`agent/squad/provenance_pips.py`. Data: research repo
`data/parquet_tier2/` (Dukascopy, H4+D1, banked 2026-08-04; 2023+
SEALED per DATA_LEDGER rule 4).

## Conventions

- "pip" = the unit all stop/KPI math is quoted in (`pip_size_for`).
- "pip value @ min lot" = USD per pip at broker minimum 0.01 lot,
  Exness-style CFD contract sizes (`pip_value_per_min_lot_for`).
  Sentinel R1 uses this for the implied-risk floor; it does NOT touch
  KPI pips.
- Equity context: the v2 demo account is $500. R1's 5% cap = $25.
  The FX-era sandbox default ($100 -> $5 cap) strangles metals at min
  lot; Tier-2 replays declare `equity=500` (the real account), not a
  bigger imaginary one.

## XAUUSD (gold)

- pip size 0.1 ($0.10 price move); pips/unit 10.
- 1 lot = 100 oz; 0.01 lot = 1 oz -> $0.10/pip.
- Typical H4 stop $3–15 = 30–150 pips -> $3–15 min-lot risk: fits the
  $25 cap, would mostly BLOCK at the $100 sandbox ($5 cap).
- Sessions ~23h/5d; liquid US morning; thin daily-rollover hour.

## XAGUSD (silver)

- pip size 0.01; pips/unit 100.
- 1 lot = 5,000 oz; 0.01 lot = 50 oz -> $0.50/pip.
- Typical H4 stop $0.20–0.60 = 20–60 pips -> $10–30 min-lot risk:
  brushes the $25 cap. HONEST constraint — silver at min lot is rich
  for a $500 account; expect R1 to prune the widest-stop proposals.

## USOIL (WTI)

- pip size 0.01 (1 cent); pips/unit 100.
- 1 lot = 1,000 bbl; 0.01 lot = 10 bbl -> $0.10/pip.
- Typical H4 stop $0.60–2.50 = 60–250 pips -> $6–25 min-lot risk.
- Negative-price episode Apr 2020 in the tape — KPI code must not
  assume positive prices; survey report should flag that window.

## USTEC (Nasdaq-100 CFD)

- pip size 1.0 (1 index point); pips/unit 1.
- Assumed contract: 1 lot = $1/point; 0.01 lot = $0.01/point.
  VERIFY against the live broker's USTECm spec before any live wiring.
- Typical H4 stop 50–300 points -> $0.50–3 min-lot risk: trivially
  inside the cap; position sizing (not R1) is the binding rule here.

## Known distortions carried into the first survey (declared)

1. **Zone-grammar pip thresholds are still major-calibrated**: v1
   detector code converts price moves with the 1e-4 pip, so on gold a
   $3 move reads as 30,000 "pips" and impulse/HTF-move floors pass
   trivially — the grammar's price-scale filters are effectively OFF
   on non-FX fields. Survey results are therefore directional only;
   a chartered follow-up on any Tier-2 cell requires per-instrument
   grammar calibration first.
2. Spread/slippage cost model is FX-calibrated (`cost_for` charges
   pips at 1e-4 scale) — costs are UNDERSTATED on Tier-2 tapes.
   Another reason survey verdicts nominate rather than promote.
3. `DEFAULT_MEAN_ATR_PIPS = 30` (regime_fit centering) is FX-H4
   calibrated; regime_fit will tilt high on metals/indices.
