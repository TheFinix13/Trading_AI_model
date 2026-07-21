# Review Chain — canonical feature lifecycle

Every feature that ships passes through the stages below. Each stage
has (a) an **owner role**, (b) an **input artifact** required to enter
the stage, and (c) an **output artifact** produced when the stage
completes. Some stages are **conditional** — see the "when it fires"
column.

## The standard path

```
       spec ──► research ──► design ──► architecture ──► build
                                                            │
                                                            ▼
                                                            qa
                                                            │
                       ┌────────────────────────────────────┤
                       ▼            (conditional)           ▼
                   security*                              legal*
                       │                                     │
                       └─────────────► signoff ◄─────────────┘
                                          │
                                          ▼
                                        ship
```

Stages marked `*` fire only when the conditional-fire criterion below
is met. The signoff stage waits for whichever conditional stages fired
before proceeding.

## Fast path (small-fix path)

For polish, bug-fixes, and copy tweaks that don't change behaviour:

```
   spec ──► design ──► build ──► qa ──► signoff ──► ship
                          (skip research, architecture, security, legal)
```

**Eligibility for fast path** — ALL of these must be true:
- No new module. No changed API. No new user-facing string beyond a
  micro-tweak (≤ 5 words) that Brand has pre-approved.
- No auth / credentials / user-data surface touched.
- No dependency added.
- ≤ 30 lines of diff.

Any fast-path feature that grows beyond the eligibility criteria
during build must be **kicked back to spec** and re-planned on the
standard path.

## Stages

| # | Stage | Owner(s) | Input artifact | Output artifact | Mandatory? |
|---|---|---|---|---|---|
| 1 | `spec` | CPO | User-signal / roadmap slot | `company/sprints/<S>/<F###>-<slug>.md` (feature spec) | Always |
| 2 | `research` | UX Researcher | Feature spec | `company/research/<F###>-user-journey.md` (research memo) | Always for P0/P1; skipped on fast path |
| 3 | `design` | UI Designer (+ Brand for copy) | Research memo | `company/design/<F###>-mocks.md` (annotated mocks, incl. mobile + skeleton + error state) | Always |
| 4 | `architecture` | CTO | Design mocks | `company/handoffs/<F###>-cto-review.json` (green/yellow/red + modules_touched + tests_expected_delta + security_relevant + legal_relevant) | Always for P0/P1; skipped on fast path |
| 5 | `build` | Frontend, Backend, AI/ML (as applicable) | Architecture review (green) | Implementation diff + new tests + `company/handoffs/<F###>-<role>-build.json` (one per contributing engineer) | Always |
| 6 | `qa` | QA | Build + tests | `company/handoffs/<F###>-qa-verdict.json` (pass / pass-with-notes / fail) | Always |
| 7 | `security`* | Security | QA-passed feature | `company/handoffs/<F###>-security-review.json` | **Conditional** — fires when: (a) auth/session/cookie/credentials touched, (b) user-generated content accepted, (c) external API key introduced, (d) broker connection changed, (e) file upload path added. CTO architecture-review flag `security_relevant: true` triggers this stage. |
| 8 | `legal`* | Legal (with Brand copy-check + Marketing claim-check pre-input) | QA-passed feature | `company/handoffs/<F###>-legal-review.json` | **Conditional** — fires when: (a) route is publicly reachable (no auth token required), (b) any performance / claim data displayed, (c) any user-data collection introduced, (d) any third-party name (Blue Lock characters, broker names) displayed. CTO architecture-review flag `legal_relevant: true` triggers this stage. |
| 9 | `signoff` | CEO (Fiyin via The Ego persona) | All prior stages green; conditional stages either fired-and-passed or explicitly skipped-with-reason | Signature bullet in `company/ledger/decisions_log.md` + `history[]` entry in `company_state.json` | Always for P0; CPO-delegable for P1/P2 |
| 10 | `ship` | DevOps | CEO signoff | Deploy note at `company/handoffs/<F###>-devops-ship.json` + `docs/DEPLOY_LOG.md` entry + healthcheck-green confirmation | Always |

## Conditional-stage decision matrix

The CTO's architecture review is the authoritative gate for
conditional stages. Its JSON output includes:

```json
{
  "verdict": "green",
  "modules_touched": ["agent/platform/hq.py", "scripts/serve_platform.py"],
  "tests_expected_delta": 3,
  "security_relevant": false,
  "legal_relevant": true,
  "notes": "Public route with no auth. Legal reviews disclaimer copy."
}
```

If the CTO sets `security_relevant: true`, the `security` stage
fires. If the CTO sets `legal_relevant: true`, the `legal` stage
fires. Personas cannot skip these flags — attempts to route around a
`legal_relevant: true` gate escalate to CEO.

## Ledger discipline

At every stage transition, the owner role:

1. Writes the output artifact.
2. Writes the corresponding handoff JSON blob to
   `company/handoffs/`.
3. Appends a `history[]` entry to the feature's row in
   `company/ledger/company_state.json`:
   ```json
   {"stage": "design", "at": "2026-07-22T10:15:00Z",
    "role": "ui_designer", "deliverable": "company/design/F001-mocks.md",
    "note": "Mocks + mobile + skeleton + error state"}
   ```
4. Sets `current_stage` and `current_owner_role` to the next stage /
   owner.
5. Adds a bullet to `company/ledger/decisions_log.md` referencing the
   feature ID and the transition.

The HQ dashboard reads `current_stage` and `history[]` to render the
Kanban card position and its age-in-stage.

## Blockers

A feature can be marked blocked mid-stage:

```json
"blockers": [
  {"raised_by": "ux_researcher", "raised_at": "2026-07-22T09:00:00Z",
   "summary": "Accessibility conflict — green/red equity curve fails
    colour-blind check", "awaiting_ceo": true}
],
"awaiting_ceo": true
```

Setting `awaiting_ceo: true` surfaces the feature in the HQ blockers
panel. Any persona can raise a blocker; only the CEO (or the role
that raised it) can clear it.

## Rework loop

If a downstream stage rejects an upstream deliverable (QA fails a
build, Legal rejects a claim, CEO rejects at signoff), the feature
returns to the last owner whose deliverable needs revision — not
always all the way back to spec. The stage transition is recorded in
`history[]` with `note: "rework: <reason>"`.

Two rework loops for the same feature triggers a CPO scope-review
conversation with the CEO — usually the spec is under-scoped.

## The "no ensemble, no aggregator" gate

At every stage that produces user-facing copy (design, build, legal),
the Brand Designer performs a lightweight sweep for the banned words
listed in the founding charter. This is not a formal stage — it's a
gate the Brand Designer runs asynchronously and can trigger a rework
loop if violated.

## What the review chain is not

- **Not bureaucracy.** If a stage adds no value, the CPO can advocate
  it be waived — waivers land in the feature's `history[]` with a
  reason. CTO reviews the waiver pattern quarterly; systemic waivers
  become fast-path eligibility criteria.
- **Not sequential-by-default.** `design` and `architecture` can
  overlap; `security` and `legal` are parallel when both fire. Only
  the strict data dependencies are sequential.
- **Not a substitute for judgment.** A green verdict at every stage
  does not mean "must ship" — CEO retains veto at `signoff` and can
  bounce a feature that is technically complete but strategically
  wrong.
