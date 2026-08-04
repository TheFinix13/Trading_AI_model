---
id: I026
source: post-mortem
submitter: "user (v1 weekly review noted 'a scheduled H4 close is skipped silently'; confirmed on v2 tape)"
submitted_at: 2026-08-04T03:30:00Z
classification: BUG
priority: P1
status: shipped
route: bug
linked_features: []
linked_decisions: [D137]
linked_experiments: []
contact: null
resolved_at: 2026-08-04T04:30:00Z
history:
  - stage: filed
    at: 2026-08-04T03:30:00Z
    by: engineering
    note: "Aug 3 tape ends at the 04:00 bar; the 08:00 close was never evaluated despite the loop polling until 14:07."
  - stage: shipped
    at: 2026-08-04T04:30:00Z
    by: engineering
    note: "Catch-up emission + mark_seen resume from state.json."
---

# I026 — Mt5Feed emits only the newest closed bar: H4 closes missed during a gap are skipped forever

## What happened

`Mt5Feed.poll_new_closed` emitted only `series[-1]` per symbol. Any
H4 close missed while the loop was not polling healthily — a feed
outage (the Aug 3 DNS death starved MT5 from 10:26 UTC), a VM pause,
or a runtime restart — was silently skipped and never evaluated.
The runner also never seeded the feed's cursor from `state.json`'s
`last_bar_times`, so a restart always dropped the gap bars between
the last processed close and "now".

## Why it matters

The squad's shadow record has silent holes exactly where the
interesting sessions are (outages cluster around volatile periods).
A restart after a weekend or an incident should catch up the tape,
not lose it.

## Closure notes

- **Outcome:** `poll_new_closed` now emits EVERY cached bar newer
  than the per-symbol cursor, oldest first (fresh boot without a
  cursor still emits only the newest bar — older history is
  prepare() hydration, not live tape). `run_loop` seeds the cursor
  via `feed.mark_seen` from persisted `last_bar_times`, turning a
  restart into a bounded catch-up. Catch-up fills use the next bar
  in the same batch (I025 fix).
- **Measurement:** `tests/squad/test_feed_catchup.py` (5 tests; 3
  fail against the pre-fix code).
- **User notified:** yes · 2026-08-04
- **Related decisions:** D137
