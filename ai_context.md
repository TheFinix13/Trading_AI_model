# AI Context — brain dump (updated 2026-07-21, v0.42)

> v0.42 — **Sprint 0 (Trust Foundation) shipped** in a single autonomous
> executor session on `product`. All 5 P0 features landed: F005
> (shared `withStates()` skeleton + friendly-error helper), F001
> (`/performance` + `/api/performance/state`, 4 KPI tiles + equity
> curve + per-pair breakdown), F002 (`/players` index + 10 striker
> detail pages + APIs, IP disclaimer verbatim, retired/standby pills),
> F003 (`/research` CPO-gated verdict timeline against 6-entry
> `publication_manifest.json`, native `<details>` FDR explainer), F004
> (mobile 375 px pass via `_BASE_CSS` `.nav` flex-wrap + 700 px media
> query + 62-test smoke suite). Ledger `company_state.json` now
> carries 45 D### decisions and 6 sprint-verdict rows; `/hq` dashboard
> reflects 5/5 features shipped. **348 platform tests pass** (100 →
> 348, +248). 42 handoff JSONs on tape under `company/handoffs/`.
> Zero blockers surfaced, zero budget spent, zero commits landed off
> `product`.
>
> Prior landmarks preserved on `next-gen`: v0.40 (`2e04eac`) workspace
> panel + LIVE controls + v1 excursion. v0.39 (`f5ef13b`) /v2 UX pass.
> v0.38 (`8dd2669`) hub redesign. v0.37 (`762d7d8`) heartbeat +
> `tick_summary`. v0.36 Karasu / Sae + `risk_scale`. Full history:
> `docs/00-journey.md`.

Read this first in a fresh chat. Deeper history: `docs/00-journey.md`
and `docs/CHECKPOINT.md`. **Active branches:** `main` = live demo
agent; `next-gen` = v2 platform + squad paper runtime; **`product` =
commercial shipping lane** (this session's work lives here). Research
at `finance-research-experiments` on `multi-agent-ensemble`. Live
trading on demo only.

## 1) What is built and working

- **Blue Lock Trading Co. (`product`):** 17-role company-of-agents
  around the platform. Every feature flows through the canonical
  review chain (spec → research → design → architecture → build →
  qa → security\* → legal\* → signoff → ship). Sprint 0 verdict on
  the ledger = **COMPLETE**; features_shipped_sprint_0 = 5/5.
- **Public routes shipped in Sprint 0:**
  - `/performance` + `/api/performance/state` (F001) — read-only
    parser over v1 daily logs + v2 shadow-paper events. 4 KPIs,
    equity curve, per-pair table, Sharpe only when ≥ 30 daily
    returns. Full legal disclaimer verbatim.
  - `/players` (index) + `/players/<id>` (10 detail pages) +
    `/api/players/list` + `/api/players/<id>` (F002) — read-only
    parser over `company/roster/players/*.md` bios + `squad_live/
    events.jsonl`. Retired / standby / active status pills; setup
    ASCII diagrams; IP notice on every page.
  - `/research` + `/api/research/verdicts` (F003) — read-only
    parser over sibling repo's REPORT.md files, filtered through
    `company/research/publication_manifest.json` (6 approved
    entries; 3 of 6 non-passing preserves the receipt-trail
    thesis). Native `<details>` FDR explainer.
- **Shared UI primitives (F005 + F004):** `withStates()` helper
  (skeleton → data / empty / error / retry lifecycle) consumed by
  every Sprint 0 page. `_BASE_CSS` `.nav` is flex-wrap + carries a
  700 px media query so all 7 nav pills reflow at 375 px; smoke
  test locks the invariants (viewport meta, mobile media query per
  page, no body-level horizontal scroll, no font-size < 10 px).
- **`/hq` dashboard (v0.41, still current):** live over
  `company_state.json`. KPI strip + 5-column Kanban + 17-tile role
  grid + decisions log + blockers panel + 30 s poll.
- **Live (`main`):** `zone_d1_against` H4, router EURUSD @ 1.0 /
  GBPUSD @ 0.5 / USDCAD @ 0.5; risk 0.5-2 % × `risk_scale`, 5 %
  portfolio open-risk cap, per-symbol kill files, healthchecks.io
  dead-man ping.
- **Squad paper runtime (`next-gen`):** ported v1 core in
  `agent/squad/`, `scripts/run_squad_live.py`. Roster A1-A7 + A8
  Karasu (R7 news) + A9 Sae (off) + A10 Kunigami (R5). ~97 %
  proposal-key parity vs `g7retry1-phi41` (G7 = FAIL, not a
  graduation).
- **Observability:** daily logs, heartbeat, vaults, weekly bundle,
  rejection-review digest. **348 platform tests pass.**

## 2) Key file paths

| Area | Files |
|---|---|
| Sprint 0 backend (`product`) | `agent/platform/{performance,players,research,hq}.py`, `agent/platform/pages.py` (constants: `HUB_PAGE`, `V1_PAGE`, `V2_PAGE`, `HQ_PAGE`, `PERFORMANCE_PAGE`, `PLAYERS_INDEX_PAGE`, `RESEARCH_PAGE`, factories `player_detail_page`, `players_not_found_page`; helpers `_SKELETON_CSS`, `_ERROR_COPY_JS`, `_WITH_STATES_JS`), `scripts/serve_platform.py` (routes for `/performance`, `/players[/<id>]`, `/research`, `/hq`, plus APIs) |
| Company (`product`) | `company/README.md`, `company/roles/*.md` (17), `company/protocols/{review-chain,persona-handoff,escalation}.md`, `company/ledger/{company_state.json,decisions_log.md}` (45 D### entries + sprint-verdict rows), `company/sprints/sprint-0-trust-foundation/{README,F001-F005,REPORT,BACKLOG}.md`, `company/brand/{copy,error_copy}.md`, `company/legal/{disclaimers,blue-lock-ip-notice,F001-disclaimer-review,F002-disclaimer-review,F003-disclaimer-review}.md`, `company/qa/F00{1,2,3,4,5}-verdict.md`, `company/design/F00{1,2,3,5}-mocks.md`, `company/research/{F001-user-journey,F002-user-journey,F003-user-journey,publication_manifest.json}`, `company/handoffs/` (42 JSON files), `company/roster/players/*.md` (10 striker bios) |
| Sprint 0 tests (`product`) | `tests/platform/test_pages_shared_states.py`, `tests/platform/test_performance_{module,page,api}.py`, `tests/platform/test_players_{module,page,api}.py`, `tests/platform/test_research_{module,page,api}.py`, `tests/platform/test_mobile_responsive.py`, `tests/platform/test_hq_{module,page,api}.py` |
| Company protocol (brain-box) | `agents/company-of-agents-protocol.md` |
| Strategy | `agent/alphas/concepts/{zone_alpha,_htf}.py`, `agent/alphas/zone_routing.py` |
| Live (`main`) | `scripts/run_live.py`, `agent/live/*.py`, `agent/risk/*.py` |
| Squad (`next-gen`) | `agent/squad/{engine,sentinel,roster,paper_broker,aggregator,workspace,lot_intent,types}.py`, `agent/squad/agents/a0[1-9]_*.py` + `a10_kunigami.py`, `scripts/run_squad_live.py` |
| Data | `agent/data/*.py`, `data/parquet/*.parquet` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-journey.md`, `docs/RUNBOOK_demo_launch.md`, `docs/08-live-trading-and-deployment.md` |

## 3) Next immediate goal

**Sprint 1 (Access) — see `company/sprints/BACKLOG.md`.** Three P0
features to land:

1. Broker connection wizard (MT5 credentials, sandbox mode default;
   any paid API request triggers Finance activation + CEO signoff).
2. Real user accounts (auth surface, per-user setting isolation) —
   Sprint 1 is when the Security persona activates for real. First
   feature to require `tests/security/` module.
3. First-time setup flow (`/onboarding`) — walk a new user from `/`
   to their first proposal without prior context.

**Parked (do not start without discussion):** deploying §7b.6 market
paper on the VM platform clone; graduating the squad to real broker
orders; rewriting v1 zones live path; touching `agent/live/` or
`agent/risk/` from a concurrent session's WIP; enabling Sae by default
before the AC verdict; PLG cooldown retune (E013 follow-up); any spend
of money (Finance stays at zero-authority-spend until Sprint 1 broker
wizard forces the first shopping list).

**Retro asks for Sprint 1 (see `sprint-0-trust-foundation/REPORT.md`
"Retro suggestions"):** keep F005-first serialisation; add a spec-lock
"spec vs on-disk" validation step; introduce mandatory security tests
for auth-adjacent features; auto-check the Legal claim register on
every push; version-bump `_BASE_CSS` when it changes.
