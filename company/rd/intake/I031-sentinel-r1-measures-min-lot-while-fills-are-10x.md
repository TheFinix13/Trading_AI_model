---
id: I031
source: post-mortem
submitter: "self-observation"
submitted_at: 2026-08-19T13:40:00Z
classification: BUG
priority: P0
status: in_progress
route: bug
linked_features: [F025]
linked_decisions: []
linked_experiments: []
contact: null
resolved_at: null
history:
  - stage: filed
    at: 2026-08-19T13:40:00Z
    by: self-observation
    note: "Found while scoping F025 (squad -> $500 demo bridge) as blocker B3."
  - stage: triaged
    at: 2026-08-19T13:40:00Z
    by: self-observation
    note: >-
      Classified P0 BUG at filing rather than waiting for Monday: the
      operator has asked for the squad on a funded $500 account, and this
      is the defect that makes that unsafe. Fix landed default-OFF the
      same day; the flag flip is the remaining decision.
---

# I031 — Sentinel R1 measures risk at min-lot while fills are 10x larger

## What happened

Sentinel rule R1 computes `sl_distance_pips × pip_value_per_min_lot` and
refuses the proposal when that exceeds 5 % of equity. `pip_value_per_min_lot`
is the value of a pip at the broker minimum, 0.01 lots. The engine then
filled `FIXED_LOT = 0.1` — ten times that — because nothing between R1
and the paper broker ever sized the position to the budget R1 checked.

Worse, the one place the engine *did* override the fill lot was gated on
`if risk_scale != 1.0`, so on the ordinary path (no R5 loss-streak, no R7
news dampener) any computed lot was discarded and the broker's own
default stood.

Concretely on EURUSD, where a pip is $0.10 at min lot and $10.00 at 1.0
lot, with a $500 book and the 5 % cap ($25 budget):

| Stop | R1's measured risk | Actual risk at 0.1 lot | Actual % of $500 |
|---|---|---|---|
| 20 pips | $2.00 | $20 | 4 % |
| 30 pips | $3.00 | $30 | 6 % |
| 100 pips | $10.00 | $100 | 20 % |
| 250 pips | $25.00 (exactly at cap, R1 **allows**) | $250 | **50 %** |

The last row is the one that matters. R1's own boundary — the widest stop
it permits on a $500 account — is the trade that costs half the account
when it stops out. Two of those and the account is gone.

## Why it matters

Not at all, until money is real. The squad has only ever traded a paper
book, where the discrepancy is bookkeeping and the R-multiples the
research lane scores are unaffected (R is normalised by the stop, so a
uniform lot error cancels). That is why eleven months of shadow tape
never surfaced it.

It becomes a P0 the moment a fill settles on the Exness demo, which is
exactly what the operator has asked for. The system advertises a 5 %
per-trade cap in its own Sentinel documentation, in `platform.toml.example`,
and on the /risk page. On a funded account that number is wrong by 10x.
Shipping a risk control that misstates risk by an order of magnitude is a
credibility problem independent of the money.

## Diagnosis — R1 is not the bug

R1 is a **floor** check and correct as one: "even at the smallest legal
position, does this stop cost more than the cap? If so there is no size
at which this trade is acceptable, so refuse." That question is worth
asking and R1 answers it correctly.

The missing piece is the **cap**: the step that, having established the
trade is fundable, sizes it down so the actual loss lands inside the
budget. That step never existed. So the fix is additive, and R1 is
unchanged.

The two caps sharing one constant also means the unfundable case is R1's
by construction — R1 fires first, so the sizing step never has to return
a zero lot on the live path. Pinned in
`tests/squad/test_engine_risk_scale.py::test_r1_catches_the_unfundable_case_before_sizing_runs`.

## Resolution (landed 2026-08-19, default OFF)

`agent/squad/lot_intent.risk_budget_lot()` returns the largest lot whose
stop-out loss stays inside `per_trade_risk_frac × equity`, rounded DOWN
to a lot increment, using the per-symbol `pip_value_per_min_lot` from
`provenance_pips` so JPY crosses and metals size correctly too (the I030
lesson). Two safety properties:

- **Never sizes up.** The result is capped at `desired_lot`, so enabling
  the flag can only reduce exposure relative to fixed-lot. This is what
  makes it safe to turn on without re-validating the roster's book.
- **Returns 0.0 rather than MIN_LOT** when the budget cannot fund the
  minimum. Rounding back up is the same class of error as the original
  bug.

Wired into `SquadEngine` behind `risk_derived_sizing` (default `False`),
settable via `[squad_live] risk_derived_sizing` or
`--risk-derived-sizing`. The engine's lot override now compares against
the lot the broker actually filled instead of testing `risk_scale != 1.0`,
which is what made the ordinary path a no-op. Advisory R5/R7 scale-downs
compose on top of the budget lot rather than replacing it.

Default OFF is deliberate and load-bearing: every banked replay and the
entire shadow tape were produced fixed-lot, so flipping the default would
silently make new tape non-comparable with the evidence base. Pinned by
`test_default_off_still_fills_fixed_lot`.

Tests: `tests/test_squad_risk_derived_sizing.py` (arithmetic + safety
properties, parametrised across stops and equities),
`tests/squad/test_engine_risk_scale.py` (engine-level: default-off
identity, shrink-to-budget, commission scaling, R5/R7 composition,
defensive zero-lot), `tests/platform/test_squad_live_config_block.py`
(default-off through the config file).

## Notes for triage

Two adjacent findings surfaced while fixing this, both deliberately left
alone:

1. **F19 `lot_intent` is dead code on the fill path.** Every agent
   implements agent-owned lot cognition per doctrine 4.1a, and G7
   criterion #5 grades its dispersion — but `engine._admit` never calls
   it. Fills were `FIXED_LOT` and are now the risk-budget lot; neither
   consults the agent's own sizing opinion. That is a real gap between
   the doctrine and the runtime, but wiring it changes per-agent position
   sizes and therefore the book. It needs its own pre-registration, not
   a bug fix.
2. **R6's per-symbol risk cap has the same min-lot basis** and would
   want the same treatment before real orders. Not touched here because
   R6 only engages on the arm4 multi-position path, which the live loop
   does not run.

## Closure notes

- **Outcome:** fix landed default-OFF; the remaining action is the dated
  decision to enable it, which belongs with the F025 bridge rather than
  here. Not resolved until that flip happens, because until then the
  running configuration is still the 10x one.
- **Measurement:** first funded-account fill's `executions.jsonl` row
  should show realised risk within the advertised cap; compare against
  the pre-flip tape's implied risk on the same stop distance.
- **User notified:** n-a (operator is the submitter).
- **Related decisions:** pending.
