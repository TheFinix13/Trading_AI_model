---
id: I011
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: BUG
priority: P2
status: resolved
route: product
linked_features:
  - F024
linked_decisions:
  - D107
  - D113
  - D114
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A011)
resolved_at: 2026-07-24T14:15:00Z
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A011)."
  - stage: scoped
    at: 2026-07-24T04:10:00Z
    by: cpo
    note: "Cycle-2 triage (D113): P2 re-affirmed and scoped into Sprint 3 as F024 (D114) -- swap the hand-rolled scalar front-matter parser for yaml.safe_load (PyYAML already a dependency), preserving the never-raise contract. The intake_sla check guards the company loop itself; a mis-parse can silently age a P0. Small, well-bounded, P1-in-sprint."
  - stage: resolved
    at: 2026-07-24T14:15:00Z
    by: cto
    note: "Resolved by F024's ship (D122, Sprint 3, fast path): _parse_front_matter now feeds the fence-delimited block to yaml.safe_load; list-bearing/nested front matter (this very file's history block included) parses correctly; never-raise contract and SLA colour semantics byte-identical; +9 tests incl. a real post-triage I003 regression fixture. Sprint close-out 2026-07-24."
---

# I011 — Watchdog front-matter parser is scalar-only (A011)

## What happened

The watchdog's `intake_sla` check parses intake-file front-matter
with a hand-rolled parser that only understands scalar `key: value`
lines. YAML lists (`linked_features:` blocks) and nested values are
skipped or mis-read, so SLA state derived from those fields can be
wrong.

## Why it matters

The intake SLA check is the company loop's own watchdog — if it
mis-parses priority/status on a list-bearing file, a P0 item can age
without the alarm firing.

## Proposed resolution

PyYAML is already a dependency: split the front-matter block and feed
it to `yaml.safe_load` instead of the hand parser. Keep the na/never-
raise contract.

## Triage decision

- **Classification:** BUG · **Priority:** P2 · **Route:** product
  backlog (small, well-bounded change in `watchdog.py`).
- **Owner from here:** cto lane, next platform sprint scoping.

## Closure notes

Resolved 2026-07-24 by F024 (D122): the `intake_sla` check parses
real YAML front matter now, so a list-bearing P0 can no longer age
past its 4-hour SLA unseen. Full audit:
`reviews/audits/2026-07-24-full-system-audit.md`.

- **Related decisions:** D107, D122.
