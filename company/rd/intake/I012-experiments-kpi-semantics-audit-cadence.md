---
id: I012
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: PROCESS
priority: P3
status: routed
route: cpo
linked_features: []
linked_decisions:
  - D107
  - D108
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A012)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A012) + the audit-cadence process proposal (D108, pending CEO ratification)."
  - stage: re-affirmed
    at: 2026-07-24T04:10:00Z
    by: cpo
    note: "Cycle-2 triage (D113): P3 re-affirmed; the KPI semantic call is MADE -- experiments_in_flight counts experiments with an OPEN evaluation panel or scheduled compute; not-started and awaiting-panel states are 'queued', not in flight (current truthful value: 0). The pinned test that locks ledger and derived values to this rule is flagged to the Sprint 3 build executor as housekeeping. Item stays open for that test + the D108 cadence CEO ratification."
---

# I012 — `experiments_in_flight` KPI semantics + recurring-audit cadence (A012 + process)

## What happened

Part 1 (A012): the `/hq` `experiments_in_flight` KPI is inconsistent
— ledger-recorded values and the derived
`_count_experiments_in_flight` disagree on whether `not-started` /
`awaiting-panel` experiment states count as "in flight". The number
shown depends on which code path produced it.

Part 2 (process): tonight's audit found two shipped P1 defects inside
the four-gate pathway (A005, A006) that 1691 green tests did not
catch. Test suites verify what they were shaped to verify; periodic
adversarial reads catch the rest.

## Proposed resolution

Part 1: CPO makes the one-line semantic call (which states count),
then the derivation gets a pinned test so ledger and derived values
cannot drift again.

Part 2: adopt a recurring audit cadence — a full-system audit
**quarterly**, plus one **before any live-wiring milestone** (first
real-broker order, first paid user, first hosted deployment). Logged
as D108, pending CEO ratification.

## Triage decision

- **Classification:** PROCESS (+ POLISH for the KPI half) ·
  **Priority:** P3 · **Route:** cpo.
- **Owner from here:** cpo (KPI semantics call + cadence ratification
  with ceo).

## Closure notes

Open. Full audit: `reviews/audits/2026-07-24-full-system-audit.md`.

- **Related decisions:** D107, D108.
