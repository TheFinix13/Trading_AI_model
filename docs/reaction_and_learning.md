# Reaction engine, adaptive sizing & live learning

This document covers the quant upgrade that turned the agent from a pure
*anticipation* system (which waited for a full retest choreography and rarely
fired) into one that also **reacts to committed moves in present time**, **sizes
by risk**, and **learns from its own results day by day**.

Four pieces work together:

1. **Reaction engine** — measures committed price action and trades it.
2. **Anticipation → reaction flip** — abandons an anticipated trade when momentum
   commits hard the other way.
3. **Adaptive position sizing** — risks a conviction-scaled % of live equity.
4. **Learning journal + online performance memory** — present-time daily logs and
   a feedback loop that leans into what's working.

---

## 1. Reaction engine

Code: `agent/reaction/` (`components.py`, `engine.py`), config: `ReactionConfig`
in `agent/config.py`.

The anticipation stack asks *"will price react at this level?"* and waits for
touch → consume → reaction wick → displacement (an AND-chain that almost never
completes). The reaction engine instead asks *"is price committing **right now**
at a level I already marked?"* using four **measured** facts about the just-closed
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
max positions, sizing/margin) but does **not** require the full retest
choreography — committed displacement + momentum + imbalance at a level *is* the
confirmation.

`ReactionEngine.assess(...)` always returns a full `ReactionAssessment` (scores,
conviction, agreement, level, rejection reason) so the explainer can show *why* it
did or didn't react on every bar. `evaluate(...)` is the thin wrapper that returns
just the `ReactionSignal` when one fires.

---

## 2. Anticipation → reaction flip

When an anticipated setup is invalidated — a strong opposing reaction signal whose
conviction clears `flip_min_conviction` points the other way — the agent abandons
the anticipated trade and engages the reaction engine in the dominant-momentum
direction, targeting the next liquidity level before exhaustion.

This lives in `SignalLoop._decide_action` and is gated by `flip_enabled`. Flipped
trades are tagged `[FLIP]` in the logs, the notifier, and the journal.

---

## 3. Modes

A `--mode` flag (and `ReactionConfig.mode`) selects how the two engines combine:

| Mode | Behaviour |
| --- | --- |
| `anticipation` | Legacy: only the strategy/gate stack trades. |
| `reaction` | Only the reaction engine pulls the trigger. |
| `hybrid` *(default)* | Anticipation marks levels and still trades when confirmed; the reaction engine pulls the trigger on committed moves and can flip an anticipated setup. |

---

## 4. Adaptive / risk-based position sizing

Code: `agent/live/position_sizer.py` (`PositionSizer`, `SymbolConstraints`,
`SizingResult`).

The legacy `--lot` hard-coded one size regardless of stop distance. The sizer
instead computes the lot that risks **exactly** a chosen % of live balance:

```
lot = (balance × risk_pct) / (stop_distance_pips × pip_value)
```

then:

- rounds **down** to the broker lot step (never exceeds the risk budget),
- clamps to `[min_lot, max_lot]` (snaps a tiny account up to min lot only if the
  resulting risk stays within band),
- never exceeds free margin under leverage
  (`margin_per_lot = contract_size × price / leverage`),
- optionally caps at a manual `--lot` override.

**Conviction scaling:** `risk_pct` is interpolated within a band
(`--risk-min`…`--risk-max`, default 0.5%–2.0%) by signal conviction — a blend of
HTF alignment + ML score + setup quality for anticipation, and the reaction
composite for reaction trades. High conviction → more size; marginal → less.

Live balance, free margin and leverage are pulled from the broker
(`account_info`) on every trade. The full math is surfaced in the logs (see
below).

---

## 5. Learning journal + online performance memory

### Fresh present-time journal

Code: `agent/journal/live_journal.py` (`LiveJournal`).

The agent learns only from when it runs **now**. On startup with
`--reset-journal`, any existing live-journal files are moved aside into
`data/journal/archive/` (history is never deleted) and a fresh store is started
under `data/journal/live/`.

One file per calendar day (markdown + a JSONL sidecar):

- **Market read at the open** — HTF bias, anticipated vs reactive view, active zones.
- **Intraday notes** — moves, levels taken, flips.
- **Every trade** — entry/stop/TP, R:R, lot, conviction, setup signature, the
  full **sizing math**, and the rationale.
- **Every exit** — win/loss, P&L, pips, R-multiple, MAE/MFE, and a **loss-focused
  reflection** ("what would have made this better").
- A **full feature snapshot at entry** is written to the JSONL sidecar for later
  scorer retraining.

### Online performance memory (the learning loop)

Code: `agent/journal/performance_memory.py` (`PerformanceMemory`,
`make_signature`).

Each trade is keyed by a **setup signature**:

```
strategy | direction | session | htf_aligned | source(reaction|anticipation)
```

The memory tracks realised **win-rate** and **expectancy (R)** per signature and
returns a bounded **conviction adjustment** (±`max_adjustment`, ramped by sample
size, requires ≥ `min_samples` trades). That adjustment is added to a setup's
conviction *before* sizing — so the agent literally leans into the signatures that
have been working and de-weights the ones that haven't, without waiting for a
heavy offline retrain. State persists to JSON and survives restarts.

> The heavier follow-on — periodic full ML-scorer retraining on the captured
> feature snapshots — is intentionally separate. The journal captures exactly the
> data that retrain needs; this online memory is the always-on, day-to-day
> adaptation.

---

## 6. Running it live

```bash
# Hybrid (default): anticipation marks levels, reaction triggers, flip enabled.
PYTHONPATH=. .venv/bin/python scripts/run_live.py \
    --broker exness --timeframe H1 --mode hybrid \
    --risk-min 0.005 --risk-max 0.02 --reset-journal --verbose
```

Other modes: `--mode reaction` (reaction only) or `--mode anticipation` (legacy).
`--lot 0.05` acts as an upper cap on the risk-based size. `--reset-journal`
archives the old journal and starts fresh.

---

## 7. Reading the logs (what proves it's reacting & learning)

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

On a trade, the sizing math is shown:

```
SIZING: balance=$100.00 | conviction=0.73 -> risk=1.59% ($2.28) | stop=23p
        | lot=0.01 | margin=$1.15/$100.00 free | capped:min_lot
```

And the learning feedback prints on every close:

```
LEARN: Reaction|short|london|htfNA|reaction -> -1.07R | signature n=4 wr=0% exp=-0.33R next-adj=-0.013
```

The daily journal lives at `data/journal/live/YYYY-MM-DD.md` (+ `.jsonl`).

---

## 8. Learning backtest

Code: `scripts/run_learning_backtest.py`.

This mirrors the live agent over history: the reaction engine drives entries, the
`PositionSizer` sizes by risk % of the *current* equity (conviction-scaled, a
leverage mindset rather than fixed lots), and the performance memory updates
trade-by-trade so **each day's results feed the next day's conviction**. It writes
a separate per-day archive under `data/journal/backtest/` (distinct from live
logs) and prints the equity curve plus a final per-signature expectancy table.

```bash
PYTHONPATH=. .venv/bin/python scripts/run_learning_backtest.py \
    --years 2 --start-balance 100 --leverage 1000 --reset
```

Useful flags: `--max-bars N` (faster smoke runs), `--risk-min/--risk-max`,
`--max-hold` (time-stop in bars), `--timeframe`.

---

## 9. Configuration reference

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

Sizing band: `--risk-min` / `--risk-max` (CLI) → `LiveConfig.risk_min_pct` /
`risk_max_pct`. Performance memory: `min_samples`, `max_adjustment`.
