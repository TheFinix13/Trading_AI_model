# AI Context — brain dump (updated 2026-07-23, v0.46)

> v0.46 — **R&D cycle 1 + org web + dogfood cast + sellability memo**
> 2026-07-23 (D087–D095, commits 797913e..25d8491 on `product`).
> Cycle 1 PASS (`company/rd/loop-validation.md`): I001 resolved D087
> (executor-days = sprint planning unit); I002 dashboard-silence
> filed/routed (P1, /v2 fix = next-gen Sprint 3); first real finding
> published `company/rd/findings/2026-07-phase-ac-pitch-assignment.md`
> (honest negative, manifest + claim register wired, D089); W30
> rollup D090. **F015 Org & Flow on `/hq`** (D091): `hq.org_state()`
> → `/api/hq/org`, 19 roles by tier + report lines, 11-stage pipeline,
> recent handoffs; CSS page-scoped, `_BASE_CSS_VERSION` stays 1.1.0.
> **F016 dogfood cast** (D092): 6 personas `company/rd/personas/`
> (P006 = fake-billing test customers), `scripts/dogfood_personas.py`
> drives real make_handler in-process (keychain-safe seams), first
> run 113/113; frictions → I003 broker non-Windows dead-end (D093),
> I004 internal-token repo-root pinning (D094). **Sellability memo**
> `company/strategy/sellability-gaps.md` (D095): off-backlog flags =
> live-order wiring, 30–90d shadow clock, packaging, legal/ToS; repo
> split PARKED until product #2. **1540 pass + 1 env-skip.** Zero
> diffs to `agent/{live,risk,squad}/*`. Prior v0.45 charter detail in
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
- **R&D loop validated (cycle 1 PASS):** intake I001 resolved,
  I002–I004 routed (queue depth 3); first finding published (Phase
  AC honest negative, on `/research` manifest); W30 rollup on tape.
- **Public routes:** `/performance`, `/players[/:id]`, `/research`,
  `/onboarding`, `/settings/{broker,live-mode,kill-switches,reset-install}`,
  `/risk`, `/approvals`, `/alerts`, `/hq` (R&D pulse + F015 Org &
  Flow via `/api/hq/org`). F005 `withStates()` +
  `_BASE_CSS_VERSION = "1.1.0"`.
- **Dogfood cast (F016):** 6 personas + `scripts/dogfood_personas.py`
  (in-process server, keychain-safe, no live mode by construction);
  first run 113/113 across onboarding/broker/kill/approvals/alerts.
- **Live (`main`) + Squad (`next-gen`):** unchanged; zero diffs.
- **Tests:** **1540 pass + 1 env-skip** (security 204).

## 2) Key file paths

| Area | Files |
|---|---|
| Charter + R&D | `company/protocols/{review-chain,escalation,rd-loop,literature-standards}.md`, `company/roles/{cto,cpo,ceo,research_lead,user_advocate}.md`, `company/rd/{README,intake/{TEMPLATE,I001–I004},findings/2026-07-phase-ac-pitch-assignment.md,personas/,loop-validation.md}`, `company/strategy/sellability-gaps.md`, `company/ledger/{company_state.json (95 D### + 19 roles + intake×4 + experiments),decisions_log.md}` |
| Sprint 2 real-trading | `agent/platform/{rate_limiter,kill_switches,kill_switch_admin,risk_budget,broker_health,approval_queue,alerts,alerts_sse,alerts_telegram,auth}.py`, `agent/platform/pages.py` (KILL_SWITCHES / RISK / APPROVALS / LIVE_MODE_TOGGLE / ALERTS + HQ R&D pulse), `scripts/{serve_platform,check_claim_register,install_git_hooks}.py`, `scripts/git-hooks/pre-commit`, `company/legal/{live-mode,approval-queue}-warning.md` + `claim_register.md` |
| Sprint 0/1 backend | `agent/platform/{performance,players,research,hq (R&D pulse extension),credentials,broker_connection,onboarding}.py` |
| Tests | `tests/security/test_live_mode_off_invariant.py`, `tests/platform/{test_hq_org,test_dogfood_personas,test_hq_page_rd_pulse}.py` |
| Org web + dogfood | `agent/platform/hq.py` (`org_state()`), `agent/platform/pages.py` (HQ Org & Flow), `scripts/dogfood_personas.py`, `company/rd/personas/` |
| Strategy / Live / Squad | `agent/alphas/{concepts/{zone_alpha,_htf},zone_routing}.py`; **off-limits:** `agent/{live,risk,squad}/*`, `scripts/run_{live,squad_live}.py` |
| Docs | `docs/{CHECKPOINT,00-journey,RUNBOOK_demo_launch}.md` |

## 3) Next immediate goal

**Act on the sellability memo's top three (D095):** scope the
live-order wiring charter (demo-MT5 first, escalation.md §5 order),
start the 30–90 day shadow clock on the VM (calendar-constrained —
every idle week delays the earliest sale date), and charter the
install-token → multi-user auth migration. In parallel: Sprint 3
scoping picks up I002 (/v2 silence legibility, next-gen lane) and
I003 (broker dead-end copy); cycle-2 R&D drain re-validates the loop
with a non-trivial queue (I002–I004 open).

**Parked (no start without discussion):** wiring four-gate composition
to squad's real-order path; Sprint 4 `/feedback` route (D084 defers —
F013/F014 signals drain via User Advocate + CPO Monday triage);
external peer-review budget (Sprint 6+ whitepaper); squad → real
broker orders; v1 zones live-path rewrite; any touch of
`agent/{live,risk,squad}/*` from a non-integration sprint; enabling
Sae before AC verdict; PLG cooldown retune (E013 f/u); any spend
(Finance zero-authority).
