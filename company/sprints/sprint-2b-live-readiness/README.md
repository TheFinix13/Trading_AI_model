# Sprint 2b — Live Readiness (the D065 successor)

- **Sprint:** sprint-2b-live-readiness
- **Started:** 2026-07-24
- **Target end:** 2026-07-25 (1–2 executor-days per D087 re-baselining)
- **Verdict (in-flight):** _in_progress_
- **Owner (executor):** Sprint 2b Executor (single worker, two feature
  lanes: F017 → F018)
- **Kickoff decisions:** D095 (sellability memo names live-order wiring
  as the biggest product gap), D097 (this sprint's charter).

## Why this sprint exists — the CEO mandate (2026-07-24)

Two direct CEO directives tonight:

> "why not connect to mt5 and my exness and use a demo account"

> "we can't have a black box system... we need to be notified of
> irregular behaviors or problems within any of our systems, including
> the company loop"

This sprint is the **D065 successor charter** that D095 called for.
Sprint 2 (D064/D065) deliberately shipped the four live-order safety
gates as SCAFFOLDING with no caller — the right call then. D095's gap
analysis ranked "live-order wiring" as the gap that blocks a sale the
longest, and prescribed the safety ordering from `escalation.md` §5:

**demo wiring → shadow track record → real-broker only after pen test
(Sprint 5) + external legal signoff.**

Sprint 2b executes step one of that ordering and nothing beyond it.
The D065 scaffolding-only invariant is being deliberately and
narrowly superseded **for DEMO accounts only**: the four gates get
exactly one caller (`live_executor.execute_approved`), that caller is
default-disabled, and it structurally cannot talk to a non-demo
server (fail-closed allowlist + `demo_only = true` acknowledgement).
Real-broker connections remain a hard NO per `escalation.md` §5.

## Scope (in) — two P0 features

| ID | Title | Lane |
|---|---|---|
| F017 | Ops Watchdog — check registry + alert publisher + `/hq` strip + cron runner | No-black-boxes directive |
| F018 | Demo-order executor — the four gates get their caller, DEMO-only | D065-successor step 1 |

Build order: F017 → F018 (watchdog first so the executor is born
observable).

## Scope (out)

- **Squad → approval_queue submission wiring.** The squad proposing
  orders into `/api/approvals/submit` is next-gen-lane territory plus
  a future integration decision. Sprint 2b's executor consumes
  ALREADY-APPROVED entries only.
- Any change to `agent/live/*`, `agent/risk/*`, `agent/squad/*`,
  `scripts/run_squad_live.py`, `scripts/run_live.py` (invariant
  carried forward from Sprint 2 — end-of-sprint zero-diff check
  against `c56e561`).
- Real (non-demo) broker connections — hard NO, `escalation.md` §5.
- Auto-retry of failed orders, position management loops, anything
  that acts without a fresh human approval.
- Multi-user, packaging, paid services (later sprints per D095).

## Hard invariants (P0)

1. **Zero diffs** on `agent/live agent/risk agent/squad
   scripts/run_squad_live.py scripts/run_live.py` vs `c56e561`.
2. `tests/security/test_live_mode_off_invariant.py` passes
   **unweakened** — extended with executor cases, never edited down.
   Every F018 pathway composes through `can_send_live_order` (all
   four gates), re-checked immediately before send.
3. **DEMO-ONLY guard in code, not docs:** server-name allowlist
   (`[live_executor] allowed_server_patterns`, default
   `["*Trial*", "*Demo*", "*demo*"]`, fail-closed) AND a required
   `demo_only = true` config acknowledgement (refuse if false or
   absent).
4. No real credentials in code/config/tests. The designated demo
   account ("V2 Platform", login 436983644, Exness-MT5Trial9) may be
   referenced in RUNBOOK docs; its password lives only in the F006
   keyring path.
5. MetaTrader5 is Windows-only: all MT5 interaction goes through an
   injectable adapter seam; tests mock it; nothing in the suite
   requires a live MT5.
6. Ledger discipline: additive edits, JSON↔MD ids 1:1, explicit-path
   staging, small commits, push `origin product` per logical commit.

## Exit gates

- F017 + F018 shipped with specs on tape BEFORE build (review-chain
  fast-path as solo executor; specs land first).
- ≥35 F017 tests, ≥45 F018 tests (incl. P0 invariant extensions).
- Full suite green (baseline 1540 + 1 env-skip), claim audit green.
- Legal reviews on tape: `watchdog_alert` event-type whitelist
  expansion (F014 rolling constraint) + executor warning copy.
- `docs/RUNBOOK_demo_launch.md` gains the V2-Platform demo-account
  connection + executor ceremony + kill-switch drill section.
- REPORT.md post-mortem; sprint verdict + KPIs in company_state.json;
  ai_context.md bumped v0.46 → v0.47.

## See also

- `../../strategy/sellability-gaps.md` — gap 8 (live-order wiring) and
  gap 4 (shadow clock) are this sprint's reason to exist.
- `../../ledger/decisions_log.md` — D064/D065 (the invariant being
  superseded for demo only), D080 (Sprint 2 close), D095 (ordering),
  D097+ (this sprint).
- `../../protocols/escalation.md` §5 — real-broker connections remain
  a hard NO on this repo.
