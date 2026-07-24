# Sprint 3 — Stickiness (reasons to return daily)

- **Sprint:** sprint-3-stickiness
- **Chartered:** 2026-07-24 (this document; D114 scope-lock)
- **Status:** CHARTERED — awaiting CEO review before the build
  executor starts. No build work happens off this charter alone.
- **Target duration:** 1 executor-day (the D087/I001 planning unit;
  Sprints 1/2/2b each shipped 3–6 features per executor run)
- **Owner (planned):** single build executor, per the Sprint 2b model
- **Kickoff decisions:** D113 (cycle-2 triage feeds three features),
  D114 (this scope-lock)

## Numbering note (read before citing F-numbers)

The Sprint 0 backlog (`sprint-0-trust-foundation/BACKLOG.md`) carries
stale placeholder F019–F024 labels that never became specs — the
sellability memo (D095) already disowns those numbers. Canonical
numbering follows specs on tape: last real spec is F018, so **this
sprint owns F019–F024**. Where a backlog placeholder overlaps an item
here (leaderboards), the spec cites it.

## Why this sprint exists — sellability framing

The mission order is trust → access → stickiness. Sprints 0–2b built
trust surfaces and access safely; the sellability memo's biggest gaps
(live wiring, shadow clock) are now either shipped (F018) or
calendar-bound (the 30–90 day shadow window starts at the VM cutover,
runbook 7b.8, and **cannot be sprinted**). What the product lacks
while that clock runs is a reason for a user to come back *daily*:
today the dashboard is honest but flat — decisions happen in
`events.jsonl` and nobody retells them. Stickiness here = narrative
surfaces computed from evidence we already record, plus the first-run
and reliability polish the R&D loop surfaced.

**Sprint goal:** a returning user finds something new and true every
day — a match report of what the squad did, a form guide per striker,
a standings table — and a new user's first run no longer dead-ends.

## Scope (in) — six features, P0/P1 split

| ID | Title | Size | In-sprint priority | Source |
|---|---|---|---|---|
| F019 | Broker-wizard recovery path + missing-broker chip (+ internal-token config seam) | S | P0 | I003 + I004 |
| F020 | Match highlights — auto-generated match reports from `events.jsonl` | M | P0 | Blue Lock differentiation (charter value 3) |
| F021 | Player career depth — per-agent form guide on `/players/:id` | M | P0 | turns the Phase AE honest negative into product surface |
| F022 | Leaderboard groundwork — per-agent/per-pair standings table | M | P1 | shadow-paper history; backlog "leaderboards" seed |
| F023 | Alerts durability (JSONL sink) + SSE stream cap | S | P1 | I010 |
| F024 | Watchdog front-matter parser → `yaml.safe_load` | S | P1 | I011 |

P0 = the sprint fails without it. P1 = ships if the executor-day has
room; each P1 is small and independently shippable, so cutting any of
them cuts cleanly. Build order: F019 first (drains the oldest open
user-harm item), then F020 → F021 → F022 (F021/F022 reuse F020's
event-derived stats helpers where sensible), then F023/F024.

### Scope-lock reasoning (CPO, feasibility-checked by CTO)

- Capacity is one executor-day; historical throughput 3–6 features per
  run. Six features fits only because three are S-sized and the three
  M-sized ones are read-only compute over one artifact family.
- The pool was the six candidates named at chartering; all six made
  the cut, ranked as recommended, with the P0/P1 line as the re-rank
  instrument: the three items that create *daily-return* value or fix
  *first-run churn* are P0; reliability polish is P1 because a slipped
  P1 costs us nothing a later sprint can't recover.
- CTO feasibility: every feature is additive platform-module work
  (`agent/platform/*`, `scripts/serve_platform.py` routes, `pages.py`
  templates) of the same shape as F001/F002/F015 — no new dependency,
  no schema break, no blast radius beyond 2–3 modules each.

## Binding constraints (every spec inherits these)

1. **Read-only over existing runtime artifacts.** Features consume
   `squad_live/events.jsonl`, roster metadata (`players.roster_meta`),
   and the research manifest. **Zero writes to `agent/{live,risk,squad}/*`
   or `scripts/run_*.py`** — end-of-sprint zero-diff check as in
   Sprints 2/2b.
2. **Claim discipline.** Every public-facing number must be
   claim-register-able: module + accessor + code path + disclaimer in
   `company/legal/claim_register.md`, same commit that introduces it.
   F020, F021, F022 introduce claims (flagged in each spec); F019,
   F023, F024 do not.
3. **F005 conventions.** Mobile responsive at 375 px; every new page
   or panel uses `withStates()` (skeleton / error / empty contract);
   `_BASE_CSS_VERSION` bump only per review-chain §5.5 rules.
4. **Shadow-paper provenance stays explicit.** Any surface showing
   performance-shaped numbers carries the same provenance labelling
   `/performance` already uses. No profit claims; standings and form
   guides are activity/quality metrics with their computation named.
5. **Tests per spec.** Each spec names its test plan; suite count only
   goes up (baseline 1784 + 1 env-skip).

## NOT in scope (explicit)

- **Accounts / multi-user auth** — chartered separately
  (`company/strategy/auth-migration-charter.md`, D115); its own sprint.
- **Marketplace, copy-trading, community/forum features** — Sticky
  backlog items that all presuppose multi-user; parked until the auth
  migration ships.
- **Anything needing the shadow clock** — 30/90-day track-record
  surfaces, "verified live" badges: calendar-bound, not sprintable.
- **Squad → approval-queue submission wiring** and any live-path /
  runtime change (`agent/{live,risk,squad}/*`, `scripts/run_*.py`) —
  integration decisions, not this sprint.
- **I007** (timezone verify-then-fix — needs a live event on the VM),
  **I009** (VM venv rebuild — ops step), **I008** checklist (runbook).
- New dependencies, paid services, hosting/packaging.

## Success criteria (exit gates)

- F019/F020/F021 shipped (P0); F022/F023/F024 shipped or explicitly
  cut with a ledger note.
- Dogfood re-run: P002/P005 broker journeys find actionable copy
  (I003's measurement) — F019 acceptance.
- Every new public number registered in the claim register; claim
  audit green; Legal review on tape for the routes that fire it.
- Full suite green ≥ baseline; zero-diff verified on the protected
  runtime paths; ledger JSON↔MD 1:1 at close.
- REPORT.md post-mortem; KPIs updated; ai_context.md bumped.

## Review-chain stages per feature

| Feature | Path | Conditional stages |
|---|---|---|
| F019 | standard (spec→research→design→arch→build→qa→signoff→ship) | legal (public copy change on first-run surface); security NOT fired — no auth/credential logic change (CTO confirms at arch) |
| F020 | standard | legal (public route + claim data) + research-lead 7b (emits a testable "match reports increase return visits" hypothesis — declared, not measured, this sprint) |
| F021 | standard | legal (public claim data incl. the Sae "benched — Phase AE FAIL" surface; Brand copy sweep for banned words) |
| F022 | standard | legal (public ranking claims + provenance disclaimer) |
| F023 | fast-path INELIGIBLE (new config keys) → standard minus design | security (touches the SSE/auth-adjacent surface) |
| F024 | fast path (small fix, no API change, no new strings) | none |

CEO signoff required on all P0s (review-chain stage 9); CPO-delegable
for the P1s.

## See also

- `../../rd/intake/2026-W30-cycle2-triage.md` — the queue state that
  fed this scope (D113).
- `../../strategy/sellability-gaps.md` — gaps 4 (shadow clock — runs
  in parallel) and 1 (multi-user — chartered at D115, not here).
- `../../strategy/auth-migration-charter.md` — the D115 companion.
- `../../ledger/decisions_log.md` — D113, D114, D115.
