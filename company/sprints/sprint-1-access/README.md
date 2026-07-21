# Sprint 1 — Access

- **Sprint:** sprint-1-access
- **Started:** 2026-07-21
- **Target end:** ~2026-08-04 (11–13 day honest-review window)
- **Verdict (in-flight):** _in_progress_
- **Owner (executor):** Sprint 1 Executor (single worker, three internal
  lane-personas per D050 — Auth Developer, Broker Integrations,
  Onboarding UX)
- **Kickoff decisions:** D050 (lane split), D051 (Finance stays parked
  until first-spend moment), D052 (single-user auth scope), D047
  (retro amendments — §3.5 / §4.2 / §5.5 / §6.3), D048 (mandatory
  security tests for auth-adjacent features).

## Goal

Turn the trust-only Sprint 0 platform into a **usable installation**:
one user, one install, credentials in the OS keychain, MT5 broker
connection wizard, first-time setup flow. Zero real money moves; every
new surface is behind an install-scoped token on non-localhost binds.

## In scope — P0 features

| ID | Title | Lane |
|---|---|---|
| F006 | Encrypted credential storage + install-scoped auth | Auth Developer |
| F007 | MT5 broker connection wizard | Broker Integrations |
| F008 | First-time setup / onboarding flow | Onboarding UX |

Sprint 0's F006 backlog stub ("User accounts") is **replaced** by the
D052 scope: single-user install, no signup / login / password reset,
no multi-tenant story. Multi-user auth returns as a Sprint 5+
(Compliance) concern.

## Out of scope

- Real user accounts / multi-tenancy (deferred to Sprint 5).
- Real broker orders (Sprint 5 gated by pen test).
- Public deploy / DevOps activation (deferred until a paying user).
- Any new SaaS purchase (Finance stays parked per D051; a shopping
  list triggers activation).

## Sprint charter (day plan is soft — honest wall-clock target 11–13
days if run at multi-day human cadence; a single-session executor
compresses to hours, matching Sprint 0's pattern)

| Day | Milestone |
|---|---|
| 1 | Retro amendments land (§3.5, §4.2, §5.5, §6.3) + claim register seeded. Sprint 1 opened in ledger. |
| 2 | F006 spec locked; research + design in parallel. |
| 3–5 | F006 build: credentials + auth + redaction filter + security tests. |
| 6 | F006 QA + security review + Legal sign-off (secrets-at-rest disclaimer). |
| 6–8 | F007 build: broker_connection.py + BROKER_WIZARD_PAGE + security tests. Legal drafts live-broker warning in parallel. |
| 8–10 | F007 QA + security review + Legal sign-off + ship. |
| 9–11 | F008 build: onboarding module + ONBOARDING_PAGE + reset flow. |
| 11–13 | F008 QA + security review + Legal sign-off + ship + REPORT + close-out. |

## Exit gates

- 3 P0 features shipped (F006 → F007 → F008) with all handoffs on tape.
- `tests/security/` populated with per-feature test modules (per D048).
- All new public accessors registered in `company/legal/claim_register.md`.
- Full test suite green (971 + n).
- Ledger `sprints[1].verdict = "COMPLETE"`; HQ dashboard reflects
  3/3 features in ship column.
- Zero commits off `product`. Zero real credentials anywhere. Zero
  spend triggered (or [BLOCKER][SPEND] filed and CEO-ratified).

## Personas active

Same 11 as Sprint 0 **plus** Security (D048 activation). Finance stays
parked per D051. DevOps stays parked (no public deploy this sprint).
Sales / Support parked until later sprints.

## Retro amendments landed at kickoff

Per D047, these four protocol improvements ship in Sprint 1's first
commit before any feature work starts:

1. §3.5 — Shared-primitive-first serialisation (F006 first, per D050
   internal-lane serialisation, plays the F005 role for this sprint).
2. §4.2 — Spec-lock validation at start of build stage.
3. §5.5 — `_BASE_CSS_VERSION` semver tag pinned by tests.
4. §6.3 — Automated Legal claim-register audit (`claim_register.md`
   seeded; automation hook is Sprint 2+).

## See also

- `../sprint-0-trust-foundation/REPORT.md` — the post-mortem that fed
  the retro amendments above.
- `../sprint-0-trust-foundation/BACKLOG.md` — original Sprint 1 sketch
  (superseded by this charter and D052 scope).
- `../../protocols/review-chain.md` — updated with §3.5 / §4.2 / §5.5 /
  §6.3.
- `../../ledger/decisions_log.md` — D045–D052 for kickoff context;
  D053+ for in-sprint decisions.
