---
id: I013
source: ceo
submitter: research_lead
submitted_at: 2026-07-24T04:58:00Z
classification: RESEARCH_IDEA
priority: P3
status: routed
route: research
linked_features: []
linked_decisions:
  - D111
  - D113
linked_experiments:
  - phase_ae_sae_event_specialist
contact: internal (CEO question after Phase AE FAIL, 2026-07-24 session)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-24T04:58:00Z
    by: research_lead
    note: "Filed from the CEO's post-verdict question: was M15 the wrong scale for a precision striker? Parked as a v2 hypothesis, NOT a v1 retune."
  - stage: triaged
    at: 2026-07-24T05:05:00Z
    by: cpo
    note: "Cycle-2 triage (D113): stays PARKED -- research lane, P3, behind the Phase AC follow-ups and behind Sprint 3 on the product side. Gate to un-park is unchanged: a data plan for M5/M1 + actual-vs-consensus surprise data, then a fresh locked pre-registration (D111 stop rule: no v1 retune against the spent panel). No compute before both exist."
---

# I013 — Sae v2 hypothesis: finer-timeframe precision mechanics (post-AE)

## What happened

Phase AE killed Sae v1 (M15 fade/ride bar geometry, fixed 1.5R) with a
uniform FAIL — 28.7% wins where breakeven needs 40%, both mechanics
negative independently (D111). The CEO's post-verdict question: canon
Sae is *precision* — calculated, efficient — so was M15 the wrong
lens? Should a v2 read finer microstructure (M5/M1)?

## Why it is credible

- The failure signature indicts the *predicate* (bar geometry at
  T+15/T+30 predicting direction), not obviously the sampling grid —
  but the study cannot rule out that a genuinely different
  specification has an edge. AE4 proved the chassis is clean: an
  event striker integrates with zero squad-chemistry damage
  (max incumbent delta +0.001), so a v2 starts from a working seam.
- Candidate v2 ingredients (each a real difference from v1, not a
  retune): M5/M1 microstructure reads; surprise-z gating on
  actual-vs-consensus release values (the Phase AE.2 slot reserved in
  the original protocol); spread-aware brackets instead of fixed
  1.5R; possibly limit-style entries into the post-spike vacuum.

## Constraints (from the D111 stop rules)

1. **Not a v1 retune.** The v1 fade/ride thresholds and 1.5R bracket
   may not be re-evaluated against the spent §11.17 panel. A v2 must
   be a materially different hypothesis with a fresh pre-registration
   and fresh evaluation budget.
2. **Data gaps to close first:** no M5/M1 parquet cache exists for
   any pair; no actual-vs-consensus data source is chosen (Phase AE
   used release *timestamps* only); an event-window spread/slippage
   model is mandatory at finer timeframes — at NFP the spread is a
   first-order cost, and Phase AE's zero-spread harness already
   flattered v1.
3. **Priority:** P3 — behind the Nagi extended-panel diagnostic,
   Kunigami wiring fix, and SquadEngineMulti follow-ups already in
   the research queue, and behind Sprint 3 on the product side.

## Suggested routing

Research lane. Sits parked until (a) a data plan for M5 + surprise
data exists and (b) the research queue drains the Phase AC follow-ups.
Do not schedule compute before a pre-registration is drafted and
locked.
