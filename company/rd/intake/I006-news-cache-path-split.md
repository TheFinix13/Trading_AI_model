---
id: I006
source: audit
submitter: user_advocate
submitted_at: 2026-07-24T00:30:00Z
classification: BUG
priority: P1
status: resolved
route: next-gen-fix-lane
linked_features: []
linked_decisions:
  - D107
  - D110
  - D113
linked_experiments: []
contact: internal (2026-07-24 full-system audit, A003)
resolved_at: 2026-07-24T04:10:00Z
history:
  - stage: filed
    at: 2026-07-24T00:30:00Z
    by: user_advocate
    note: "Filed from the 2026-07-24 full-system audit (A003)."
  - stage: resolved
    at: 2026-07-24T04:10:00Z
    by: cpo
    note: "Cycle-2 triage (D113): RESOLVED. The next-gen fix session anchored the calendar cache to the repo root / config-dir seam (fix commit be5706e on next-gen) and that commit arrived on product inside the D110 reconciliation merge (c97e8f7). Writer and watchdog calendar_feed reader now resolve through the same absolute anchor; calendar fetch failures additionally became visible on /v2."
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

Resolved 2026-07-24 (D113). Fix commit `be5706e` (repo-root/config-dir
anchor for the calendar cache) landed on `product` via the D110 merge
(`c97e8f7`). Full audit:
`reviews/audits/2026-07-24-full-system-audit.md`.

- **Related decisions:** D107, D110, D113.
