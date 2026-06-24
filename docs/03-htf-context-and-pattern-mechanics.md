# 03 — HTF Context & Pattern Mechanics

> ⚠️ **PARTLY HISTORICAL — superseded by the zone-only validated pipeline.**
> Detector *mechanics* under `agent/detectors/` still match the sections below.
> The **v1 HTF context layer** (`agent/context/htf_context.py`, ERL/IRL magnets,
> reaction-engine draws) was burned in the v2 reset. The one HTF finding that
> validated is **mean-reversion**: fade the zone touch **against** the D1 trend
> (`zone_d1_against`). Implementation: `agent/alphas/concepts/_htf.py` +
> `SupplyDemandAlpha`. See [00-journey.md](00-journey.md) and
> [CHECKPOINT.md](CHECKPOINT.md).

> Part of the numbered docs — start at [00 — Overview](00-overview.md).
> v1 strategy/architecture docs are archived under
> [`docs/archive/`](archive/) (01, 02, 04).

---

## What's live today (2026-06-24)

| Component | Code | Role |
|---|---|---|
| Detector battery | `agent/rules/engine.py::precompute` | Runs zones, swings, BOS, FVG, sweeps, sessions, daily levels, trendlines on every closed bar |
| Zone alpha HTF gate | `agent/alphas/concepts/_htf.py` | D1 trend slope + min-move filter; **against-trend** mode is the validated edge |
| Target ladder | `agent/journal/target_ladder.py` | Observation-only structural rungs beyond 1.5R TP |
| Precompute-only detectors | FVG, BOS, sweeps, etc. | Computed every bar; not all are consumed by `SupplyDemandAlpha` today |

The sections below document **detector mechanics** (still accurate). Sections
labelled *v1 historical* describe modules that no longer sit on the live path.

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
direction and bar index. Precomputed every bar; consumed by target ladder and
future M001 strikers (Chigiri breakout).

---

## Fair Value Gap (FVG)

A 3-candle imbalance where the middle candle's range doesn't overlap candles 1 and 3.

**Detection (`agent/detectors/fvg.py`):** bullish FVG when `bar[i-2].high <
bar[i].low`; bearish when `bar[i-2].low > bar[i].high`; minimum `fvg_min_size_pips`
(default 5, TF-scaled); marked `filled` when price later closes through it.
Precomputed every bar. v1 confluence win-rate claims in older audits were
in-sample and did not survive the ablation grid.

---

## Daily levels

| Level | Meaning |
|-------|---------|
| PDH / PDL / PDM | Prior day high / low / mid |
| PWH / PWL / PWM | Prior week high / low / mid |

**Detection (`agent/detectors/daily_levels.py`):** computed per bar from completed
prior day/week data (strictly no look-ahead); tagged when price is within tolerance
(≤8 pips or 0.5× ATR). Used by target ladder and precompute.

---

## Liquidity sweeps

A sweep is price briefly piercing a known level (grabbing stops), then reversing.

**Detection (`agent/detectors/liquidity_sweep.py`):** track PDH/PDL/PDM/PWH/PWL/PWM,
swing highs/lows, equal highs/lows; a sweep fires when price wicks beyond a level
(within `pierce_buffer_pips`) and reverses within `confirm_max_bars` (default 3) by
`confirm_pips` (default 5). Precomputed on M1–H1 timeframes.

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
DST-aware via `zoneinfo`. Session labels feed zone detection and the deployment
router's per-(symbol, TF, session) cells.

---

## v1 historical — HTF context layer (burned)

> The following described `agent/context/htf_context.py` and the v1 reaction
> engine. Neither is on the live path. Preserved for detector-history context
> only; see [`archive/04-reaction-engine.md`](archive/04-reaction-engine.md).

D1 and H4 supplied bias, structural levels, HTF zones, fib levels, and weekly
context to the reaction engine. Deep zone draws (`htf_draws.py`) were measured
and found net-negative on the full span — they ship as scored-but-off variants,
not defaults. ERL/IRL magnets and range-phase detection were eliminated in the
ablation grid (`agent/detectors/range_phase.py` and `agent/detectors/fib.py` are
no longer referenced by production code).

For the validated pipeline, HTF influence is limited to the D1 against-trend
gate in `_htf.py` — not the full multi-field context object above.
