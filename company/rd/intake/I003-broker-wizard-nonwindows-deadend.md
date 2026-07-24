---
id: I003
source: dogfood
submitter: user_advocate
submitted_at: 2026-07-23T23:10:00Z
classification: UX
priority: P1
status: routed
route: product
linked_features:
  - F016
  - F019
linked_decisions:
  - D093
  - D113
  - D114
linked_experiments: []
contact: internal (dogfood harness, D092)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-23T23:10:00Z
    by: user_advocate
    note: "Filed from the first dogfood-cast run (scripts/dogfood_personas.py, report dogfood_20260723T230550Z). Surfaced by P002 (cautious first-timer) and P005 (non-technical customer) journeys."
  - stage: triaged
    at: 2026-07-23T23:10:00Z
    by: cpo
    note: "Triaged same-day: UX / P2 / route product. Copy + wizard-flow fix, no research needed."
  - stage: scoped
    at: 2026-07-24T04:10:00Z
    by: cpo
    note: "Cycle-2 triage (D113): promoted P2 -> P1 and scoped into Sprint 3 as F019 (broker-wizard recovery path + missing-broker state chip), bundled with I004's internal-token config-dir resolution while the spec stays small (D114). Rationale: real dogfood-found friction on the first screen a paying customer sees; smallest item in the pool with the clearest churn story."
---

# I003 — Broker wizard dead-ends on non-Windows hosts

## What happened

First dogfood-cast run (D092), personas P002 (cautious first-time
retail trader) and P005 (non-technical customer): on a macOS host,
`POST /api/broker/test-connection` with well-formed credentials
returns, verbatim from `agent/platform/broker_connection.py`:

> "MT5 client is not available on this platform. MT5 runs on Windows
> only."

Two problems the run made concrete:

1. **The message is a dead end.** It states a fact and offers no next
   action. A non-technical user (P005) does not know what "MT5
   client" is, whether this is their fault, or what to do next —
   there is no link, no "run the platform on your Windows machine /
   VM" guidance, no support path.
2. **Onboarding completes silently without a broker.** The wizard's
   `POST /api/onboarding/complete` succeeds regardless, and
   `broker_connected` stays `false` with no follow-up prompt. Ada
   (P002) finishes setup believing she is done; nothing tells her the
   product cannot trade until a broker connects on a supported host.

## Why it matters

- The dev/demo host today is macOS and the deployed VM is Windows, so
  internally we route around this daily — but a customer install has
  no such tribal knowledge. This is the first screen where a paying
  customer would silently churn.
- Compounds I002 (illegible silence): a user who completed onboarding
  without a broker sees a quiet dashboard forever, with no breadcrumb
  back to the actual blocker.

## Proposed resolution

1. Rewrite the non-Windows failure copy to state the constraint AND
   the recovery path (supported hosts, link to setup doc, "you can
   finish setup now and connect a broker later from Settings →
   Broker").
2. Onboarding completion screen (and `/` hub) should carry a visible
   "broker not connected yet" state chip when `broker_connected` is
   false, linking to the wizard.

## Triage decision (CPO, 2026-07-23)

- **Classification:** `UX`
- **Priority:** `P2` — no data loss, but a churn-shaped dead end on
  the first-run path.
- **Route:** `product` — copy + wizard-state work in
  `agent/platform/pages.py` / `broker_connection.py` message surface.
- **Owner from here:** frontend engineer, next product sprint.

## Closure notes

Open. Closes when the failure copy carries a recovery path and the
post-onboarding surfaces expose the missing-broker state.

- **Outcome:** _pending_
- **Measurement (if applicable):** rerun the dogfood cast; P002/P005
  broker journeys should find actionable copy (assertable substring).
- **User notified:** n/a — internal harness finding.
- **Related decisions:** D092 (harness), D093 (this filing).
