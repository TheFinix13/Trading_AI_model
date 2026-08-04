---
id: I029
source: research
submitter: "research_lead (Phase AF causal re-tune sweep, finance-research-experiments)"
submitted_at: 2026-08-04T12:10:00Z
classification: BUG
priority: P2
status: filed
route: bug
linked_features: []
linked_decisions: [D142]
linked_experiments: ["phase_af_causal_retune"]
contact: null
resolved_at: null
history:
  - stage: filed
    at: 2026-08-04T12:10:00Z
    by: research_lead
    note: "Reo produced ZERO trades in all 11 Phase AF replay cells (8 IS 2019-2023 + 3 validation 2024-2026, three symbols, causal semantics) while publishing ~24k workspace thoughts per cell."
---

# I029 — Reo proposes zero trades across 7.5 years of batch replay

## What happened

Every Phase AF sweep cell (`finance-research-experiments`,
`programs/M001_multi_agent_ensemble/experiments/phase_af_causal_retune/`)
shows `reo_mikage` absent from `trades.jsonl` entirely: 0 trades in
2019–2023 AND 2024–2026, across EURUSD/GBPUSD/USDCAD, at every
impulse threshold from 20 to 50 pips. Meanwhile `workspace_publish`
counts show Reo publishing ~24,173 thoughts per cell — he observes
every bar and never converts.

## Why it matters

Reo is in `roster.proposers`. Either (a) his weapon's fire condition
is unreachable in batch replay (a prepare/index bug of the I024
class), (b) his conditions are so strict they never occur (then he is
dead weight in the ensemble and his slot misleads the dashboard), or
(c) his proposals are generated but rejected upstream 100% of the
time (aggregator/risk gate interaction). Each explanation has a
different fix; none of them is "fine".

## Suggested first checks

1. Grep one cell's `events.jsonl` for Reo proposal/rejection rows —
   distinguishes (c) from (a)/(b) immediately.
2. `inner_signal_at` parity harness on Reo (same proof-of-equivalence
   pattern as `tests/test_a01_isagi_wrap.py`) over a window where his
   weapon SHOULD fire by design.
3. Check whether Reo fired at all in the LIVE tapes (v0.53–v0.56
   weekly bundles) — if he proposed live but not in batch, this is
   an I024-class prepare bug in replay only.
