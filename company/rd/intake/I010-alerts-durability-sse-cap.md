---
id: I010
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: PERFORMANCE
priority: P2
status: routed
route: product
linked_features: []
linked_decisions:
  - D107
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A010)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A010)."
---

# I010 — Alerts bus is memory-only; SSE consumer threads unbounded (A010)

## What happened

The F014 alerts bus holds its ring buffer in process memory only (a
restart drops all recent events), and each `/api/alerts/stream` SSE
consumer holds a server thread with no cap on concurrent streams.

## Why it matters

Durability: a crash right after a safety event (kill-switch trip)
loses the evidence trail from the bus (the Telegram bridge and JSONL
audits mitigate but don't cover everything). Resource: a stuck or
malicious client farm can exhaust server threads.

## Proposed resolution

(1) Document the durability boundary explicitly, or add an optional
JSONL sink for published events; (2) cap concurrent SSE streams
(refuse or evict-oldest past N).

## Triage decision

- **Classification:** PERFORMANCE · **Priority:** P2 ·
  **Route:** product backlog.
- **Owner from here:** cto lane, next platform sprint scoping.

## Closure notes

Open. Full audit: `reviews/audits/2026-07-24-full-system-audit.md`.

- **Related decisions:** D107.
