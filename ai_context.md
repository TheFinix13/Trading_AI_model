# AI Context — brain dump (updated 2026-07-22, v0.45)

> v0.45 — **Company charter elevated** 2026-07-22 per CEO (Fiyin)
> directive: real product / real users / literature-standard R&D
> (D081). Two new roles: **Research Lead** ("The Anri Junior",
> exec-adjacent, dual-report CTO+CPO — owns E0xx/M0xx portfolio +
> `/research` manifest) and **User Advocate** (business — feedback
> intake, weekly triage, GDPR/CCPA hygiene). Two new protocols:
> `rd-loop.md` (intake `I###`, Monday drain, cross-repo bridge to
> `finance-research-experiments`) + `literature-standards.md`
> (pre-reg + FDR + reproducibility + honest negatives + 5
> non-negotiables). `escalation.md §6` (research-negative
> suppression); `review-chain.md §7b` (`research` stage, gated by
> `research_relevant: true`). Ledger 17→19 roles, +3 R&D KPIs, +2
> arrays (`intake` seeded `I001`; `experiments` seeded Phase AC
> negative + F013 30d approval-rate). `/hq` R&D-pulse section;
> `_BASE_CSS_VERSION 1.0.0 → 1.1.0`. **1483 → 1503 tests (+20).**
> Zero diffs to `agent/{live,risk,squad}/*` (D065 Invariant #2).
> D081–D086 on tape. Prior v0.40–v0.44 detail in
> [docs/00-journey.md](docs/00-journey.md#2026-07-22-·-company-charter-elevated).

Read this first in a fresh chat. Deeper history: `docs/00-journey.md`
+ `docs/CHECKPOINT.md`. **Branches:** `main` = live demo agent;
`next-gen` = v2 platform + squad paper; **`product` = commercial
lane** (Sprint 0–2 + charter elevation). Research on
`finance-research-experiments::multi-agent-ensemble`. Demo only.

## 1) What is built and working

- **Blue Lock Trading Co. (`product`):** 19-role company; review
  chain spec → research → design → architecture → build → qa →
  security\* → 7b research\* → legal\* → signoff → ship
  (\* = conditional). Sprint 0+1+2 COMPLETE (5/5+3/3+6/6). Charter
  principles: real-product-real-users, closed-feedback-loop,
  literature-standard-research.
- **Real-Trading scaffolding (Sprint 2, default-OFF):** four-gate
  live-order composition pinned by
  `tests/security/test_live_mode_off_invariant.py`. F009 auth, F010
  claim-audit, F011 kill-switches, F012 risk+broker-health, F013
  approval+live-mode, F014 SSE alerts + Telegram.
- **R&D loop live:** `company/rd/{intake,experiments,findings}/`;
  `I001` filed (PROCESS/P2, ties D062); tracked: M001-PhaseAC
  (closed-negative), F013 30d approval-rate (awaiting-panel).
- **Public routes:** `/performance`, `/players[/:id]`, `/research`,
  `/onboarding`, `/settings/{broker,live-mode,kill-switches,reset-install}`,
  `/risk`, `/approvals`, `/alerts`, `/hq` (with R&D pulse).
  F005 `withStates()` + `_BASE_CSS_VERSION = "1.1.0"`.
- **Live (`main`) + Squad (`next-gen`):** unchanged; zero diffs.
- **Tests:** **1503 pass** (security 204).

## 2) Key file paths

| Area | Files |
|---|---|
| Charter + R&D | `company/protocols/{review-chain,escalation,rd-loop,literature-standards}.md`, `company/roles/{cto,cpo,ceo,research_lead,user_advocate}.md`, `company/rd/{README,intake/{TEMPLATE,I001-*},experiments/README,findings/README}.md`, `company/ledger/{company_state.json (86 D### + 19 roles + intake + experiments + 3 R&D KPIs),decisions_log.md}` |
| Sprint 2 real-trading | `agent/platform/{rate_limiter,kill_switches,kill_switch_admin,risk_budget,broker_health,approval_queue,alerts,alerts_sse,alerts_telegram,auth}.py`, `agent/platform/pages.py` (KILL_SWITCHES / RISK / APPROVALS / LIVE_MODE_TOGGLE / ALERTS + HQ R&D pulse), `scripts/{serve_platform,check_claim_register,install_git_hooks}.py`, `scripts/git-hooks/pre-commit`, `company/legal/{live-mode,approval-queue}-warning.md` + `claim_register.md` |
| Sprint 0/1 backend | `agent/platform/{performance,players,research,hq (R&D pulse extension),credentials,broker_connection,onboarding}.py` |
| Tests | `tests/security/test_live_mode_off_invariant.py`, `tests/platform/test_hq_page_rd_pulse.py` + `test_hq_{module,api}.py` R&D extensions |
| Strategy / Live / Squad | `agent/alphas/{concepts/{zone_alpha,_htf},zone_routing}.py`; **off-limits:** `agent/{live,risk,squad}/*`, `scripts/run_{live,squad_live}.py` |
| Docs | `docs/{CHECKPOINT,00-journey,RUNBOOK_demo_launch}.md` |

## 3) Next immediate goal

**Run the R&D loop for one week and file the first weekly rollup**
per `protocols/rd-loop.md` §3 (Monday drain). CPO drains `I001` +
any new intake; Research Lead sets up the first weekly cross-repo
sync; User Advocate wires the F013 approval-queue signal into
intake once real-mode traffic appears. Sprint 3 (Stickiness) waits
until the loop is ratified — candidates: strategy marketplace,
character seasons, match highlights (first legit
`[BLOCKER][SPEND]` for video infra), community.

**Parked (no start without discussion):** wiring four-gate composition
to squad's real-order path; Sprint 4 `/feedback` route (D084 defers —
F013/F014 signals drain via User Advocate + CPO Monday triage);
external peer-review budget (Sprint 6+ whitepaper); squad → real
broker orders; v1 zones live-path rewrite; any touch of
`agent/{live,risk,squad}/*` from a non-integration sprint; enabling
Sae before AC verdict; PLG cooldown retune (E013 f/u); any spend
(Finance zero-authority).
