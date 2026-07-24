---
id: I007
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: BUG
priority: P1
status: routed
route: next-gen-fix-lane
linked_features: []
linked_decisions:
  - D107
  - D113
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A004)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A004). Verify-then-fix."
  - stage: re-affirmed
    at: 2026-07-24T04:10:00Z
    by: cpo
    note: "Cycle-2 triage (D113): P1 re-affirmed, route updated -- the next-gen fix lane is retired (D110), the calendar code now lives on product. Still VERIFY-THEN-FIX: needs one live high-impact event captured on the VM (FF timestamp vs broker server time vs UTC side by side) before any offset patch. NOT Sprint 3 scope (Sprint 3 is read-only over existing artifacts; this needs a live capture during VM operation). Rides the post-cutover shadow window; first qualifying event is FOMC Jul 28-29."
---

# I007 — ForexFactory-calendar vs broker timezone never verified (A004)

## What happened

The FF calendar feed's event timestamps have never been verified
against the broker's server timezone. FF publishes US-Eastern-style
times; MT5 brokers typically run UTC+2/+3 server time. If they
disagree, news-window logic guards the wrong hour.

## Why it matters

A news guard that fires an hour off is worse than none — it creates
false confidence while leaving the actual event window unguarded.

## Proposed resolution

VERIFY-THEN-FIX: capture one known high-impact event, log the FF
timestamp, broker server time, and UTC side by side, and only then
patch the offset handling. Do not patch on assumption.

## Triage decision

- **Classification:** BUG (suspected) · **Priority:** P1 ·
  **Route:** next-gen fix lane — feed code lives on `next-gen`; NOT
  touched from the product-hardening session (filing only).
- **Owner from here:** next-gen fix session

## Closure notes

Open. Full audit: `reviews/audits/2026-07-24-full-system-audit.md`.

- **Related decisions:** D107.
