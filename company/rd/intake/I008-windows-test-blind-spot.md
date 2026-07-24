---
id: I008
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: PROCESS
priority: P2
status: routed
route: engineering-process
linked_features: []
linked_decisions:
  - D107
  - D113
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A008)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A008)."
  - stage: re-affirmed
    at: 2026-07-24T04:10:00Z
    by: cpo
    note: "Cycle-2 triage (D113): P2 re-affirmed, half-delivered. The mockable-MT5-seam half landed with F018 (Mt5OrderAdapter, D103) -- argument marshalling is now exercised on mac CI via the Fake adapter. The pre-demo-VM-checklist half is open: fold it into the runbook as a preflight section during the 7b.8 cutover (run the full suite + MT5 seam smoke ON the VM before any demo). Process item, not Sprint 3 feature scope."
---

# I008 — Windows/MT5 code paths never tested from the mac dev loop (A008)

## What happened

Every MT5-touching path (`RealMt5OrderAdapter`, broker connection
probes, squad live mt5 feed) is Windows-only, and the dev loop runs
on mac. The first time any of those lines executes for real is on the
VM — typically during a demo.

## Why it matters

The riskiest code (real broker interface) has the least test
coverage. A trivial marshalling bug surfaces at the worst possible
moment.

## Proposed resolution

Two-part: (1) a pre-demo VM checklist — run the full platform suite +
a scripted smoke of each MT5 seam ON THE VM before any demo session;
(2) a mockable MT5 seam so the argument-marshalling layer is at least
exercised in CI on mac.

## Triage decision

- **Classification:** PROCESS · **Priority:** P2 ·
  **Route:** engineering/process.
- **Owner from here:** cto

## Closure notes

Open. Full audit: `reviews/audits/2026-07-24-full-system-audit.md`.

- **Related decisions:** D107. Related: I003 (broker wizard
  non-Windows dead-end — same blind spot, user-facing edge).
