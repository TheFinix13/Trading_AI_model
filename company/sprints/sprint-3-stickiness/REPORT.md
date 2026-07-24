# Sprint 3 (Stickiness) — Report

- **Charter:** `company/sprints/sprint-3-stickiness/README.md` (D114
  scope-lock; CEO charter approval D116).
- **Scope:** six features — F019/F020/F021 (P0), F022/F023/F024 (P1).
  All six shipped; nothing cut.
- **Duration:** 2026-07-24, one executor-day (the D087/I001 planning
  unit), on target.
- **Executors:** THREE hands, one review chain — see the honest
  section below. Decisions: D116 (CEO charter approval), D117 (F019
  ship), D118 (F020 ship), D119 (F021 ship), D120 (F022 ship), D121
  (F023 ship), D122 (F024 ship), D123 (CEO close-out). JSON↔MD 1:1
  verified at every commit.

## The build that lost a builder (honest, on tape at D119)

The sprint was planned for a single build executor. The first
executor shipped F019 (D117) and F020 (D118), drafted F021's
implementation, and then **lost its API budget mid-F021** — dead
mid-feature, draft uncommitted. The parent session picked the draft
up, reviewed it against the spec (the manifest seam was verified
against `research.load_manifest` before trust), wrote the tests,
legal note, claim rows and ledger entries itself, and shipped F021 as
D119. A second (completion) executor then took over for F022–F024 and
this close-out. Same review chain throughout, different hands; the
session-claim file (`.sessions/2026-07-24_sprint3-build.md`) tracked
each takeover. Lesson recorded: mid-feature executor death is
recoverable exactly BECAUSE every feature is one commit-unit — the
half-built F021 never touched the tree until a session could own the
whole unit.

## Features shipped

### P0 — shipped by the first executor + parent session

- **F019 (D117)** — broker-wizard recovery path: the non-Windows
  dead-end copy now states the constraint AND the recovery path;
  post-onboarding surfaces carry the missing-broker state chip;
  I004's internal-token config-dir seam rode along. Resolves I003 +
  I004.
- **F020 (D118)** — match highlights: `agent/platform/highlights.py`
  computes daily match reports read-only from `events.jsonl`;
  `/highlights` page + API; claims registered same-commit
  (`company/legal/F020-review.md`).
- **F021 (D119)** — player career depth: form guide (rolling TQS
  sparkline, windowed win-rate under the `MIN_FORM_SAMPLE=5`
  insufficient-sample rule) and manifest-derived gate status on
  `/players/:id`. The Phase AE honest negative is product surface:
  Sae renders "Benched — fails pre-registered AE2 quality criterion"
  with the manifest's own D112-gated strings, never hardcoded prose
  (`company/legal/F021-review.md`).

### P1 — shipped by the completion executor

- **F022 (D120, commit `2c820dd`)** — `/leaderboard` standings:
  per-agent / per-pair rankings (closed trades, cumulative R primary
  sort, mean-TQS tie-break, win rate, last-active) computed read-only
  from the shadow-paper tape, all/30d/7d windows, deterministic
  ordering. Insufficient-sample rule SHARED with F021 (same constant).
  Standings nav pill added (nav-count pins 8 → 9). All ranked metrics
  registered same-commit under the internal-standings /
  NOT-investment-performance disclaimer (`company/legal/F022-review.md`).
  **+43 tests** vs ≥18 target (25 module + 9 API + 9 page).
- **F023 (D121, commit `ac75d8e`)** — alerts durability + SSE cap:
  opt-in JSONL sink (`[alerts] jsonl_sink`, literal-true only, default
  OFF — memory-only behaviour byte-identical; sink failures never
  block `publish()`); concurrent-stream cap (`[alerts]
  max_sse_streams`, default 8; 429 + Retry-After at the cap — refuse,
  never evict; finally-guarded slot release); `/alerts` page bounded
  exponential-backoff reconnect. All F014/D100 rolling constraints
  re-verified preserved (`company/legal/F023-review.md`). **+25
  tests** vs ≥12 target. Resolves I010.
- **F024 (D122, commit `dada6f9`)** — watchdog front-matter parser →
  `yaml.safe_load`, via the FAST PATH: non-test diff **23 insertions /
  13 deletions** (one function + one import; ≤30-line budget held).
  List-bearing / nested intake front matter parses correctly — a
  list-bearing P0 can no longer age past its 4-hour SLA unseen.
  Never-raise contract and SLA colour semantics byte-identical; no
  new dependency (PyYAML already pinned). **+9 tests** vs ≥8 target
  incl. a regression fixture built from the real post-triage I003
  front matter. Resolves I011.

### Housekeeping rider (chartering commitment)

**I012 `experiments_in_flight` pinned test** (commit `541fcd6`): the
D113 semantic call — in flight = open evaluation panel or scheduled
compute only — is now pinned by
`tests/platform/test_experiments_kpi_semantics.py` (7 tests incl. a
real-ledger pin asserting the truthful value 0). The pin exposed that
the `/hq` derivation was counting the queued `not-started` experiment
as in flight (reporting 1, truth 0); the derivation was corrected in
the same commit.

## Test counts

| Feature | Tests added | Target |
|---|---|---|
| F019 + F020 + F021 (first executor + parent) | ~+95 | per specs |
| F022 | +43 | ≥18 |
| F023 | +25 | ≥12 |
| F024 | +9 | ≥8 |
| I012 rider | +7 (net −1 assertion semantics change) | pinned test |
| Full suite before sprint | 1784 passed + 1 env-skip | baseline |
| Full suite at close | 1969 collected — see close-out tail | must only go up |

Claim audit at close: `OK -- claim register is in sync.` (21 modules
audited, 21 exemptions; F022 §1 + F023 §2 sections added this
sprint; F024 added no claims by design.)

## P0 invariant evidence

- `tests/security/test_live_mode_off_invariant.py` untouched, 23/23
  green at close (output in the close-out ledger entry).
- Zero-diff on protected paths, verified against the sprint baseline:
  `git diff --stat 9c0a591 -- agent/live agent/risk agent/squad
  scripts/run_squad_live.py scripts/run_live.py` → **empty**.

## Deviations and honest notes

1. **Executor death mid-F021** — covered above; on tape at D119.
2. **F021's ledger stage was left at `spec`** by the interrupted
   session even though D119 shipped it. Corrected at close-out with a
   dated RECONCILIATION history entry rather than silently rewriting
   history.
3. **Pre-existing stale test pin found at close** (not caused by this
   sprint): `tests/test_platform_e2e.py::test_v2_page_plays_a_match`
   pinned 8 pitch players, but the I002 legibility fix (`beb9472`,
   pre-sprint) put Sae + Karasu on the pitch (10). The pin was
   updated to 10 with a comment naming `squad_events.ROSTER` as the
   source of truth. This is the only pre-existing test this sprint
   edited, and it is not the protected security suite.
4. **One timing flake fixed in-sprint**: the new F023 stream-cap test
   used a fixed 50 ms attach sleep that flaked under full-suite load;
   replaced with a deterministic poll for stream attachment.
5. **The I012 rider changed one existing assertion**
   (`test_hq_module.py`): the old derivation test asserted the
   pre-D113 semantics (queued counts as in-flight). Updated to the
   D113 call, cross-referencing the new pinned suite.
6. **F023's charter row said "fast-path INELIGIBLE → standard minus
   design"** — it was built that way: spec → build → security → ship
   with a combined Legal+Security note; no design stage (no new
   visual surface beyond the reconnect copy).

## Deferred / out of scope (unchanged from charter)

- Accounts / multi-user auth — D115 charter, its own sprint.
- Anything needing the shadow clock (30/90-day track records).
- Squad → approval-queue submission wiring; any live-path change.
- I007 (needs a live VM event), I009 (VM venv rebuild — ops), I008
  checklist (runbook).
- Alerts sink retention/rotation policy — documented as
  operator-managed (D121); revisit if the file ever matters at scale.

## Verdict: COMPLETE

All six features shipped same-day (6/6 vs the 3–6 historical range),
+84 tests from the completion executor's half alone (~+180 for the
sprint), claim audit green, both P0 invariants verified, intake I003 /
I004 / I010 / I011 resolved with the sprint (intake_items_open
10 → 6).
