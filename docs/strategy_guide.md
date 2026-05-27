# EURUSD AI Trading Strategy — Complete Guide

## Executive Summary

This system is a human-AI collaborative trading engine for EURUSD, built around institutional order-flow concepts (ICT methodology) and enhanced with per-strategy machine learning scorers. Its edge comes from **two-phase entries** — detecting a structural event first, then *waiting* for price to confirm the thesis before entering — combined with quality grading, depletion tracking, and intelligent confluence optimization. On out-of-sample data (2024–2026), the system produces 92 trades at 33.7% win rate with a 4.37:1 average reward-to-risk on its primary strategy (LZI Retest), yielding a profit factor of 1.12, a Sharpe ratio of 0.72, and a +10.4% return on a $100 account.

---

## How We Got Here (Development Journey)

The system evolved through six intensive development sessions over May 2026, each informed by honest backtesting and trader feedback:

1. **Baseline build (Sessions 1–2):** Started with a generic multi-timeframe backtester using zone + fib + BOS detection. Initial results were mediocre — roughly 50% WR but profit factor below 1.0. The system entered too early, too often, on signals that looked good in isolation but lacked confirmation.

2. **Precision gating (Session 2–3):** A detector audit revealed the noise sources: bare zone entries (47% WR, -84 pips), BOS-only entries (39% WR, -144 pips), and London–NY overlap trades (-153 pips). Added precision partner requirements (need FVG or sweep alongside zone/BOS) and structural anchor gates. This cut trade count dramatically but raised quality.

3. **The core insight:** The human trader taught us the critical lesson — *wait for the retest, confirm the reaction, then target opposite-side liquidity.* This became the foundation of every primary strategy: detect the setup → DO NOT TRADE → wait for price to return and confirm → THEN enter.

4. **Two-phase rebuild (Session 6):** Each strategy was rebuilt with self-contained two-phase logic:
   - LZI: sweep → mark zone → wait for retest → consumption bars → displacement → enter
   - FVG: gap detected → quality graded → wait for price to return → reaction confirmed → enter
   - SD Zone: order block identified → quality scored → wait for retest → reaction confirmed → enter

5. **Per-strategy ML (Session 6):** Instead of one generic scorer for all setups, we trained strategy-specific models — most importantly the LZI scorer with 15 LZI-specific features (sweep type, consumption bar count, displacement strength, etc.).

6. **Confluence optimization (Session 6):** Built an intelligent booster selection system that measures each confluence factor's marginal lift per strategy, tests pairwise combinations for additivity vs redundancy, and selects the optimal booster subset in real-time.

7. **Result:** The unified system went from **-9.6% return** (v7 baseline with generic scoring) to **+10.4% return** on OOS 2024–2026 data, with 92 trades, 13.1% max drawdown, and a clear edge on Monday/Tuesday setups.

---

## System Architecture

### Primary Strategies (Two-Phase, Self-Validating)

These are the only strategies that generate entry signals. Each follows the same philosophy: detect a structural event, wait for price to confirm, then enter with a structural take-profit target. They never enter on the initial detection — the "wait" phase is what separates this system from retail algos that chase every signal.

---

#### 1. LZI Retest (Liquidity Zone of Interest)

**File:** `agent/strategy/strategies/liquidity_grab_reversal.py`

The system's highest-conviction strategy. It capitalizes on institutional liquidity sweeps — moments when price runs through a cluster of stop losses to fill large orders, then reverses.

**Two-phase logic:**

- **Phase 1 — Sweep Detection:** Price wicks aggressively through a prior swing high/low, PDH/PDL, or equal highs/lows. The wick must be significant (≥10 pips on H1, ≥15 pips on H4). At this point the system marks a *Liquidity Zone of Interest* — the area where stops were taken. **It does NOT trade.**

- **Phase 2 — Retest Confirmation:** The system waits (up to 50 bars) for price to return to the zone. On retest, it requires:
  1. **Proximity:** Price must reach within 5 pips of the zone.
  2. **Consumption:** At least 3 bars spending time in the zone (institutions absorbing remaining liquidity).
  3. **Displacement:** A strong candle (≥60% body ratio, ≥10 pips body on H1) moving away from the zone in the expected direction. This is the institutional "hand" showing.
  4. **Entry:** Placed on the close of the displacement candle.
  5. **Stop:** Below/above the zone with a 3-pip buffer.
  6. **Take-profit:** Opposite-side unswept liquidity via PD Array targeting (not arbitrary R:R).

**Dedicated ML scorer:** The LZI strategy has its own XGBoost model trained on 15 LZI-specific features: sweep type (PDH/PDL/swing/equal), sweep wick size, consumption bar count, displacement candle metrics, zone age, session timing, and HTF alignment. Threshold: 0.40 (relaxed vs generic 0.55, because the six-step internal validation already filters heavily).

**Gate profile:** Relaxed — precision partner, structural anchor, close confirmation, and minimum confluence gates are all bypassed. The six-step internal logic (sweep → zone → retest → consumption → displacement → PD target) is its own quality control. Only safety gates (R:R minimum, daily DD halt, max positions, stop bounds) remain active.

**Best conditions:** Choppy/ranging markets, session opens (London/NY), range edges, sweeps of daily levels (PDH/PDL/PWH/PWL).

**OOS performance (2024–2026):** 26.4% WR at 4.37:1 average R:R. Despite a low win rate, the extreme R:R makes this profitable — one winner pays for 3–4 losers.

---

#### 2. FVG Retest (Fair Value Gap)

**File:** `agent/strategy/strategies/fvg_retest.py` (conceptual — logic distributed across detectors and rule engine)

Fair value gaps represent price inefficiency — a three-candle pattern where the middle candle's range is entirely beyond the prior and next candles' ranges, leaving an unfilled gap. Institutions tend to return to fill these gaps before continuing.

**Quality grading:** Not all FVGs are equal. Each is scored (0–100) on:
- **Size:** Larger gaps indicate stronger commitment (measured in pips).
- **Creation aggressiveness:** How impulsive was the move that created it (body-to-range ratio of the middle candle).
- **Session:** FVGs created during kill zones (London 07–10 UTC, NY 13–16 UTC) are weighted higher.
- **Fill tracking:** How much of the gap has been filled by subsequent price action.

**Entry logic:**
1. FVG detected with quality score ≥ 40.
2. Wait for price to return to the gap.
3. Confirm reaction: rejection wick (≥2:1 wick-to-body ratio), engulfing candle, or displacement candle moving away from the gap.
4. Enter on confirmed reaction.

**Depletion:** FVGs visited 3+ times or 80%+ filled are considered depleted and removed from the active list. This prevents trading stale levels.

**Gate profile:** Relaxed — the FVG IS the precision partner, and quality scoring + reaction confirmation replaces structural anchor and close confirmation gates. False-breakout filter remains active (FVGs near false breakouts are poor entries).

**Best conditions:** Trending markets, continuation plays. Works best when confirmed by BOS context (BOS + FVG left behind = high conviction).

---

#### 3. SD Zone Retest (Supply/Demand)

**File:** `agent/strategy/strategies/sd_zone_retest.py` (conceptual — logic in detectors and rule engine)

Supply and demand zones mark where institutional orders were placed. Unlike traditional support/resistance (horizontal lines), SD zones are precise areas defined by the last opposing candle before a strong move — the "order block."

**Order-block precision:** The zone boundary is the last bearish candle before a bullish impulse (demand) or the last bullish candle before a bearish impulse (supply). This is where the unfilled institutional orders sit.

**Quality scoring (0–100):**
- **Origin type:** First-time breakout zones > retested zones. Zones created by liquidity sweeps are highest quality.
- **Base tightness:** Narrow consolidation before departure = stronger zone.
- **Departure strength:** How impulsive was the move away from the zone (body size, range, pip displacement).
- **Session:** Kill-zone origins weighted higher.
- **FVG left behind:** If the departure created an FVG, the zone is stronger (unfilled orders + price inefficiency).

**Depletion tracking:** Each revisit depletes the zone. First touch = full strength. Second touch = reduced. Third touch = mostly spent. This models the real-world dynamic of institutional orders being filled on each revisit.

**Entry logic:**
1. Quality SD zone identified (quality score above threshold).
2. Wait for price to return to the zone.
3. Confirm reaction: similar to FVG retest (rejection, engulfing, displacement).
4. Enter on confirmed reaction.

**Gate profile:** Relaxed — the zone IS the core level. Quality scoring + reaction confirmation + depletion tracking provides self-contained validation. False-breakout filter remains active.

**Best conditions:** Ranging/choppy markets, key structural levels, areas with historical institutional activity.

---

### Confluence Boosters (Never Standalone)

These factors enhance primary strategy signals. They are NEVER standalone entry triggers — they add conviction to setups identified by LZI, FVG, or SD Zone strategies.

---

#### Fibonacci Retracements

**File:** `agent/detectors/fib.py`, config in `FibConfig`

**Level hierarchy:**
- **OTE zone (61.8%–71.0%):** Highest weight. The "Optimal Trade Entry" zone where institutional retracements typically reverse. Setups within OTE get maximum confluence bonus.
- **50% (fair value):** Strong. Price returning to 50% of an impulse represents a fair-value retest.
- **38.2%:** Moderate. Valid in strong trends only — shallow pullbacks that don't reach deeper levels often indicate trend strength.
- **78.6%:** INVALIDATION signal. If price retraces to 78.6%, the impulse is considered dead — the trend has been broken. This is used as a *negative* signal, penalizing setups at this level.

**Quality gate:** Fibonacci levels are only drawn from impulses with a quality score ≥ 35 and a minimum size of 20 pips. This prevents drawing fibs from noise moves.

**Critical rule:** Fibonacci NEVER trades alone. It must accompany a primary strategy signal. A fib level at 61.8% means nothing without an LZI zone, FVG, or SD zone at that level.

---

#### Break of Structure (BOS)

**File:** `agent/detectors/bos.py`

BOS marks when price breaks a prior swing high (bullish BOS) or swing low (bearish BOS). It's a context signal that confirms trend direction.

**Quality scoring:**
- **Body break > wick break:** A candle that closes beyond the swing level is a higher-quality BOS than one that only wicks through it (which could be a fake-out).
- **Recent > ancient:** BOS from 5 bars ago is more relevant than BOS from 200 bars ago.
- **FVG left behind:** If the BOS move left an FVG, it's a high-quality structural break (price committed so hard it left inefficiency).

**Role:** Enhances FVG and SD Zone entries by confirming directional bias. BOS + FVG left behind = high-conviction continuation setup. **Never triggers entries by itself** — BOS-only entries had 39% WR and bled -144 pips in the detector audit.

---

#### Session Timing

**File:** `agent/detectors/sessions.py`

Kill zones are the windows when institutional volume is highest and price moves are most likely to be genuine:
- **London open (07–10 UTC):** European session; major moves, especially EURUSD.
- **NY open (13–16 UTC):** US session; high-impact news releases, trend reversals or continuations.

Entries during kill zones receive a score bonus. Off-session entries (Asia, dead zones between sessions) are penalized — not blocked, but the bar is higher.

**Blocked hours (NY time):** Hours 03, 04, 12, 13, 16, 17, 18 are fully blocked based on 3-year audit data showing statistically significant losses in these windows.

---

#### HTF Alignment

**File:** `agent/rules/engine.py` (htf_bias_mode)

D1 and H4 trend direction provide context for H1/M15 entries:
- **With-trend entries:** Score bonus. Trading in the direction of the daily trend has a statistical edge.
- **Counter-trend entries:** Score penalty. Not blocked, but the conviction threshold is higher.
- **Neutral HTF:** No adjustment. When D1/H4 show no clear trend (slope < 0.5 pips), entries are evaluated on their own merit.

Currently in "off" mode — available but not yet contributing to scoring. The infrastructure is built for when we want to activate it.

---

#### Daily Levels

**File:** `agent/detectors/daily_levels.py`

Key reference levels computed from prior sessions:
- **PDH/PDL:** Previous Day High/Low — where yesterday's range was.
- **PWH/PWL:** Previous Week High/Low — weekly context.
- **PDM/PWM:** Previous Day/Week Midpoint.

These serve two purposes:
1. **Zone identification:** Sweeps of PDH/PDL/PWH/PWL create LZI zones.
2. **PD Array targeting:** Opposite-side daily levels are used as take-profit targets (sweeping PDL? Target PDH).

---

### Meta-Layer (Intelligent Combination)

The meta-layer sits above individual strategies and boosters, making decisions about *which* signals to trust and *how* to combine them.

---

#### Confluence Optimizer

**File:** `agent/strategy/confluence_optimizer.py`

Not all confluence combinations are additive. Some boosters help specific strategies while hurting others. The optimizer:

1. **Measures marginal lift:** For each booster × strategy pair, calculates the change in win rate and profit factor when that booster is present vs absent.
2. **Tests pairwise combinations:** Some boosters are redundant together (e.g., two fib levels confirming the same thing) while others are synergistic (FVG + BOS = institutional commitment + trend confirmation).
3. **Selects optimal subset:** In real-time, given the active strategy and available confluences, picks the combination that maximizes expected value based on historical performance.
4. **Checks alignment:** Verifies that all selected boosters are pointing at the same price area. Divergent signals (fib says long, BOS says short) reduce conviction.
5. **Online learning:** Updates booster scores after each trade, adapting to changing market conditions.

---

#### Gate Profiles (Per-Strategy Quality Control)

**File:** `agent/config.py` (GateProfile class, GATE_PROFILES dict)

Each strategy has a custom gate profile that controls which quality gates apply:

- **Default profile:** All gates active. Used for any strategy without a custom profile.
- **LZI profile:** Relaxed. Disables precision partner, structural anchor, close confirmation, false-breakout filter, FVG-or-sweep-with-BOS, and minimum confluence gates. The six-step internal validation is sufficient. Only safety gates (R:R, DD halt, max positions, stop bounds) and ML scorer remain.
- **FVG profile:** Relaxed. FVG IS the precision partner; quality score + reaction replaces structural anchor and close confirmation. False-breakout filter stays on. ML scorer active with a slightly relaxed threshold (0.30 vs 0.35).
- **SD Zone profile:** Relaxed. Quality scoring + depletion + reaction provides self-contained validation. Similar to FVG profile.

---

#### SQS Rankings (Strategy Quality Score)

**File:** `agent/strategy/ranking.py`

Every completed trade receives a quality score (0–100) across five dimensions:

| Component | Max Points | What It Measures |
|-----------|-----------|------------------|
| Risk-Reward | 30 | Achieved R:R (capped at 3× for scoring) |
| Execution | 25 | Hold time efficiency — fast resolution = better |
| Zone Respect | 20 | MAE relative to stop size — price shouldn't deeply violate the zone |
| Timing | 15 | Entry during kill zones vs dead periods |
| Regime Fit | 10 | Was the strategy used in its preferred market regime? |

SQS tracks which strategy/timeframe/session combinations perform over time, building a performance database that informs future confidence levels. Strategies with consistently high SQS scores get more trust; those with declining scores are flagged for review.

---

#### Regime Router

**File:** `agent/regime/classifier.py`

Classifies current market conditions into regimes:
- **Trending (up/down):** Strong directional movement. Favors FVG Retest, BOS continuation.
- **Choppy:** Range-bound, mean-reverting. Favors LZI Retest, SD Zone Retest.
- **High-vol:** Wide ranges, rapid swings. All strategies require extra confirmation.
- **Low-vol:** Tight ranges, low-conviction moves. LZI and SD Zone can work; trend strategies struggle.

Each strategy has an affinity map (configured in `RankingConfig.regime_affinity`):
- LZI → chop, low_vol
- FVG → trending_up, trending_down
- SD Zone → chop, low_vol
- Fib → trending_up, trending_down, chop

The router doesn't block trades outright — it adjusts confidence scores based on regime-strategy fit. A trending-market LZI setup gets a penalty; a choppy-market FVG gets a penalty. Trading against your regime is allowed but requires higher conviction.

---

## Configuration Philosophy

### Caution Days (Thursday, Friday)

**Not blocked — the system CAN trade.** Both Thursday and Friday are designated as "caution days," meaning autonomous signals require an elevated score threshold (+0.15 boost to `score_threshold`). Only the highest-conviction setups pass.

**Rationale:**
- **Thursday:** Historical OOS data shows 30% WR, -74.4 pips, -$8.14 (2024–2026). Genuine moves do occur, but there's more noise as the market positions ahead of Friday.
- **Friday:** 22% WR, -82.8 pips, -$8.91 (2025–2026). End-of-week position squaring creates unpredictable volatility.

The elevated threshold ensures the system only takes Thursday/Friday trades when multiple independent signals align (high ML score + strong zone + kill-zone timing + trend alignment). The human partner can always override and take a trade the system flags but doesn't auto-execute.

### Timeframe Tiers

| Timeframe | Tier | Behavior |
|-----------|------|----------|
| H1 | Active | Primary timeframe. Proven edge: 62.5% WR OOS. Standard thresholds. |
| M15 | Dormant | Poor OOS (28.6% WR). Signals detected but require elevated threshold (+0.15) and extra confluence. Learning continues. |
| H4 | Bias only | Provides zone/trend context to H1/M15. Never enters trades. |
| D1 | Bias only | Daily bias and zone mapping. Never enters trades. |
| M5 | Disabled | No model trained. Too noisy for current gate configuration. |

The human partner can override dormant → active for a specific trade if they see something the system doesn't.

### Risk Management

- **1% risk per trade:** Position sized so that stop-loss = 1% of account equity.
- **3% daily drawdown halt:** If cumulative daily losses hit 3%, all trading stops for the day.
- **One position at a time:** No stacking. Ensures each trade gets full attention and risk allocation.
- **Kill switch:** Creating a `kill_switch` file in the project root immediately halts all trading. Emergency brake.
- **Breakeven at 1R:** Once a trade moves 1× the stop distance in our favor, stop is moved to entry (or entry + 0.2R if `be_lock_r` is set). Eliminates the "went 3R then stopped out at -1R" scenario.
- **Lot caps:** Hard caps based on account size — 0.01 lots under $300, 0.10 under $1,000, 1.0 max.

---

## Current Performance (OOS 2024–2026)

| Metric | Value |
|--------|-------|
| Total trades | 92 |
| Win rate | 33.7% |
| Profit factor | 1.12 |
| Sharpe ratio | 0.72 |
| Return | +10.4% ($100 → $110.40) |
| Max drawdown | 13.1% |
| Avg R:R (LZI) | 4.37:1 |
| Best day | Monday (40.7% WR) |
| Primary edge | LZI Retest + high R:R |

**By day of week (OOS):**

| Day | WR | Notes |
|-----|-----|-------|
| Monday | 40.7% | Best day — fresh weekly positioning |
| Tuesday | 35.2% | Second best — trends established |
| Wednesday | 33.1% | Average — mid-week noise increases |
| Thursday | 30.0% | Caution day — pre-Friday positioning noise |
| Friday | 22.0% | Caution day — end-of-week squaring |

**Development trajectory:**
- v6 baseline (generic scoring, no gates): -37.6%, 463 trades, 43.6% WR
- v7 (precision gates, blocked hours, day filters): -9.6%, 108 trades, 35.2% WR
- v8 (two-phase strategies, LZI scorer, confluence optimizer): +10.4%, 92 trades, 33.7% WR

---

## What Makes This Different From Retail Algos

1. **Two-phase entries:** Detect the structural event → WAIT for confirmation → enter only when price proves the thesis. Most retail algos enter on detection, getting swept by the noise the system is designed to exploit.

2. **Quality grading:** Not all zones, FVGs, or BOS events are equal. Each is scored on multiple dimensions (creation aggressiveness, session timing, depletion state, etc.). Low-quality signals are filtered before they reach the ML scorer.

3. **Order-flow thinking:** The system reads institutional intent — where are the stops? Where is the liquidity? Where did unfilled orders sit? — rather than just pattern-matching candle formations.

4. **PD Array targeting:** Take-profits are placed at structural targets (opposite-side unswept liquidity, unfilled FVGs, key daily levels) rather than arbitrary R:R ratios. This means TPs are placed where price is *likely to go* based on market structure, not where we *hope* it goes.

5. **Per-strategy ML:** Each strategy has its own brain. The LZI scorer knows about sweep types, consumption bars, and displacement metrics. The generic scorer handles FVG and SD Zone setups. This prevents one strategy's feature importance from dominating another's.

6. **Confluence optimization:** Instead of blindly stacking every available signal (which often adds noise), the optimizer measures each booster's actual marginal lift per strategy and selects only the combinations that are historically additive.

7. **Depletion awareness:** Zones, FVGs, and SD areas weaken with each revisit. The system tracks fill percentage and visit count, depreciating levels that have been worked over. Fresh, untouched zones get maximum weight; depleted ones are discarded.

8. **Human-AI partnership:** The system handles the grunt work — scanning hundreds of bars across multiple timeframes, scoring setups, tracking zone quality — while the human provides nuance, overrides on judgment calls, and teaches the system new patterns through journal ingestion. Neither operates alone.

---

*Last updated: 2026-05-27*
