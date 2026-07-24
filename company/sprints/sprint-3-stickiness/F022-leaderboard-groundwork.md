# F022 — Leaderboard groundwork: per-agent / per-pair standings

- **Sprint:** sprint-3-stickiness
- **Priority:** P1 (in-sprint — ships if the executor-day has room) ·
  Size **M**
- **Source:** stickiness pillar; seeds the Sprint-0 backlog's
  "public leaderboards (opt-in), best squads across users" idea
  (stale placeholder F019 there) at single-install scale — **no
  accounts dependency**: one install, ranked within itself.
- **Consumes:** `squad_live/events.jsonl` closed-trade rows; roster
  metadata; F020's stats helpers where they overlap (build after F020)
- **Consumed by:** `/leaderboard` (new public route); future
  multi-user leaderboards inherit the table shape (see the D115
  charter's Phase 2 — cross-user ranking is OUT until accounts exist)
- **Feature flags:** `legal_relevant: true` (public ranking claims),
  `security_relevant: false`, `research_relevant: false`
- **Claims introduced:** YES — every ranked metric (closed-trade
  count, cumulative R, mean TQS, win rate per agent and per pair) is
  a registered claim with the shadow-paper provenance disclaimer and
  the explicit "activity/quality ranking, not investment performance"
  wording (Legal pre-approves the header copy).

## User story

A returning user checks the standings like a league table: which
striker is in form this month, which pair has been kindest to the
squad. Rankings change as the shadow window accrues — another reason
to come back — and every cell links to the evidence behind it.

## Scope (in)

1. **`agent/platform/leaderboard.py` (new, read-only):**
   - `standings(by="agent"|"pair", window_days=None, live_dir=None)
     -> dict` — table rows: entity, closed trades, cumulative R, mean
     TQS, win rate (insufficient-sample rule shared with F021: below
     n=5 the rate cell renders "n=…"), last-active timestamp. Sorted
     by cumulative R; ties by mean TQS. `window_days=None` = all
     recorded history; 7/30-day windows supported.
   - Deterministic, injectable paths/clock, never-raise (empty-state
     degradation per F005).
2. **Surfaces:** `GET /leaderboard` page (`withStates()`, mobile,
   agent/pair toggle + window toggle), `GET /api/leaderboard?by=&window=`.
   Same public-route gating pattern as F020.
3. **Provenance + framing:** header states the computation window,
   the shadow-paper provenance, and that rankings are internal squad
   standings on a demo feed — no external comparison implied.

## Scope (out)

- Cross-install / cross-user ranking, opt-in sharing, anything
  needing accounts (blocked on the D115 auth migration; explicitly
  Phase-2-shaped there).
- No "best squad" claims against any external benchmark.
- No persistence layer — computed on read like every other surface.

## Acceptance criteria

- Standings equal an independent recomputation from fixture events
  for both groupings and all windows; deterministic ordering pinned.
- Empty history renders the empty state; sub-sample win rates render
  the n-rule, not a percentage.
- All ranked metrics registered; claim audit green; Legal review on
  tape for the header framing.

## Test plan

`tests/platform/test_leaderboard_module.py` (grouping, windows,
ordering + tie-break, n-rule, empty/malformed events);
`test_leaderboard_api.py` + page smoke (toggles, auth gate,
provenance header). Target ≥ 18 tests.

## Files touched (expected)

New: `agent/platform/leaderboard.py`, 2–3 test files.
Edited: `agent/platform/pages.py`, `scripts/serve_platform.py`,
`company/legal/claim_register.md` (F022 section).
