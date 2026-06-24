# EURUSD AI Trading Agent — Strategy Architecture

> ⚠️ **HISTORICAL — superseded by the zone-only validated pipeline.** This doc
> describes the **v1 multi-strategy stack** (LZI/FVG/SD-zone strategies, gate
> profiles, confluence optimizer, ML scorers, regime router, dashboard). That
> stack was **burned in the 2026-06-09 reset** after its OOS numbers proved to be
> overfitting; its concepts were then tested ALONE in the ablation grid and all
> but the supply/demand zone were **eliminated with data**. The "lead candidate"
> below (reaction + ERL/IRL) was likewise superseded: under the v2 fair-shot
> grids it showed no BH-significant edge. What trades live today is the
> **zone_d1_against router deployment** — see [00-journey.md](00-journey.md) and
> [CHECKPOINT.md](CHECKPOINT.md). Most modules referenced below no longer exist
> (see [audit/README.md](audit/README.md) for the burn list).

**Last updated:** 2026-06-09 (frozen as historical 2026-06-10)
**Status (at the time):** Under honest revalidation. The stacked rule engine's tuned OOS numbers
(PF 1.12, +10.4%, Sharpe 0.72) **do not survive** purged walk-forward (Phase A) and
isolated per-alpha measurement (Phase B) — see [10](10-quant-validation-and-modular-overhaul.md).
The system carries a present-time **reaction engine** ([04](04-reaction-engine.md)),
**risk-based adaptive sizing** ([05](05-position-sizing-and-risk.md)), and an
**online learning** loop ([06](06-learning-journal.md)); the current lead candidate
is the reaction engine + ERL/IRL liquidity magnets (see the modular-alpha section below).

> Part of the numbered docs — start at [00 — Overview](00-overview.md).

---

## Executive Summary

This system is a systematic trading agent for EURUSD that combines three primary 
strategies with intelligent confluence boosting and per-strategy risk controls. 
It was built iteratively through collaboration between a discretionary ICT-style 
trader and a quantitative framework, encoding the trader's market intuition into 
testable, repeatable logic.

**Key philosophy:** Every strategy uses a two-phase approach — detect the opportunity, 
then WAIT for confirmation before entering. This patience is what separates 
profitable from breakeven.

---

## How We Got Here (The Journey)

### Phase 1: Naive System (April 2026)
- Basic zone detection + BOS + fib → enter on touch
- Result: 50.7% WR but PF 0.84 (losing money to transaction costs)
- Problem: Entering too early, no quality filtering, no confirmation

### Phase 2: Gate Stack (May 2026 Week 1)
- Added precision partners, structural anchors, blocked hours
- Result: Reduced noise but also reduced trade count drastically
- Problem: One-size-fits-all gates blocked good setups too

### Phase 3: Liquidity Rewrite (May 2026 Week 4)
- Trader taught: "Don't trade the sweep — trade the RETEST"
- Built two-phase LZI system with PD Array targeting
- Dedicated LZI scorer with 15 purpose-built features
- Result: LZI profitable on OOS (26.4% WR at 4.37:1 R:R)

### Phase 4: Strategy Ecosystem (May 2026 Week 4)
- Applied same two-phase philosophy to FVG and SD Zones
- Quality grading for every detector (score 0-100)
- Reaction confirmation required (rejection wick, engulfing, displacement)
- Per-strategy GateProfiles (each strategy gets appropriate controls)
- Confluence Optimizer (scores which boosters help which strategy)
- Result: Unified system PF 1.12, +10.4% OOS, 13.1% max DD

---

## Architecture Overview

```
MARKET DATA (H1/H4/D1 candles)
        │
        ▼
┌─────────────────────────────────────────────┐
│         DETECTION LAYER                      │
│  Zones │ FVGs │ BOS │ Sweeps │ Fibs │ Levels│
│  (quality-scored, not just detected)         │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│      PRIMARY STRATEGIES (Two-Phase)          │
│                                              │
│  LZI Retest:   sweep → zone → retest →      │
│                consume → displace → ENTER    │
│                                              │
│  FVG Retest:   quality FVG → return →        │
│                reaction confirmed → ENTER     │
│                                              │
│  SD Zone:      order-block zone → fresh →    │
│                reaction confirmed → ENTER     │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│      CONFLUENCE BOOSTERS                     │
│  (enhance, never standalone)                 │
│                                              │
│  • Fibonacci OTE zone (61.8-71%)            │
│  • BOS quality (context signal)              │
│  • Session timing (London/NY killzones)      │
│  • HTF alignment (D1/H4 trend)              │
│  • Daily levels (PDH/PDL proximity)          │
│                                              │
│  Confluence Optimizer selects which          │
│  boosters help THIS specific setup           │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│      META-LAYER (Quality Control)            │
│                                              │
│  • GateProfile per strategy                  │
│  • ML Scorer (generic v8 + LZI-specific v1)  │
│  • Caution days (Thu/Fri = elevated bar)     │
│  • Blocked hours (low-edge NY hours)         │
│  • Risk manager (1% risk, 3% daily DD halt)  │
│  • SQS Rankings (track what works over time) │
│  • Regime Router (trending/chop/vol)         │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│      EXECUTION                               │
│                                              │
│  • Adaptive sizing (risk-%, conviction-      │
│    scaled, broker-constraint safe)           │
│  • PD Array TP targeting (opposite liquidity)│
│  • Breakeven at 1R                           │
│  • One position at a time                    │
│  • Kill switch (kill.txt file)               │
│  • Daily journal + online perf memory        │
└─────────────────────────────────────────────┘
```

The detection + strategy + meta layers above are the **anticipation** path. In
parallel, a **reaction engine** measures committed price action every bar and
pulls the trigger on present-time commitment at marked levels. The `--mode` flag
(`anticipation` | `reaction` | `hybrid`, default `hybrid`) selects how they
combine. See [04 — Reaction Engine](04-reaction-engine.md) for the reaction
engine and the anticipation→reaction flip,
[05 — Position Sizing & Risk](05-position-sizing-and-risk.md) for adaptive sizing,
and [06 — Learning Journal](06-learning-journal.md) for the learning loop.

---

## 01.1 Detection layer (detectors)

Each detector is a pure function (`list[Bar] → list[Detection]`): no state, no
side effects, so the whole suite can be precomputed once per backtest. Detector
mechanics (how each is computed and when it's valid) are documented in
[03 — HTF Context & Pattern Mechanics](03-htf-context-and-pattern-mechanics.md).

| File | What it detects |
|------|-----------------|
| `agent/detectors/zones.py` | Supply/demand zones (base + impulse; rolling local median). The one required factor by default. |
| `agent/detectors/fvg.py` | Fair value gaps (unfilled 3-candle imbalances), with fill tracking. |
| `agent/detectors/bos.py` | Break of structure (swing high/low violations), body vs wick quality. |
| `agent/detectors/fib.py` | Fibonacci retracements (38.2 / 50 / 61.8 / 78.6) off the last significant swing. |
| `agent/detectors/daily_levels.py` | PDH/PDL/PDM, PWH/PWL/PWM — no look-ahead. |
| `agent/detectors/liquidity_sweep.py` | Tagged sweeps (names what was swept: PDH, swing_high, equal_lows…). |
| `agent/detectors/sessions.py` | Session labels (Asia/London/NY/overlap), DST-aware. |
| `agent/detectors/range_phase.py` | ICT Power of Three (accumulation → manipulation → distribution). |
| `agent/detectors/pd_array.py` | Next unswept PD-array / liquidity level used for take-profit targeting. |
| `agent/detectors/trendlines.py`, `liquidity.py`, `swings.py`, `atr.py` | Trendlines, liquidity wicks, swings, ATR (volatility-aware tolerance). |

Two evaluation modes feed off these: `RuleEngine.evaluate()` (live, detect from
scratch on the latest bars) and `evaluate_precomputed()` (backtests — run
detectors once, slice by index, ~100× faster).

---

## Primary Strategies (Detail)

> This is the architecture-level summary. The full per-strategy playbook (entry
> choreography, quality grading, gate profile, best conditions) lives in
> [02 — Strategies](02-strategies.md).

### 1. LZI Retest (Liquidity Zone of Interest)

**Philosophy:** When smart money grabs liquidity (sweeps stops), they leave 
unfilled orders in the wick zone. Price WILL return to fill those orders. 
We trade the return, not the sweep itself.

**Detection (Phase 1):**
- Bar wick pierces a tagged level (PDH/PDL/PWH/PWL/swing/equal)
- Bar closes back inside (failed breakout = confirmed grab)
- Wick size ≥ 10 pips (H1) or 15 pips (H4)
- Mark wick range as Liquidity Zone of Interest

**Entry (Phase 2):**
- Wait for price to return to the LZI (retest)
- Confirm consumption: 3+ bars inside/touching the zone
- Confirm displacement: strong candle (body > 60%, > 10 pips) closes away
- Enter at displacement close

**Stop:** Beyond the LZI extreme + 3 pip buffer
**Target:** Nearest unswept opposite-side liquidity (PD Array)
**Average R:R:** 4.37:1
**ML Scorer:** Dedicated LZI scorer (15 features, threshold 0.40)
**Gate Profile:** Self-validating (bypasses generic gates)

### 2. FVG Retest (Fair Value Gap)

**Philosophy:** Institutional displacement leaves imbalances (FVGs) in price. 
These are unfilled orders that price WILL return to. But not all FVGs are 
equal — only quality ones with aggressive creation deserve attention.

**Quality Grading (0-100):**
- Size: 15+ pips = 25 pts
- Creation aggressiveness: body > 80% = 25 pts  
- Session: London/NY killzone = 20 pts
- Fill status: unfilled = 15 pts (degrades with each revisit)

**Entry:**
- Only FVGs with quality ≥ 40
- Max 2 revisits, fill < 80%
- Must see reaction: rejection wick (50%+ wick) OR engulfing OR displacement
- Enter on reaction candle close

### 3. SD Zone Retest (Supply/Demand)

**Philosophy:** Zones form where institutions accumulated orders (the "base" 
before a displacement move). The zone boundary is the ORDER BLOCK — the last 
opposing candle before the move, not the whole consolidation.

**Quality Grading (0-100):**
- Origin type: rally-base-drop/drop-base-rally = 15 pts
- Base tightness: 1-2 candles = 15 pts
- Departure aggressiveness: body > 75% = 20 pts
- FVG left behind: +10 pts
- Session: killzone = 15 pts
- Width vs ATR: proportional = 10 pts
- Depletion: -5 per revisit

**Entry:**
- Quality ≥ 45, not depleted (revisits < 3, fill < 80%)
- Reaction confirmation required
- Enter on reaction candle close

---

## Confluence Boosters (Detail)

### Fibonacci (OTE Zone)
- Only drawn from quality impulses (score ≥ 35)
- Active levels: 38.2%, 50%, 61.8%, 70.5%
- OTE Zone (61.8-71%): highest weight
- 78.6% = INVALIDATION (trend thesis dead)
- NEVER standalone — enhances primary strategies only

### BOS (Break of Structure)
- Quality-scored: body break >> wick break
- Recency matters: break within 20 bars = significant
- Context only: confirms trend direction for FVG/LZI
- Bonus: if BOS leaves an FVG behind → that FVG gets extra quality

### Session Timing
- London open (07-10 UTC): sweeps and FVGs here are institutional
- NY open (13-16 UTC): highest volume, strongest moves
- Asia: signals here are weaker (retail activity)
- Off-session: lowest confidence

### HTF Alignment
- D1/H4 trend direction informs H1 entries
- Trading WITH the higher timeframe = higher WR
- Against HTF = only if very high confluence

### Daily Levels
- PDH/PDL: previous day's high/low (key liquidity pools)
- PWH/PWL: previous week's high/low
- Used as both sweep targets AND TP levels (PD Array)

---

## Meta-Layer (Detail)

### 01.2 Gate profiles

**Code:** `agent/config.py` (`GateProfile` class, `GATE_PROFILES` dict).

Each strategy carries a custom gate profile that controls which quality gates
apply, so one strategy's controls don't strangle another's:

- **Default** — all gates active (precision partner, structural anchor, close
  confirmation, false-breakout filter, minimum confluence). Used for any strategy
  without a custom profile.
- **LZI** — self-validating. Disables precision partner, structural anchor, close
  confirmation, false-breakout filter, FVG-or-sweep-with-BOS, and min-confluence;
  the six-step internal logic (sweep → zone → retest → consume → displace → PD
  target) is its own quality control. Only safety gates (R:R, DD halt, max
  positions, stop bounds) + ML scorer remain.
- **FVG** — relaxed. The FVG *is* the precision partner; quality score + reaction
  replaces structural anchor and close confirmation. False-breakout filter stays
  on; ML threshold slightly relaxed (0.30).
- **SD Zone** — relaxed. Quality scoring + depletion + reaction is the
  self-contained validation. Similar to FVG.

The **reaction engine** uses its own lighter gate set (see
[04](04-reaction-engine.md)) — committed displacement + momentum + imbalance at a
level is the confirmation, but the hard risk gates still apply.

### 01.3 Confluence optimizer

**Code:** `agent/strategy/confluence_optimizer.py`.

Not all confluence combinations are additive. The optimizer:

- measures each booster × strategy pair's marginal lift (Δ win-rate / Δ PF when
  present vs absent),
- tests pairwise combinations for additivity vs redundancy (FVG + BOS is
  synergistic; two fibs confirming the same thing is redundant),
- selects the optimal booster subset in real time for the active strategy,
- checks alignment (all boosters pointing at the same price area), and
- updates booster scores after each trade (online learning).

Two related meta-components ride alongside it:

- **SQS rankings** (`agent/strategy/ranking.py`) — every closed trade gets a 0–100
  Strategy Quality Score across risk-reward, execution, zone respect, timing and
  regime fit, building a per strategy/TF/session performance database.
- **Regime router** (`agent/regime/`) — classifies trending / chop / high-vol /
  low-vol and adjusts (does not block) conviction by strategy-regime affinity
  (LZI & SD Zone favour chop/low-vol; FVG favours trends).

### Caution Days (Thu/Fri)
- NOT blocked — just elevated bar (+0.15 score threshold)
- Requires positive confluence booster
- Human can always override

### Risk Management

Risk-based adaptive sizing (conviction-scaled within a band, respecting lot step,
min/max lot and free margin), the 3% daily DD halt, one-position-at-a-time,
breakeven at 1R and the file-based kill switch are all documented in
[05 — Position Sizing & Risk](05-position-sizing-and-risk.md).

---

## Reaction Engine & Online Learning

The anticipation stack waits for a full retest choreography and rarely fires. A
**reaction engine** (`agent/reaction/`) trades present-time commitment instead —
measured displacement, range expansion, momentum and order-flow imbalance at a
pre-marked level — using a lighter gate set so it actually pulls the trigger. An
**anticipation→reaction flip** abandons an anticipated setup when momentum commits
hard the other way. A fresh per-day **learning journal** (`data/journal/live/`)
plus an **online performance memory** (expectancy per setup signature) feed
results back into conviction so the agent leans into what's working. Full detail,
log examples and run commands: **[04 — Reaction Engine](04-reaction-engine.md)**,
**[05 — Position Sizing & Risk](05-position-sizing-and-risk.md)**, and
**[06 — Learning Journal](06-learning-journal.md)**.

---

## Performance (OOS Test: 2024-2026)

| Metric | Value |
|--------|-------|
| Trades | 92 |
| Win Rate | 33.7% |
| Profit Factor | 1.12 |
| Sharpe | 0.72 |
| Max Drawdown | 13.1% |
| Return | +10.4% |
| Avg R:R | ~3.2:1 |

---

## Modular alpha layer (decomposition for honest measurement)

> ⚠️ **Important caveat on the OOS table above.** Those numbers come from the
> *stacked* rule engine. When the same concepts are measured **in isolation under
> a clean fill model** (Phase B), none of the five anticipation strategies shows a
> standalone out-of-sample edge, and a fill-state **look-ahead** was found to have
> inflated FVG results. Treat the stacked numbers with suspicion until the
> rebuild lands. Full diagnosis: [10 — Quant Validation & Modular Overhaul](10-quant-validation-and-modular-overhaul.md).

To fight overfitting we decomposed the tangled engine into **alphas** — one
isolated trading concept each — that can be kept or cut individually on data we
haven't fit to. See `agent/alphas/`.

- **`Alpha` interface** (`agent/alphas/base.py`): `signal(actx, i) -> AlphaSignal|None`.
  Causal by contract (uses only `bars[:i+1]`). Strategies and the reaction engine
  are wrapped as alphas via thin adapters.
- **Isolated fill model** (`agent/alphas/backtest.py`): every alpha runs through
  the *same* simulator — market entry on the next open, stop/TP **re-anchored to
  the fill** with the signal's own risk geometry, intra-bar worst-case SL, one
  position at a time. No gates, no ML, no BE migration: we measure each concept's
  *raw* edge, not the gated blob. A causal FVG fill-state tracker prevents the
  look-ahead leak described in doc 10.
- **Per-alpha scorecards** (`scripts/evaluate_alphas.py`): expectancy / PF / WR /
  Sharpe / maxDD with bootstrap CIs, and a sample-size guard (a great win rate over
  a handful of trades is flagged `thin`, not `EDGE`).
- **Correlation-aware meta-allocator** (`agent/alphas/allocator.py`): mean-variance
  (tangency) weights with covariance shrinkage, long-only, so two alphas firing the
  same trade don't double-size. Reports the ensemble vs the best single alpha.

**Current standings (dev span H1, 2015→2025-12).** The five anticipation
strategies are all noise/negative standalone. The reaction engine alone is a coin
flip. The **reaction engine + ERL/IRL liquidity magnets** is the single best alpha
(expectancy +5.47 pips, PF 1.16, maxDD 10.1%, Sharpe 0.92) with a CI lower bound
just below zero — promoted to **lead candidate**, pending sealed-test confirmation,
and handed **79.8%** of the correlation-aware book (the ensemble doesn't beat it
alone). See the full table in [10 §10.4](10-quant-validation-and-modular-overhaul.md).

**Reaction-engine variants under measurement.** Because the reaction path is the
lead, its risk/targeting nuances are scored as sibling alphas rather than baked in:
`reaction_erl_irl` (ERL/IRL magnets), `reaction_htf_draws` and
`reaction_erl_irl_htf` (target the **deep daily demand/supply draw** — built
causally over the full series, symmetric for supply-above and demand-below, see
`agent/context/htf_draws.py`), plus an optional managed-exit (partial scale-out)
A/B via `--manage`. Findings so far: partial scaling and deep-draw targeting are
each **net-neutral-to-negative** on the lead alpha (deep draws *do* cut drawdown ~⅓
on the ERL variant) — so both ship measured-but-off, and the runner-to-nearest-draw
default stands. Detail in [10 §10.5](10-quant-validation-and-modular-overhaul.md).

---

## What's Next

1. Train FVG-specific and SD Zone-specific scorers (like we did for LZI)
2. Volume profile integration (HVN/LVN/POC from M1 data)
3. Order flow approximation (delta, CVD divergence)
4. Periodic full scorer retraining on the journal's captured entry-feature
   snapshots (the heavy follow-on to the always-on online performance memory)
5. Continuous learning from user feedback (drawing → analysis loop)

**Recently shipped:** present-time reaction engine + anticipation→reaction flip,
risk-based conviction-scaled position sizing, fresh per-day learning journal with
an online performance-memory feedback loop, and a learning backtest
(`scripts/run_learning_backtest.py`). Live demo on Exness via MT5 is wired through
`scripts/run_live.py --mode hybrid`.

---

*This document was the v1 source of truth. It is preserved as history; the
current source of truth is [CHECKPOINT.md](CHECKPOINT.md).*
