# 03 — HTF Context & Pattern Mechanics

> Part of the numbered docs — start at [00 — Overview](00-overview.md). This is the
> reference for *how* each ICT concept is detected and *when* it's valid. The
> strategies that consume them are in [02 — Strategies](02-strategies.md); the
> architecture that wires them together is in
> [01 — Strategy Architecture](01-strategy-architecture.md).

The agent reads the market top-down: higher-timeframe (HTF) context first, then
lower-timeframe pattern mechanics for the actual entry.

---

## Higher-timeframe (HTF) context

D1 and H4 supply **bias and zone context** to H1/M15 entries — they never trade
themselves.

- **With-trend entries** get a conviction bonus; **counter-trend** entries get a
  penalty (not blocked, but the bar is higher); **neutral HTF** (slope < ~0.5 pips)
  is evaluated on its own merit.
- `htf_bias_mode` in `agent/rules/engine.py` can run **off**, **advisory** (scores
  but doesn't block) or **strict** (rejects LTF setups against D1 trend).
- The HTF context layer also maps daily/weekly zones and the prevailing structure
  so the reaction engine ([04](04-reaction-engine.md)) knows which marked levels
  matter right now.

**Timeframe tiers:** H1 active (primary edge), M15 dormant (signals detected but
elevated threshold), H4 + D1 bias-only, M5 disabled.

---

## Supply & demand zones

A **demand zone** is where institutional buying created a bullish impulse; a
**supply zone** is where selling created a bearish impulse. The zone is the
consolidation base just before the impulse.

**Detection (`agent/detectors/zones.py`):** find a bar with body ≥
`min_impulse_pips` (default 30, TF-scaled) that's also ≥ 2× the local rolling
median body (200-bar centred window); look back `base_lookback` (default 3) for the
smallest-body base candle; zone bounds = the base candle's high-low. Bullish
impulse → demand (LONG); bearish → supply (SHORT).

**Valid when:** not mitigated (a *body close* through the zone breaks it; a wick
does not), younger than `max_age_bars` (default 500, checked at use-time not
detection-time), fresh as-of the evaluation index (no look-ahead), and deduped
(zones within 5 pips on both edges merge). Zone is the only **required factor** by
default — every trade must touch a zone.

---

## Break of Structure (BOS)

A **BOS** is price breaking a prior swing high (bullish) or low (bearish).

**Detection (`agent/detectors/bos.py`):** swing highs/lows via `swing_lookback`
(default 5 each side); bullish BOS = close above the most recent swing high,
bearish = close below the most recent swing low; records the broken price,
direction and bar index. **Use as confirmation, not entry** (39% WR alone); pair
with FVG/sweep via `require_fvg_or_sweep_with_bos`; only BOS within ~50 bars counts.

---

## Fair Value Gap (FVG)

A 3-candle imbalance where the middle candle's range doesn't overlap candles 1 and 3.

**Detection (`agent/detectors/fvg.py`):** bullish FVG when `bar[i-2].high <
bar[i].low`; bearish when `bar[i-2].low > bar[i].high`; minimum `fvg_min_size_pips`
(default 5, TF-scaled); marked `filled` when price later closes through it. FVG is a
**precision partner** — its presence says price committed aggressively and left an
imbalance to re-enter on. `fvg + zone` scored 80–89% WR, `fvg + phase_distribution
+ zone` 90% WR in the 3-year audit.

---

## Fibonacci retracements

Four levels off the last significant swing: **38.2%** (shallow), **50%**
(equilibrium), **61.8%** (golden), **78.6%** (near-reversal / invalidation).

**Detection (`agent/detectors/fib.py`):** `auto_fib()` finds the last significant
swing, computes levels, and marks one "hit" when the bar's range tags it within
ATR-based tolerance (recomputed every ~25 bars in backtest). Fibs are **structural
anchors** (`require_structural_anchor`): they prove price pulled back to a
meaningful level. Best performers from the audit: 38.2% and 61.8%
(`fib_382 + fvg + zone` = 100% WR / +321 pips).

---

## Daily levels

| Level | Meaning |
|-------|---------|
| PDH / PDL / PDM | Prior day high / low / mid |
| PWH / PWL / PWM | Prior week high / low / mid |

**Detection (`agent/detectors/daily_levels.py`):** computed per bar from completed
prior day/week data (strictly no look-ahead); tagged `near_PDH`, `near_PDL`… when
within tolerance (≤8 pips or 0.5× ATR). They are **context tags**, not triggers, and
serve two roles: sweeps of them create LZI zones, and opposite-side levels are
PD-array take-profit targets (sweeping PDL → target PDH).

---

## Liquidity sweeps

A sweep is price briefly piercing a known level (grabbing stops), then reversing —
institutional stop-hunting.

**Detection (`agent/detectors/liquidity_sweep.py`):** track PDH/PDL/PDM/PWH/PWL/PWM,
swing highs/lows, equal highs/lows; a sweep fires when price wicks beyond a level
(within `pierce_buffer_pips`) and reverses within `confirm_max_bars` (default 3) by
`confirm_pips` (default 5); each is **tagged** with what was swept.

**Direction-aware semantics (enforced in `engine.py`):**
- **HIGH-type** (PDH, PWH, swing_high, equal_highs) → only valid for **SHORT** (buyside grabbed → sell).
- **LOW-type** (PDL, PWL, swing_low, equal_lows) → only valid for **LONG** (sellside grabbed → buy).
- **MID-type** (PDM, PWM) → **dropped** (not true liquidity pools; 0/3 wins in the audit).

Sweeps are **precision partners** — they turn a passive zone into an active setup.

---

## Sessions

| NY hour | Session | Character |
|---------|---------|-----------|
| 00–01 | Asia | low volume, range-bound |
| 02–07 | London | volatility picks up, trend initiation |
| 08–12 | London+NY overlap | highest volume |
| 13–16 | NY | continuation / reversal |
| 17–19 | NY late | winding down |
| 20–23 | Asia (early) | range formation |

**Detection (`agent/detectors/sessions.py`):** per-bar label from UTC → NY local,
DST-aware via `zoneinfo`. **NY session** is a structural anchor. The **London-NY
overlap is blocked** by default (−153 pips / 20% WR in the audit) and **NY hours 03,
04, 12, 13** are blocked (combined −1,921 pips over 3 years).

---

## Range phases (ICT Power of Three)

| Phase | Description |
|-------|-------------|
| **Accumulation** | tight range; smart money builds positions (often Asia) |
| **Manipulation** | false move/sweep to trigger stops (often early London) |
| **Distribution** | the real move to target (London → NY) |

**Detection (`agent/detectors/range_phase.py`):** per-bar phase label from recent
price action + session context. **Distribution** (`phase_distribution`) is a
structural anchor and the highest-WR confluence found: `fvg + phase_distribution +
zone` = 90% WR / +473 pips. Accumulation/manipulation are informational only.

---

## User-specific concepts

- **PD range (open→close):** today opening above yesterday's close = bullish bias,
  below = bearish (distinct from PDH/PDL which use the full range).
- **No-trade on consolidation days:** when the prior day's open/close cluster
  (small body vs range) there's no directional bias — maps to `no_trade_days`.
- **Multi-entry at fib levels:** the trader scales in at 38.2 / 50 / 61.8 within one
  zone sharing a structural stop. Documented for future implementation; the agent
  currently trades one position at a time.
