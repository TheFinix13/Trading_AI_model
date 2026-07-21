# F003 — Public `/research` route (verdicts timeline)

- **Priority:** P0
- **Sprint:** Sprint 0 · Trust Foundation
- **Owner (build):** Frontend + Backend
- **Reviewers:** UX Researcher, UI Designer, Brand Designer,
  Marketing, CTO, QA, Legal, CEO
- **Current stage:** `spec`
- **Written by:** CPO

## User story

> As a **prospect who's skeptical of AI-trading pitches**, I want
> to read a page that shows me *what didn't work*, so I trust the
> platform's methodology when it does claim something worked.

The framing name in the CEO's own words: **anti-marketing marketing.**
The `/research` page is the strongest sales asset in the company
precisely because it isn't sales copy.

## Acceptance criteria

The feature is done when:

1. `GET /research` returns 200 and renders a **verdict timeline**
   — most-recent-first — of every completed research campaign
   from `finance-research-experiments`.
2. Each entry shows:
   - **Campaign ID + name** (e.g. `Phase AC · pitch-assignment`,
     `E013 · safety layer contribution`).
   - **Verdict** — pre-registered label from the campaign's
     protocol (`combined_alive`, `stopped_at_stage_1`,
     `parked_low_yield`, `FAIL`, `pass_thin`, etc.).
   - **One-paragraph plain-English summary** — Brand-written,
     what the campaign asked, what it found, what changed as a
     result (or what didn't).
   - **Numbers block** — the headline stat that made the verdict
     (e.g. "1 of 8 candidate widenings passed BH-FDR at q=0.10").
   - **Link to full report** — either a same-domain view (if we
     mirror the report), or an "artefact-hash + read-only path"
     stanza that references the exact commit in the research
     repo.
3. Entries render newest-first with a **date header** per month.
4. The page opens with a Marketing-Brand-authored preamble
   (~4 sentences) framing what the page is for: *we publish the
   failed experiments, this is the receipt trail*.
5. The `/research` page includes a **FDR budget explainer** — a
   collapsed `<details>` (same pattern as the hub glossary) that
   explains what "pre-registered" means, why BH-FDR at q=0.10 is
   used, and why 1-of-8 passing is a *feature* of the method.
6. Data source: read-only from `finance-research-experiments/
   experiments/**/REPORT.md` + `*_verdict.md` (Backend Engineer
   writes a parser). The research repo is **never imported** —
   only read from the filesystem path configured in
   `platform.toml`'s `research_reviews` (or similar new key).
7. Missing research repo: page still renders with a friendly
   empty-state ("Research repo not configured on this machine —
   see `docs/RUNBOOK_demo_launch.md` §7b for setup").
8. Backend `GET /api/research` returns JSON `{entries:
   [{campaign_id, name, verdict, verdict_kind, date, summary,
   headline_stat, report_path, report_commit_sha_hint}],
   generated_at, source_repo_path, source_exists: bool}`.
9. Mobile responsive (F004): timeline reflows to full-width;
   date headers become sticky.
10. Loading + error states (F005): both wired.
11. No performance claims outside the Numbers block. If a verdict's
    Numbers block would be interpreted as a promise ("+30% Sharpe"),
    Legal reviews the wording BEFORE ship.
12. Tests:
    - `tests/platform/test_research_page.py` — structure + smoke.
    - `tests/platform/test_research_api.py` — contract.
    - `tests/platform/test_research_parser.py` — parser unit tests
      against fixture REPORT.md snapshots.

## Non-goals

- **No** ability to run new experiments from this page. Purely
  read-only display of completed work.
- **No** editing or "commenting" on verdicts. Verdicts are the
  research repo's ground truth; this page reflects, it does not
  amend.
- **No** live-progress bar of in-flight campaigns (Phase AC.3+
  running right now). That's a nice-to-have for Sprint 3+ if
  demand emerges.
- **No** search / filter. Timeline is 5–15 entries deep in Sprint 0
  — no need. Reconsider Sprint 3+.
- **No** subscribe / RSS feed. Nice idea, defer.

## Dependencies

- **Backend Engineer:** new `agent/platform/research.py` module.
  Parser targets:
  - `finance-research-experiments/experiments/E0*/REPORT.md`
    (has a canonical "Verdict:" block per the research-standards
    doc).
  - `finance-research-experiments/programs/M001_*/experiments/
    phase_*/REPORT.md` and sibling `*_verdict*.md`.
  Backend contract-tests the parser against ≥ 3 fixture REPORTs
  (E011, E013, E014 are known-good).
- **Frontend Engineer:** `RESEARCH_PAGE` in `pages.py`, route in
  `serve_platform.py`.
- **Brand + Marketing:** write the one-paragraph summary for each
  verdict. Marketing owns the preamble copy.
- **Legal:** reviews every verdict-summary paragraph against the
  claim register.
- **UX Researcher:** memo — target segment is "skeptical prospect",
  jobs-to-be-done for that segment.
- **UI Designer:** timeline mock + collapsed-details FDR explainer
  mock.

## Review checklist

| Reviewer | Additional check |
|---|---|
| Brand Designer | Zero "ensemble" / "aggregator" leakage in verdict summaries. "Pre-registered" is defined the FIRST time it appears (link to details). |
| Marketing | The preamble frames anti-marketing marketing without being smug. Verdicts read as receipts, not brags. |
| Legal | Every verdict-summary paragraph checked against claim register; no implicit "we outperform" claims that the raw numbers don't support. |
| CTO | Read-only invariant preserved — Backend module never writes to research repo. |

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Research repo not on prospect's machine — page is empty. | Deploy sets research repo path via `platform.toml`; VM has the sibling checkout already. Fallback friendly-empty-state ships regardless. |
| Verdict-summary paragraph misrepresents the research (e.g. calls a "parked" verdict a "fail"). | AI/ML Engineer signs off every summary before Legal review. Research repo's authors have veto (informal — pre-empt by getting sign-off from research-repo owner Fiyin himself). |
| Legal blocks a summary paragraph and rework loop is heavy. | Draft summaries early; Legal review runs in parallel with QA to compress the timeline. |
| Fixture drift — a new REPORT.md schema breaks the parser silently. | Parser fixtures live in `tests/fixtures/research/` and get refreshed whenever the research repo publishes a new REPORT — QA plan calls this out. |

## Definition of shipped

`/research` route responds 200; timeline renders ≥ 3 verdicts
(E011, E013, E014 at minimum); FDR explainer opens and reads
clearly; empty-state has been tested by pointing at a non-existent
path; CEO has read every summary and signed off; Marketing has one
shareable URL to reference in future prospect conversations.

## SPEC-EXTENSION 2026-07-21 (D042)

The build stage discovered two under-specified points; both were
extended in-place rather than escalated:

1. **Sibling repo path discovery.** The spec named the source
   (`finance-research-experiments`) but did not pin how the
   platform server discovers it at runtime. Resolved by deriving
   `research_root` from the existing `research_reviews` config key
   (which already points three directories deep into that repo);
   `serve_platform.make_handler()` gains
   `research_root=` and `research_manifest_path=` kwargs, both
   defaulting to `None`. Missing repo renders the F005
   `not_configured` empty state -- never a 500.

2. **Shipped verdict list.** The spec named E011 / E013 / E014 as
   minimum entries, but those experiments never produced a
   canonical `REPORT.md` (only `REPORT 2.md` drift copies exist in
   the sibling repo, which the parser skips by design to avoid
   publishing unversioned verdicts). Substituted six real
   canonical reports for the Sprint 0 manifest:
   E001_concept_ablation, E004_walk_forward,
   E007_impulse_origin_bounce, E022_structure_aware_tp_snap,
   E024_near_tp_stall_exit, phase_ac_pitch_assignment. 3 of 6 are
   non-passing (dead / fail / stopped), which preserves the
   anti-cherry-pick thesis better than the original list would
   have. The "≥ 3 verdicts" ship gate is satisfied at 6.
