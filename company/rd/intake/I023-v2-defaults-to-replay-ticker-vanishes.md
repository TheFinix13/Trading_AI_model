---
id: I023
source: ceo-report
submitter: "user_advocate"
submitted_at: 2026-07-28T19:40:00Z
classification: BUG
priority: P3
status: shipped
route: bug
linked_features: []
linked_decisions: [D134]
linked_experiments: []
contact: null
resolved_at: 2026-07-28T19:55:00Z
history:
  - stage: filed
    at: 2026-07-28T19:40:00Z
    by: user_advocate
    note: "CEO report, first evening of live /v2 use: 'the match
      ticker by the right side disappears once i reload the page or
      i go to a new tab ... and i come back to v2'."
  - stage: shipped
    at: 2026-07-28T19:55:00Z
    by: engineering
    note: "LIVE made the first option and the default view (D134)."
---

# I023 — /v2 defaults to a historical replay on every load; the match ticker "disappears"

## What happened

On the first evening of real live use (2026-07-28, right after the
I019 feed fix brought the tape to life), the CEO reported that the
match ticker vanished whenever the page was reloaded or navigated
away from and back. Screenshot evidence shows the page stuck on
`loaded 40000/70150 events…` — the client was downloading the ~70k
event historical replay cache.

Root cause: `init()` in the /v2 page loaded `data.matches[0]` (the
first replay cache) whenever ANY replay cache existed, and only fell
back to LIVE when there were none. The LIVE option was also appended
LAST in the mode picker. A replay's ticker starts empty until the
user presses play, so every reload looked like the ticker had been
wiped. The LIVE view, by contrast, catches the ticker up to the
recent tail on load.

## Why it matters

The live shadow view is the product's front door — it's what the
operator checks between H4 closes and what the FOMC capture will be
watched on. Defaulting to a 70k-event replay download on every visit
buries the live tape behind a manual dropdown pick, wastes bandwidth,
and reads as data loss ("my ticker disappeared") when nothing was
lost at all.

## Resolution (shipped same day, D134)

`init()` now appends the LIVE option FIRST in the mode picker and
defaults to `loadLive()` whenever the live dir exists
(`/api/v2/live/status` `exists`); replay caches remain available in
the dropdown and are the fallback when the squad never ran here.
Regression pins in `tests/platform/test_v2_page.py`
(`TestV2LiveIsDefaultMode`): option order, the new default branch,
and the absence of the old replay-first branch.
