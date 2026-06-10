# 10 — Quant Validation & Modular Overhaul (Phased Plan)

> ⚠️ **HISTORICAL — this plan completed and led to the v2 reset.** Phases A–D
> ran to completion and their conclusions stand (the v1 stack had no OOS edge;
> partial scaling and multi-position failed their gates). One conclusion was
> later **overturned by better testing**: the "lead candidate" promotion of
> `reaction + ERL/IRL` (§10.4/§10.6) did not survive the v2 stage-1 ablation
> grid — under fair single-concept tests with BH-FDR correction, no
> reaction-engine variant showed significant edge, and the **supply/demand zone**
> emerged as the sole survivor. The modules built for Phases C/D
> (`managed_exit.py`, `portfolio.py`, the purged-walk-forward harness) were
> burned in the reset (see [audit/README.md](audit/README.md)). The current
> methodology and deployment live in [00-journey.md](00-journey.md) and
> [CHECKPOINT.md](CHECKPOINT.md).

> Part of the numbered docs — start at [00 — Overview](00-overview.md). This is the
> **plan of record** for moving the agent from "tuned on the backtest" to
> "validated out-of-sample, modular, and risk-budgeted." It exists because we
> identified a real overfitting risk (see §10.1) and want to fix the *process*,
> not just add features.

This is a living document. Each phase has an explicit **goal**, **deliverables**,
and an **acceptance gate** (what must be true on *out-of-sample* data before we
keep it). Phases run **sequentially** — each one is validated before the next
begins, so every new capability earns its place on data it has not seen.

```
Phase E (this doc)  →  A (eval)  →  B (modular alphas)  →  C (position mgmt)  →  D (multi-position)
   plan                 lock OOS      independent scorecards    partials + late entry    pyramiding + risk budget
```

---

## 10.1 Why we're doing this (the overfitting diagnosis)

We are tuning and selecting on the **same** historical data we measure on. Every
keep/drop decision made by looking at the 2-year backtest silently turns that
data into training data. Specific tells in this project:

- **Threshold tuning on in-sample data** — e.g. conviction `0.54→0.50`, gate
  profiles, "keep impulse override / disable ERL-IRL" — all decided on the same
  backtest window.
- **Implausible audit numbers** — `fib_382 + fvg + zone = 100% WR`,
  `90% WR` combos are tiny-sample, in-sample selections. A 100% win rate over a
  handful of trades is noise, not edge.
- **Multiple testing** — many features tried; some "wins" are luck and will not
  repeat.
- **Leakage in the existing walk-forward** (`agent/backtest/walkforward.py`): the
  test window begins the same instant the train window ends, with **no embargo**.
  Adjacent H1 bars are autocorrelated, so the model effectively peeks across the
  seam. It also only retrains the ML scorer — the hand-tuned config thresholds
  remain global.

**"Start afresh" means a clean evaluation protocol, not deleting code.** The
detectors and engines are fine; the discipline around how we validate them is
what we are rebuilding.

---

## 10.2 Guiding principles (apply to every phase)

1. **Lock a hold-out test set.** Reserve the most recent ~6–9 months. Do **not**
   look at it until a phase's final sign-off. One look and it is burned.
2. **Decide on validation, confirm once on test.** No iterating against the test
   set.
3. **Purge + embargo** every train/test seam (drop ~1–2 days of straddling bars)
   to kill autocorrelation leakage.
4. **Report with uncertainty.** Expectancy (R), profit factor, and Sharpe with
   confidence/standard-error bands. Ignore improvements smaller than their noise.
5. **The demo account is the real OOS.** Forward paper-trading on Exness demo is
   the unfakeable final judge; every phase that passes backtest gates also gets a
   forward-test window before it is trusted live.
6. **One change at a time.** Never bundle a feature change with a threshold change
   — you won't know which one moved the metric.

---

## 10.3 Phase A — Lock the evaluation protocol

**Goal:** an honest, reusable out-of-sample harness that every later phase reports
through. Nothing about strategy logic changes here — only how we measure.

**Deliverables**
- A **fixed split**: `train` (oldest) / `validation` (middle) / `test` (most
  recent, locked). Persist the date boundaries in config so they can't drift.
- **Purged walk-forward** — extend `walkforward.py` with a configurable embargo
  (gap bars dropped at each seam) and optional purging of overlapping-label bars.
- **Metrics with CIs** — extend `agent/backtest/metrics.py` to emit standard
  errors / bootstrap confidence intervals for expectancy, PF, win-rate, Sharpe.
- A single **`scripts/evaluate.py`** entry point that runs the locked protocol and
  prints a one-page scorecard (in-sample vs validation vs the still-sealed test
  count, never the test *result* until sign-off).
- Document the protocol in [07 — Backtesting](07-backtesting.md).

**Acceptance gate (to "pass" Phase A):** the harness reproduces the current
stack's numbers on the *training* window and produces a *validation* read that is
directionally consistent (no absurd jumps). We then record the validation
baseline as the bar every future change must beat.

---

## 10.4 Phase B — Modularize into independent alphas + meta-allocator

**Goal:** turn the tangled signal blob into separately-measurable **alpha
modules**, so we can keep what survives OOS and cut what doesn't — *individually*.

> **"Subagent" = a strategy module, not a separate AI/LLM process.** The value is
> separation of concerns and independent measurement, not parallelism. Each alpha
> is a pure function evaluated on each closed bar.

**Candidate alphas (each gets its own scorecard)**
- Zone reaction (SD-zone retest)
- FVG retest
- Liquidity sweep (LZI)
- BOS continuation
- HTF-draw reaction (the daily demand/supply zone draw — see [03](03-htf-context-and-pattern-mechanics.md))
- Reaction engine (present-time commitment) as its own alpha
- **Quarantined**: ERL/IRL liquidity magnets + draw-bias (see §10.6)

**Deliverables**
- A common `Alpha` interface: `evaluate(closed_bars, context) -> AlphaSignal|None`
  with a stable feature/label contract.
- A **per-alpha OOS scorecard** (expectancy, PF, Sharpe, trade count, with CIs)
  produced by the Phase-A harness.
- A **meta-allocator** that combines surviving alphas: conviction-weighted and
  **correlation-aware** (two alphas firing the same trade must not double-size).
- Document the alpha roster + allocator in [01 — Strategy Architecture](01-strategy-architecture.md).

**Acceptance gate:** each alpha kept must show positive expectancy on
**validation** with a CI that doesn't straddle zero by much; the ensemble must
beat the best single alpha (diversification benefit) on validation. Cut the rest.

**What shipped**
- `agent/alphas/base.py` — the `Alpha` interface (`signal(actx, i) -> AlphaSignal|None`).
- `agent/alphas/backtest.py` — one identical, isolated fill model for every alpha
  (market entry next open, stop/TP **re-anchored to the fill** with the signal's
  own risk geometry, intra-bar worst-case SL, one position at a time). Chunked
  runner (`run_alphas_chunked`) keeps `precompute` off its O(N²) path on long spans.
- `agent/alphas/strategy_alpha.py` / `reaction_alpha.py` — adapters wrapping the
  five registry strategies and the reaction engine (incl. the ERL/IRL variant).
- `agent/alphas/allocator.py` — correlation-aware mean-variance (tangency)
  allocator with covariance shrinkage, long-only weights, thin-stream exclusion.
- `scripts/evaluate_alphas.py` — per-alpha CI scorecards + correlation matrix +
  ensemble-vs-best-single, over the locked dev span. Also emits a **session /
  killzone scorecard** for the reaction path (`metrics.scorecard_by_session`),
  bucketing each trade by the killzone of its entry so the overlap's numbers can
  be read in isolation before the bigger refactor.

**Two findings that justify the whole exercise**

1. **A look-ahead bug, caught by clean measurement.** FVG fill state
   (`fill_pct` / `is_fully_filled` / `revisit_count`) was computed in `precompute`
   by scanning the **entire** series, so a decision-time filter of "not yet filled"
   secretly selected FVGs the future never filled — guaranteed winners. In
   isolation this showed a *fake* **100% win rate / PF=∞** for `FVGRetest`. Fixed
   with a causal, incremental fill-state tracker (`_CausalFVGTracker`) + an
   `up_to_index` bound on `_update_fill_tracking`. After the fix `FVGRetest` reads
   **35.6% WR, expectancy −1.8 → noise**. ⚠️ *The production rule engine shares this
   pipeline and is almost certainly inflated by the same leak* — flagged for a
   follow-up audit of zone/wick mitigation state.

2. **ERL/IRL — the quarantined concept — is the single best alpha.** Honest dev-span
   scorecards (H1, 2015→2025-12):

   | alpha | n | exp/trade (pips) | PF | WR | maxDD | Sharpe | verdict |
   |---|---|---|---|---|---|---|---|
   | **reaction + ERL/IRL** | 826 | **+5.47 [−0.64, +12.0]** | **1.16 [0.98, 1.36]** | 34.3% | **10.1%** | **0.92** | best (CI kisses 0) |
   | reaction + ERL/IRL + HTF draws | 729 | +2.38 [−4.1, +9.8] | 1.07 | 33.7% | 10.6% | 0.40 | draws hurt |
   | reaction (plain) | 915 | +0.05 [−5.8, +6.1] | 1.00 | 33.4% | 32.8% | 0.01 | noise |
   | reaction + HTF draws | 831 | −3.50 [−9.3, +2.5] | 0.91 | 31.4% | 42.7% | −0.62 | draws hurt |
   | SDZoneRetest | 5511 | −1.20 | 0.92 | 39.0% | 67.8% | −0.63 | noise |
   | LiquidityGrabReversal | 1526 | −1.45 | 0.94 | 35.8% | 26.7% | −0.41 | noise |
   | FVGRetest *(leak fixed)* | 1116 | −1.80 | 0.93 | 35.6% | 31.3% | −0.47 | noise |
   | FibRetracement | 2546 | −2.03 | 0.86 | 37.2% | 55.1% | −1.15 | noise |
   | BOSContinuation | 101 | −5.37 | 0.83 | 26.7% | 11.1% | −1.06 | noise |

   The five anticipation strategies have **no standalone OOS edge** (consistent with
   Phase A). The reaction engine alone is a coin flip. Adding the ERL/IRL draw-bias
   turns it into the only positive-expectancy, low-drawdown alpha (Sharpe ≈ 0.9,
   maxDD 10% vs 33%). Its expectancy CI lower bound sits just below zero, so it is not
   yet a confirmed edge — but it is the clear lead candidate, and the correlation-aware
   meta-allocator hands it **79.8%** of the book (the ensemble's 0.52 Sharpe does *not*
   beat it alone at 0.57). The Phase-C/D elaborations (partial scaling, deep HTF draws,
   multi-position) all **reduce** its quality — see §10.5/§10.7. **This inverts the prior
   assumption:** ERL/IRL is the most additive idea we have, not the underperformer.

   The five strategies are near-uncorrelated with each other (|ρ|≈0–0.14); reaction
   and reaction+ERL/IRL correlate 0.67 (same engine). With only one positive alpha,
   the allocator puts 100% on `reaction_erl_irl` and there is no ensemble gain yet —
   diversification needs ≥2 surviving alphas.

**Session / killzone breakdown (reaction path).** With session-awareness on (the
overlap block removed; off-session reactions dampened — see
[04 §04.2d](04-reaction-engine.md)), the per-killzone scorecards confirm the overlap
is where the reaction engine earns its keep:

| killzone | reaction (plain) | reaction + ERL/IRL |
|---|---|---|
| **London/NY overlap** | n=363, exp +1.9, PF 1.05, Sharpe 0.30 | **n=368, exp +6.5, PF 1.17, Sharpe 1.02, DD 10%** |
| London | n=365, exp +1.3, Sharpe 0.28 | n=317, exp +2.5, Sharpe 0.55 |
| NY | n=134, exp **−7.2**, Sharpe −1.11 | n=101, exp +3.4, Sharpe 0.50 |
| Asia | n=47, exp +4.4 (noisy) | n=37, exp +27 (tiny n, wide CI) |
| off | thin | thin |

Two takeaways: (1) the **overlap is the single best killzone** for the reaction +
ERL/IRL path (Sharpe ≈ 1.0, +6.5 pips/trade) — validating the decision to stop
blocking it and route it to the reaction engine; (2) ERL/IRL flips **NY** from a −7.2
pip bleeder into +3.4. Overlap CIs still straddle zero, so it is the lead *candidate*,
not a confirmed edge — but it is unambiguously the engine's best window.

**Verdict / next:** promote ERL/IRL from quarantine to **lead candidate**; confirm
on the **sealed test** (`scripts/evaluate.py --unseal-test`) only after Phase C/D.
Keep the dead strategies disabled but in-tree for reference. Audit the production
engine for the same fill-state leak.

---

## 10.5 Phase C — Position management: partial scaling + delayed-but-decisive entry

**Goal:** capitalize on confirmed impulsive moves the way a desk does — book
partials, run a piece to the HTF draw, and enter *late but decisively* when RR
still justifies it. Low-risk, high-value; built only after A & B are locked.

**C.1 Partial scaling-out**
- Book a partial (e.g. close ⅔) at ~1R, trail/run the remainder to the HTF-zone
  draw or PD-array target. Reduces variance and locks the "let it run to demand"
  thesis without round-tripping.

**C.2 Delayed-but-decisive impulse entry** *(the key reframe)*
- The agent does **not** need to catch the tick. On a **closed bar** it detects
  the impulse, then asks one question: *is there still enough distance to the draw
  (the demand/supply zone) for acceptable RR?* If yes, it enters — even 60–90 min
  late. Friday's 9am NY sweep is enterable at 9:30/10:00 as long as the demand
  zone still leaves meat on the move.
- This is "is there still RR to the target?" — not "did I catch the move?" — and
  it pairs directly with the HTF-zone-draw work already shipped.

**Deliverables:** partial-exit logic in the monitor; a "late-entry-while-RR-
remains" check in the reaction path; explainable log lines for both. Tests +
documentation in [05 — Position Sizing & Risk](05-position-sizing-and-risk.md).

**Acceptance gate:** improves expectancy or materially reduces variance on
**validation** without degrading PF; confirmed once on the locked test set.

### What shipped (and the result of the gate)

- **A measurable managed-exit policy** — `agent/risk/managed_exit.py`
  (`ExitPolicy` + `simulate_managed_exit`): a pure, path-aware replay of a
  partial scale-out at `partial_at_r` R with a break-even (or original-stop)
  runner to the draw. Conservative intrabar ordering (adverse level first).
- **Wired into the alpha backtest** — `run_alpha(..., exit_policy=, min_entry_rr=)`
  so the policy is *measured on the same signals* as the baseline. The default
  path is byte-for-byte the validated Phase-B path (knobs off).
- **Reproducible A/B** — `python scripts/evaluate_alphas.py --manage` prints
  baseline-vs-managed for every reaction alpha, overall **and** in the overlap.
- **Live wiring, gated** — broker partial-close (`close_position(volume=…)`,
  MT5 + paper), monitor partial scale-out + BE on the runner
  (`LiveConfig.partial_exit_enabled`, **default off**), and a delayed-but-decisive
  room guard in the reaction path (`LiveConfig.min_room_rr`, default 0 = off).

**The gate verdict — partial scaling FAILS for the lead alpha, so it ships OFF.**
On `reaction + ERL/IRL` over 4y, every scale-out variant cut variance but
**degraded PF and expectancy** — it failed "without degrading PF":

| Exit on reaction+ERL/IRL | n | exp/trade | PF | WR | Sharpe | pnl σ |
|---|---|---|---|---|---|---|
| baseline (runner to draw) | 291 | **+4.21** | **1.12** | 31.6% | **0.71** | 93.6 |
| partial 50% @1R + BE | 406 | −0.75 | 0.97 | 50.0% | −0.19 | 63.4 |
| partial 50% @1R, runner orig-stop | 349 | −2.26 | 0.92 | 30.9% | −0.54 | 66.5 |
| partial 50% @2R + BE | 343 | +0.81 | 1.03 | 32.4% | 0.16 | 82.6 |

**Overlap killzone tells the same story, louder:** baseline overlap is the best
result on the desk — n=143, **exp +12.9, PF 1.37, Sharpe 2.03** — and *every*
partial variant collapses it (best managed overlap Sharpe ≈ 0.3). The edge of
this alpha **is the runner reaching the draw**; the fat right tail is the alpha.
Scaling out converts winners into scratches and trades the edge away for a
smoother (but flat-to-negative) equity curve.

**So "trade the overlap with risk control" ≠ chop the winners.** The risk control
that *fits* this alpha is the stack already in place: the wick-proof soft stop,
conviction-scaled sizing, the post-loss/consecutive-loss guards, and — the
Phase-B finding — **routing the overlap to the reaction engine** (session
selectivity) while **letting the runner ride to the HTF draw**. The partial-exit
machinery is kept, tested, and config-gated for alphas/regimes whose edge is
*not* tail-driven; it does not earn its keep on today's lead alpha.

**Delayed-but-decisive entry** (`min_entry_rr` / live `min_room_rr`): roughly
P&L-neutral overall and it **preserves the overlap edge** (Sharpe 1.59 at a 1.5
floor vs 2.03 baseline) while refusing late chases with no room left to the draw.
Shipped as an available, default-off discipline rather than a forced filter.

### Deeper HTF draws — now measured, both sides, symmetric

The reaction alphas previously targeted only daily anchors + a 60-bar swing
window + ERL/IRL; they never saw the **deep daily demand/supply zones** the live
loop already targets. That left "does targeting the deeper draw add edge?"
untested. `agent/context/htf_draws.py` now reconstructs those draws **causally**
over the full series (daily cadence, closed D1/H4 only — so the 9-month
`d1_zone_lookback_bars` window survives, which a per-chunk warm-up cannot), keyed
by bar time so it survives chunk-slicing. Detection is symmetric — a long's
**supply-above** draw is marked on ~23.8k of 25k bars and a short's **demand-below**
draw on ~23.9k — so the upside is perceived exactly like the downside.

Two variants (`reaction_htf_draws`, `reaction_erl_irl_htf`) measure the value.
On the **full locked dev span (2015→2025, A/B vs their no-draw twin):**

| Alpha | n | exp/trade | PF | Sharpe | maxDD |
|---|---|---|---|---|---|
| reaction | 915 | +0.05 | 1.00 | 0.01 | 32.8% |
| reaction + HTF draws | 831 | −3.50 | 0.91 | −0.62 | 42.7% |
| reaction + ERL/IRL | 826 | **+5.47** | **1.16** | **0.92** | 10.1% |
| reaction + ERL/IRL + HTF draws | 729 | +2.38 | 1.07 | 0.40 | 10.6% |

**Verdict: net-negative — ships off.** Targeting the distant daily zone *hurts*
both the plain reaction (badly) and the ERL lead (exp +5.47→+2.38, Sharpe
0.92→0.40). The deep draw is often far, so `_target` reaches for it and trades
away hit-rate. The meta-allocator agrees: `reaction_htf_draws` gets **0% weight**.

> **A note on honest measurement.** An earlier 4-year window showed HTF draws
> *lowering* the ERL variant's drawdown (9.2%→6.6%) — encouraging, and exactly the
> kind of result that becomes a permanent "improvement" if you stop there. The
> **full locked span reversed it.** That is the whole point of the Phase-A
> protocol: short windows are noise; the deeper draws are kept as scored-but-off
> variants, not promoted. The value of the deeper draws is now **measured** (and,
> symmetrically, *rejected* as a default), not assumed.

---

## 10.6 Quarantine: ERL/IRL magnets (and other underperformers)

Per decision, the ERL/IRL liquidity-magnet concept and its draw-bias were **not
removed** — they were **quarantined into the Phase-B modular structure** so they
got a *fair, standalone* OOS scorecard before any verdict.

**Outcome (see §10.4):** the fair test cleared them. `reaction + ERL/IRL` is the
**single best alpha** on the dev span (expectancy +6.07 pips, PF 1.18, maxDD 8.8%
vs 31% for plain reaction). ERL/IRL is therefore **promoted from quarantine to lead
candidate** — pending confirmation on the sealed test. They remain disabled in the
live default (`liquidity_magnet_enabled=False`) until that sealed-test confirmation.
Same fair-trial treatment still applies to any other feature that can't show
standalone OOS edge.

---

## 10.7 Phase D — Multi-position / pyramiding behind a hard risk budget

**Goal:** lift the single-position-slot limiter so the agent can hold multiple
trades (and flip on strong opposite impulses) — **only** with portfolio risk
controls, because "add more positions" with no cap is exactly how the account gets
blown.

**Non-negotiable guardrails**
- **Aggregate risk cap** — total open risk ≤ X% of equity across all positions.
- **Max N concurrent positions.**
- **Exposure-decaying size** — each additional position is sized *smaller* as
  aggregate exposure grows.
- **Net, don't offset** — on the same instrument, prefer **flipping** (reduce the
  loser, open the winner) over holding simultaneous long+short, which just pays
  two spreads to be market-neutral. (Hedging tickets allowed on Exness, but netting
  is the cheaper expression of the same view.)

**Deliverables:** a portfolio risk manager; multi-position support in the live
loop + monitor; flip logic; explainable logs. Tests + documentation in
[05 — Position Sizing & Risk](05-position-sizing-and-risk.md) and
[08 — Live Trading](08-live-trading-and-deployment.md).

**Acceptance gate:** improves risk-adjusted return (Sharpe / return-per-unit-risk)
on **validation** with no increase in max drawdown beyond a pre-agreed bound;
confirmed once on the locked test set; then forward-tested on demo before live.

### What shipped (and the result of the gate)

- **Pure `PortfolioRiskManager`** (`agent/risk/portfolio.py`): a decision-only
  policy enforcing the four guardrails — aggregate risk cap, max-N concurrent,
  exposure-decayed add size, and **net-don't-offset** (an opposite signal *flips*,
  it doesn't hold a hedged pair). Returns OPEN / ADD / FLIP / DENY + the admitted
  risk slice.
- **Portfolio-aware backtest** (`agent/alphas/portfolio_backtest.py`): runs the
  *same* alpha signals while holding up to N positions, sizing each as a fraction
  of equity, so multi-position behaviour is measured on the equity curve
  (return / maxDD / return-per-DD / per-trade Sharpe), not assumed.
- **Live wiring, gated** (`LiveConfig.portfolio_enabled`, **default off**): the
  manager replaces the bare max-positions block; a FLIP closes opposite tickets
  before entry; adds are exposure-decayed and budget-capped. Default config = the
  current single-slot behaviour, so nothing changes until it's switched on.

**The gate verdict — multi-position FAILS, so it ships OFF.** A/B on
`reaction + ERL/IRL` over 4y (equity terms, 1% base risk):

| Mode | n (flips/adds) | return | maxDD | ret/DD |
|---|---|---|---|---|
| single (baseline) | 291 (0/0) | −4.0% | **24.0%** | −0.17 |
| flip-only | 707 (268/0) | −16.5% | 37.9% | −0.44 |
| pyramid ×2 | 516 (0/297) | −12.2% | 35.5% | −0.35 |
| pyramid ×2 + flip | 1102 (300/449) | −7.9% | 41.8% | −0.19 |

Lifting the single slot **balloons drawdown (24%→38-42%)** and worsens return.
Flips churn (268 of them — the reaction engine's opposite signals are not reliable
reversals, so flipping pays spread to bleed), and pyramiding stacks size into
moves that then reverse. This fails the gate's core condition ("no increase in max
drawdown") decisively. The **single-position slot is protective** and stays the
default; the flip behaviour that *does* help — a committed reversal bypassing the
post-loss cooldown — already lives in the [no-revenge guard](05-position-sizing-and-risk.md)
and doesn't require holding concurrent exposure. The portfolio machinery is kept,
tested, and gated for alphas/regimes where concurrency might earn its keep.

---

## 10.8 Status tracker

| Phase | Scope | Status |
|-------|-------|--------|
| E | This plan doc | ✅ done |
| A | Lock evaluation protocol (hold-out + purged walk-forward + CIs) | ✅ done — see [07.4](07-backtesting.md) |
| B | Modular alphas + meta-allocator (+ quarantine ERL/IRL) | ✅ done — see §10.4 findings + [01 §Modular alphas](01-strategy-architecture.md) |
| C | Partial scaling + delayed-decisive entry | ✅ done — built, measured, **scaling ships OFF** (fails PF gate on lead alpha); see §10.5 |
| D | Multi-position + portfolio risk budget | ✅ done — built, measured, **ships OFF** (DD balloons 24%→38-42% on lead alpha); see §10.7 |

### Phase A finding (the baseline to beat)

The first honest run is sobering and validates the overfitting concern: the
**rules-only** stack over a purged 36-fold walk-forward (2015→2025, 1,900 trades)
scores **expectancy +0.72 [−4.82, +5.88]** and **PF 1.01 [0.91, 1.12]** — both
intervals straddle break-even, i.e. **no demonstrable out-of-sample edge**. The
tuned backtest numbers do not survive honest validation. Phase B's job is to find
which *individual* concepts clear this bar.
