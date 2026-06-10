# 04 — Reaction Engine & Anticipation→Reaction Flip

> ⚠️ **HISTORICAL — the reaction engine no longer trades live by default.**
> This doc describes the v1 reaction engine as the primary live trigger. After
> the 2026-06-09 reset and the ablation pipeline, the reaction path never
> demonstrated a validated edge; `scripts/run_live.py` now trades the
> **validated zone router** by default, and the `ReactionAlpha` survives only as
> an explicit `--alpha reaction` escape hatch (UNVALIDATED / experimental —
> never on a funded account). The anticipation→reaction flip, `--mode` flags,
> impulse override, session-awareness and ERL/IRL draw-bias described below were
> removed or reset in v2. See [00-journey.md](00-journey.md) and
> [CHECKPOINT.md](CHECKPOINT.md).

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

## 04.2a Impulse override — reacting to clean moves in open space

**Code:** `ReactionEngine.assess` · **Config:** `impulse_override_enabled`,
`impulse_min_conviction` (0.66), `impulse_min_displacement` (0.45),
`impulse_min_expansion` (0.60).

The Jun-2026 Friday post-mortem exposed a real gap. On the violent break to the
lows the engine *measured* the move correctly — a 55-pip displacement bar scored
**conviction 0.92 SHORT** — but the **continuation** bars (0.77, 0.64) were
*declined* with `no level of interest at price`: price had run into open space
*between* marked levels, and `require_level` refused to react. A quant reacts to
the impulse itself.

The impulse override lets a reaction fire **without an adjacent level** when the
move is a genuine volatility ignition — conviction, displacement **and** range
expansion all clear higher floors (so we only chase real impulses, not noise).
Ordinary, non-impulsive reactions still need a level. Re-running that Friday, the
13:00 / 14:00 / 15:00 continuation shorts now fire instead of being skipped.

Validated on the 2-yr H1 learning backtest: the override is **performance-neutral
on aggregate** (89→90 trades, expectancy −0.025R and PF 0.88 both unchanged) —
impulses in open space are rare, so it almost never changes the average week, but
it makes the agent *participate* on the high-impulse days that matter (it is the
direct answer to "react like a quant to high impulsive moves").

## 04.2b ERL / IRL liquidity magnets (internal-to-external range framing)

**Code:** `agent/detectors/liquidity_magnet.py` · **Config:** `liquidity_magnet_enabled`
(**off by default**), `range_lookback_bars`, `magnet_*`, `range_premium_frac`.

This encodes the "internal-to-external range liquidity" framing: the dealing-range
extremes are **External Range Liquidity (ERL)** — the *draw*, where price wants to
go; unfilled FVGs and minor swing pools inside are **Internal Range Liquidity (IRL)**
— inefficiencies to rebalance and minor stops to raid. When on, the ERL extremes
join the reaction level set (so impulse moves toward them register and target
them) and a **draw bias** adjusts conviction: *fade* an external draw (short the
premium / long the discount), *penalise chasing into* it.

**Measured and left OFF by default.** On the 2-yr H1 EURUSD learning backtest the
"fade the draw" bias **degrades** performance (PF 0.88 → 0.69, expectancy −0.025R
→ −0.144R) and the extra levels are a mild drag (PF → 0.86). The reason is honest
and important: *fade the external draw* is a **ranging-market** tactic, but EURUSD
**trends** — fading draws is counter-trend bleed (shorting strength, buying
weakness). The module ships complete and unit-tested, but stays disabled until it
is **regime-gated** (only fade in a balanced/ranging HTF context; ride the draw in
a trend). This is exactly the "add it only if it improves what we have" discipline:
the data said it doesn't, as a blanket rule, so it is not enabled.

## 04.2c Breakouts, fakeouts, stop losses — and "does it wait for the close?"

**Yes — the reaction engine works on _closed_ bars and the exits confirm on close.**
Three places make the hunt-vs-real-breakout distinction:

1. **Entry on a breakout.** A reaction only treats a level break as tradeable when
   the bar **closes** beyond the level *in the trade direction* on a high-displacement
   bar (`_level_context`, `displacement ≥ 0.5`). A wick that pokes through and snaps
   back does **not** close beyond → no breakout entry. That is the difference between
   a *hunt* (wick, weak/indecisive close) and *acceptance* (a strong close beyond).
2. **Fading the hunt.** The LZI / two-phase liquidity detector
   ([02 — Strategies](02-strategies.md)) is built to do the opposite of chasing: it
   waits for the sweep of an obvious pool, the **return** to the zone, and a
   displacement *away* — i.e. it sells *after* buy-side liquidity is taken, which is
   the reels' "wait for the sweep, then enter the other way."
3. **Stops that survive the hunt.** The **synthetic soft stop**
   ([05 — Position Sizing & Risk §05.5](05-position-sizing-and-risk.md)) holds the
   real risk level in memory and only exits on a **confirmed close** beyond it, so a
   single hunting wick does not stop the trade out; a wide *catastrophe* stop rests
   on the broker only as an offline backstop. A `panic` rule still exits intrabar if
   price blows clean through, so a genuine breakdown is not ridden to the backstop.

So the agent neither chases naked breakouts nor sits naked: it waits for the close
to tell hunt from acceptance, both on the way in and on the way out.

## 04.2d Session awareness — the overlap is the reaction engine's window

The London/NY **overlap** (08:00–12:00 NY) is where the impulsive moves the user
cares about erupt — the Friday 9am-NY sweep being the canonical example. Historically
the overlap was **blocked outright** for every setup (`RulesConfig.blocked_session_tags`
= `["session_london_ny_overlap"]`), a rule tuned on a single in-sample week that did
**not** survive OOS validation (Phase A purged walk-forward + Phase B per-alpha
scorecards — see [10](10-quant-validation-and-modular-overhaul.md)).

That block is now **removed** (`blocked_session_tags = []`). Instead the overlap is
made *essential and conditional for the reaction engine*: `_session_bias` adjusts
reaction conviction by the bar's session (`ReactionConfig.session_aware`). The engine
is allowed to react during the majors (`high_impulse_sessions` = overlap / London / NY)
and is **dampened** in the dead hours (Asia / off-session), so it effectively requires
a high-liquidity session to fire — leaning into the windows where committed moves
actually happen rather than being silenced there.

**Why a penalty, not a boost.** A per-alpha sweep (EURUSD H1, 4y to 2025-12) showed a
conviction *boost* in the busy windows just **dilutes** the edge — it lowers the
effective bar and lets in more marginal trades. The win is *selectivity*: a small
off-session penalty trims dead-hour reactions for the same expectancy at a modestly
lower drawdown (≈10%→8%). So `session_conviction_boost` defaults to **0.0** and
`off_session_conviction_penalty` to **0.08**. The matcher accepts both the raw label
(`london_ny_overlap`) and the prefixed confluence tag (`session_london_ny_overlap`).

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
- **Impulse override:** `impulse_override_enabled`, `impulse_min_conviction`,
  `impulse_min_displacement`, `impulse_min_expansion`.
- **ERL/IRL magnets (off by default):** `liquidity_magnet_enabled`,
  `range_lookback_bars`, `magnet_proximity_atr_mult`, `magnet_conviction_boost`,
  `magnet_chase_penalty`, `range_premium_frac`.
- **Stop/target:** `stop_atr_mult`, `stop_buffer_pips`, `fallback_rr`, `min_rr`.
- **Flip:** `flip_enabled`, `flip_min_conviction`.
- **HTF filter:** `reaction_htf_boost`, `reaction_htf_penalty`.
- **Session awareness:** `session_aware`, `high_impulse_sessions`,
  `session_conviction_boost` (default 0.0), `off_session_conviction_penalty`
  (default 0.08). The overlap block in `RulesConfig.blocked_session_tags` is now
  empty by default.
- **Mode:** `mode` (`anticipation` | `reaction` | `hybrid`).
