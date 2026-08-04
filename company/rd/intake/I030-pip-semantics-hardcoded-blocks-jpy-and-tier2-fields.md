---
id: I030
source: research
submitter: "research_lead (Phase AL Tier-1 field survey)"
submitted_at: 2026-08-04T16:45:00Z
classification: BUG
priority: P1
status: fix_landed
route: bug
linked_features: []
linked_decisions: [D148, D149]
linked_experiments: ["phase_al_tier1_field_survey", "i030_pip_semantics"]
contact: null
resolved_at: null
history:
  - stage: filed
    at: 2026-08-04T16:45:00Z
    by: research_lead
    note: "USDJPY produced ZERO trades in the Phase AL survey (12,889 bars, 2015-2022): all 14,621 aggregator-winning proposals were blocked by sentinel_R1. Root cause: PIP_SIZE=0.0001 is hardcoded (agent/utils.py) so a 0.50-yen stop computes as 5,000 'pips' and R1's implied-risk check (sl_distance_pips x $0.10 vs 5% equity cap) rejects everything."
  - stage: fix_landed
    at: 2026-08-04T17:30:00Z
    by: platform_engineer
    note: "Squad-path fix shipped: per-symbol pip tables in provenance_pips.py (pip_size_for / pips_per_unit_for / pip_value_per_min_lot_for), threaded through sentinel R1, arm4 R6 risk dollars, paper-broker sl/mae/mfe/pnl/r_multiple, Rin+Barou stop-pips math, and all five proposers' provenance stamps. 10 pinned regression tests (tests/squad/test_instrument_pips.py). Parity PROVEN: 2019 full-roster replay on the 3 majors is byte-identical pre-fix vs post-fix across trades/proposals/rejections/events (each call site keeps its legacy mult-or-div op so majors' float bit patterns are unchanged). Remaining before close: USDJPY re-survey (AL amendment) must show JPY trades flow; v1-derived live path (position sizer) + zone-grammar pip thresholds stay major-calibrated -- FIELD_CARD scope per D148."
---

# I030 — pip semantics hardcoded to 0.0001 blocks JPY pairs and every Tier-2 field

## What happened

Phase AL (research repo, `phase_al_tier1_field_survey`) ran the squad
on AUDUSD/NZDUSD/USDJPY/USDCHF, 2015–2022. Three pairs traded
normally (2,437 trades). USDJPY: agents proposed fine (24k+ proposals
reached the aggregator), conviction contests resolved, and then
**sentinel R1 blocked 100% of the 14,621 winners**.

## Root cause

`agent/utils.py: PIP_SIZE = 0.0001` — a global constant. Agents
compute `stop_pips = (entry - stop) / PIP_SIZE`. On USDJPY (pip =
0.01, price ~150) a normal 0.50-yen stop becomes 5,000 "pips";
R1's implied risk `5000 × $0.10 = $500` blows the 5%-of-equity cap
on every proposal. Nothing is wrong with R1 — it is faithfully
protecting the account from a unit error.

## Blast radius

- USDJPY, all JPY crosses (EURJPY/GBPJPY/AUDJPY/CADJPY/NZDJPY).
- Every Tier-2 instrument with non-1e-4 point semantics: XAUUSD
  (0.1/0.01), XAGUSD, USOIL, indices (1.0 points), BTCUSD.
- Also silently DISTORTS (not blocks) anything reading
  `SANDBOX_PIP_VALUE_PER_MIN_LOT = 0.10` as a universal pip value.

## Fix direction (needs its own engineering pass + pinned tests)

Per-symbol instrument spec (pip size, pip value per lot, point
digits) threaded through: agent stop_pips computation
(`agent/utils.py` to_pips/from_pips call sites), sentinel R1/R6 risk
math, engine KPI pips, league table pips, live position sizer.
FIELD_CARD per instrument (D148) becomes the source of the spec.
Until fixed: JPY/metals/indices replays are INVALID — Phase AL's
USDJPY cell is recorded as `invalid_pip_semantics`, not "no edge".
