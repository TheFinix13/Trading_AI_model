---
id: I001
source: post-mortem
submitter: self-observation
submitted_at: 2026-07-22T00:45:00Z
classification: PROCESS
priority: P2
status: resolved
route: process
linked_features: []
linked_decisions:
  - D062
  - D087
linked_experiments: []
contact: null
resolved_at: 2026-07-23T22:45:00Z
history:
  - stage: filed
    at: 2026-07-22T00:45:00Z
    by: user_advocate
    note: "Initial filing during company-evolution session. First intake item — bootstraps the R&D loop with a real signal, not empty theatre."
  - stage: triaged
    at: 2026-07-22T00:45:00Z
    by: user_advocate
    note: "Self-triaged at filing because CPO has not yet run its first Monday drain — parent will confirm at first drain."
  - stage: resolved
    at: 2026-07-23T22:45:00Z
    by: cpo
    note: "First real CPO drain (R&D loop cycle 1). Self-triage confirmed (PROCESS / P2 / process). Resolution adopted per D087: codify the solo-executor compression and adopt executor-days as the sprint planning unit. Closure path (b) from the item's own closure criteria."
---

# I001 — Sprint 1 honest-review flag: solo-executor sprint compression is not portable

## What happened

Sprint 1 (Access) closed COMPLETE on 2026-07-21 in one wall-clock day
against a 13-day target. Sprint 1 REPORT.md, and D061 (CEO acceptance)
+ D062 (CTO retro carry-over) in `company/ledger/decisions_log.md`,
carry a written honesty flag:

> "1 wall-clock day is only possible because the Executor persona
> owns every lane; a real 3-persona split would take longer."

Sprint 0 (Trust Foundation) closed COMPLETE the day before, same
pattern: single Executor persona running Auth Developer + Broker
Integrations + Onboarding UX serially rather than three personas in
parallel.

The pattern *works* — Sprint 0 and Sprint 1 both shipped every P0
feature — but the sprint duration on paper is an artefact of the
single-executor topology, not of a real 3-way parallelism. Any future
planning that projects sprint duration off the 1-day observation will
project wrong.

## Why it matters

- **Planning credibility.** Sprint 2 (Real-Trading) is currently
  planned with the same solo-executor topology (see Sprint 2 kickoff
  D064; Sprint 2 Executor's `.sessions` claim confirms). If Sprint 3
  quotes "1 day per sprint" as a norm, that quote embeds a
  fragile assumption.
- **Persona theater risk.** The company-of-agents protocol
  (`brain-box/agents/company-of-agents-protocol.md` §Anti-patterns)
  warns against "role-play without producing an actual deliverable".
  Solo-executor + persona-labelled handoffs sits on the boundary of
  that anti-pattern — the handoffs are real (25+ JSON artefacts on
  disk per sprint) but they were all authored by one process, so the
  independence-of-review invariant is thinner than the ledger implies.
- **Future scaling.** If real users generate a real intake queue and
  Support / User Advocate / CPO all need parallel bandwidth,
  compressing everything through one executor will bottleneck. The
  question "at what queue depth does solo-executor stop working?"
  needs an answer before we hit it.

## Proposed resolution

Sprint 3 (or the first sprint where genuine role parallelism is
tested) evaluates one of:

1. **Split executor personas for real** — three separate Cursor
   sessions with independent write-scope, following the
   concurrent-session-safety protocol (`.sessions/` claims, no
   `git add -A`, narrower scope wins contested paths). This is the
   test.
2. **Codify current pattern as accepted compression** — publish the
   solo-executor model as the intended shape for small-team
   operation, with an explicit trigger threshold ("switch to
   split-persona above X features / week" or "above Y open intake
   items").

The choice depends on Sprint 2's own duration. Sprint 2 has 6 P0
features (F009-F014) vs Sprint 0/1's 5 and 3 respectively; if it
still runs 1 day, evidence points at (2). If it takes 3+ days,
evidence points at (1).

## Notes for triage

Classification is `PROCESS`, not `BUG` or `FEATURE-REQUEST` — this
is company-shape, not product-shape. Route is `process` accordingly
(new route type introduced with this intake; see
`rd-loop.md` §4 for the taxonomy — process is a documented but
low-frequency route).

Priority P2 because the current pattern is producing complete
sprints — there is no immediate harm. Escalates to P1 the moment
Sprint 2 misses its target or an intake queue backs up past 20
items.

Ties to D062 (CTO retro carry-overs) and, transitively, to the
Sprint 1 REPORT flag. Any measurement here piggybacks on Sprint 2's
own duration + intake-queue-depth observations.

## Triage decision

- **Classification:** `PROCESS`
- **Priority:** `P2`
- **Route:** `process`
- **Reasoning:** Company-shape observation, not product-shape. No
  user actively harmed. Ties to an already-logged retro flag (D062).
  Triggers a Sprint-3 revisit conditional on Sprint 2's observed
  duration.
- **Owner from here:** `cpo` (owns sprint topology decisions)
- **Linked feature spec (if any):** none
- **Linked experiment pre-registration (if any):** none — the
  measurement is Sprint 2's own duration, not a pre-registered study.

## Resolution (CPO, 2026-07-23 — D087)

The item's own decision fork asked: split executors for real, or
codify the compression? The evidence since filing points at (2),
codify:

- **Sprint 2 (Real-Trading)** carried 6 P0 features (vs Sprint 0/1's
  5 and 3) and still closed COMPLETE in 1 wall-clock day
  (2026-07-21 → 2026-07-22, D080). The item's own pre-declared
  test — "if Sprint 2 still runs 1 day, evidence points at (2)" —
  resolved in favour of codification.
- **The Company Evolution session** (2026-07-22, D081–D086) ran the
  same solo-executor topology across CEO/CPO/CTO/Legal lanes and
  landed 2 protocols + 2 role activations + charter elevation in one
  session, again without a missed deliverable.

**Adopted resolution — "executor-days" as the sprint planning unit.**
The honest finding is that one Executor owning every persona lane
compresses a 13-persona-day sprint into ~1 wall-clock day. Future
sprint `day_target`s are re-baselined in executor-days: plan 1–2
executor-days per sprint of Sprint-0/1/2 shape, OR staff genuinely
parallel sub-executors where file-scopes allow (per
concurrent-session-safety `.sessions/` claims), in which case
persona-day targets apply to each lane independently.

The persona-theater caveat stays on-record: handoff JSONs authored
by one process carry a thinner independence-of-review invariant than
the ledger implies. The mitigation is the existing artefact
discipline (every stage transition on tape, every handoff a JSON,
every claim register-audited) — not a pretence of parallelism.

Escalation trigger retained from the original filing: if the intake
queue backs up past 20 items/week for two consecutive weeks, or a
sprint misses its (re-baselined) executor-day target, this decision
is revisited as a P1.

## Closure notes

- **Outcome:** Resolved via closure path (b) — solo-executor
  compression codified; "executor-days" adopted as the sprint
  planning unit with re-baselined day_targets (D087).
- **Measurement:** Sprint 2 duration (1 wall-clock day for 6 P0
  features, D080) — the item's own pre-declared discriminator.
- **User notified:** n/a (self-observation, no external submitter)
- **Related decisions:** D062, D080, D087.
