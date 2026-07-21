# F002 -- QA verdict

- **Feature:** F002 -- `/players` + `/players/:id`
- **QA reviewer:** QA Engineer
- **Verdict:** `pass`
- **Date:** 2026-07-21

## Automated tests

- `tests/platform/test_players_module.py` -- 29 tests (id
  normalisation, bio markdown parsing, per-agent stats, empty
  case handling, source-hint variants, ten-id sweep, read-only
  invariant, default bio dir wiring).
- `tests/platform/test_players_page.py` -- 24 tests covering
  the index page, the detail-page factory (for all 10 strikers),
  the 404 shell, nav pill count / active class, mobile media
  queries, IP disclaimer verbatim, no CDN / no Cursor attribution.
- `tests/platform/test_players_api.py` -- 17 tests covering
  HTML routes, JSON APIs, cold-start / seeded behaviour, unknown-id
  404 payload shape, canon-variant id normalisation, and the
  read-only invariant on live_dir.

Platform test count: 170 -> 240 (+70).

## Manual verification

- ✅ `/players` renders cold-start with the ten-card grid; retired
  card (Kunigami) renders at 65 % opacity; standby cards (Karasu,
  Sae) render with the blue "standby" pill.
- ✅ Each of the ten `/players/<id>` routes returns 200 and shows
  Career stats + Playstyle + Signature setup + Recent activity +
  Evolution history + IP disclaimer.
- ✅ `/players/Isagi` (case-variant) resolves to `/players/isagi`
  data; `/players/isagi_yoichi` also resolves; `/players/isagi/`
  handled by the route regex.
- ✅ `/players/obiwan` renders the 404 shell with all ten valid
  striker slugs as links; API mirror returns HTTP 404 with a
  `valid_ids` payload.
- ✅ Empty state on the detail page fires cleanly via F005's
  `withStates()` for strikers with no events (source_hint copy
  matches the standby / retired case).
- ✅ IP disclaimer footer is byte-verbatim from
  `company/legal/disclaimers.md::third-party-name-usage`.

## Manual mobile check (F004 baked-in)

- ✅ 375 px viewport: card grid collapses to single column below
  700 px; stat grid collapses to 2-col below 700 px, then 1-col
  below 480 px. Signature-setup ASCII scrolls horizontally in
  `overflow-x:auto` container instead of wrapping the diagram.
- ✅ Status pills render both colour AND text label -- colour-blind
  users still see "retired" / "active" / "standby".

## Regressions to watch for

- Bio markdown format drift. `_parse_bio_markdown` looks for
  specific header meta bullets (`- **signature_blurb:** ...`) and
  H2 headings `## Playstyle prose` / `## Signature setup` /
  `## Evolution history`. Renaming any of these silently drops
  the section; the API keeps returning shape but the page falls
  back to "Bio not yet written."
- `agent_key` drift. If a striker's `agent_id` on the wire ever
  changes (e.g. `isagi_yoichi` -> `striker_1` per the IP fallback
  plan), the `_ROSTER.agent_key` needs to change with it or stats
  read empty.

## Sign-off

F002 tests green; disclaimer legal-approved; mobile responsive.
Ready for CEO signoff.
