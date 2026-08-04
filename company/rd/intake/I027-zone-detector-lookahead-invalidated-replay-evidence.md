---
id: I027
source: research-audit
submitter: "engineering (prefix-parity audit chartered by the user's 'full fix, research if needed' directive)"
submitted_at: 2026-08-04T04:45:00Z
classification: BUG
priority: P0
status: shipped
route: bug
linked_features: []
linked_decisions: [D138, D139]
linked_experiments: []
contact: null
resolved_at: 2026-08-04T05:30:00Z
history:
  - stage: filed
    at: 2026-08-04T04:45:00Z
    by: engineering
    note: "Prefix-vs-full prepare parity audit: live fires only ~70-75% of the replay's signals; two lookahead channels in detect_zones + one in structural TP."
  - stage: shipped
    at: 2026-08-04T05:30:00Z
    by: engineering
    note: "Causal detector (trailing median, impulse knowability, confirmed-swing TP); post-fix parity ZERO divergence across 15 agent-symbol cells."
---

# I027 — zone detector lookahead: the squad's replay evidence did not describe a strategy live could run

## What happened

The I024 fix made the live squad re-prepare the roster on every new
bar (prefix semantics: history-so-far only). Auditing whether that is
equivalent to the validated full-series replays exposed lookahead in
the shared perception layer itself:

1. `detect_zones` judged impulse validity against a rolling median of
   candle bodies CENTERED on the impulse bar — up to 100 FUTURE bars
   voted on whether a zone existed.
2. `fresh_zones` filtered on `created_bar_index` (the base candle),
   which precedes the defining displacement by up to 3 bars — a
   replay could touch-trade a zone before the move that creates it
   happened.
3. `_structural_tp` accepted fractal swings not yet confirmable at
   the decision bar (needs `swing_lookback` future bars).

Empirically (600 H4 decision bars × 3 symbols, real cached data), the
live-causal semantics fired only ~70–75% of the replay's signals; the
missing ones existed only because of future knowledge.

## Why it matters

Replay A/B over 2019→2026 (36 698 bars, live roster shape, identical
data): pre-fix +29 207 pips / PF 1.52 / mean R +0.30 → causal
**−2 324 pips / PF 0.95 / mean R −0.03**. The squad's replay edge was
substantially a lookahead artifact — the G7/E004-lineage evidence is
invalidated as a live performance forecast. Per-agent: Bachira 1.67→
0.93 and Isagi 1.60→0.96 collapse; **Rin survives at PF 1.20
(+1 014 pips, 218 trades)**; Nagi small-sample positive (PF 1.47,
n=30); Chigiri (already causal) unchanged-negative.

## Closure notes

- **Outcome:** detector made causal — trailing strictly-past median,
  `Zone.impulse_bar_index` knowability gate in `fresh_zones` /
  `fresh_qualified_zones`, `confirm_bars` filter in `_structural_tp`.
  Post-fix prefix-vs-full parity: ZERO divergence (15/15 cells);
  live == replay byte-for-byte from now on.
- **Measurement:** `reviews/audits/2026-08-04-prefix-parity/`
  (FINDINGS.md + harnesses + result JSONs);
  `tests/test_causal_zones.py` (4 regression pins).
- **Follow-up:** re-validation/re-tuning of the roster under causal
  semantics chartered to `finance-research-experiments` (D139). No
  parameter retuning was done in this repo.
- **User notified:** yes · 2026-08-04
- **Related decisions:** D138 (fix), D139 (verdict + charter)
