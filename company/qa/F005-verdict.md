# F005 — QA verdict

- **Feature:** F005 — Loading skeletons + friendly error-state recovery
- **QA reviewer:** QA Engineer
- **Verdict:** `pass`
- **Date:** 2026-07-21

## Test scope

F005 is a horizontal-concern feature: it ships the shared
`withStates()` helper + `_SKELETON_CSS` + `_ERROR_COPY_JS` block that
F001 / F002 / F003 build stages consume during their own build. QA
here covers the helper contract (structure of the CSS + JS blobs,
Brand copy library) rather than a specific page's UX.

## Automated tests

`tests/platform/test_pages_shared_states.py` — 19 tests, all green:

- 4 assertions on `_SKELETON_CSS` — keyframes, class families,
  retry-button styling, palette-token reuse.
- 3 assertions on `_ERROR_COPY_JS` — every canonical copy key from
  `company/brand/error_copy.md` shows up, the default fetch-outcome
  map covers the six standard branches, no banned phrases leak
  ("Error 500", "undefined", "Failed to fetch", ...).
- 6 assertions on `_WITH_STATES_JS` — API signature, branching
  helpers, retry-button copy, unconfigured routing, empty-state
  swap, default skeleton helper.
- 2 assertions that the brand copy files exist on disk with the
  right sections.
- 4 assertions on the nav extension (7 pills, active-here class,
  regressions on old pills).

Full platform suite (119 tests) green after F005 lands.

## Manual verification (F005-specific)

- ✅ Nav pills render as: Hub / v1 / v2 / HQ / Performance / Squad /
  Research (verified via string assertion; live smoke deferred to
  F001 build stage when a page consumes the extended nav).
- ✅ Copy library files present: `company/brand/copy.md`,
  `company/brand/error_copy.md`.
- ✅ Nothing in `_SKELETON_CSS` introduces a new palette token; only
  `--panel`, `--border`, `--fg`, `--dim` referenced.

## Regressions to watch for

Because F001 / F002 / F003 will consume these helpers directly in
their build stages:

- If any of the constants get renamed or split, the consuming pages
  break. Test coverage locks the names.
- If Brand revises `error_copy.md` without updating `_ERROR_COPY_JS`,
  the doc + code drift silently. Fix: `TestErrorCopyLibrary` in this
  test file pins the canonical key set.
- If the shared `nav()` function gets called with an unknown active
  value from a consuming page, no `.here` marker appears — safe
  degradation but harmless-looking bug. Regression-locked by
  `test_unknown_active_renders_with_no_here`.

## Sign-off

F005 helper landed and green. F001 / F002 / F003 may consume
`withStates()` + `_SKELETON_CSS` + `_ERROR_COPY_JS` directly from
`agent.platform.pages`.
