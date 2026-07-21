# Sprint 0 (Trust Foundation) — post-mortem

- **Sprint:** sprint-0-trust-foundation
- **Started:** 2026-07-21 14:00 UTC
- **Actual end:** 2026-07-21 18:00 UTC
- **Target end:** 2026-08-04
- **Verdict:** **COMPLETE**
- **Author:** cpo (Sprint 0 Executor persona)

## Executive summary

Sprint 0 shipped all five P0 features (F001–F005) against the specs
locked at 14:00 UTC. Sprint completed 14 calendar days ahead of the
target end date because the executor persona could run the full
review chain end-to-end in one session; the day-by-day plan in the
sprint charter assumed multi-day human cadence and remains the
right pacing for future sprints where personas are separated across
sessions.

The platform now carries seven public routes (`/`, `/v1`, `/v2`,
`/hq`, `/performance`, `/players[/:id]`, `/research`), each of
which:

- renders correctly at 375 × 667 px (F004);
- ships a friendly skeleton + error + empty-state lifecycle via the
  shared `withStates()` helper (F005);
- carries the appropriate legal disclaimer verbatim from
  `company/legal/disclaimers.md`;
- is backed by a read-only backend module that never writes to the
  agent's live path or the sibling research repo.

## What shipped

| ID | Title | Backend module | New tests | Handoffs |
| --- | --- | --- | --- | --- |
| **F005** | Shared skeleton + friendly-error helper | `agent/platform/pages.py` (helper only) | 19 | 5 |
| **F001** | Public `/performance` route | `agent/platform/performance.py` | 48 (24 module + 16 page + 8 API) | 8 |
| **F002** | Character bio routes `/players/:id` | `agent/platform/players.py` | 70 (29 module + 24 page + 17 API) | 8 |
| **F003** | Public `/research` route (anti-marketing marketing) | `agent/platform/research.py` | 46 (23 module + 17 page + 6 API) | 8 |
| **F004** | Mobile-responsive pass at 375 px | (CSS-only, `_BASE_CSS` diff) | 62 | 3 |

Test-count trajectory:

```
pre-sprint:   100 platform tests
after F005:   119
after F001:   170
after F002:   240
after F003:   286
after F004:   348
```

Delta: **+248 tests** across the sprint. Full platform suite green
at every commit; final `python -m pytest tests/platform/ -q`
returns `348 passed`.

Commits landed on `product`:

```
5940721 platform(research): F003 backend module + CPO-gated publication manifest
35990b6 platform(research): F003 /research page + routes + full review-chain artefacts
6a60dcb sprint-0(F002): /players routes + review-chain artefacts
b6e776e sprint-0(F002): players parser + 10 striker bios + 29 tests
5adffe0 sprint-0(F001): /performance page + route + review-chain artefacts
f488429 sprint-0(F001): performance parser module + 24 tests
a8f0990 sprint-0(F005): shared skeleton + friendly-error helper + Brand copy library
```

(Plus the F004 close-out commit landing after this report is
written.) Every push targeted `product`; zero commits landed on
`main` or `next-gen`.

## What didn't ship

Nothing was cut from the sprint scope. No blockers surfaced to CEO.
Two spec-extension decisions were logged in-place per protocol:

- **D027** *(F002 [SPEC-EXTENSION])* — Reo bio marked
  active-with-caveat rather than fully retired, matching the actual
  agent registry state.
- **D042** *(F003 [SPEC-EXTENSION])* — `serve_platform.make_handler()`
  gained `research_root` + `research_manifest_path` kwargs to
  discover the sibling repo path at runtime.

Both were within the fast-path autonomy bounds (single-module,
non-brand-defining, ≤ 3 modules touched).

## What worked

1. **F005 first as a serialisation anchor.** Landing the shared
   `withStates()` helper before F001/F002/F003 meant every
   subsequent page consumed a fully-tested skeleton / error /
   empty-state contract instead of re-inventing one per feature.
   Copy-paste risk collapsed and the `tests/platform/
   test_pages_shared_states.py` suite became the invariant for
   later features.
2. **Review chain as artefact chain.** Writing the handoff JSON at
   every transition forced each stage to state its output cleanly.
   The chain became self-checking — a missing handoff JSON was a
   visible signal that a stage had been skipped.
3. **Ledger as source of truth.** Because every stage transition
   was recorded on `company_state.json` before the next stage
   started, `/hq` never lied about the current state. The CEO
   watching the dashboard mid-sprint would have seen accurate
   Kanban movement in real time.
4. **Read-only backend invariant.** F001, F002, F003 all wrote
   zero bytes to their upstream data sources (v1 daily logs, v2
   events, roster bios, research repo). This was locked by
   dedicated read-only-invariant tests in every module's suite,
   which caught two would-be write paths during build.
5. **F004 as a horizontal concern, not a phase.** Baking the
   375 px pass into each feature's mocks + build eliminated the
   "retrofit temptation" the CPO explicitly warned against in the
   F004 spec. The residual smoke-test pass at the end took ~15
   minutes and caught two pre-existing gaps (`.nav` not flex-wrap;
   `V1_PAGE` lacking any `@media` block).

## What didn't work

1. **Spec date pins were too aggressive.** The sprint charter's
   day-by-day plan assumed multi-day human cadence; the actual
   executor session compressed to hours. For future sprints
   run under this persona, day counts in the charter should be
   dropped in favour of stage-count checkpoints.
2. **`decisions_log.md` grew fast.** 45 D### entries in a single
   session pushed the log past 500 lines. Suggested Sprint 1
   change: append a per-feature summary block at the end of each
   feature's ship stage so the log stays scannable at the
   feature-summary level (D### entries remain the source of truth
   underneath).
3. **F003 publication manifest under-specified.** The spec named
   E011 / E013 / E014 as minimum verdicts, but those experiments
   never produced canonical `REPORT.md` files (only `REPORT 2.md`
   drift copies). The build stage picked six real canonical
   reports instead, which was the right move but required a
   [SPEC-EXTENSION] entry (D042). Future research-page sprints
   should validate the manifest against the on-disk canonical
   files at spec-lock time.
4. **Legal claim register is manual.** Every public number on
   `/performance` is traced to a code path in the claim register,
   but the trace is currently a human table entry. If a future
   sprint bumps `performance.py` fields, nothing enforces the
   register update. Suggested Sprint 2+ item: automate the trace
   via a `claim_register.py` module that reflects the module's
   public fields into the ledger and CI-fails on drift.

## Retro suggestions for Sprint 1 (Access)

1. **Keep F005-first serialisation.** If Sprint 1 introduces a
   shared onboarding-form primitive (broker credential form,
   first-time setup wizard) it should land as the sprint's
   anchor feature the same way F005 did — before any feature that
   consumes it.
2. **Add a spec-lock validation step.** Before the sprint charter
   is signed off, run a lightweight "spec vs on-disk" check for
   any spec that names external artefacts (research reports,
   config files, backend endpoints). This would have caught the
   E011/E013/E014 drift up-front.
3. **Introduce security stage tests.** Sprint 1 will land the first
   auth surface. Security stage should not be a document-only
   review — it should produce a `tests/security/` module with at
   least one negative test per new auth path (bad token, expired
   token, wrong scope). Add this to `review-chain.md` as a Sprint
   1+ mandatory artefact for any feature that touches an
   auth surface.
4. **Rolling claim-register audit.** The three Legal rolling
   constraints logged in D040 (cherry-pick guardrail, portfolio
   claim ban, new-verdict-kind handshake) should become
   auto-checked at every `/research` publication. Small cron-
   testable job on the ledger.
5. **`_BASE_CSS` as a versioned surface.** F004's fix landed by
   editing `_BASE_CSS` in place. If a future page ships without
   inheriting it, F004's smoke test will still catch it — but a
   version bump / breaking-change note on `_BASE_CSS` would make
   Sprint 1's onboarding forms honour the mobile bar without
   re-litigation.
6. **Split the executor persona.** Sprint 0's autonomy bounds
   worked because Sprint 0 was UI-only and non-money. Sprint 1
   (Access) introduces credentials + broker connections; the
   Sprint 1 Executor persona will need tighter bounds and an
   escalation-first default for anything security-adjacent.

## HQ dashboard state at close

Kanban column occupancy:

- **Spec / Research / Design / Architecture:** 0 features
- **Build / QA / Security / Legal / Signoff:** 0 features
- **Ship:** 5 features (F001, F002, F003, F004, F005)

Blockers panel: empty.

Decisions panel: 45 entries (D001–D045).

Handoffs directory: 42 JSON files across F001–F005 (F001 × 7,
F002 × 8, F003 × 8, F004 × 3, F005 × 5 + 11 legacy pre-Sprint-0
handoffs from the founding pass).

## Next immediate goal

Sprint 1 (Access):

- Broker connection wizard (MT5 credentials, sandbox mode default,
  green-lit-by-Finance-first for any paid API).
- Real user accounts (auth surface, per-user setting isolation).
- First-time setup flow (walk a new user from `/` to their first
  proposal without prior context).

See `docs/BACKLOG.md` for the Sprint 1 spec seeds.
