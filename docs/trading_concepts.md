# Trading Concepts Reference

**Last updated:** 2026-05-13

A reference for the LLM, future development sessions, and anyone new to the codebase. Covers every ICT concept the agent detects, how it's detected, and when it's valid for trade entries.

---

## Supply & Demand Zones

### What they are
A **demand zone** is a price area where institutional buying created a strong bullish impulse. A **supply zone** is where institutional selling created a strong bearish impulse. The "zone" is the consolidation base (small-body candles) just before the impulse — this is where the orders were placed.

### How detected (`agent/detectors/zones.py`)
1. Scan for bars with body >= `min_impulse_pips` (default 30, scaled by timeframe).
2. The impulse body must also be >= 2x the local rolling median body (200-bar window centered on the impulse).
3. Look back `base_lookback` bars (default 3) for the smallest-body candle — this is the base.
4. Zone boundaries = high-low range of the base candle.
5. Bullish impulse → demand zone (LONG). Bearish impulse → supply zone (SHORT).

### When valid
- **Not mitigated:** a zone is mitigated when price *closes through* it (not just wicks into it). A body close below demand bottom = broken. A body close above supply top = broken.
- **Age:** zones older than `max_age_bars` (default 500) from the current bar are filtered out. Age is checked at use-time, not detection-time.
- **Fresh:** `fresh_zones()` returns zones that exist before `at_index` and haven't been mitigated as of `at_index`. No look-ahead.
- **Deduplication:** zones within 5 pips on both edges are deduped.

### Role in the agent
Zone is the only **required factor** by default (`required_factors: ["zone"]`). Every trade must touch a zone. Other confluences layer on top.

---

## Break of Structure (BOS)

### Definition
A **BOS** occurs when price breaks a prior swing high (bullish BOS) or swing low (bearish BOS). It signals a shift in market structure — the trend has changed or continued.

### Detection logic (`agent/detectors/bos.py`)
1. Detect swing highs and lows using `swing_lookback` (default 5 bars on each side).
2. A bullish BOS: current bar closes above the most recent swing high.
3. A bearish BOS: current bar closes below the most recent swing low.
4. Records the broken swing price, direction, and bar index.

### When to use
- **As confirmation, not entry:** BOS alone has a 39% WR and bled -144 pips in the W18 audit. It confirms direction but doesn't identify a good entry level.
- **With FVG or sweep:** `require_fvg_or_sweep_with_bos` gate ensures BOS is always paired with displacement evidence.
- **Recency:** only BOS events within 50 bars of the current bar are considered.

---

## Fair Value Gap (FVG)

### Definition
An **FVG** is a three-candle pattern where the middle candle's range doesn't overlap with the first and third candles — creating a "gap" in fair value. This imbalance tends to get filled (price returns to the gap).

### Detection (`agent/detectors/fvg.py`)
1. Bullish FVG: bar[i-2].high < bar[i].low (gap between candle 1's high and candle 3's low, with candle 2 in between).
2. Bearish FVG: bar[i-2].low > bar[i].high.
3. Minimum size: `fvg_min_size_pips` (default 5, scaled by timeframe).
4. Marked as `filled` when price subsequently closes through the gap.

### Role in entries
- FVG is a **precision partner** — its presence says price has committed aggressively, leaving behind an imbalance. The gap is a natural re-entry zone.
- `fvg + zone` = 80-89% WR in the W18 audit.
- `fvg + phase_distribution + zone` = 90% WR in the 3-year audit.
- FVG contributes to the confluence count and satisfies `require_precision_partner`.

---

## Fibonacci Retracements

### Levels used
The agent tracks four fib levels from the last significant swing:
- **38.2%** (`fib_382`) — shallow retrace, strong trend continuation
- **50.0%** (`fib_500`) — equilibrium level
- **61.8%** (`fib_618`) — golden ratio, deep retrace
- **78.6%** (`fib_786`) — deep retrace, near full reversal

### Which work best
From the user's journal and 3-year audit:
- **38.2%** and **61.8%** are the best performers.
- `fib_382 + fvg + zone` = 100% WR / +321 pips (3-year audit).
- `fib_382 + sweep_swing_high + zone` = 54% WR / +343 pips (57 trades — good sample size).
- The user uses multiple entries at different fib levels within the same zone.

### Detection (`agent/detectors/fib.py`)
1. `auto_fib()` finds the last significant swing (using swing detection with configurable lookback).
2. Computes retracement levels from the swing.
3. A fib level is "hit" when the current bar's range tags the level within ATR-based tolerance.
4. Recomputed every 25 bars in backtest (balance between accuracy and performance).

### Role in entries
- Fib levels are **structural anchors** — they satisfy `require_structural_anchor`.
- They prove price has pulled back to a meaningful level, not just randomly touching a zone.

---

## Daily Levels

### Definitions
| Level | Full Name | Source |
|-------|-----------|--------|
| **PDH** | Prior Day High | Yesterday's high |
| **PDL** | Prior Day Low | Yesterday's low |
| **PDM** | Prior Day Mid | (PDH + PDL) / 2 |
| **PWH** | Prior Week High | Last week's high |
| **PWL** | Prior Week Low | Last week's low |
| **PWM** | Prior Week Mid | (PWH + PWL) / 2 |

### Detection (`agent/detectors/daily_levels.py`)
- Computed per bar from historical daily/weekly data.
- Strictly no look-ahead: only uses completed prior-day/week data.
- Tagged as `near_PDH`, `near_PDL`, etc. when price is within tolerance (max 8 pips or 0.5x ATR tolerance).
- Source timeframe is always tagged as `D1` in `confluence_tfs`.

### How used
- Daily levels are **context tags**, not entry triggers by themselves.
- `near_PDH` tells the agent "we're at a key daily level" but doesn't satisfy `require_precision_partner` — it marks where to look, not whether to enter.
- They combine with zones and sweeps: `fib_382 + session_ny + zone` near PDH is a high-conviction setup.

---

## Liquidity Sweeps

### What they are
A **liquidity sweep** occurs when price briefly pierces beyond a known level (grabbing stop-loss orders from traders positioned at that level), then reverses. This is institutional "stop hunting" — smart money triggers retail stops to fill their own orders at better prices.

### Detection (`agent/detectors/liquidity_sweep.py`)
1. Track known levels: PDH, PDL, PDM, PWH, PWL, PWM, swing highs, swing lows, equal highs, equal lows.
2. A sweep fires when price wicks beyond the level (within `pierce_buffer_pips`) and then reverses back within `confirm_max_bars` (default 3) by `confirm_pips` (default 5).
3. Each sweep is **tagged** with what was swept: `sweep_PDH`, `sweep_swing_high`, `sweep_equal_lows`, etc.
4. Only computed on M1/M5/M15/H1 (daily-level sweeps on D1 are the chart itself).

### Direction-aware semantics (enforced in `engine.py`)
The detector classifies levels by position relative to current price. The rules engine enforces ICT semantics:
- **HIGH-type** (PDH, PWH, swing_high, equal_highs): only valid for **SHORT** setups. Buyside liquidity was grabbed → smart money sells.
- **LOW-type** (PDL, PWL, swing_low, equal_lows): only valid for **LONG** setups. Sellside liquidity was grabbed → smart money buys.
- **MID-type** (PDM, PWM): **dropped entirely**. Mid-pivots aren't true liquidity pools. 0/3 wins, -25 pips in the audit.

### Role in entries
- Sweeps are **precision partners** — they satisfy `require_precision_partner`.
- A sweep proves institutional activity at a level, transforming a passive zone into an active setup.

---

## Sessions

### Session windows (NY local time)
| NY Hour | Session | Character |
|---------|---------|-----------|
| 00-01 | Asia | Low volume, range-bound |
| 02-07 | London | Volatility picks up, trend initiation |
| 08-12 | Overlap (London + NY) | Highest volume, strongest moves |
| 13-16 | NY | Continuation or reversal of London moves |
| 17-19 | NY Late | Winding down, lower volume |
| 20-23 | Asia (early) | Range formation |

### Detection (`agent/detectors/sessions.py`)
- Per-bar label based on UTC timestamp converted to NY local time.
- DST-aware via Python `zoneinfo`.
- Kill zones: London, NY, and Overlap are considered active trading sessions.

### Which are best for trading
- **NY session** (`session_ny`) is a **structural anchor** — it satisfies `require_structural_anchor`.
- **London-NY overlap** is **blocked** by default (`blocked_session_tags: ["session_london_ny_overlap"]`). It showed -153 pips / 20% WR in the W18 audit — too choppy and news-driven.
- **Blocked hours:** NY 03 (London open chop), 04 (London early), 12 (London close), 13 (NY pre-close) — combined -1,921 pips in the 3-year audit.

---

## Range Phases (ICT Power of Three)

### Definitions
| Phase | Description | Timeframe |
|-------|-------------|-----------|
| **Accumulation** | Price consolidates in a tight range. Smart money is building positions quietly. | Early session (often Asia). |
| **Manipulation** | Price makes a false move (sweep/fake breakout) to trigger retail stops and build liquidity for the real move. | Often early London. |
| **Distribution** | The real move. Smart money distributes (sells what they accumulated) or price extends to the actual target. | Usually London → NY. |

### Detection (`agent/detectors/range_phase.py`)
- Labels each bar with its current phase based on recent price action and session context.
- Computed per bar for the full series.

### Role in entries
- **Distribution** (`phase_distribution`) is a **structural anchor** — it satisfies `require_structural_anchor` and counts as a confluence.
- `fvg + phase_distribution + zone` = 90% WR / +473 pips in the 3-year audit. This is the highest-WR combo found.
- Accumulation and manipulation phases are stored in `confluence_tfs` metadata for the narrative but do NOT count toward `min_confluences` — they're informational, not entry triggers.

---

## User-Specific Trading Concepts

### PD Range (Prior Day Open/Close Range)
The user uses the prior day's open-to-close range (not high-to-low) as a directional bias indicator:
- If today opens above yesterday's close → bullish bias.
- If today opens below yesterday's close → bearish bias.
- This is distinct from PDH/PDL which uses the full range.

### No-Trade on Consolidation Days
When the prior day's open and close are clustered (small body relative to range), the user skips trading — there's no clear directional bias to work with. This maps to the `no_trade_days` config and can be automated via the D1 body-to-range ratio.

### Multi-Entry at Fib Levels
The user often opens multiple 0.01-lot positions at different fib levels within the same zone:
- First entry at 38.2% retrace.
- Second entry at 50% if the first hasn't hit TP.
- Third entry at 61.8% (deepest, highest conviction).
- All share the same structural stop (below/above the zone).

This is a position-building strategy that the agent currently doesn't replicate (one-position-at-a-time), but is documented for future implementation.

---

*Update this reference when new trading concepts are added to the detector suite or when the user's trading rules evolve.*
