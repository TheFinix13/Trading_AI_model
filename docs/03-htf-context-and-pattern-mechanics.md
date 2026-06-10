# 03 — HTF Context & Pattern Mechanics

> ⚠️ **PARTLY HISTORICAL — superseded by the zone-only validated pipeline.**
> The detector *mechanics* described here (zones, BOS, FVG, sweeps, sessions,
> daily levels) still match code under `agent/detectors/` and
> `agent/context/`, but the **trading claims are v1 artifacts**: the audit
> win-rates quoted below (e.g. "fvg + zone 80–89% WR", "fib_382 + fvg + zone =
> 100% WR") were in-sample, tiny-sample selections that did not survive honest
> validation, and the concepts they promote were **eliminated in the ablation
> grid**. ERL/IRL magnets and HTF "draws" are not live components. The one HTF
> finding that *did* validate is the opposite of v1's with-trend bias: the zone
> edge is **mean-reversion**, gated AGAINST the D1 trend (`zone_d1_against`).
> See [00-journey.md](00-journey.md) and [CHECKPOINT.md](CHECKPOINT.md).

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

### What HTF stores (beyond bias)

The context (`agent/context/htf_context.py::HTFContext`) carries more than a
bias label — these are the "details and zones" the lower-timeframe reaction
engine reads:

| Field | What it is | How the LTF uses it |
|-------|-----------|---------------------|
| `combined_bias` + `buy/sell_aligned` | D1/H4 trend. When bias is neutral, the **net pattern lean** (confidence-weighted) breaks the tie, so a dominant double-top still biases short in a range. | Directional filter — boosts/penalises reaction conviction. |
| `structural_levels` | D1/H4 swing highs/lows as **support/resistance points**. | Added to the reaction level set ("is price at a level"). |
| `htf_zones` | D1/H4 demand & supply **zones (ranges)** — from order blocks *and* clustered structural bands (the broad daily zone you draw by hand). Tagged `mitigated`/`swept`. | A fresh zone ahead is the **draw / take-profit target**; zone mids join the level set. |
| `htf_fib_levels` | Fib retracements off the last **H4 *and* D1** swing (38.2/50/61.8/78.6). | Fib confluence as a level of interest. |
| `weekly` | Week high/low/open, unswept liquidity, expansion direction. | Narrative + unswept-liquidity targets. |

### HTF zones as draws (the daily demand zone an impulse heads toward)

A daily demand/supply zone is the *area price is being pulled into* — the
**draw**. `htf_zones` represents it as a band (`top`/`bottom`), not a point, and
flags it `mitigated` once price trades back into it and `swept` once price closes
fully through.

**Deep lookback (zones live for months).** A discretionary trader keeps a daily
zone drawn until it's consumed — often weeks or months. So zone detection uses a
dedicated `htf.d1_zone_lookback_bars` (default **180 D1 bars ≈ 9 months**),
*separate* from the short bias/level window (`d1_lookback_bars = 20`). This is the
fix for "the demand zone was drawn from April 6 but it's now June": with the
shallow window the agent literally couldn't see it; with the deep window an
April base and the March lower-low liquidity both remain on the radar as draws
until price actually consumes them. Bias and structural-level detection still use
their own short windows, so the deeper history only affects zones.

`HTFContext.nearest_zone_draw(direction, price)` returns the
nearest **fresh** (unmitigated) zone *ahead* of price — a demand zone below for a
short, a supply zone above for a long. The reaction engine
([04](04-reaction-engine.md)) takes that as its take-profit when the resulting
risk-reward clears `min_rr` (target label `htf_zone_draw`), otherwise it falls
back to PD-array liquidity. This is what lets the agent "see reason" to ride an
impulsive move *toward* the daily zone instead of guessing a fixed RR. Because it
targets a *with-trend* draw (not a counter-trend fade), it improves expected RR
rather than degrading it — unlike the ERL "fade the draw" experiment in
[04.2b](04-reaction-engine.md).

**Symmetry — supply is perceived exactly like demand.** Detection is fully
two-sided at every stage: `_zones_from_df` emits a **demand** zone on a bullish
displacement *and* a **supply** zone on a bearish one; `_zones_from_levels`
clusters support→demand bands *and* resistance→supply bands; `_deep_d1_levels`
marks old swing **lows** (demand/resting sell-side liquidity) *and* swing **highs**
(supply/buy-side liquidity) over the same 9-month window. So the agent sees the
upside supply draws a long is pulled toward just as it sees the downside demand
draws — confirmed empirically: over a 4-year H1 span a supply-above draw is marked
on ~23.8k bars and a demand-below draw on ~23.9k (balanced).

**Now measured in Phase B/C.** The isolated alphas previously never received these
deep draws, so their *value* was untested. `agent/context/htf_draws.py`
reconstructs them **causally** over the full series (daily cadence, only closed
D1/H4 bars — preserving the 9-month lookback that a per-chunk warm-up can't), keyed
by bar time so it survives chunk-slicing. Two new alpha variants — `reaction_htf_draws`
and `reaction_erl_irl_htf` — target them. Finding (full locked span 2015→2025):
targeting the deeper daily draw is **net-negative** — it hurts both the plain
reaction and the ERL lead (expectancy +5.47→+2.38, Sharpe 0.92→0.40) because the
draw is often far and trades away hit-rate; the meta-allocator gives
`reaction_htf_draws` 0% weight. (A shorter 4-year window had *flattered* it with a
drawdown improvement that the full span reversed — see the honest-measurement note
in [10 §10.5](10-quant-validation-and-modular-overhaul.md).) So they ship as
scored-but-off variants, not defaults — but the value is now **measured**,
symmetrically, rather than assumed.

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
