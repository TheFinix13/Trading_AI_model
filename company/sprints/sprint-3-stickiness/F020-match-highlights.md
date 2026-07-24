# F020 — Match highlights: auto-generated match reports from `events.jsonl`

- **Sprint:** sprint-3-stickiness
- **Priority:** P0 (in-sprint) · Size **M**
- **Source:** charter value 3 ("the Blue Lock metaphor is the moat") —
  the squad's decisions are already on tape; nobody retells them.
- **Consumes:** `squad_live/events.jsonl` (tick_summary / proposal /
  tackle / close rows written by `agent/squad/engine.py`), roster
  metadata (`players.roster_meta()`), `paper_loop.live_status()`
- **Consumed by:** `/highlights` (new public route), a "latest match
  report" teaser on `/v2`
- **Feature flags:** `legal_relevant: true` (public route, claim
  data), `research_relevant: true` (emits a user-behaviour
  hypothesis — see §Hypothesis), `security_relevant: false`
- **Claims introduced:** YES — every stat in a match report (trade
  counts, TQS values, R multiples, win/loss outcomes, per-agent
  involvement) must land in `company/legal/claim_register.md` in the
  same commit (module `highlights.py`, accessor per field, provenance
  disclaimer: shadow-paper, demo feed).

## User story

A returning visitor opens `/highlights` and reads yesterday like a
match report: "Quiet first half — no H4 setups cleared Sentinel.
57' Isagi spots a GBPUSD demand zone, Bachira confirms; Sentinel
approves at 0.62 quality. Full time: 1 shot, 1 on target, +1.4R."
Every line is derived from recorded events; every number is
click-through-able to the raw evidence. The user comes back tomorrow
because tomorrow's match hasn't been written yet.

## Scope (in)

1. **`agent/platform/highlights.py` (new, read-only).** Public API:
   - `match_report(day, live_dir=None) -> dict` — one day's narrative:
     ordered timeline of notable events (proposals, tackles/rejections,
     opens, closes with R outcome), per-agent involvement, quiet-period
     summaries reusing the I002 quiet-reason vocabulary.
   - `list_reports(n, live_dir=None) -> list[dict]` — newest-first
     index (day, one-line headline, key stat).
   - `trade_story(trade_id, live_dir=None) -> dict` — per-closed-trade
     retelling (zone found → confluence → gate verdict → outcome).
   - Injectable `live_dir` + clock; malformed/absent events degrade to
     empty-state, never raise (F005 contract).
2. **Narrative templating**: deterministic string assembly from event
   fields — squad metaphor voice, banned-words gate respected (no
   "ensemble", no "aggregator"). Template strings pre-swept by Brand.
3. **Surfaces**: `GET /highlights` (public page, `withStates()`,
   mobile-responsive), `GET /api/highlights/reports?n=`,
   `GET /api/highlights/report/<day>`; a teaser card on `/v2` linking
   to the latest report. API gated exactly like existing public data
   routes (localhost-open per D052; token on non-localhost binds).
4. **Provenance banner** on the page: shadow-paper / demo-account
   provenance, same wording family as `/performance`.

## Scope (out)

- No LLM calls, no external services — templating only.
- No writes anywhere in the runtime tree; no new event types; no
  changes to what the engine logs.
- No per-user state (read-only, stateless).
- No social sharing/export (marketplace-adjacent, parked).

## Hypothesis (declared, NOT measured this sprint)

"Users with access to daily match reports return on more distinct
days than users without." Declared per literature-standards §5 so the
Research Lead can pre-register a measurement once real visitors
exist; NO number about engagement is published anywhere until that
experiment reports. This spec flags the hypothesis; it does not wire
any measurement.

## Acceptance criteria

- A day with activity renders a report whose every number matches a
  recomputation from the raw `events.jsonl` rows (test asserts
  equality, not snapshot).
- A quiet day renders an honest quiet report (reusing quiet_reason),
  not an empty page; a missing `events.jsonl` renders the empty state.
- All public fields registered; claim audit green; Legal + Research
  Lead reviews on tape before ship.

## Test plan

`tests/platform/test_highlights_module.py` (report assembly from
fixture event files: active day, quiet day, malformed rows, absent
dir); `test_highlights_api.py` (routes, auth gate on non-localhost,
empty states); `test_highlights_page.py` (page smoke, banned-words
absence, provenance banner presence). Target ≥ 25 tests.

## Files touched (expected)

New: `agent/platform/highlights.py`, 3 test files.
Edited: `agent/platform/pages.py` (HIGHLIGHTS page + /v2 teaser),
`scripts/serve_platform.py` (routes),
`company/legal/claim_register.md` (F020 section).
