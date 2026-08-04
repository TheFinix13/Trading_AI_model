# Prefix-parity audit + causal-zones re-validation — 2026-08-04

## Question

The I024 fix (frozen-prepare) makes the live squad re-prepare the roster
on every new bar, so agents compute detector context from history-so-far
only ("prefix" semantics). The research replays that legitimized the
roster prepared once on the entire series ("full" semantics). Are the
two semantics equivalent — i.e. is the live squad running the validated
strategy?

## Method

1. **Code audit** of every detector output the five bar-based agents
   consume (zones, mitigation, ATR, HTF bias, swings, Chigiri's
   self-computed ATR/median, Bachira's rebel scan).
2. **Empirical parity harness** (`prefix_parity_audit.py`): for each of
   the last 600 H4 decision bars per symbol (EURUSD/GBPUSD/USDCAD, real
   cached data, 2 500-bar history), compare `alpha.signal(ctx_full, i)`
   vs `alpha.signal(precompute(bars[:i+1]), i)` for all five zone-alpha
   param sets (isagi, bachira, rin, barou v1, barou v13).
3. **Replay A/B** (`squad_replay_kpis.py`): full `SquadEngine.run_batch`
   2019-01-01 → 2026-08-03, 36 698 bars, live roster shape (barou v13,
   Sae benched, phi41), identical data — once at pre-fix HEAD
   (`1d0b9b7`), once with the causal fix.

## Findings

### Two lookahead channels (code audit)

1. **`detect_zones` centered median** — impulse validity used a rolling
   median of candle bodies centered on the impulse bar
   (`bars[i-100 .. i+100]`): up to 100 FUTURE bars voted on whether a
   zone existed.
2. **Zone tradable before its impulse** — `fresh_zones` filtered on
   `created_bar_index` (the base candle), which precedes the defining
   displacement by up to `base_lookback` (3) bars: a replay could
   touch-trade a zone 1–3 bars before the move that creates it existed.
   Verified live on tape: EURUSD 2026-03-20 12:00 short — the signal
   fired on a zone whose validity came from the future-informed median.
3. (Minor) **`_structural_tp` unconfirmed swings** — fractal swings need
   `lookback` (5) bars on both sides; the full-series prepare handed the
   TP picker swings a live agent cannot know yet.

Everything else is strictly index-causal (Chigiri entirely so).

### Parity, pre-fix (`results_prefix_vs_full_baseline.json`)

Live (prefix) fired only **~70–75%** of the signals the replay (full)
semantics fired; e.g. Bachira GBPUSD: 127 full vs 82 prefix, only 72
identical. Divergence dominated by `only_full` — signals that existed
only because of future knowledge.

### Fix

* Trailing median (`bars[i-200 .. i-1]`, strictly past) in
  `detect_zones` / `detect_qualified_zones`.
* `Zone.impulse_bar_index` stamped at detection; `fresh_zones` /
  `fresh_qualified_zones` refuse zones whose impulse closes after
  `at_index`.
* `_structural_tp(confirm_bars=swing_lookback)` — TP only off confirmed
  swings.

### Parity, post-fix (`results_causal_semantics.json`)

**Zero divergence** across all 15 agent×symbol cells (1 800 decision
bars): live and replay semantics are byte-identical. Signal frequency
stays healthy (e.g. Bachira EURUSD 126 causal vs 137 lookahead).

Regression tests: `tests/test_causal_zones.py` (prefix stability,
impulse knowability, strictly-past median, confirmed-swing TP).

### Replay A/B 2019→2026 (the headline)

| metric | pre-fix (lookahead) | causal |
|---|---|---|
| trades | 3 866 | 2 504 |
| win rate | 50.7% | 37.5% |
| total pips | **+29 207** | **−2 324** |
| profit factor | **1.52** | **0.95** |
| mean R | +0.30 | −0.03 |

Per agent (pips / PF, baseline → causal):

| agent | baseline | causal |
|---|---|---|
| Bachira | +16 924 / 1.67 | −1 502 / 0.93 |
| Isagi | +9 789 / 1.60 | −606 / 0.96 |
| **Rin** | +3 407 / 1.66 | **+1 014 / 1.20** |
| Nagi | +204 / 1.13 | +258 / 1.47 (n=30) |
| Barou v13 | +24 / 1.02 | −82 / 0.92 (n=44) |
| Chigiri | −1 140 / 0.82 | −1 406 / 0.80 (already causal) |

## Interpretation

**The squad's replay edge was substantially a lookahead artifact.** The
zone-fade weapon shared by Isagi/Bachira/Barou collapses to breakeven-
negative once the future stops voting on zone existence. Rin's
tighter-filtered variant retains a real causal edge (PF 1.20, 218
trades). Nagi stays positive on a small sample. Chigiri was honest all
along (and honestly negative).

Implications:

1. **The G7/E004-lineage replay evidence is invalidated** as a live
   performance forecast — it was measured under semantics live can never
   reproduce. Honest expectation for the squad as-currently-parameterised
   is ~breakeven.
2. **Live runtime is now honest**: after this fix, live == replay
   byte-for-byte, so the coming shadow-paper weeks measure the true
   strategy. The squad risks no money (shadow-only), so relaunching for
   honest measurement remains sound.
3. **Research charter (next)**: re-tune / re-validate the roster under
   causal semantics in `finance-research-experiments` (fresh
   pre-registration; Rin's surviving parameterisation is the natural
   anchor). No parameter retuning was done here — that belongs behind
   the research repo's discipline gates.
4. **v1 lane note**: v1's live loop is naturally causal (it cannot see
   the future), so its LIVE track record stands; but any v1 backtest
   evidence produced with the centered-median detector carries the same
   contamination. Flagged to the shared-findings ledger.

## Artifacts

* `prefix_parity_audit.py`, `results_prefix_vs_full_baseline.json`
  (pre-fix), `results_causal_semantics.json` (post-fix, zero divergence)
* `squad_replay_kpis.py`, `replay_kpis_baseline.json` (pre-fix HEAD),
  `replay_kpis_causal.json`, `replay_kpis_trial.json` (2026 YTD smoke)
