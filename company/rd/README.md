# company/rd/ — R&D team home

R&D team's operating directory. Established 2026-07-22 as the operating
consequence of the CEO's "real product / real users / literature-standard
R&D" directive. See `company/protocols/rd-loop.md` for the loop
mechanics and `company/protocols/literature-standards.md` for the
research rigour standards.

## Directory layout

| Path | Contents | Owner |
|---|---|---|
| `intake/` | `I###` intake items — one file per user-facing signal. Weekly rollups. | User Advocate (files) + CPO (triages) |
| `experiments/` | Active-experiment index. Points at `finance-research-experiments/` for compute; product-side experiments live inline. | Research Lead |
| `findings/` | Published condensed findings — "public-facing" versions of `finance-research-experiments/**/REPORT.md`. One finding per file. Peer-reviewed by CTO or CPO before landing. | Research Lead |

## Intake queue

`intake/` holds every open intake item as `I###-<slug>.md`. Weekly
rollups land as `<YYYY-WW>-rollup.md` (Research Lead) and
`<YYYY-WW>-triage-brief.md` (User Advocate, delivered to CPO on
Monday). Template at `intake/TEMPLATE.md`.

Intake IDs are monotonic starting at `I001`. Never reuse an ID even
if the item is declined or superseded.

## Experiments index

`experiments/README.md` is the single-source-of-truth index of
active-and-recent research campaigns, both sides of the workspace pair:

- **finance-research-experiments** — E-line experiments (E0##) and
  M-line programs (M0## with N-phase sub-arms). The
  `finance-research-experiments/EXPERIMENTS.md` file is the canonical
  registry; this directory carries a synced pointer plus the
  cross-repo bridge annotations (which intake item motivated which
  experiment).
- **Product-side experiments** — user-behaviour hypotheses declared
  in feature specs per `literature-standards.md` §5. Currently the
  first candidate is F013's 30-day approval-review rate.

Sync cadence: manual (Research Lead) until the R&D-loop protocol
grows an automation hook (Sprint 3+).

## Findings

`findings/README.md` documents the publish-a-finding path — where a
condensed public-facing version of a research verdict lands, who
peer-reviews it, and how it flows to `/research` (F003).

Every finding lives at `findings/<slug>.md`. The full underlying
report stays canonical at
`finance-research-experiments/programs/**/REPORT.md`; the findings
copy is 1-2 pages of Brand-reviewed prose with a link back.

First candidate finding staged for publication: **Phase AC negative**
(AC.2 A2 FAIL, delta −0.006, p=0.861 — stay with A1 baseline). See
`finding/README.md` for the publication path.

## What lives here vs. what doesn't

**Lives here:**

- Intake items, triage briefs, rollups.
- Published condensed findings.
- Cross-repo experiment index.
- Cohort reports (Sprint 4+, User Advocate).

**Does NOT live here:**

- `PROTOCOL.md` for a research campaign → lives in
  `finance-research-experiments/programs/**/` where the compute
  fires.
- Raw walk-forward artefacts (`*.json`, `*.parquet`, `*.jsonl`) →
  same.
- Feature specs → `company/sprints/<sprint>/F###-<slug>.md`.
- Ledger updates → `company/ledger/decisions_log.md` +
  `company_state.json`.

## Ownership

- **Research Lead** — portfolio index, findings, weekly rollup.
- **User Advocate** — intake filing, triage brief.
- **CPO** — triage decisions (Mondays), routing calls.
- **CTO** — reproducibility audit on any published finding.
- **Legal** — citation + non-negotiable enforcement on findings.
- **Brand** — copy review on findings + `/research` promotion.

## First-week operating calendar (2026-07-22 →)

Per `rd-loop.md` §9 — the loop is live, not aspirational:

| Day | Action | Owner | Deliverable |
|---|---|---|---|
| Mon | Drain intake queue; classify; route | CPO | `[INTAKE]` bullets in decisions log for P0/P1 |
| Tue | File `[RESEARCH-QUESTION]` pre-registrations in F-R-E | Research Lead | PROTOCOL commit(s) |
| Wed | Publish first condensed finding | Research Lead | `findings/phase-ac-pitch-assignment.md` |
| Thu | Ship measurements for shipped items | CTO | KPI-strip update on `/hq` |
| Fri | Weekly rollup | Research Lead | `intake/<YYYY-WW>-rollup.md` |
