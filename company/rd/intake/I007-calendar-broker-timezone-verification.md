---
id: I007
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: BUG
priority: P1
status: resolved
route: engineering
linked_features: []
linked_decisions:
  - D107
  - D113
  - D125
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A004)
resolved_at: 2026-07-24T15:45:00Z
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A004). Verify-then-fix."
  - stage: re-affirmed
    at: 2026-07-24T04:10:00Z
    by: cpo
    note: "Cycle-2 triage (D113): P1 re-affirmed, route updated -- the next-gen fix lane is retired (D110), the calendar code now lives on product. Still VERIFY-THEN-FIX: needs one live high-impact event captured on the VM (FF timestamp vs broker server time vs UTC side by side) before any offset patch. NOT Sprint 3 scope (Sprint 3 is read-only over existing artifacts; this needs a live capture during VM operation). Rides the post-cutover shadow window; first qualifying event is FOMC Jul 28-29."
  - stage: resolved
    at: 2026-07-24T15:45:00Z
    by: engineering
    note: "VERIFIED CLEAN, no fix needed (D125) -- didn't wait for FOMC. Feed side: two known-schedule anchors in the live weekly feed (Unemployment Claims 08:30 ET = 12:30 UTC -> feed row `12:30pm`; Flash PMI 09:45 ET = 13:45 UTC -> feed row `1:45pm`) prove FF publishes GMT/UTC, matching the parser. Broker side: VM screenshot shows the Exness Trial server clock at UTC+0 and H4 closes on the UTC grid, so the broker layer's epoch-as-UTC conversion is correct for this broker. Anchors pinned in tests/test_news_calendar_tz_anchors.py; full note reviews/audits/2026-07-24-a004-calendar-tz-verification.md. Residual (documented, no intake): a future non-UTC-server broker would need a connect-time clock-skew check."
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
