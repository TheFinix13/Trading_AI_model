---
id: I025
source: post-mortem
submitter: "self-observation (engineering, while fixing I024)"
submitted_at: 2026-08-04T03:30:00Z
classification: BUG
priority: P1
status: shipped
route: bug
linked_features: []
linked_decisions: [D136]
linked_experiments: []
contact: null
resolved_at: 2026-08-04T04:30:00Z
history:
  - stage: filed
    at: 2026-08-04T03:30:00Z
    by: engineering
    note: "Found reading run_loop while diagnosing I024."
  - stage: shipped
    at: 2026-08-04T04:30:00Z
    by: engineering
    note: "mt5 path no longer passes feed indices into engine space."
---

# I025 — run_loop passes the mt5 feed's sliding-window bar index into the engine's append-only history

## What happened

`run_loop` forwarded `FeedBar.bar_index` — an index into `Mt5Feed`'s
SLIDING ~2,500-bar cache window — into `SquadEngine.on_bar`, whose
`bars_by_symbol` history is APPEND-ONLY. The two index spaces diverge
from the first live bar onward. Consequences: `on_bar`'s
`series[bar_index] = bar` overwrote a historical bar with each new
live bar (progressive history corruption), and the `next_bar` fill
lookup picked the wrong bar (`series[feed_index + 1]`), in the
first-divergence case the just-closed bar itself.

Masked last week only because I024 had already blinded the agents;
with I024 fixed, this would have corrupted every zone computation and
paper fill.

## Why it matters

Shadow-paper fills and zone context would be silently wrong — worse
than being visibly down, same trust class as I019/I024.

## Closure notes

- **Outcome:** on the mt5 path `run_loop` now passes
  `bar_index=None` (engine assigns its own index) and picks the fill
  bar as the next newer closed bar for that symbol in the same poll
  batch (catch-up case), else the currently-forming bar's open.
  cache/fake feeds keep the original path — their indices ARE
  engine-aligned (the engine is prepared on the feed's full series).
- **Measurement:** `tests/squad/test_live_reprepare.py::
  test_live_bars_append_never_overwrite_history` +
  `tests/test_squad_live_mt5_loop.py`.
- **User notified:** yes · 2026-08-04
- **Related decisions:** D136
