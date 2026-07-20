# AI Context — brain dump (updated 2026-07-20, v0.39)

> v0.39 — **/v2 UX pass + first-visit guided tour** (commit `6e14735`
> on `next-gen`). Display-only rewrite of `V2_PAGE`: mode dropdown
> now plain English ("LIVE — Today's market" / "Historical replay ·
> Single-shot rule" for phi41 / "Twin-strike rule" for arm4; wire ids
> unchanged as `<option value=>`), speed picker as 🐢/⏩/🚀/⚡ tiers
> (8/16/60/120 ev/s). New surfaces: ℹ️ info popover (mode-aware,
> `/#glossary` deep-link), mode-aware H1 subtitle, live
> "waiting on the market" empty-state panel (next-H4 countdown,
> workspace count, standby pills), player hover tooltips,
> first-visit ribbon (`localStorage.v2_visited`, 60 s auto-hide),
> 6-step guided tour (dim shade + spotlight ring, Esc exits).
> `HUB_PAGE` gained `id="glossary"` anchor. **654 tests pass**
> (was 635); +19 in `tests/platform/test_v2_page.py` + hub anchor.
>
> v0.38 (`8dd2669`): platform hub redesigned — KPI strip, plain-
> English explainer, native `<details>` glossary, recent-activity
> feed, mode-aware v2 badge. v0.37 (`5ba01ec`, `762d7d8`): /v2
> heartbeat + `tick_summary`. Landmarks: **v0.36** Karasu A8 + Sae
> A9 + R7 news ladder + `risk_scale`; **v0.35** live-market squad
> paper; **v0.27** `next-gen` split; **v0.25** live-agent
> reliability. Full history: `git log --oneline main..next-gen`
> and `docs/00-journey.md`.

Read this first in a fresh chat. Deeper history: `docs/00-journey.md`
and `docs/CHECKPOINT.md`. **Active R&D:** `finance-research-experiments`
on `multi-agent-ensemble` — **Phase AC pitch-assignment**. Live trading
on demo only.

## 1) What is built and working

- **Live (`main`):** `zone_d1_against` H4, router EURUSD @ 1.0 /
  GBPUSD @ 0.5 / USDCAD @ 0.5; risk 0.5-2 % × `risk_scale`, 5 %
  portfolio open-risk cap, per-symbol kill files, MT5-first close
  resolution, healthchecks.io dead-man ping.
- **Squad paper runtime (`next-gen`):** ported v1 core in
  `agent/squad/`, `scripts/run_squad_live.py` (MT5 or cache feed).
  Roster A1-A7 proposers + A8 Karasu (news defender, R7) + A9 Sae
  (event specialist, off) + A10 Kunigami (R5). Shadow JSONL fills,
  kill/state/heartbeat. ≈97 % proposal-key parity vs `g7retry1-phi41`.
  Not a G7 graduation (G7 = FAIL 3/7).
- **Sentinel:** R1-R6 as before + **R7 news-impact ladder** (block
  high, 0.5× medium); `risk_scale` now enforced end-to-end (v0.36).
- **Platform (`next-gen`, read-only):** `scripts/serve_platform.py`,
  hub (v0.38 KPI-strip redesign) + /v1 live view + /v2 squad pitch
  (v0.39 UX pass — plain-English mode picker, info popover, live
  waiting-panel, hover tooltips, first-visit ribbon + guided tour)
  tailing paper JSONL; runbook §7b/§7b.5/§7b.6.
- **Data cache:** `data/parquet/` — EURUSD / GBPUSD / USDCAD +
  **USDJPY / USDCHF new** (17,706 H4 + 3,436 D1 each, 2015 → 2026-07-20).
- **Observability:** daily logs, heartbeat, vaults, weekly bundle,
  rejection-review digest. **654 tests pass.**

## 2) Key file paths

| Area | Files |
|---|---|
| Strategy | `agent/alphas/concepts/{zone_alpha,_htf}.py`, `agent/alphas/zone_routing.py` |
| Live (`main`) | `scripts/run_live.py`, `agent/live/*.py`, `agent/risk/*.py` |
| Squad (`next-gen`) | `agent/squad/{engine,sentinel,roster,paper_broker,aggregator,workspace,lot_intent,types}.py`, `agent/squad/agents/a0[1-9]_*.py` + `a10_kunigami.py`, `scripts/run_squad_live.py` |
| Karasu + Sae | `agent/squad/agents/a0{8,9}_*.py`, `agent/squad/{news,sae}_config.py`, `agent/news/calendar.py` |
| Platform | `agent/platform/*.py`, `scripts/{serve_platform,run_squad_paper,build_dashboard,weekly_report}.py` |
| Data | `agent/data/*.py`, `data/parquet/*.parquet` |
| Tests | `tests/test_squad_*.py`, `tests/squad/test_engine_{risk_scale,tick_summary}.py`, `tests/platform/{test_squad_events_parsing,test_hub_page,test_v2_page}.py` (v2 UX tests new v0.39), `tests/test_platform_*.py` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-journey.md`, `docs/RUNBOOK_demo_launch.md`, `docs/08-live-trading-and-deployment.md` |
| M001 pointer | `docs/research/multi-agent-ensemble/README.md` |

## 3) Next immediate goal

**Watch this week's live shadow-paper on the fixed /v2 dashboard.**
Then watch Phase AC campaign land in the research repo — when AC
verdicts register, decide whether Karasu / Sae get squad-slot changes
on `next-gen`, and whether Sae ships enabled-by-default.

**Parked (do not start without discussion):** deploying §7b.6 market
paper on the VM platform clone; graduating the squad to real broker
orders; rewriting v1 zones live path; touching `agent/live/` or
`agent/risk/` from a concurrent session's WIP; enabling Sae by default
before the AC verdict; PLG cooldown retune (E013 follow-up).
