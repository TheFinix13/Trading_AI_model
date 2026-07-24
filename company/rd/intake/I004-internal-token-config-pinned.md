---
id: I004
source: dogfood
submitter: user_advocate
submitted_at: 2026-07-23T23:12:00Z
classification: DX
priority: P3
status: resolved
route: product
linked_features:
  - F016
  - F019
linked_decisions:
  - D094
  - D113
  - D114
linked_experiments: []
contact: internal (dogfood harness, D092)
resolved_at: 2026-07-24T14:15:00Z
history:
  - stage: filed
    at: 2026-07-23T23:12:00Z
    by: user_advocate
    note: "Filed from building the dogfood harness (D092): the harness had to write a temporary platform.toml into the repo root to exercise /api/approvals/submit, because the internal token cannot live anywhere else."
  - stage: triaged
    at: 2026-07-23T23:12:00Z
    by: cpo
    note: "Triaged same-day: DX / P3 / route product. Config-surface unification; fold into the packaging/hosting sprint rather than a standalone fix."
  - stage: scoped
    at: 2026-07-24T04:10:00Z
    by: cpo
    note: "Cycle-2 triage (D113): priority stays P3 but the fix rides EARLY -- bundled into Sprint 3's F019 (D114) because the change is one config-resolution seam (config-dir first, repo-root fallback, fail-closed-when-unset unchanged) and F019 already touches the same wizard/config surface. Closes with F019's ship instead of waiting for the packaging sprint."
  - stage: resolved
    at: 2026-07-24T14:15:00Z
    by: cto
    note: "Resolved by F019's ship (D117, Sprint 3): the internal token now resolves through the config-dir seam (config-dir platform.toml first, repo-root fallback; fail-closed-when-unset unchanged). Sprint close-out 2026-07-24."
---

# I004 — Internal-token config is pinned to the repo root

## What happened

While building the dogfood harness (D092): every piece of platform
state relocates cleanly through the `BLUELOCK_CONFIG_DIR` seam
(credentials, kill switches, risk budget, approvals audit trail) —
**except** the F013 internal token that gates
`POST /api/approvals/submit`. The handler calls
`load_config(REPO_ROOT)` at request time, so the token can only ever
be read from `<repo>/platform.toml`.

Consequence in practice: the harness could isolate 100% of its state
in a temp dir but still had to write a temporary `platform.toml` into
the repo root (and guarantee cleanup) just to exercise the
submit/approve/reject path. Anything packaged or hosted hits the same
wall — the config surface is split between an env-relocatable dir and
one hardcoded repo-root file.

## Why it matters

- **Packaging blocker in miniature.** The sellability memo
  (`company/strategy/sellability-gaps.md`) lists hosting/packaged
  installer as a gap; a config file pinned to the source checkout is
  exactly the kind of assumption that breaks there.
- **Test ergonomics.** Any future integration test of the submit path
  inherits the same write-into-repo-root workaround.

## Proposed resolution

Let `[internal] token` resolve like everything else: check
`BLUELOCK_CONFIG_DIR` (e.g. `<config_dir>/platform.toml` or the
existing credentials store) before falling back to the repo-root
file. Fail-closed behavior when unset stays exactly as is.

## Triage decision (CPO, 2026-07-23)

- **Classification:** `DX`
- **Priority:** `P3` — no user-facing breakage today; single-host
  installs work. Becomes P1 the moment packaging work starts.
- **Route:** `product` — small change in `agent/platform/config.py` +
  `scripts/serve_platform.py`; fold into the packaging sprint.
- **Owner from here:** cto lane, packaging sprint scoping.

## Closure notes

Resolved 2026-07-24 by F019 (D117): the internal token resolves
through the config-dir seam with the repo-root file still honoured
for backwards compat; fail-closed behaviour when unset unchanged.

- **Outcome:** shipped in F019 (Sprint 3, D117)
- **Measurement (if applicable):** dogfood harness runs with zero
  repo-root writes.
- **User notified:** n/a — internal harness finding.
- **Related decisions:** D092 (harness), D094 (this filing).
