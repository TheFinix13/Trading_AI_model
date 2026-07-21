# Sprint 0 — Trust Foundation

- **Started:** 2026-07-21
- **Target end:** 2026-08-04 (14 days)
- **Sprint owner:** CPO (Noel Noa)
- **CEO signoff at kickoff:** D002 in `../../ledger/decisions_log.md`

## Goal

Ship the five features that turn the multi-pair AI trading prototype
into something a stranger can look at for two minutes and trust.

> "Prospects must be able to open the platform cold, see the
> `/performance` numbers, click into `/players/isagi`, read the
> `/research` page, do the whole tour on a phone, and never once
> stare at a blank screen."
>
> — The CEO's own words, D002

## Features

| ID | Title | Priority | Owner (build) | Reviewers |
|---|---|---|---|---|
| F001 | Public `/performance` route | P0 | Frontend + Backend | UX, UI, Brand, CTO, QA, Legal, CEO |
| F002 | `/players/:id` character bios | P0 | Frontend + Backend (+ AI/ML for stats) | UX, UI, Brand, CTO, QA, Legal, CEO |
| F003 | `/research` verdicts timeline | P0 | Frontend + Backend | UX, UI, Brand, Marketing, CTO, QA, Legal, CEO |
| F004 | Mobile-responsive pass at 375 px | P0 | Frontend | UI, QA, CPO, CEO |
| F005 | Loading skeletons + friendly error states | P0 | Frontend | UI, Brand, QA, CPO, CEO |

All five are P0 by design — losing any one of them means Sprint 0
misses its "trust in two minutes" bar and fails. If a P0 is at risk
mid-sprint (day 7 check-in), the CPO cuts scope inside the feature
rather than dropping the feature entirely.

## Exit gates

Sprint 0 ships successfully when ALL of these are true:

1. **All 5 P0 features have shipped** — meaning: CEO signoff logged
   in `decisions_log.md`, ship-note in
   `../../handoffs/<F###>-devops-ship.json`, and the feature is
   reachable at its route on `scripts/serve_platform.py`.
2. **Test suite is green** — `pytest tests/` passes, count is
   strictly greater than 686 (the pre-sprint baseline). Every
   feature contributed ≥ 1 new test.
3. **HQ dashboard reflects final state** — `/hq` renders and shows
   all 5 features in the `Ship` column, decisions log up to date,
   role grid accurate.
4. **Dogfood pass on real devices** — CEO does the full tour on
   desktop (1440 × 900) and on a phone (375 px viewport, real
   device or Chrome DevTools device mode) with no blocker-severity
   observations.
5. **Backlog is drafted for Sprint 1** — `../../sprints/sprint-1-.../`
   exists with a stub README before Sprint 0 closes.

## Non-goals (do NOT do this sprint)

- User accounts, sign-up, login. That's Sprint 1.
- Multi-broker support beyond MT5. That's Sprint 2.
- Payment infrastructure. Deferred until users exist.
- Any change to `agent/live/`, `agent/squad/engine.py`, or the
  running live squad's behaviour.
- Any change to the strategy — the CEO explicitly wants this sprint
  to change *how the product is seen*, not *how it trades*.
- A public landing page separate from the hub. Marketing landing
  page is Sprint 1.
- A native mobile app. Web at 375 px, that's it.

## Timeline (day-by-day best-guess)

| Day | Date | Focus |
|---|---|---|
| 1 | 2026-07-21 | Founding team pass (this document lands). |
| 2–3 | 22–23 | F001/F002/F003 through research + design (parallel). |
| 4 | 24 | F001/F002/F003 through architecture review (CTO). |
| 5–8 | 25–28 | Build (Frontend + Backend), F001/F002/F003 in parallel. |
| 9 | 29 | Mid-sprint check-in (CPO). F004 mobile pass starts. |
| 10 | 30 | F005 skeletons + error states applied to F001/F002/F003. |
| 11 | 31 | QA sweep across all 5 features (desktop + mobile). |
| 12 | 08-01 | Legal review (F001, F002, F003 all user-facing). |
| 13 | 08-02 | Rework loop (expected). |
| 14 | 08-03 | Signoff + ship. Retro. |
| — | 08-04 | Buffer day. Sprint 1 kickoff. |

## Rota

- **On-call CEO:** Fiyin (always).
- **Sprint owner:** CPO (Noel Noa persona).
- **Architecture reviewer:** CTO (The Anri persona).
- **QA lead:** QA Engineer.
- **Blocker triage:** CPO daily; CEO on `awaiting_ceo: true`.

## Success metric

The one KPI that matters:

> **CEO can send the platform URL to a friend they've never told
> about this project. Friend opens it on their phone, spends two
> minutes, and comes back with an intelligent question about the
> striker roster or the /performance numbers.**

Not: features shipped. Not: tests passing. Not: line-count.
**The friend-test.**
