# F024 — Watchdog front-matter parser → `yaml.safe_load`

- **Sprint:** sprint-3-stickiness
- **Priority:** P1 (in-sprint) · Size **S**
- **Source:** I011 (audit A011, P2)
- **Consumes:** `agent/platform/watchdog.py` `intake_sla` check;
  `company/rd/intake/I*.md` front matter
- **Consumed by:** watchdog snapshot → `/hq` strip, `watchdog_alert`
  bus events (no payload change — D100 constraints untouched)
- **Feature flags:** none fire — internal parsing fix, no new public
  field, no copy, no dependency (`PyYAML` already installed).
  **Fast-path eligible** (review-chain §Fast path) provided the diff
  stays ≤ 30 lines of non-test change; if it grows, kick back to
  standard path per the rules.
- **Claims introduced:** NONE

## Problem statement

The `intake_sla` check parses intake front matter with a hand-rolled
scalar-only parser. YAML lists (`linked_decisions:` blocks) and
nested `history:` entries are skipped or mis-read, so the check can
mis-derive `priority`/`status` on any list-bearing file — and a P0
item could age past its 4-hour SLA without the alarm firing. This
cycle's triage added history blocks to every open item, making the
mis-parse surface *larger*, which is why the fix rides this sprint.

## Scope (in)

- Split the front-matter block (`--- ... ---`) and feed it to
  `yaml.safe_load`; read `priority`/`status`/`submitted_at` from the
  resulting dict.
- Preserve the never-raise contract exactly: unparseable YAML,
  missing keys, or a missing front-matter fence degrade the check to
  the documented `alarm`-with-detail / `na` behaviour — a broken
  intake file must surface as a watchdog colour, not an exception.
- Keep the check's thresholds and colour semantics byte-identical
  (P0 filed > 4 h alarm; P1 > 7 d warn; any open > 30 d warn).

## Scope (out)

- No changes to other checks, the publisher, state persistence, or
  the API/page surfaces.
- No intake front-matter schema change.

## Acceptance criteria

- A list-bearing intake file (fixture mirroring I003's real shape:
  `linked_features` list + multi-entry `history`) parses correctly
  and its SLA state matches expectation.
- Malformed YAML fixture → documented degraded colour, no exception.
- All existing watchdog tests pass unchanged.

## Test plan

Extend `tests/platform/test_watchdog_module.py` intake_sla cases:
list-bearing front matter, nested history entries, malformed YAML,
fence-missing file, and a regression case constructed from the real
post-triage I003 front matter. Target ≥ 8 new cases.

## Files touched (expected)

Edited: `agent/platform/watchdog.py` (one parser function),
`tests/platform/test_watchdog_module.py`.
