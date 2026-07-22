---
id: I000  # <-- assign next monotonic; do not reuse a retired ID
source: bug | feature-request | dogfood | agent-anomaly | post-mortem | survey
submitter: <user_id | persona_id | "self-observation">
submitted_at: YYYY-MM-DDTHH:MM:SSZ
classification: null  # filled at triage: BUG | FEATURE-REQUEST | RESEARCH-QUESTION | PERFORMANCE | POLISH | OUT-OF-SCOPE | PROCESS
priority: null        # filled at triage: P0 | P1 | P2
status: new           # new | triaged | routed | in_progress | shipped | declined | deferred
route: null           # filled at triage: bug | feature | research | performance | polish | out-of-scope | process
linked_features: []   # F### references once routed to a feature
linked_decisions: []  # D### references once routed
linked_experiments: [] # finance-research-experiments E### / M### references
contact: null         # user contact only if they consented; else null
resolved_at: null
history:
  - stage: filed
    at: YYYY-MM-DDTHH:MM:SSZ
    by: user_advocate  # or persona-id
    note: "Initial filing."
---

# I000 — <one-line title>

## What happened

<3-8 sentences describing what the user / persona observed. Be
concrete: which page, which action, which time. Quote the user
verbatim if possible.>

## Why it matters

<2-4 sentences on the impact. Is a user actively harmed? Losing
trust? Losing money? Is credibility on the line? Is this a
finding-caliber question that would benefit from pre-registration?>

## Proposed resolution (optional)

<If the submitter has a proposal, include it. Otherwise blank. CPO
picks the classification at triage; the proposal here is a starting
point, not a commitment.>

## Notes for triage

<Anything the triager should know before classifying. E.g. "This
came from a user who has also filed I003, I005, I009 — cohort
signal, not one-off." Or "This is a research question but the
compute is cheap — 1 h dry-run in `finance-research-experiments`
would answer it."

Delete this section after triage or before promoting to a Research
Question pre-registration.>

## Triage decision (filled by CPO, Mondays)

- **Classification:** <BUG | FEATURE-REQUEST | RESEARCH-QUESTION |
  PERFORMANCE | POLISH | OUT-OF-SCOPE | PROCESS>
- **Priority:** <P0 | P1 | P2>
- **Route:** <bug | feature | research | performance | polish |
  out-of-scope | process>
- **Reasoning:** <1-2 sentences on why this classification. Cite
  precedents (other `I###` items) if they exist.>
- **Owner from here:** <role_id>
- **Linked feature spec (if any):** <F### slug>
- **Linked experiment pre-registration (if any):** <path>

## Closure notes

<Filled when status flips to shipped/declined/deferred:>

- **Outcome:** <one-line summary>
- **Measurement (if applicable):** <link to measurement artefact — /hq
  KPI update, `finance-research-experiments` REPORT commit, /performance
  update, etc.>
- **User notified:** <yes/no/n-a> · <date if yes>
- **Related decisions:** <D### list>
