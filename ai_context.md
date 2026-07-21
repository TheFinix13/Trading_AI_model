# AI Context — brain dump (updated 2026-07-21, v0.41)

> v0.41 — **Blue Lock Trading Co. founded** on new branch `product`
> (branched off `next-gen` at `9319804`). Company-of-agents apparatus
> around the trading platform: charter (`company/README.md`) + 17 role
> docs (executive / design / engineering / business tiers) + 3
> protocols (review chain, persona handoff, escalation) + ledger
> (`company/ledger/company_state.json` 17 roles / 5 features / 10
> decisions, `decisions_log.md`) + Sprint 0 "Trust Foundation" charter
> and 5 P0 feature specs (F001 `/performance`, F002 `/players/:id` all
> 10 strikers, F003 `/research` verdicts timeline, F004 mobile 375 px,
> F005 skeletons + friendly errors) + Sprints 1-6 BACKLOG (Access,
> Real-Trading, Stickiness, Polish, Compliance, Sales). New `/hq`
> route + `/api/hq/state` JSON API render the live ledger as a
> dashboard (KPI strip, 5-column Kanban, 17-tile role grid, decisions
> log, blockers panel, 30 s poll). Commits `e6a99fa` company scaffold
> + `357f334` HQ dashboard on `product`; brain-box gains canonical
> `agents/company-of-agents-protocol.md` (~416 lines). **723 tests
> pass** (was 686; +37 across hq module / page / API).
>
> Prior landmarks preserved on `next-gen`: v0.40 (`2e04eac`) workspace
> panel + LIVE controls + v1 excursion. v0.39 (`f5ef13b`) /v2 UX pass.
> v0.38 (`8dd2669`) hub redesign. v0.37 (`762d7d8`) heartbeat +
> `tick_summary`. v0.36 Karasu / Sae + `risk_scale`. Full history:
> `docs/00-journey.md`.

Read this first in a fresh chat. Deeper history: `docs/00-journey.md`
and `docs/CHECKPOINT.md`. **Active branches:** `main` = live demo agent;
`next-gen` = v2 platform + squad paper runtime; **`product` = commercial
shipping lane** (this session's work lives here). Research at
`finance-research-experiments` on `multi-agent-ensemble`. Live trading
on demo only.

## 1) What is built and working

- **Blue Lock Trading Co. (`product`, new):** 17-role company-of-agents
  around the platform. Every product feature flows through a canonical
  review chain (spec → research → design → architecture → build → qa →
  security\* → legal\* → signoff → ship). Persona handoffs produce JSON
  artefacts under `company/handoffs/`. Escalation to CEO (Fiyin)
  triggers on: money spend, brand-defining calls, legal risk, arch
  changes >3 modules, real broker connections. `/hq` dashboard is the
  operating view; ledger at `company/ledger/company_state.json` is the
  source of truth.
- **Sprint 0 = Trust Foundation** (2026-07-21 → 2026-08-04, 14 days,
  5 P0 features, 10 of 17 roles active). Estimated 11-13 days
  wall-clock through honest review chain.
- **Live (`main`):** `zone_d1_against` H4, router EURUSD @ 1.0 /
  GBPUSD @ 0.5 / USDCAD @ 0.5; risk 0.5-2 % × `risk_scale`, 5 %
  portfolio open-risk cap, per-symbol kill files, MT5-first close
  resolution, healthchecks.io dead-man ping.
- **Squad paper runtime (`next-gen`):** ported v1 core in
  `agent/squad/`, `scripts/run_squad_live.py` (MT5/cache). Roster
  A1-A7 proposers + A8 Karasu (R7 news) + A9 Sae (off) + A10 Kunigami
  (R5). Shadow JSONL fills, ≈97 % proposal-key parity vs
  `g7retry1-phi41` (G7 = FAIL 3/7, not a graduation).
- **Sentinel:** R1-R6 + **R7 news-impact ladder** (block high, 0.5×
  medium); `risk_scale` enforced end-to-end (v0.36).
- **Platform (`next-gen` + `product`, read-only):**
  `scripts/serve_platform.py`, hub (v0.38 KPI-strip redesign, v0.41
  4th HQ tile) + /v1 live view (v0.40 excursion pills) + /v2 squad
  pitch (v0.39 UX + v0.40 workspace panel) + **/hq HQ dashboard
  (v0.41 new)**. New routes: `GET /api/v2/live/workspace`, `GET /hq`,
  `GET /api/hq/state`. Runbook §7b / §7b.5 / §7b.6.
- **Workspace snapshot:** `agent/squad/engine.py` writes
  `workspace_snapshot.json` on every `on_bar()` (cap 60, atomic
  tmp+replace); every `tick_summary` event carries a compact
  `thoughts_top5` array so historical replays render the same panel.
- **Data cache:** `data/parquet/` — EURUSD / GBPUSD / USDCAD +
  USDJPY / USDCHF (17,706 H4 + 3,436 D1 each, 2015 → 2026-07-20).
- **Observability:** daily logs, heartbeat, vaults, weekly bundle,
  rejection-review digest. **723 tests pass.**

## 2) Key file paths

| Area | Files |
|---|---|
| Company (`product`) | `company/README.md`, `company/roles/*.md` (17), `company/protocols/{review-chain,persona-handoff,escalation}.md`, `company/ledger/{company_state.json,decisions_log.md}`, `company/sprints/sprint-0-trust-foundation/{README,F001-F005,BACKLOG}.md`, `company/handoffs/` |
| HQ dashboard (`product`) | `agent/platform/hq.py`, `agent/platform/pages.py` (`HQ_PAGE`), `scripts/serve_platform.py` (`/hq`, `/api/hq/state`, `--company-ledger`) |
| Company protocol (brain-box) | `agents/company-of-agents-protocol.md` |
| Strategy | `agent/alphas/concepts/{zone_alpha,_htf}.py`, `agent/alphas/zone_routing.py` |
| Live (`main`) | `scripts/run_live.py`, `agent/live/*.py`, `agent/risk/*.py` |
| Squad (`next-gen`) | `agent/squad/{engine,sentinel,roster,paper_broker,aggregator,workspace,lot_intent,types}.py`, `agent/squad/agents/a0[1-9]_*.py` + `a10_kunigami.py`, `scripts/run_squad_live.py` |
| Karasu + Sae | `agent/squad/agents/a0{8,9}_*.py`, `agent/squad/{news,sae}_config.py`, `agent/news/calendar.py` |
| Platform | `agent/platform/*.py`, `scripts/{serve_platform,run_squad_paper,build_dashboard,weekly_report}.py` |
| Data | `agent/data/*.py`, `data/parquet/*.parquet` |
| Tests | `tests/test_squad_*.py`, `tests/squad/test_engine_{risk_scale,tick_summary,workspace_snapshot}.py`, `tests/platform/{test_hub_page,test_v2_page,test_paper_loop_live_workspace,test_v1_excursion_rendering,test_v2_live_workspace_endpoint,test_hq_module,test_hq_page,test_hq_api}.py`, `tests/test_platform_*.py` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-journey.md`, `docs/RUNBOOK_demo_launch.md`, `docs/08-live-trading-and-deployment.md` |
| M001 pointer | `docs/research/multi-agent-ensemble/README.md` |

## 3) Next immediate goal

**Dispatch Sprint 0 Executor.** Ship F005 (skeletons + errors) helper
first (day 3) so F001 / F002 / F003 consume it during build. F001-F003
run in parallel from day 4. F004 mobile checks land with each feature,
not as a retrofit. Every stage transition updates
`company/ledger/company_state.json` + `decisions_log.md` + a handoff
JSON under `company/handoffs/`. HQ dashboard shows progress live. CEO
(Fiyin) approves at end-of-sprint via a dogfood walk-through on desktop
+ mobile.

**Parked (do not start without discussion):** deploying §7b.6 market
paper on the VM platform clone; graduating the squad to real broker
orders; rewriting v1 zones live path; touching `agent/live/` or
`agent/risk/` from a concurrent session's WIP; enabling Sae by default
before the AC verdict; PLG cooldown retune (E013 follow-up); any spend
of money (Finance stays at zero-authority-spend through Sprint 0).
