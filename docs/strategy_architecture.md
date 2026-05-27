# EURUSD AI Trading System — Strategy Architecture

**Version:** v9b (May 2026)  
**Status:** Profitable on OOS (2024-2026): +10.4%, PF 1.12, Sharpe 0.72, Max DD 13.1%

---

## Philosophy

This system is a **dual-partnership trading agent** — combining a discretionary trader's pattern recognition with systematic execution. Every component answers two questions:

1. **WHY** does this pattern work? (institutional order flow logic)
2. **WHEN** does it apply? (regime, session, quality grading)

The system does NOT blindly trade patterns. It understands the intent behind price action.

---

## How We Got Here (Development Journey)

### Phase 1: Naive Detection (April 2026)
- Built basic detectors: zones, FVGs, BOS, fibs, trendlines
- Rules engine counted confluences: more = better
- Result: 50.7% WR but PF 0.84 (losing money after fees)
- Problem: entering on DETECTION without CONFIRMATION

### Phase 2: Gate Stack (May 2026, Week 1)
- Added precision gates, blocked hours, session filters
- Reduced noise from thousands of signals to ~73 trades
- Result: still breakeven-to-negative. Gates reduced bad trades but also blocked good ones.

### Phase 3: Two-Phase Philosophy (May 2026, Week 4)
- Key insight from the human partner: "You don't trade the sweep. You trade the RETEST."
- Rebuilt every strategy with: Detect → Wait → Confirm Reaction → Enter
- Added quality grading to every detector (not all zones/FVGs/sweeps are equal)
- Added PD Array targeting (targets based on market structure, not arbitrary R:R)
- Result: +10.4% OOS, profitable system

### Phase 4: Intelligence Layer (Current)
- Per-strategy ML scorers (LZI has its own model with 15 purpose-built features)
- Confluence Optimizer (learns which boosters help which strategy)
- SQS Rankings (tracks strategy/timeframe/session performance over time)
- Gate Profiles (each strategy has tailored quality control, not one-size-fits-all)

---

## System Architecture

### PRIMARY STRATEGIES (Two-Phase, Self-Validating)

#### 1. LZI Retest (Liquidity Zone of Interest)
**Edge:** Institutional order flow footprints via sweep-and-retest

**How it works:**
1. A significant wick (≥10 pips H1, ≥15 pips H4) sweeps a tagged level (PDH/PDL/PWH/PWL/swing/equal levels)
2. Bar closes back inside (confirmed failed breakout = liquidity grab)
3. System marks the wick range as a Liquidity Zone of Interest — does NOT trade
4. Waits for price to RETURN to the zone (retest)
5. Confirms consumption: 3+ bars spending time in/near the zone (orders filling)
6. Confirms displacement: strong candle (body >60%, >10 pips) closes away from zone
7. ENTERS in the reversal direction
8. Stop: beyond zone extreme + 3 pip buffer
9. TP: nearest unswept opposite-side liquidity (PD Array targeting)

**Dedicated ML Scorer:** 15 LZI-specific features (wick quality, retest speed, displacement strength, session context, trend alignment). Threshold: 0.40.

**Performance:** 26.4% WR at 4.37:1 R:R (profitable — breakeven is 18.6%)

---

#### 2. FVG Retest (Fair Value Gap)
**Edge:** Institutional imbalances that price returns to fill

**How it works:**
1. Detects 3-candle imbalances (gap between candle 1 high and candle 3 low)
2. Grades quality (0-100): size, creation aggressiveness, session, fill status, revisit count
3. Only trades FVGs with quality ≥ 40, fill < 80%, revisits ≤ 2
4. Waits for price to return to the FVG zone
5. Confirms reaction: rejection wick (50%+ on correct side), engulfing, OR displacement
6. ENTERS on confirmed reaction
7. Stop: beyond FVG boundary
8. TP: structural target (next swing level)

**Quality factors:** FVGs created during London/NY open with displacement > 65% body and leaving no prior fill are highest quality.

---

#### 3. SD Zone Retest (Supply/Demand Order Blocks)
**Edge:** Institutional accumulation footprints at key levels

**How it works:**
1. Detects zones using order-block precision (last opposing candle before displacement)
2. Grades quality (0-100): origin type (rally-base-drop/drop-base-rally), base tightness (1-3 candles ideal), departure aggressiveness, session, FVG left behind, width vs ATR
3. Tracks depletion: each revisit depletes remaining orders, fill % tracked
4. Only trades zones with quality ≥ 45, not depleted (revisits < 3, fill < 80%)
5. Waits for fresh zone touch + reaction confirmation
6. ENTERS on confirmed reaction
7. Stop: beyond zone extreme
8. TP: structural target

**Key nuance:** More touches = WEAKER zone (orders draining), not stronger.

---

### CONFLUENCE BOOSTERS (Never Standalone)

#### Fibonacci
- OTE Zone (61.8%-71.0%) = maximum weight
- 50% = fair value equilibrium (strong)
- 38.2% = shallow pullback (moderate, only in strong trends)
- 78.6% = INVALIDATION level (if reached, all fibs from that impulse are dead)
- Only drawn from quality impulses (score ≥ 35, size ≥ 20 pips, displacement-driven)
- NEVER enters alone — must confirm another primary strategy

#### BOS (Break of Structure)
- Context signal only — confirms trend direction
- Quality scored: body break >> wick break, recent swing >> ancient, killzone >> off-session
- Enhances FVG entries when structure breaks clean with FVG left behind
- NOT a standalone entry trigger

#### Session Timing
- London Open (07-10 UTC) and NY Open (13-16 UTC) = kill zones (highest institutional volume)
- Kill-zone entries get bonus conviction
- Asia/off-session = reduced conviction

#### HTF Alignment
- D1/H4 trend direction confirms or contradicts LTF entries
- Trading WITH the higher TF trend = bonus conviction
- Counter-trend setups need extra confluence to compensate

#### Daily Levels (PDH/PDL/PWH/PWL)
- Proximity to previous day/week highs and lows
- Used for sweep detection and TP targeting
- NOT entry triggers — context for other strategies

---

### META-LAYER (Intelligence)

#### Confluence Optimizer
- Scores each booster individually per strategy (marginal WR lift)
- Tests pairwise combinations for additivity vs redundancy
- In real-time: selects optimal booster subset for each setup
- Checks price alignment (boosters pointing at same area = high conviction)
- Updates online from every new trade (exponential moving average)

#### GateProfiles
- Each strategy has its own gate configuration
- LZI: bypasses most gates (its 6-step internal validation is more rigorous)
- FVG/SD Zone: bypass structural anchor (quality scoring replaces it)
- Legacy: full gate stack active
- Essential safety gates always on: R:R check, DD halt, position limits

#### SQS Rankings (Strategy Quality Score)
- Scores each trade 0-100 across 5 dimensions:
  - Risk-Reward Actual (0-30)
  - Execution Efficiency (0-25)
  - Zone Respect / MAE (0-20)
  - Timing (0-15)
  - Regime Bonus (0-10)
- Ranks strategies, timeframes, and sessions by cumulative performance

#### Regime Router
- Classifies market: trending / choppy / high-vol / low-vol
- Routes signal priority: LZI thrives in chop, FVG thrives in trends
- Multiple strategies can fire; highest SQS-ranked wins

---

## Risk Management

| Parameter | Value |
|---|---|
| Risk per trade | 1% of balance |
| Daily DD halt | 3% |
| Max open positions | 1 |
| Lot sizing | Adaptive (0.01 under $300, 0.10 under $1000) |
| Breakeven trigger | Move stop to entry at 1R profit |
| Kill switch | `kill.txt` file halts all trading |
| Caution days | Thursday + Friday (threshold += 0.15) |
| Blocked hours (NY) | 03, 04, 12, 13, 16, 17, 18 |

---

## Performance Summary

| Metric | Training (2020-2023) | Test OOS (2024-2026) |
|---|---|---|
| Trades | 288 | 92 |
| Win Rate | 44.8% | 33.7% |
| Profit Factor | 1.45 | 1.12 |
| Sharpe Ratio | 2.32 | 0.72 |
| Max Drawdown | 21.5% | 13.1% |
| Return | +73.7% | +10.4% |

---

## Timeframe Tiers

| Timeframe | Role | Status |
|---|---|---|
| H1 | Primary execution | Active (62.5% of trades, 35.9% WR) |
| M15 | Secondary execution | Dormant (needs 0.55 score — only exceptional setups) |
| H4 | Bias + zone context | Bias-only (no entries, feeds HTF analysis) |
| D1 | Trend direction | Bias-only |
| M5 | Not used | Disabled |

---

## Next Steps

1. Train per-strategy scorers for FVG and SD Zone (like we did for LZI)
2. Volume profile integration (HVN/LVN/POC from M1 data)
3. Order flow proxies (absorption, effort-vs-result, delta approximation)
4. Live demo deployment on Exness via MT5 (Windows VPS)
5. Continuous learning from human partner feedback

---

*This document is the source of truth for the system's logic. Update after each significant change.*
