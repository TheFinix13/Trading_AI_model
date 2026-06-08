# EURUSD AI Trading Agent — Strategy Architecture

**Last updated:** 2026-06-08
**Status:** Profitable on OOS data (PF 1.12, +10.4%, Sharpe 0.72). Now augmented
with a present-time **reaction engine**, **risk-based adaptive sizing**, and an
**online learning** loop — see
[reaction_and_learning.md](reaction_and_learning.md).

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
combine. See [reaction_and_learning.md](reaction_and_learning.md) for the reaction
engine, the anticipation→reaction flip, adaptive sizing, and the learning journal.

---

## Primary Strategies (Detail)

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

### Confluence Optimizer
- Scores each booster's WR lift per strategy
- Tests pairwise combos for additivity vs redundancy
- Checks price alignment (are boosters pointing at same price?)
- Online learning: updates after each trade

### GateProfiles
- Each strategy has tailored quality controls
- LZI: self-validating (bypasses generic gates)
- FVG/SD Zone: relaxed structural anchor (their scoring IS structural)
- Legacy: all gates active

### Caution Days (Thu/Fri)
- NOT blocked — just elevated bar (+0.15 score threshold)
- Requires positive confluence booster
- Human can always override

### Risk Management
- Risk-based adaptive sizing: conviction-scaled within a band (default 0.5%–2.0%),
  respecting lot step, min/max lot and free margin (see
  [reaction_and_learning.md](reaction_and_learning.md))
- 3% daily drawdown halt
- One position at a time
- Breakeven at 1R
- Kill switch (file-based)

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
log examples and run commands: **[reaction_and_learning.md](reaction_and_learning.md)**.

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

*This document is the single source of truth for the trading strategy. 
Update it whenever strategies are modified.*
