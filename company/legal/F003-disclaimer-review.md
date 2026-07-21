# F003 -- legal review

- **Feature:** F003 -- `/research` verdict timeline
- **Reviewer:** legal (Sprint 0)
- **Signed:** 2026-07-21 17:53 UTC
- **Verdict:** PASS

## Claim register updates

Adding the following to `company/legal/disclaimers.md` Claim register:

| Feature | Claim | Verified against | Signed off by |
|---|---|---|---|
| F003 | Individual verdict labels (`alive_survivor`, `dead`, `fail`, `stopped`, `complete`) per campaign | Research repo REPORT.md per-experiment | cpo |

Each of the six shipped campaigns has its `verdict_kind` cross-checked
against the canonical `REPORT.md` on tape. The manifest's
`brand_summary` field is checked against the abstract of the same
report; where the summary paraphrases, it must not add a claim not
present in the abstract. Sample audit:

| Campaign | Manifest verdict_kind | REPORT.md status line | Match? |
|---|---|---|---|
| `E001_concept_ablation` | `alive_survivor` | "Status: complete · sole survivor handed to E002" | yes |
| `E004_walk_forward` | `alive_survivor` | "Status: complete · UR/USD passes ; EUR/USD fails" | yes |
| `E007_impulse_origin_bounce` | `alive_survivor` | "Status: complete (2026-07-19)" | yes (self-stopping receipt intact) |
| `E022_structure_aware_tp_snap` | `dead` | "Status: dead · did not pass promotion" | yes |
| `E024_near_tp_stall_exit` | `fail_at_stage_1` | "Status: fail at stage 1" | yes |
| `phase_ac_pitch_assignment` | `stopped_at_stage_1` | "Status: stopped at stage 1 · low-yield abort" | yes |

## Anti-cherry-pick claim

**Assertion:** "We publish the experiments that failed."

**Test:** Of six shipped entries, **three (50 %)** are non-passing:
E022 (dead), E024 (fail), phase_ac (stopped). This satisfies the
anti-cherry-pick truthfulness bar comfortably.

**Rule going forward:** If the manifest ever tips to > 66 %
"alive_survivor" entries, Legal must be re-consulted. This preserves
the "receipt trail first" invariant. Recording as a rolling
constraint below.

## FDR explainer prose

Copy reviewed line-by-line:

- "Pre-registration means the verdict criteria are written down (in
  a PROTOCOL.md file) before the numbers come in." -- truthful; the
  research repo's `PROTOCOL.md` files carry timestamps prior to
  results.
- "If we don't hit the pre-committed number, the campaign is dead."
  -- truthful; the stopped and dead cards demonstrate the rule.
- "BH-FDR at q = 0.10 means the Benjamini-Hochberg false-discovery-
  rate correction is applied across each campaign's family of
  hypotheses." -- accurate description of the method as stated in
  the research repo's `docs/decisions/2026-07-01_fdr_protocol.md`.
- "Many candidates pass raw p-values and fail BH-FDR -- and that is
  a feature of the method, not a bug." -- opinion / rhetorical
  framing but defensible; does not overstate.
- "The 'dead' and 'fail' cards on this page are the receipt trail.
  Read them first if you want to trust the 'alive' ones." -- product
  copy, not a legal claim. Passes.

**Legal opinion:** The FDR explainer reads at ~7th-grade level per
Flesch, avoids advanced statistics jargon in visible copy, and
matches the underlying research repo's documentation. Approved.

## Closing disclaimer

Verbatim `company/legal/disclaimers.md::research-verdict`. Approved
as shipped in `RESEARCH_PAGE`.

## Rolling constraints (bind future sprints)

1. **Cherry-pick guardrail.** If < 33 % of published entries are
   dead / fail / stopped, Legal must review before the next
   `/research` push.
2. **Whole-portfolio claim ban.** No entry, headline_stat, or
   summary may compose individual "alive" verdicts into a
   portfolio-level or expected-return claim. This is spelled out
   in the closing disclaimer; Legal will audit each new manifest
   entry for compliance.
3. **New verdict_kind requires legal handshake.** Any new
   `verdict_kind` in the parser (beyond the 14 currently
   supported) must ship with a Legal-approved verdict_label
   before it can appear on `/research`.

## Signoff

Legal PASSES F003 for ship. No blockers. Handing to CEO for the
signoff -> ship transition on `/hq`.
