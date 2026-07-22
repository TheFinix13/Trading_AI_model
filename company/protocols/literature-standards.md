# Literature Standards — what "credible by literature standards" means

Blue Lock Trading Co. makes public claims: on `/performance`, on
`/research`, on `/players/<id>`, on `/hq`, and (Sprint 4+) on any
marketing / landing surface. Every one of those claims must survive
being read back by a hypothetical outside reader — a researcher, a
regulator, a journalist, a savvy user — who asks:

> *"Where did that number come from, was the test pre-registered,
> what were the kill conditions, what is the p-value after multiple
> testing correction, and can I reproduce it?"*

If we can't answer all five, the claim comes down. This protocol codifies
the answering apparatus.

Written 2026-07-22 as the operating consequence of the CEO's
"literature-standard R&D" directive. Adopted by CTO decision; CEO signs
off. Extends the pre-registration discipline already practised in
`finance-research-experiments/programs/**/PROTOCOL.md` and codified in
that repo's `PROTOCOL_DISCIPLINE.md` and
`07-research-standards.md` §11.

## §1 Pre-registration

**Every research experiment declares hypothesis, methodology,
statistical test, success criteria, and kill conditions BEFORE the
experiment runs.** This is the single most important sentence in this
document.

Concretely, a pre-registration file (`PROTOCOL.md` or equivalent) MUST
be committed to git BEFORE any compute or measurement that could
influence the analysis is executed. The file MUST contain:

1. **Hypothesis** — one sentence, falsifiable. "Widening Rin's pair set
   to include USDCHF raises squad-level TQS by ≥ 0.02" is a hypothesis.
   "USDCHF is good for Rin" is not.
2. **Methodology** — the data, the panel, the split (in-sample /
   out-of-sample), the statistic, the seed. Enough detail that a
   stranger could re-run the study from the file alone.
3. **Statistical test** — the test, the alpha, and (if part of a
   family) the FDR budget. See §2.
4. **Success criterion** — a threshold. "≥ 5/7 windows pass C1 at
   mean-TQS ≥ 0.30" is a success criterion. "Rin looks better" is not.
5. **Kill conditions** — under what observable outcome does the study
   STOP (rather than pivot to something else). Kill conditions prevent
   forever-fishing.
6. **Non-goals / out-of-scope** — what this study is NOT trying to
   answer, so readers do not silently expand its claim.

The commit that lands the pre-registration MUST predate the commit
that lands the results. Both commits are on-record. If the analysis
needs to change after pre-registration (data problem discovered,
methodology bug found, panel unavailable), the pre-registration is
**amended in a new commit**, with the amendment section explaining
what changed and why. The original stays on-disk. See
`finance-research-experiments/programs/M001_multi_agent_ensemble/experiments/phase_ac_pitch_assignment/AMENDMENT_2026-07-20_ac0_methodology_switch.md`
as the canonical worked example.

## §2 Statistical rigour

- **FDR budget per campaign.** When a study runs N pre-registered
  tests, control the false discovery rate at a pre-declared q (usually
  q = 0.10) using Benjamini-Hochberg. `finance-research-experiments`
  already does this — Phase AC accounted 3 rejects out of 28
  pre-registered tests at q=0.10, and the STRICT reading (credit only
  `evaluated_pairs`) is documented in AC.1's verdict file. Codify:
  every campaign declares its budget in its PROTOCOL §Statistical
  test.
- **No p-hacking, no post-hoc test selection, no double-dipping
  datasets.** If you ran three tests and reported the one with the
  smallest p, the report is wrong. If you picked the metric after
  seeing the outcome, the report is wrong. If you tuned on the OOS
  panel that also produced the verdict, the report is wrong.
- **No post-freeze retuning.** Once a threshold is locked in the
  pre-registration, it does not change on the basis of the current
  study's numbers. Threshold changes require a new pre-registration.
  (This is the exact rule that has kept
  `finance-research-experiments` honest across 25 E-line experiments
  + G7 gate + Phase AC.)
- **CI / bootstrap not point estimates.** Wherever the underlying
  statistic supports it, report confidence intervals or bootstrap
  distributions, not just means. AC.2's headline was "delta A2−A1 =
  −0.006 [boot 95 % CI −0.017, +0.005], p(delta ≤ 0) = 0.861" — that
  is the standard we hold ourselves to.

## §3 Reproducibility

- **Fixed seeds.** Any process involving randomness (bootstrap,
  train/test split, roster ordering, tie-breaking) declares its seed.
  `sim/analysis/regress_ac0.py` locks `rng_seed=20260720` and is
  bit-for-bit reproducible; that is the pattern.
- **Versioned artefacts.** Every result file lives under a directory
  named after its study (`experiments/E011.../results.json`, not a
  loose `output/final.json`). Never overwrite; version (`_v2`, `_v3`)
  and preserve the prior file on disk per
  `07-research-standards.md` §3.
- **Exact commit SHA on every result.** The result file, the
  `REPORT.md`, or the `verdict.md` records the commit SHA of the
  codebase used to produce the numbers. If someone comes back six
  months later, they can `git checkout <sha>` and re-run.
- **Containerised or venv'd runs.** All runs use the same Python
  venv (`../multi-pair-trading-agent/.venv` for
  finance-research-experiments, or the platform's own venv for
  product-side experiments). Never rely on system Python.
- **Existing harnesses are the model.**
  `run_g7_v1_checkpoint_gate.py`,
  `run_ac0_compute.py`, `regress_ac0.py`, and the E011-E024 harnesses
  under `finance-research-experiments/programs/E0xx/` all take the
  same shape: CLI-driven, seed-locked, artefact-under-versioned-dir.
  Any new harness copies this pattern.

## §4 Honest negatives

**A failed hypothesis is a publishable finding.**

- Phase AC is the canonical company example: 1 of 8 AC.1 sub-arms
  cleared BH q=0.10, then AC.2 A2 failed the pre-registered squad-lift
  test (delta −0.006, p=0.861), and the negative shipped as
  `REPORT.md` with a top-line recommendation ("stay with A1
  baseline"). That report is the single most credibility-building
  research artefact this stack has produced.
- Every negative goes to `company/rd/findings/` in a condensed
  public-facing version, with a link back to the underlying
  `finance-research-experiments/programs/**/REPORT.md` for full detail.
- **We do not memory-hole negatives.** A `[RESEARCH-QUESTION]`
  intake item that fails its pre-registered test STILL closes the loop
  — the finding is published, the intake is marked `shipped` (in the
  sense that "we answered the question with 'no'"), and the user is
  notified with the finding link.

## §5 Product-side experiments

Every non-trivial product feature declares a hypothesis about user
behaviour BEFORE ship, defines a measurement, and reports the outcome.

The pattern in one worked example — F013 trade-approval mode:

| Field | Value |
|---|---|
| Hypothesis | "At least 30 % of proposed live orders will be reviewed within the 5-minute approval-queue timeout." |
| Panel | First 30 days of live-mode traffic (post F013 ship). |
| Measurement | `approval_queue` jsonl audit — count `approved` + `rejected` events with `latency_ms < 300_000`, divide by total `submitted`. |
| Statistic | Simple proportion + 95 % Wilson CI. |
| Success | Proportion ≥ 0.30, lower CI bound ≥ 0.20. |
| Kill | Proportion ≤ 0.05 for 3 consecutive days → auto-timeout is too aggressive, needs re-scoping. |
| Report | `company/rd/findings/F013-30d-approval-review-rate.md` + `/hq` KPI strip cell. |

Feature specs (P0 features) MUST carry a §Hypothesis section with
these fields. Fast-path features are exempt — they don't ship
capability that has a user-behaviour hypothesis worth testing.

## §6 Citation discipline

External references (papers, textbooks, blogs, industry reports) cited
in company output MUST include:

1. Authors (family names + initials).
2. Year.
3. Title.
4. Venue (journal, conference, book, URL).
5. DOI or a permanent URL where possible.

Examples of correctly-cited external work already in this stack:
Benjamini & Hochberg (1995) FDR; Kaufman-Sweeney efficiency metrics;
Almgren & Chriss (2001) friction cost. The `/research` page
(F003) renders citations in this format — that is the model to
follow.

**No fabricated citations.** If you are unsure whether a reference is
real, mark it `TODO(citation)` and move on; Legal or CTO fills in
during review. Fabricated references are a hard-fail during Legal
review and are removed before ship.

## §7 Peer review

- **Internal peer review** by another persona is table-stakes for any
  claim that ships. This is what the existing review chain does — QA,
  Legal, CTO all read the claim before signoff. Codify: no claim
  ships without a documented review-chain traversal.
- **External peer review** — a reviewer who is not on the payroll,
  including academic collaborators or a subject-matter expert
  contacted by CEO — triggers on:
  - Any public whitepaper about the Blue Lock methodology (Sprint 6+).
  - Any claim of investment-grade performance ("we beat X% of retail
    traders").
  - Any claim of statistical superiority over a named alternative
    method.
  Legal + CTO decide when external review fires; the CEO signs off on
  the reviewer choice.

## §8 The /research page as the public interface

`F003 /research` is where literature-standard claims land publicly.
Every entry on that page carries:

1. A one-line hypothesis.
2. A verdict (PASS / FAIL / AMBIGUOUS / IN-PROGRESS).
3. A link to the underlying PROTOCOL + REPORT commit in
   `finance-research-experiments`.
4. A short prose summary written by the Brand Designer + reviewed by
   Legal.
5. A DOI-style permanent slug (`/research/phase-ac-pitch-assignment`).

Research Lead is the final gate on what appears there (per D007;
now formalised in `roles/research_lead.md`). Legal reviews the
copy. CEO retains veto.

## §9 Non-negotiables (the five things that get a claim pulled)

If any of these are true about a claim we've published, that claim
is pulled within 24 h and a correction posted on `/research`:

1. **The pre-registration does not exist** or postdates the results.
2. **The test was not corrected** for multiple comparisons when it was
   part of a family.
3. **The result cannot be reproduced** from the committed code + data
   at the recorded SHA.
4. **A citation is fabricated** or misattributes a real paper.
5. **A negative was suppressed** — the study ran, produced a result,
   and we did not publish it because it wasn't the answer we wanted.

## §10 What literature standards is NOT

- **Not paralysis.** Small internal analyses that inform no public
  claim don't need a `PROTOCOL.md`. A quick dogfood ("does the
  approval-queue UI feel slow?") is an intake item, not a
  pre-registration.
- **Not academic gatekeeping.** We are not chasing peer-reviewed
  publication as the outcome — we are borrowing the *rigour* that
  peer-reviewed publication demands, so that the claims we do make
  survive scrutiny.
- **Not a hurdle to ship.** The pre-registration + reproducibility
  cost is < 1 hour per experiment on top of the compute. The
  existing `finance-research-experiments` cadence proves the tax is
  affordable.

## §11 Related documents

- `finance-research-experiments/PROTOCOL_DISCIPLINE.md` — the canonical
  research-lane discipline this protocol is codifying company-wide.
- `finance-research-experiments/programs/M001_multi_agent_ensemble/07-research-standards.md`
  §11 — verdict-comparator discipline + no-retuning rule.
- `rd-loop.md` — how `[RESEARCH-QUESTION]` intake items become
  pre-registered experiments.
- `roles/research_lead.md` — the human owner of this protocol.
- `review-chain.md` — the review that ensures literature standards
  are actually applied at every claim-shipping stage.
