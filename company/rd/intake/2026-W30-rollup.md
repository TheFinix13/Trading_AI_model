# Intake rollup — 2026-W30 (Jul 20 – Jul 26)

Published 2026-07-23 by Research Lead per `rd-loop.md` §6. First
weekly rollup of the R&D loop — covers cycle 1.

## Items opened this week

| ID | One-line | Source | Class / Priority | Status at rollup |
|---|---|---|---|---|
| I001* | Sprint 1 honest-review flag: solo-executor sprint compression is not portable | post-mortem | PROCESS / P2 | **resolved** (D087) |
| I002 | Dashboard silence is illegible — CEO watched /v2 all week, saw nothing, silence was correct but unexplained | dogfood (CEO) | FEATURE-REQUEST / P1 | **routed** → product (D088) |

*I001 was filed 2026-07-22 (late W30 by ISO reckoning — Wednesday of
this week) during the company-evolution session; counted as
opened-this-week.

## Items closed / routed this week

- **I001 — resolved** (D087, 2026-07-23). CPO drain confirmed the
  self-triage and adopted the codification fork: solo-executor
  compression is the accepted shape; "executor-days" is now the
  sprint planning unit (day_targets re-baselined to 1–2
  executor-days, or per-lane persona-days when genuinely parallel
  sub-executors are staffed). Time filed → resolved: ~46 h.
- **I002 — routed** (D088, 2026-07-23). Triaged in the same drain it
  was filed (time-to-triage ≈ 0 h). Fix targets next-gen's /v2 page;
  Sprint 3 / next-gen session candidate. Stays open until the
  legibility feature ships or is declined at Sprint 3 scoping.

## Queue depth

- **Open at rollup:** 1 (I002 — routed, awaiting Sprint 3 scoping).
- **Aged > 30 days without closure:** 0. Oldest open item is 0 days
  routed.

## Findings published this week

1 — `company/rd/findings/2026-07-phase-ac-pitch-assignment.md`
(D089, 2026-07-23). The Phase AC honest negative: squad TQS delta
A2 − A1 = −0.006 [boot 95% CI −0.017, +0.005], p = 0.861; no
pitch-assignment widening ships; squad stays on A1 baseline. First
real entry in `company/rd/findings/`; publication manifest row
carries `report_commit_sha_hint: 2c8e363`.

## Notes for next week (W31)

- I002's proposed fix (upcoming-events countdown + why-quiet status
  line on /v2) is the top P1 carry into Sprint 3 scoping.
- FOMC Jul 28–29 falls in W31 — the first real event window since
  I002 was filed; if the dashboard is still silent-and-illegible
  through a live FOMC, expect a repeat signal.
- Loop-validation verdict for cycle 1 is at
  `company/rd/loop-validation.md` (D090).
