# company/rd/findings/ — how to publish a finding

`findings/<slug>.md` files are the "public-facing" condensed versions
of research verdicts. Source of truth stays canonical at
`finance-research-experiments/programs/**/REPORT.md` (or the equivalent
product-side artefact); this directory carries the 1-2 page prose
version that Brand + Legal have signed off on, ready for promotion to
the public `/research` page (F003) — Research Lead is the final gate
per D007.

One finding = one file.

## Publication path

1. **Underlying study closes** in `finance-research-experiments/` (or
   the product-side measurement window closes).
2. **Research Lead** drafts a condensed `findings/<slug>.md` — 1-2
   pages of Brand-friendly prose, with the numbers preserved but the
   detail compressed.
3. **CTO peer review** — reproducibility check per
   `literature-standards.md` §3: commit SHA on every number, seed
   declared, artefact versioned. If a number in the condensed
   finding can't be traced back to a specific `finance-research-experiments`
   commit + file + line, it's an error.
4. **Legal review** — every citation checked (real authors + year +
   venue + DOI/URL) per `literature-standards.md` §6; every claim
   sits in `company/legal/claim_register.md`; five non-negotiables
   (`literature-standards.md` §9) all clear.
5. **Brand review** — "no ensemble, no aggregator" gate; tone matches
   `/research` page copy; user-facing language, not internal jargon.
6. **Research Lead final sign-off** — verifies the science one last
   time, including any post-review edits.
7. **Promote to `/research`** — Frontend engineer adds the entry to
   the `/research` timeline (F003 already renders from a manifest).
   The condensed finding file gets a permanent slug
   (`/research/<slug>`).
8. **Notify** the R&D loop — CPO adds a `D###` decisions-log bullet;
   any intake item that motivated the study moves to
   `status: shipped` with a `linked_experiments` entry; User Advocate
   sends the notify handshake if the intake submitter left contact.

## Template — every findings file has these sections

```markdown
# <Title — one line, human-readable>

- **Slug:** <finding-slug>
- **Study source:** <path to finance-research-experiments/**/REPORT.md
                    + commit SHA, or feature spec §Hypothesis link>
- **Panel:** <what data, what window>
- **Statistic:** <what test, what CI, what FDR budget>
- **Verdict:** PASS | FAIL | AMBIGUOUS | IN-PROGRESS
- **Filed:** YYYY-MM-DD by Research Lead
- **Reviewed:** CTO (YYYY-MM-DD) · Legal (YYYY-MM-DD) · Brand (YYYY-MM-DD)
- **Published to `/research`:** YYYY-MM-DD (or "not yet")

## What we asked

<1-3 paragraphs — the question in plain English, why it matters to a
user reading it.>

## What we did

<2-4 paragraphs — the method compressed. Panel, statistic, success
criterion, kill condition. Reproducibility anchors (seed, commit SHA,
FDR budget).>

## What we found

<2-4 paragraphs — the numbers with CIs. Both directions of the
verdict (what passed, what didn't). Include the honest limitations
(sample size, panel width, kill conditions hit).>

## What it means

<1-2 paragraphs — practical implication for the product / user.
Concrete, not abstract. Include the "so what" — did anything change
in the product because of this? if not, why not?>

## What we're doing next

<1 paragraph or bullet list — follow-up studies, product changes
motivated by the finding, or (for negatives) a clear "we're not
doing X because Y".>

## Citations

<Real authors + year + title + venue + DOI/URL. No `TODO(citation)`
entries in a published finding — those must be resolved before Legal
review.>

## Source & reproducibility

- Study commit: <full SHA>
- Codebase commit: <full SHA>
- Seed: <if applicable>
- FDR budget: q=<value>, family size N=<value>, rejects=<value>
- Artefact paths: <list of the canonical artefact files>
```

## First candidate — Phase AC negative

The Phase AC pitch-assignment negative (AC.2 A2 FAIL, delta −0.006,
p=0.861, recommended stay with A1 baseline) is the canonical
company-negative example flagged in `literature-standards.md` §4.

**Publication candidate slug:** `phase-ac-pitch-assignment`.

**Source of truth:**
`finance-research-experiments/programs/M001_multi_agent_ensemble/experiments/phase_ac_pitch_assignment/REPORT.md`
+ commit `2c8e363` (on branch `multi-agent-ensemble`).

**Why publish it:** it demonstrates the honest-negative discipline in
action. Phase AC ran three stages (AC.0-v2, AC.1, AC.2), spent
three-plus days of compute, and produced a "no, don't ship it"
verdict with quantified confidence. That is exactly what the
literature-standards protocol is asking for — and it happens to be
already on-disk in a sibling repo, waiting to be condensed for a
public audience.

**Next steps to actually publish it:**

1. Research Lead drafts `findings/phase-ac-pitch-assignment.md`
   using the template above (~1.5 pages).
2. CTO reproduces the number: `git checkout 2c8e363` in
   `finance-research-experiments`, walk through the REPORT.md
   verdict chain, verify AC.2 A2 delta = −0.006 with the recorded
   seed.
3. Legal reviews citations (BH FDR from Benjamini & Hochberg 1995 —
   real DOI: 10.1111/j.2517-6161.1995.tb02031.x).
4. Brand rewrites for `/research` tone.
5. Research Lead + CEO sign the final version.
6. Frontend adds to `/research` manifest.

Once shipped, this is the first entry on `company/rd/findings/` that
is NOT staged. It is also the first entry the `/hq` R&D-pulse
section (per `evolution/drafts/hq_page_rd_kpi_patch.md`) will render
in its "Most recent published finding" cell.

## What findings are NOT

- **Not a substitute for the underlying REPORT.md.** The condensed
  version is a public-facing summary; the canonical record stays in
  `finance-research-experiments/`.
- **Not marketing copy.** Findings can be negative — must be, if the
  study went negative. Suppressing a negative is a
  `literature-standards.md` §9 non-negotiable violation.
- **Not immutable.** If a follow-up study overturns a finding, the
  finding gets an `# Update YYYY-MM-DD` section (never rewritten in
  place). The original stays legible.
- **Not the place to break new news.** By the time a finding lands
  here, it has already been discussed internally (in the R&D loop
  and the ledger). The finding is the *publication step* of the
  loop, not the *discovery step*.
