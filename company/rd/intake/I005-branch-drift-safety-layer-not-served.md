---
id: I005
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: BUG
priority: P0
status: routed
route: engineering
linked_features: []
linked_decisions:
  - D107
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A001/A002)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A001+A002). Fix in flight: parent session merging next-gen -> product."
---

# I005 — Branch drift: the safety layer is not on the branch being served (A001+A002)

## What happened

The entire Sprint-2/2b safety layer (approval queue, kill switches,
risk budget, live executor, watchdog, claim audit) exists only on
`product` (25 platform modules). The Windows VM serves `next-gen`,
which has 8 platform modules, compares the auth token with plain `==`,
and falls OPEN when no token is configured on a non-localhost bind.
The deployed surface is the one WITHOUT the four gates.

## Why it matters

P0: every safety claim the company makes is attached to code that is
not running where the product runs. Weaker auth on the served branch
compounds it.

## Proposed resolution

Treat `product` as the single serving branch. Merge-base with
`next-gen` is `9319804`; `product`'s platform files are pure additions
relative to it, so a reconciliation merge is mechanical.

## Triage decision

- **Classification:** BUG · **Priority:** P0 · **Route:** engineering
- **Reasoning:** reconciliation merge queued. **Fix in flight: the
  parent session is merging next-gen → product** — this item tracks
  it to verified closure (VM serves the merged branch, invariant
  suite green there).
- **Owner from here:** cto

## Closure notes

Open. Closes when the VM serves a branch containing the safety layer
and the P0 invariant suite passes on the serving host.

- **Related decisions:** D107 (audit filing).
- Full audit: `reviews/audits/2026-07-24-full-system-audit.md`.
