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

## §3.5 Shared-primitive-first serialisation (Sprint 1+ amendment, per D047)

When a sprint introduces a shared UI primitive that multiple features
consume — the way Sprint 0 introduced F005's `withStates()` helper —
that primitive lands **first** in the sprint as its own dedicated
feature. Downstream features in the same sprint assume the primitive
exists in their build stage, cite it in their spec, and consume it
without re-implementing.

Why: Sprint 0 landed `withStates()` before F001/F002/F003 and every
subsequent page consumed a fully-tested skeleton / error / empty-state
contract instead of re-inventing one per feature. Sprint 0 REPORT §What
worked #1 formalises this as a first-class pattern.

Application in Sprint 1: no new shared primitive was flagged, so F006
(the security foundation) plays the equivalent role — F006 lands first
because F007 (broker wizard) and F008 (onboarding) both consume its
`credentials` and `auth` modules.

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
| 7b | `research`* | Research Lead | QA-passed feature that emits a user-behaviour hypothesis | `company/handoffs/<F###>-research-review.json` | **Conditional** — fires when CTO architecture-review flag `research_relevant: true` is set. Applies to features that emit a public claim or a testable hypothesis about user behaviour (e.g. F013 approval-rate). |
| 8 | `legal`* | Legal (with Brand copy-check + Marketing claim-check pre-input) | QA-passed feature | `company/handoffs/<F###>-legal-review.json` | **Conditional** — fires when: (a) route is publicly reachable (no auth token required), (b) any performance / claim data displayed, (c) any user-data collection introduced, (d) any third-party name (Blue Lock characters, broker names) displayed. CTO architecture-review flag `legal_relevant: true` triggers this stage. |
| 9 | `signoff` | CEO (Fiyin via The Ego persona) | All prior stages green; conditional stages either fired-and-passed or explicitly skipped-with-reason | Signature bullet in `company/ledger/decisions_log.md` + `history[]` entry in `company_state.json` | Always for P0; CPO-delegable for P1/P2 |
| 10 | `ship` | DevOps | CEO signoff | Deploy note at `company/handoffs/<F###>-devops-ship.json` + `docs/DEPLOY_LOG.md` entry + healthcheck-green confirmation | Always |

## §4.2 Spec-lock validation (Sprint 1+ amendment, per D047)

At the **start** of the `build` stage, the engineer picking up the
handoff MUST diff the spec against on-disk state before writing any
code:

1. Every module path the spec names must exist as an importable module
   OR be listed in the spec as "new".
2. Every filename / route / config key the spec references must exist
   OR be documented as "new" in the spec.
3. Every invariant the spec claims (e.g. "the existing `auth_token` in
   `platform.toml` is preserved as fallback") must be verified by reading
   the current state of the file.

If any of the above fails, the engineer **halts** and files a
`[SPEC-EXTENSION]` decision in `company/ledger/decisions_log.md`
documenting the mismatch. The CPO amends the spec (or explicitly waives
the mismatch with a written reason). Silent re-invention of the spec
by the build stage is an anti-pattern — Sprint 0's F003 hit this when
the spec named non-existent `REPORT.md` files, and only D042 saved the
build from silently drifting.

The rule fires whenever the mismatch would change **behaviour** or
**public contract**. Cosmetic drift (a rename of an internal helper) is
in-scope for the engineer's autonomy budget.

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
  "research_relevant": true,
  "notes": "Public claim (30d approval-review rate); Research Lead needs hypothesis + measurement pre-registration."
}
```

If the CTO sets `security_relevant: true`, the `security` stage
fires. If the CTO sets `legal_relevant: true`, the `legal` stage
fires. If the CTO sets `research_relevant: true`, the `research`
stage fires. Personas cannot skip these flags — attempts to route
around a `legal_relevant: true` or `research_relevant: true` gate
escalate to CEO (the latter per §6 of `escalation.md`, so a public
claim can never be silently marked `research_relevant: false`).

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

## §5.5 `_BASE_CSS` version tag (Sprint 1+ amendment, per D047)

`agent/platform/pages.py` carries a module-level constant
`_BASE_CSS_VERSION` (e.g. `"1.0.0"`). The tests in
`tests/platform/test_pages_shared_states.py` pin the version — any
change to the string is a deliberate release step.

Bump discipline:

- **Major (`X.0.0`)** — layout, typography, or class-name breaks that
  can shift page rendering. Any downstream page that consumes
  `_BASE_CSS` needs a smoke check.
- **Minor (`x.Y.0`)** — additive tokens or utilities (new CSS variable,
  new class, no removal or rename).
- **Patch (`x.y.Z`)** — bug-fix / typo / a11y correction with no
  visible layout change.

Why: F004 landed by editing `_BASE_CSS` in place. Without a version
constant, a future page that ships new pages without inheriting it
would silently drift. The version pin + smoke tests keep every page
honest.

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

## §6.3 Automated Legal claim-register audit (Sprint 1+ amendment, per D047)

Every public field exposed by any `agent/platform/*.py` module must have
a matching entry in `company/legal/claim_register.md`. A pre-commit hook
(or CI equivalent) walks the platform modules, extracts every field
returned by public accessors, and fails the commit on any unregistered
field.

Bootstrap in Sprint 1's first commit:

- Seed `company/legal/claim_register.md` with F001 (`performance.py`),
  F002 (`players.py`), and F003 (`research.py`) fields.
- Each entry lists: module, public field / accessor, human meaning,
  code path that computes it, disclaimer that must accompany it (if
  any).

New public fields (F006–F008) must be added to the register in the
same commit that introduces them. The Legal review stage confirms.

Why: Sprint 0 REPORT §What didn't work #4 flagged the manual trace as a
Sprint 2+ risk. The register + audit moves that risk to Sprint 1 where
every claim on `/performance`, `/players/:id`, and `/research` is
grounded in a code path.

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
