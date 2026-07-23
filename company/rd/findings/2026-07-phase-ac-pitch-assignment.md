# Widening a striker's pair set did not help the squad — Phase AC pitch assignment

- **Slug:** phase-ac-pitch-assignment
- **Study source:**
  `finance-research-experiments/programs/M001_multi_agent_ensemble/experiments/phase_ac_pitch_assignment/REPORT.md`
  (branch `multi-agent-ensemble`, results commit `2c8e363`)
- **Panel:** 7-pair extended FX panel (EURUSD, GBPUSD, USDCAD, AUDUSD,
  NZDUSD, USDJPY, USDCHF), 7 out-of-sample walk-forward windows,
  phi41 aggregator, `sentinel_blocks=True`.
- **Statistic:** per-window mean Trade Quality Score (TQS); 10,000-resample
  window-level bootstrap, seed 20260720; Benjamini–Hochberg FDR at
  q = 0.10 over a pre-registered 28-test family.
- **Verdict:** FAIL (pre-registered AC.2 primary criterion) — honest negative.
- **Filed:** 2026-07-23 by Research Lead.
- **Reviewed:** CTO (2026-07-23 — artifact-trace audit: every number below
  verified against the on-disk verdict files at the recorded commit SHAs;
  compute not re-fired) · Legal (2026-07-23 — citation + non-negotiables
  check) · Brand (2026-07-23 — copy review).
- **Published to `/research`:** 2026-07-21 via the CPO publication
  manifest (`campaign_id: phase_ac_pitch_assignment`); this condensed
  finding filed 2026-07-23.

## What we asked

Our squad has three "movable" striker agents whose home currency pairs
were assigned by canon, not by evidence: Chigiri (speed/momentum), Rin
(analytical precision), and Kunigami (defensive, currently retired as a
proposer). Phase AC asked, in three pre-registered stages: (AC.0) do
measurable pair-character features predict how well an agent trades a
pair at all? (AC.1) does any specific agent-pair widening pass the
individual quality bar? (AC.2) does the surviving widening actually
improve the *squad's* decision quality — the only criterion that
authorises a production change?

The question matters to a user because it is exactly the kind of
plausible-sounding improvement ("put the precision striker on the
Swiss franc, it suits his style") that gets shipped on vibes elsewhere.
We pre-committed to numbers before running anything.

## What we did

The hypothesis stack, success thresholds, and kill conditions were
locked in a pre-registration (`PROTOCOL.md`, commit `083c0e9`) before
any compute fired, and amended once, in the open, when a methodology
problem was found (`AMENDMENT_2026-07-20_ac0_methodology_switch.md`,
commit `0ac645a` — the amendment preserves the original text and the
pass criterion unchanged). The pre-registration budgeted 28 statistical
tests under a Benjamini–Hochberg false-discovery-rate correction at
q = 0.10.

Stage AC.0-v2 regressed each movable agent's per-pair per-window mean
TQS against a frozen pair-character feature vector (OLS + 10,000-sample
window-level bootstrap, seed 20260720). Stage AC.1 evaluated eight
pre-registered agent-pair sub-arms against the C1 quality criterion
(mean TQS ≥ 0.30, ≥ 5 of 7 windows ≥ 0.20, bootstrap 95% CI lower
> 0.25). Stage AC.2 ran two full squad walk-forwards — A1 (baseline)
and A2 (the one surviving widening: Rin on EURUSD + USDCHF) — with the
pre-registered success criterion: squad mean-of-window-mean TQS lift
≥ +0.02 with bootstrap 95% CI lower bound > 0, and no regression on
the three anchor agents.

## What we found

**The squad-level test failed.** A2 − A1 squad TQS delta =
**−0.006 [bootstrap 95% CI −0.017, +0.005], p(delta ≤ 0) = 0.861** —
below the pre-registered +0.02 lift and consistent with zero. The
anchor lock held (Isagi, Bachira, Barou identical in both arms), so
the widening didn't hurt the others; it simply didn't help the squad.

The stage results underneath are more nuanced than "pair character
doesn't matter":

- **AC.0-v2 PASSED, thinly.** Pair-character features do explain a
  non-trivial share of per-agent TQS variance, but only one
  (agent, feature) pair respected its pre-locked directional prior:
  Chigiri × session-open impulse (β = +1.10, bootstrap CI lower
  +0.27). Kunigami produced zero telemetry — his un-retirement wiring
  failed silently and his sub-arms were declared NOT_TESTABLE rather
  than counted as evidence.
- **AC.1: 1 of 8 sub-arms authorised a widening.** Rin on
  EURUSD + USDCHF passed C1 (mean TQS 0.357, 6/7 windows, CI lower
  0.295) and survived BH at q = 0.10. This is the one exception that
  passed — as an *individual-agent* finding it still holds (Rin passes
  C1 individually in the A2 arm at 0.341).
- **The individual pass did not survive aggregation.** In the squad
  arm, Rin's trade count rose 203 → 391 but her mean TQS fell
  0.370 → 0.341: the added USDCHF trades were lower-quality in the
  ensemble. Per-agent solo quality ≠ squad-level contribution — this
  interaction is precisely what the AC.2 layer was designed to catch.
- **FDR arithmetic, honestly accounted:** 28 tests pre-registered;
  8 (AC.1 sub-arms) reduced to 5 testable (3 NOT_TESTABLE sentinels
  excluded from the BH family with no p-value); 3 of the 20 reserved
  AC.2 tests executed this campaign (AC2.2 p = 0.8613; AC2.3 Nagi
  floor p = 1.0000 in both arms). Net: **3 rejects out of 28
  pre-registered tests, all in AC.1**; zero AC.2 rejects. The B1
  multi-squad arms and the C3-poisoning check were deferred/not
  measured and are reported as such, not assumed clean.
- **Surprise regression (unrelated to widening):** Nagi and Reo
  produced 0 trades in *both* arms on the extended 7-pair panel,
  despite Nagi passing C1 comfortably on the 3-pair panel — a
  baseline-reproduction issue the campaign surfaced but did not cause.

## What it means

**No pitch-assignment widening ships. The squad stays on the A1
baseline.** Concretely: `build_roster` keeps its current per-agent
pair assignments; the Rin-USDCHF override that AC.1 authorised at the
individual level does not clear the squad-level shipping gate and is
not deployed. Nothing about the live product changed because of this
study — and that is the finding working as intended: three days of
compute bought us a quantified "no" instead of a shipped regression.

## What we're doing next

- **Nagi extended-panel diagnostic** (highest priority): find why the
  confluence-gated agent goes silent when the panel widens from 3 to
  7 pairs. Blocks any faithful AC.2 re-run.
- **Kunigami un-retirement wiring fix** — his sub-arms were never
  actually tested.
- **`SquadEngineMulti` harness build** for the deferred B1-hard /
  B1-soft multi-squad arms, then a re-run with the C3-poisoning check
  exported.
- We are **not** re-running A2 with a lower threshold — the +0.02
  lift criterion was pre-registered and stays.

## Citations

- Benjamini, Y. & Hochberg, Y. (1995). "Controlling the False
  Discovery Rate: A Practical and Powerful Approach to Multiple
  Testing." *Journal of the Royal Statistical Society, Series B*,
  57(1), 289–300. DOI: 10.1111/j.2517-6161.1995.tb02031.x.

## Source & reproducibility

- Pre-registration commit: `083c0e9` (PROTOCOL.md, 13 sections, locked
  2026-07-20 before compute); amendment commit: `0ac645a`.
- Stage result commits: `b31a36f` (AC.0-v2 PASS-thin), `fd5d55d`
  (AC.1: 1 of 8 sub-arms), `2c8e363` (AC.2: A2 FAIL — the headline
  numbers above).
- Seed: 20260720 (10,000-resample window-level bootstrap, all stages).
- FDR budget: q = 0.10, family size N = 28 pre-registered (5 + 3
  executed), rejects = 3 (all AC.1; STRICT reading credits only
  AC.1.rin-a toward a widening).
- Artefact paths (all under
  `finance-research-experiments/programs/M001_multi_agent_ensemble/experiments/phase_ac_pitch_assignment/`):
  `PROTOCOL.md`, `AMENDMENT_2026-07-20_ac0_methodology_switch.md`,
  `REPORT.md`, `results/ac0_verdict_v2.md`,
  `results/ac0_regression_v2.json`, `results/ac1_verdicts.md`,
  `results/ac1_verdicts_summary.json`, `results/ac2/` (per-arm compute
  + verdicts), `results/pair_character.json` (frozen feature vector).
