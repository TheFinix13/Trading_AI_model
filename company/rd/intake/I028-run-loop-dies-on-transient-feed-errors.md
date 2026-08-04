---
id: I028
source: post-mortem
submitter: "engineering (Aug 3 outage review while hardening the live loop)"
submitted_at: 2026-08-04T05:00:00Z
classification: BUG
priority: P1
status: shipped
route: bug
linked_features: []
linked_decisions: [D140]
linked_experiments: []
contact: null
resolved_at: 2026-08-04T05:45:00Z
history:
  - stage: filed
    at: 2026-08-04T05:00:00Z
    by: engineering
    note: "Any exception from Mt5Feed.refresh escapes run_loop and kills the process; a starving-but-not-erroring feed idles silently with nothing on the tape."
  - stage: shipped
    at: 2026-08-04T05:45:00Z
    by: engineering
    note: "Bounded-backoff retry + system_status rows + one page per streak; feed-staleness latch with weekend suppression."
---

# I028 — run_loop dies on transient feed errors and starves silently

## What happened

Two resilience gaps in `scripts/run_squad_live.py`:

1. `asyncio.run(feed.refresh())` was unguarded — one transient MT5
   read error (network blip, terminal IPC hiccup) escaped the loop,
   the process exited "crashed", and the ops watchdog restart-churned
   it (losing the M15 window and news state each time).
2. When the feed "succeeds" but returns nothing new (the Aug 3 shape:
   terminal disconnected by the DNS outage, cache frozen), the loop
   idled happily forever. The only detection was the EXTERNAL
   tape-freshness watchdog; nothing landed on the squad's own tape.

## Why it matters

The weekly report's system-health section reads `system_status` rows
from the tape. An outage that never writes one is invisible at review
time — exactly what made the Aug 3 starvation a forensic exercise
instead of a one-line log read.

## Closure notes

- **Outcome:** refresh guarded with bounded exponential backoff (60s
  → 900s cap), `system_status` rows (`refresh_error` per failure with
  streak, `recovered` on comeback), one Telegram page per failure
  streak. Feed-staleness latch: no closed bar for
  `--feed-stale-hours` (default 9, matching the external watchdog's
  warn threshold) outside the FX weekend gap → `stale` row + page,
  `recovered` row when bars flow again. Logic errors inside
  `engine.on_bar` still crash loudly (I022 semantics) — only feed I/O
  is retried.
- **Measurement:** `tests/test_squad_live_mt5_loop.py` (+3 tests:
  transient-error survival with backoff + tape rows, staleness row,
  weekend-gap window).
- **User notified:** yes · 2026-08-04
- **Related decisions:** D140
