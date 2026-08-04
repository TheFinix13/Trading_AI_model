---
id: I029
source: research
submitter: "research_lead (Phase AF causal re-tune sweep, finance-research-experiments)"
submitted_at: 2026-08-04T12:10:00Z
classification: BUG
priority: P2
status: resolved
route: bug
linked_features: []
linked_decisions: [D142, D147]
linked_experiments: ["phase_af_causal_retune", "phase_ak_reo_ablation"]
contact: null
resolved_at: 2026-08-04T14:50:00Z
history:
  - stage: filed
    at: 2026-08-04T12:10:00Z
    by: research_lead
    note: "Reo produced ZERO trades in all 11 Phase AF replay cells (8 IS 2019-2023 + 3 validation 2024-2026, three symbols, causal semantics) while publishing ~24k workspace thoughts per cell."
  - stage: resolved
    at: 2026-08-04T14:50:00Z
    by: research_lead
    note: "WORKS-AS-DESIGNED, misfiled as striker. agent/squad/agents/a05_reo.py intend() hard-returns None by design: Reo v1 is a per-tick chameleon MIRROR whose only job is to lift a peer thought above Nagi's 0.7 confluence floor (the Phi4.1 predicate-starvation falsifier). Zero proposal rows in proposals_all/rejected confirm nothing is being eaten upstream. Real defects were legibility: (1) he renders as an active striker on /players, (2) the NEL scoreboard drained him for not shooting -- fixed same day (reo_mikage added to NON_PROPOSERS with I029 note). His roster defeat-trigger ('dInfo <= 0 -> Reo is cut') has NEVER been measured -> Phase AK ablation pre-registered to answer whether the assist earns the slot."
---

> **RESOLVED 2026-08-04 — works-as-designed, misfiled as striker.**
> Reo v1's `intend()` returns `None` by design (chameleon mirror
> feeding Nagi's confluence predicate; docstring explicit: "Reo never
> trades in v1"). Zero rows in `proposals_all.jsonl` AND
> `proposals_rejected.jsonl` rules out upstream rejection. Fixes
> shipped: NEL scoreboard exemption (`scripts/league_table.py`).
> Open question moved to research: Phase AK ablation measures whether
> Nagi's fires actually depend on Reo's mirror (roster defeat-trigger
> "ΔInfo ≤ 0 → cut" has never been evaluated).

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
