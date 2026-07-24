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
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A008)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A008)."
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
