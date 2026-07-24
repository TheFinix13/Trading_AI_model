---
id: I011
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: BUG
priority: P2
status: routed
route: product
linked_features: []
linked_decisions:
  - D107
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A011)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A011)."
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

Open. Full audit: `reviews/audits/2026-07-24-full-system-audit.md`.

- **Related decisions:** D107.
