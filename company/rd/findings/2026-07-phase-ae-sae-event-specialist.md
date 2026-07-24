# The event-window striker doesn't have an edge — Phase AE Sae event specialist

- **Slug:** phase-ae-sae-event-specialist
- **Study source:**
  `finance-research-experiments/programs/M001_multi_agent_ensemble/experiments/phase_ae_sae_event_specialist/REPORT.md`
  (branch `multi-agent-ensemble`, verdict commit `16a404b`)
- **Panel:** EURUSD M15 event windows over the §11.17 walk-forward
  panel (2015–2025), 349 frozen high-impact USD events (131 NFP,
  131 CPI, 87 FOMC), H4 replay with M15 event-tick injection,
  phi41 aggregator, R7 news-block absent by construction so Sae's
  contribution is measured cleanly.
- **Statistic:** out-of-sample mean Trade Quality Score (TQS);
  10,000-resample bootstrap 95% CI, seed 42; pre-registered
  criteria AE1–AE4 evaluated exactly once.
- **Verdict:** FAIL (pre-registered AE2 quality criterion) — honest
  negative.
- **Filed:** 2026-07-24 by Research Lead.
- **Published to `/research`:** 2026-07-24 via the CPO publication
  manifest (`campaign_id: phase_ae_sae_event_specialist`).

## What we asked

Sae Itoshi is the squad's designed event specialist: a striker that
only proposes inside a [T−30 m, T+60 m] window around high-impact
USD releases (NFP, CPI, FOMC), using two pure-price M15 mechanics —
**fade** (bet against a 40+ pip release bar with a large rejection
wick) and **ride** (bet with the impulse when the next bar retains
70%+ of the move). The implementation shipped months ago but has
been hard-gated OFF pending exactly this study. Phase AE asked the
only question that matters before enabling him: do these mechanics
make money out-of-sample, at pre-registered thresholds, without
damaging the rest of the squad?

The question matters to a user because "trade the news" is one of
the most-marketed retail forex ideas. We pre-committed thresholds
before running anything, with the August 7 NFP as the arming target
on a pass.

## What we did

The pre-registration was drafted 2026-07-20 and locked + committed
2026-07-24 (`dfe5ce1`) before any compute fired, with five factual
amendments recorded in the open — the largest being the calendar
data source: the sibling Phase AD fixture was never actually frozen,
so this campaign built a new one from primary sources (BLS release
schedules via pinned archive snapshots + federalreserve.gov FOMC
calendars), froze it with a recorded SHA-256, and never refetched.
The baseline arm reproduces the sealed walk-forward driver
byte-for-byte (equivalence test, green before the arms ran).

Two arms ran over the full panel: baseline (Sae off) and treatment
(Sae on, verbatim mechanics and config from the production
`a09_sae.py`). Success required AE1 (≥30 OOS Sae trades) AND AE2
(OOS mean TQS ≥ 0.30 with bootstrap 95% CI lower bound > 0.20) AND
AE4 (no incumbent agent regresses by more than 0.02 mean TQS).

## What we found

**Sae fires, but loses.** Volume was never the problem — 54
out-of-sample trades, comfortably over the AE1 floor. Quality was:

- **AE2 FAIL:** OOS mean TQS **0.097**, bootstrap 95% CI
  **[0.042, 0.162]** — the CI *upper* bound sits below both the
  0.30 mean floor and the 0.20 lower-bound floor. This is not a
  near-miss.
- **Trade-level signature:** 25 take-profits vs 62 stop-losses =
  **28.7% wins at a fixed 1.5R target**, where breakeven needs 40%.
  Mean −4.16 pips per trade.
- **AE3 mechanic split:** both mechanics lose independently — fade
  (22.2% of trades, −4.18 pips mean) and ride (77.8%, −8.52 pips
  mean). Neither fell under the 20% park threshold; there is no
  salvageable half.
- **Uniform failure, not one bad regime:** no OOS window exceeded
  0.266 mean TQS; one window hit 0.000.
- **AE4 PASS — the mechanism is clean even though the edge isn't:**
  five incumbent agents were bit-identical between arms; the largest
  delta was +0.001 (Chigiri), with only 2 incumbent trades displaced
  across 11 years. Adding an event-window striker does not disturb
  squad chemistry; this matters for any future Sae v2.

## What it means

**Sae stays off. No NFP trades on August 7** — or any event — from
the current mechanics. `sae_enabled` remains `False` in production;
the dashboard keeps rendering him dimmed with the "(off)" label.
The hour-13 news bleed that motivated both event studies now reads
as **"avoidable, not tradable"**: Karasu, the news *defender* that
risk-gates event windows, remains the only live event-window lever.

Live trading would have been worse than the simulation: the harness
models no event-window spread widening or slippage, both of which
are severe at NFP. The FAIL is conservative.

## What we're doing next

- **Nothing ships.** Per the locked stop rules, the v1 fade/ride
  mechanics and the 1.5R bracket may not be retuned against this
  panel — that would be threshold-shopping on spent out-of-sample
  data.
- Any **Sae v2** (e.g. surprise-z gating on the actual-vs-consensus
  release value, different bracket geometry, or a different event
  subset) requires a fresh pre-registration on fresh evaluation
  budget.
- **Phase AD (Karasu)** proceeds independently — defence was never
  contingent on offence.

## Citations

- Efron, B. (1979). "Bootstrap Methods: Another Look at the
  Jackknife." *The Annals of Statistics*, 7(1), 1–26.
  DOI: 10.1214/aos/1176344552.

## Source & reproducibility

- Pre-registration commit: `dfe5ce1` (PROTOCOL.md locked with §0
  amendments before compute); harness commit `8fbc2ba` (+15 tests);
  loader fix `766326a`; verdict commit `16a404b`; registry commit
  `2b3ef4b`.
- Calendar fixture: `data/news_calendar_frozen_2026-07-24.json`,
  349 events, sha256
  `cfd186021ea87a5acba4f672250519d89fb8657c11473a73621bcc78c0ee3134`.
- M15 data: EURUSD parquet cache, 284,277 rows,
  2015-01-01 → 2026-05-27 (read-only coupling).
- Bootstrap: 10,000 resamples, seed 42.
- One incident disclosed in REPORT §3: an early data loader
  triggered a production auto-backfill network path; it was killed
  within minutes, the cache verified undamaged, and the loader
  rewritten network-free before any scored run.
- Artefact paths (all under
  `finance-research-experiments/programs/M001_multi_agent_ensemble/`):
  `experiments/phase_ae_sae_event_specialist/{PROTOCOL,REPORT}.md`,
  `experiments/phase_ae_sae_event_specialist/results/phase_ae_evaluation.json`,
  `reviews/phase_ae_verdict.md`.
