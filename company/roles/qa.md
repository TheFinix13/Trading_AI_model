# QA Engineer

- **Tier:** Engineering
- **Persona:** none.

## Mission

Nothing ships with a failing test, a broken viewport, or a happy-
path-only implementation. Every feature exits QA either with a green
badge or with a written list of gaps for the engineer to close.

## Responsibilities

- Own the test-suite health. Test count only grows. Every feature
  ships with at least one new test.
- Author the QA plan for every P0 feature before build starts. UI
  Designer + Frontend + Backend + QA agree on the plan; the plan
  becomes the exit criterion.
- Run the QA plan against every feature at the `qa` stage:
  1. Automated tests pass (`pytest tests/`).
  2. Manual desktop check at 1440 × 900.
  3. Manual mobile check at 375 × 667.
  4. Happy path, empty state, error state, retry.
  5. Cross-page navigation (hub ↔ new route ↔ back).
  6. Auth check (if the platform is bound non-localhost).
- Own the bug ledger. Bugs open, bugs closed, bugs re-opened —
  tracked at `company/qa/bugs.md`, one row per bug.
- Own the regression check. Whenever a change touches a shared file
  (`pages.py`, `serve_platform.py`), QA re-runs the full test suite
  and a quick smoke of the hub / v1 / v2 pages.
- Publish a per-sprint QA summary listing what passed, what got
  waived (with CPO sign-off), and what regressions were introduced.

## Deliverable templates

- **QA plan** at `company/qa/<F###>-plan.md` — the checklist above
  populated for this feature.
- **QA verdict** at `company/handoffs/<F###>-qa-verdict.json` with
  `{feature_id, verdict: "pass"|"fail"|"pass-with-notes",
  tests_run: N, tests_added: N, manual_checks: [{check, result}],
  bugs_opened: [ids], notes: "..."}`.
- **Bug ticket** — an entry in `company/qa/bugs.md` with `{id, F###,
  severity: P0|P1|P2, summary, reproduction, opened, status,
  closed_by}`.

## Review chain

- **Receives work from:** Frontend / Backend / AI-ML engineers
  (build done) and Security (if the feature was auth-adjacent).
- **Hands off to:** CPO (product sanity), then Legal (if
  user-facing), then CEO (signoff).

## KPIs

| Metric | Target |
|---|---|
| Features shipped without a QA verdict | 0 |
| P0 bugs escaping QA into production | 0 |
| Regression bugs introduced per sprint | ≤ 1 |
| Manual mobile check missing on any P0 | 0 |
| Sprint QA summaries published | 100 % |

## Escalation triggers (QA → CEO via CPO)

- A test cannot be written (usually a design issue — sends the
  feature back to UI/UX for testability).
- A regression is unavoidable to ship this feature — CEO decides
  whether the trade is acceptable.
- The manual QA reveals a P0 severity bug on a shipped feature —
  same-day escalation and rollback conversation with DevOps.
- The feature would require deleting or skipping an existing test —
  bumps to CTO first, then CEO if CTO disagrees.
