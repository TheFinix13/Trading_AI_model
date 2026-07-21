# F003 -- QA verdict

- **Feature:** F003 -- `/research` verdict timeline
- **QA owner:** qa (Sprint 0)
- **Signed:** 2026-07-21 17:52 UTC
- **Verdict:** PASS

## Automated checks

| Suite | Tests | Result |
| --- | --- | --- |
| `tests/platform/test_research_module.py` | 23 | pass |
| `tests/platform/test_research_page.py` | 17 | pass |
| `tests/platform/test_research_api.py` | 6 | pass |
| `tests/platform/` (full) | 286 | pass |

Baseline before F003 build: 240 tests. Delta: **+46** (23 module + 17
page + 6 API). No regressions elsewhere; HQ / performance / players /
paper-loop / squad-events all still green.

## Manual verification

1. **`/research` cold start.** Loaded the page with the sibling repo
   present. Skeleton showed for < 200 ms; six verdict cards
   rendered newest-first: `E007_impulse_origin_bounce` (2026-07-21,
   alive) at top, `phase_ac_pitch_assignment` (2026-07-15, stopped)
   next, then E024 fail, E022 dead, E004 alive, E001 alive.
   Month sticky headers ("July 2026", "June 2026") landed as
   expected.
2. **Missing sibling repo simulation.** Ran a test server with
   `research_root=None`. `/api/research/verdicts` returned
   `source_exists=false`, `entries=[]`, and the page rendered the
   canonical "no data yet" empty state ("Research repo not
   configured on this machine. See docs/RUNBOOK_demo_launch.md §7b.")
   No 500s. Retry button visible; clicking it re-hit the endpoint
   cleanly.
3. **Missing manifest simulation.** Ran with `research_root` present
   but `research_manifest_path` pointing at a non-existent file.
   Payload returned `unconfigured=true`; page rendered the
   "not_configured" empty state ("The publication manifest is not
   on tape yet. CPO signoff pending.").
4. **Dead / fail / stopped visibility.** All three "bad news" cards
   render at the same visual weight as the "alive" cards (same
   padding, same font size, same headline stat block). Verdict pills
   colour-differentiate (green / red / grey) but nothing is buried.
5. **FDR explainer.** Collapsed by default. Keyboard-openable
   (Tab, Enter). Body prose reads at ~7th-grade level;
   `readability-and-clarity.md` sample suggests Flesch score ~55.
   Contains "pre-registration", "BH-FDR at q = 0.10", "receipt
   trail" -- the three anchor phrases from copy.md.
6. **Mobile 375 px.** Chrome DevTools iPhone SE emulation.
   Verdict pill wraps above the title; date drops to a new line;
   month sticky header stays pinned during scroll. FDR explainer
   summary remains tappable. No horizontal scrollbar.
7. **Poll cadence.** DevTools Network tab confirmed one
   `/api/research/verdicts` request on load and another after 60
   seconds; no thrashing.
8. **Read-only invariant.** Ran
   `test_read_only_invariant_on_research_root` -- snapshot of
   sibling repo bytes identical before / after four API hits.
9. **Nav pill count.** Every page (`/`, `/v1`, `/v2`, `/hq`,
   `/performance`, `/players`, `/research`) shows all 7 pills;
   `/research` marks itself `here` correctly.

## Regression risks

- **Sibling repo drift.** If the E-series REPORT.md format changes
  (title header level, date format, verdict line prefix), the
  parser may emit `verdict_kind = "unknown"`. Non-fatal (renders
  with the grey pill) but reduces information density. Mitigation:
  `test_research_module.py` covers the two verdict-line shapes we
  ship against; add fixtures as the format evolves.
- **Manifest drift.** If CPO adds a new campaign to the manifest
  without a matching REPORT.md on disk, the entry is silently
  dropped from the payload. Mitigation: the module returns
  `all_candidates` alongside `published_total`, so a discrepancy
  is diagnosable from the API response.
- **Publication side-channel.** Because backend caches everything
  it parses, an accidental log-dump of `list_all()` output could
  leak in-flight verdicts. Mitigation: only the
  `/api/research/verdicts` endpoint is publicly reachable, and it
  only ever calls `get_state()` (which filters through the
  manifest). No `list_all()` call in `serve_platform.py`.

## Signoff

QA advises **PASS with routine ship**. No blockers surfaced.
Handing to Legal for the anti-cherry-pick disclaimer review.
