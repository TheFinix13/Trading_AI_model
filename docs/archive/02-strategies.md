# 02 — Strategies

> ⚠️ **HISTORICAL — superseded by the zone-only validated pipeline.** The three
> "primary strategies" and the confluence-booster framework described here were
> v1 components, burned in the 2026-06-09 reset. Tested ALONE in the stage-1
> ablation grid: FVG-retest, BOS, order blocks and fibs were eliminated first;
> liquidity-sweep (LZI) and momentum were eliminated after fair-shot grids. The
> **supply/demand zone** concept (02.3) is the sole survivor and now trades live
> as `zone_d1_against` via the deployment router. See
> [00-journey.md](00-journey.md) and [CHECKPOINT.md](CHECKPOINT.md). The
> strategy classes referenced below (`agent/strategy/…`) no longer exist.

> Part of the numbered docs — start at [00 — Overview](00-overview.md). For the
> architecture that wraps these strategies (detectors, gate profiles, confluence
> optimizer) see [01 — Strategy Architecture](01-strategy-architecture.md). For
> the mechanics of the patterns themselves see
> [03 — HTF Context & Pattern Mechanics](03-htf-context-and-pattern-mechanics.md).

The agent runs **three primary, self-validating strategies** (02.1–02.3) and a set
of **confluence boosters** (02.4–02.5) that enhance but never trigger entries.

Every primary strategy follows the same philosophy: **detect a structural event,
then WAIT for price to confirm the thesis, then enter with a structural
take-profit target.** They never enter on the initial detection — the "wait" phase
is what separates this from algos that chase every signal.

---

## 02.1 LZI Retest (Liquidity Zone of Interest)

**File:** `agent/strategy/strategies/liquidity_grab_reversal.py` · **Gate profile:**
LZI (self-validating) · **ML scorer:** dedicated LZI model (15 features, threshold 0.40)

The highest-conviction strategy. It capitalises on institutional liquidity sweeps —
price runs a cluster of stops to fill large orders, then reverses.

**Phase 1 — sweep detection (do NOT trade):** price wicks aggressively through a
prior swing high/low, PDH/PDL or equal highs/lows. The wick must be significant
(≥10 pips on H1, ≥15 on H4). Mark the wick range as a *Liquidity Zone of Interest*.

**Phase 2 — retest confirmation:** wait up to 50 bars for price to return, then
require:
1. **Proximity** — within ~5 pips of the zone.
2. **Consumption** — ≥3 bars spending time in the zone (absorbing remaining liquidity).
3. **Displacement** — a strong candle (≥60% body, ≥10 pips body on H1) closing away
   in the expected direction (the institutional "hand").
4. **Entry** — on the displacement candle close.
5. **Stop** — beyond the zone extreme + 3-pip buffer.
6. **Target** — opposite-side unswept liquidity via PD-array targeting (not arbitrary R:R).

**Best conditions:** choppy/ranging markets, session opens, range edges, sweeps of
daily levels. **OOS (2024–2026):** ~26% WR at 4.37:1 average R:R — one winner pays
for 3–4 losers.

---

## 02.2 FVG Retest (Fair Value Gap)

**Gate profile:** FVG (relaxed; FVG is the precision partner) · **False-breakout
filter stays on.**

A fair value gap is a 3-candle imbalance where the middle candle's range is entirely
beyond candles 1 and 3, leaving an unfilled gap. Institutions tend to return to fill
it before continuing.

**Quality grading (0–100):** size (larger = stronger), creation aggressiveness
(body-to-range of the middle candle), session (kill-zone FVGs weighted higher), and
fill tracking (how much has already filled).

**Entry:**
1. FVG detected with quality ≥ 40 (max ~2 revisits, fill < 80%).
2. Wait for price to return to the gap.
3. Confirm reaction: rejection wick (≥2:1 wick-to-body), engulfing, or displacement away.
4. Enter on the reaction candle close.

**Depletion:** FVGs visited 3+ times or 80%+ filled are removed — no trading stale
levels. **Best conditions:** trending/continuation; strongest when paired with BOS
context (BOS + FVG left behind = high conviction).

---

## 02.3 SD Zone Retest (Supply / Demand)

**Gate profile:** SD Zone (relaxed; quality + depletion + reaction is the validation)
· **False-breakout filter stays on.**

SD zones mark where institutional orders sit. The zone boundary is the **order
block** — the last opposing candle before a strong move (last bearish candle before
a bullish impulse = demand; last bullish before a bearish impulse = supply) — not the
whole consolidation.

**Quality scoring (0–100):** origin type (first-time breakout > retested; sweep-born
zones highest), base tightness, departure strength, kill-zone session, and FVG left
behind (+strength). **Depletion:** first touch = full strength, each revisit depletes
it.

**Entry:**
1. Quality SD zone above threshold, not depleted (revisits < 3, fill < 80%).
2. Wait for price to return to the zone.
3. Confirm reaction (rejection / engulfing / displacement).
4. Enter on the reaction candle close.

**Best conditions:** ranging/choppy markets, key structural levels with historical
institutional activity.

---

## Confluence boosters (never standalone)

These add conviction to a primary signal; they are **never** entry triggers on their
own. The [confluence optimizer](01-strategy-architecture.md#013-confluence-optimizer)
selects which boosters actually help the active strategy.

## 02.4 Break of Structure (BOS)

**File:** `agent/detectors/bos.py`

BOS marks price breaking a prior swing high (bullish) or low (bearish) — a context
signal for trend direction.

- **Body break > wick break** — a close beyond the level beats a wick-through (fake-out).
- **Recent > ancient** — only BOS within ~20–50 bars is relevant.
- **FVG left behind** — a BOS that leaves an FVG is a high-quality structural break.

**Role:** enhances FVG and SD Zone entries by confirming bias. **Never triggers
entries by itself** — BOS-only entries had 39% WR and bled −144 pips in the detector
audit.

## 02.5 Fibonacci retracements

**File:** `agent/detectors/fib.py` (config `FibConfig`)

- **OTE zone (61.8–71%)** — highest weight; the Optimal Trade Entry where
  institutional retracements typically reverse.
- **50% (fair value)** — strong; a fair-value retest of an impulse.
- **38.2%** — moderate; valid in strong trends (shallow pullback = trend strength).
- **78.6%** — **invalidation**: if price retraces this deep the impulse is considered
  dead. Used as a *negative* signal.

**Quality gate:** fibs are only drawn from impulses with quality ≥ 35 and ≥ 20 pips,
so we never draw fibs off noise. **Critical rule:** a fib level means nothing without
an LZI zone, FVG, or SD zone at that level.

> Other boosters — **session timing** (London/NY kill zones), **HTF alignment**
> (D1/H4 trend), and **daily levels** (PDH/PDL/PWH/PWL as sweep targets and PD-array
> take-profits) — are covered in
> [03 — HTF Context & Pattern Mechanics](03-htf-context-and-pattern-mechanics.md).

---

## Strategy ↔ regime fit (quick reference)

| Strategy | Favoured regimes | Notes |
|----------|------------------|-------|
| LZI Retest | chop, low-vol | session opens, range edges, daily-level sweeps |
| FVG Retest | trending up/down | continuation; pairs with BOS |
| SD Zone Retest | chop, low-vol | key structural levels |
| Fib (booster) | trends + chop | confluence only |

The [regime router](01-strategy-architecture.md#013-confluence-optimizer) adjusts
conviction by fit rather than blocking outright.
