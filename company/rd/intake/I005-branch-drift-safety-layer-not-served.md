---
id: I005
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: BUG
priority: P0
status: resolved
route: engineering
linked_features: []
linked_decisions:
  - D107
  - D110
  - D113
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A001/A002)
resolved_at: 2026-07-24T04:10:00Z
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A001+A002). Fix in flight: parent session merging next-gen -> product."
  - stage: resolved
    at: 2026-07-24T04:10:00Z
    by: cpo
    note: "Cycle-2 triage (D113): RESOLVED by D110 -- next-gen merged into product at merge commit c97e8f7; product is the single serving branch; next-gen retired as a serving branch. Merged tree verified: 1784 tests + 1 env-skip, P0 live-mode-off invariant 23/23, claim audit green. The VM cutover itself (runbook 7b.8) is an ops step tracked by the runbook and by I002's verification, not by this item -- the drift this item names (safety layer not on the served branch's lineage) is closed at the repo level."
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

Resolved 2026-07-24 (D113). The reconciliation merge (D110, merge
commit `c97e8f7`) made `product` the single serving branch with the
full safety layer; suite 1784 + 1 env-skip, P0 invariant 23/23 on the
merged tree. Remaining VM cutover verification rides runbook 7b.8 and
I002.

- **Related decisions:** D107 (audit filing), D110 (merge), D113
  (cycle-2 triage close).
- Full audit: `reviews/audits/2026-07-24-full-system-audit.md`.
