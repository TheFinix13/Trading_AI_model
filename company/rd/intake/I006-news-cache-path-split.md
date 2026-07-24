---
id: I006
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
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A003)
resolved_at: null
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A003)."
---

# I006 — News-cache writer is CWD-relative; watchdog reader is absolute (A003)

## What happened

The news-cache writer resolves its output path relative to the
current working directory, while the watchdog `calendar_feed` check
reads an absolute path under the config dir. Running the writer from
any other cwd makes the watchdog age out (or never see) a fresh cache.

## Why it matters

A silent split: the calendar looks stale/absent while the writer
believes it is succeeding — news-window logic then runs on stale data
without any alarm.

## Proposed resolution

Writer resolves through the same absolute config-dir seam the reader
uses.

## Triage decision

- **Classification:** BUG · **Priority:** P1 · **Route:** next-gen
  fix lane — the affected code lives on `next-gen`; NOT touched from
  the product-hardening session (filing only).
- **Owner from here:** next-gen fix session

## Closure notes

Open. Full audit: `reviews/audits/2026-07-24-full-system-audit.md`.

- **Related decisions:** D107.
