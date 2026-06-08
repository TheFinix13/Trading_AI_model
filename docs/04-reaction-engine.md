# 04 — Reaction Engine & Anticipation→Reaction Flip

> Part of the numbered docs — start at [00 — Overview](00-overview.md). Sizing for
> these trades is in [05 — Position Sizing & Risk](05-position-sizing-and-risk.md);
> the journal that records and learns from them is in
> [06 — Learning Journal & Performance Memory](06-learning-journal.md).

This is the quant upgrade that turned the agent from a pure **anticipation** system
(which waited for a full retest choreography and rarely fired) into one that also
**reacts to committed moves in present time**. Two pieces live here; sizing and the
learning loop live in [05](05-position-sizing-and-risk.md) and
[06](06-learning-journal.md).

---

## 04.1 Reaction engine

**Code:** `agent/reaction/` (`components.py`, `engine.py`) · **Config:**
`ReactionConfig` in `agent/config.py`.

The anticipation stack asks *"will price react at this level?"* and waits for
touch → consume → reaction wick → displacement (an AND-chain that almost never
completes). The reaction engine instead asks *"is price committing **right now** at
a level I already marked?"* using four **measured** facts about the just-closed
bar(s) — no predictions, no look-ahead:

| Component | What it measures | Code |
| --- | --- | --- |
| **Displacement** | Candle body vs ATR (`displacement_atr_mult`) with a strong directional close (top/bottom `displacement_close_frac` of range) | `displacement_score` |
| **Range expansion** | Current bar range vs the prior rolling-average range (`expansion_mult`) — volatility ignition | `range_expansion_score` |
| **Momentum** | ROC over `momentum_lookback` normalised by ATR, blended with consecutive directional closes | `momentum_score` |
| **Imbalance** | Order-flow proxy: close location in range + wick asymmetry + tick-volume rising on the directional bar | `imbalance_score` |

Each returns a score in `[0, 1]` (directional components also vote a side). The
engine blends them with the configured weights into a **composite conviction**,
dampened by **directional agreement** (how aligned the components are). It fires
when:

- composite conviction ≥ `conviction_threshold`, **AND**
- price is at/near a pre-marked level (within `level_proximity_atr_mult × ATR`)
  **or** breaking through one with force (`require_level`), **AND**
- the resulting stop is non-degenerate and the target gives R:R ≥ `min_rr`.

Stops are structural (recent swing / ATR, whichever is wider, plus a buffer);
targets aim at the next unswept PD-array / liquidity level
(`agent/detectors/pd_array.py`), falling back to a fixed `fallback_rr`.

**Why it actually trades:** the reaction path uses a *lighter* gate set than
anticipation. It still respects the hard risk gates (kill switch, daily DD halt,
max positions, sizing/margin — see [05](05-position-sizing-and-risk.md)) but does
**not** require the full retest choreography — committed displacement + momentum +
imbalance at a level *is* the confirmation.

`ReactionEngine.assess(...)` always returns a full `ReactionAssessment` (scores,
conviction, agreement, level, rejection reason) so the explainer can show *why* it
did or didn't react on every bar. `evaluate(...)` is the thin wrapper that returns
just the `ReactionSignal` when one fires.

In `--verbose` the per-bar explainer prints a reaction step you can read directly:

```
┌─ STEP 3.5: REACTION ENGINE ──────────────────────────
│ Displacement : ████████░░ 0.81
│ Expansion    : █████████░ 0.93
│ Momentum     : █████░░░░░ 0.52
│ Imbalance    : ████████░░ 0.82
│
│ Conviction: 0.74 ✓ (threshold 0.58) | dir SELL | agreement 1.00
│ Level: at PDL
│ ✅ reaction fired
└───────────────────────────────────────────────────────
```

---

## 04.2 Anticipation → reaction flip

When an anticipated setup is invalidated — a strong opposing reaction signal whose
conviction clears `flip_min_conviction` points the other way — the agent abandons
the anticipated trade and engages the reaction engine in the dominant-momentum
direction, targeting the next liquidity level before exhaustion.

This lives in `SignalLoop._decide_action` and is gated by `flip_enabled`. Flipped
trades are tagged `[FLIP]` in the logs, the notifier, and the journal.

---

## 04.3 Modes

A `--mode` flag (and `ReactionConfig.mode`) selects how the two engines combine:

| Mode | Behaviour |
| --- | --- |
| `anticipation` | Legacy: only the strategy/gate stack trades. |
| `reaction` | Only the reaction engine pulls the trigger. |
| `hybrid` *(default)* | Anticipation marks levels and still trades when confirmed; the reaction engine pulls the trigger on committed moves and can flip an anticipated setup. |

```bash
# Hybrid (default): anticipation marks levels, reaction triggers, flip enabled.
PYTHONPATH=. .venv/bin/python scripts/run_live.py \
    --broker exness --timeframe H1 --mode hybrid \
    --risk-min 0.005 --risk-max 0.02 --reset-journal --verbose
```

For full deployment steps see
[08 — Live Trading & Deployment](08-live-trading-and-deployment.md). To validate the
reaction engine over history, use the learning backtest in
[07.2](07-backtesting.md#072-learning-backtest).

---

## 04.4 Configuration reference

All thresholds live in `ReactionConfig` (`agent/config.py`) and can be tuned
without touching code:

- **Components:** `displacement_atr_mult`, `displacement_close_frac`,
  `expansion_lookback`, `expansion_mult`, `expansion_bars`, `momentum_lookback`,
  `momentum_atr_norm`, `imbalance_use_volume`, `imbalance_volume_lookback`.
- **Blend:** `weight_displacement/expansion/momentum/imbalance`,
  `conviction_threshold`.
- **Levels:** `level_proximity_atr_mult`, `require_level`.
- **Stop/target:** `stop_atr_mult`, `stop_buffer_pips`, `fallback_rr`, `min_rr`.
- **Flip:** `flip_enabled`, `flip_min_conviction`.
- **Mode:** `mode` (`anticipation` | `reaction` | `hybrid`).
