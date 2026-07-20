# AI Context — brain dump (updated 2026-07-21, v0.40)

> v0.40 — **/v2 workspace panel + LIVE controls + /v1 excursion +
> polish** (commit `2e04eac` on `next-gen`). Engine writes
> `workspace_snapshot.json` on every `on_bar()` (atomic, cap 60);
> every `tick_summary` carries a compact `thoughts_top5` for replay.
> New route `GET /api/v2/live/workspace`. UI: `#workspace-panel`
> two-column grid of `.thought-card` cells (agent dot, confidence
> bar, tags, expected action / dir / stop), LIVE polls every 15 s;
> Play/speed hidden on LIVE, replaced by `#live-connection` pill
> with event count + manual refresh (300 ms spin); `/v1` excursion
> now MAE/MFE/Last/Profit/Stop/TP pills with `.card` word-break
> safety net. Polish: `.live-dot` pulse on every LIVE badge,
> per-second countdown, `.card` fade-in, shared `.tooltip-panel`.
> **686 tests pass** (was 654); +32 across engine snapshot /
> paper_loop / workspace endpoint / v2 markup / v1 excursion HTTP.
>
> v0.39 (`f5ef13b`): /v2 UX pass (plain-English labels, info popover,
> waiting-panel, hover tooltips, first-visit ribbon, guided tour).
> v0.38 (`8dd2669`): hub redesign. v0.37 (`762d7d8`): /v2 heartbeat +
> `tick_summary`. Landmarks: **v0.36** Karasu/Sae + R7 + `risk_scale`;
> **v0.35** live-market squad paper; **v0.27** `next-gen` split;
> **v0.25** live-agent reliability. Full history: `docs/00-journey.md`.

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
  `agent/squad/`, `scripts/run_squad_live.py` (MT5/cache). Roster
  A1-A7 proposers + A8 Karasu (R7 news) + A9 Sae (off) + A10 Kunigami
  (R5). Shadow JSONL fills, ≈97 % proposal-key parity vs
  `g7retry1-phi41` (G7 = FAIL 3/7, not a graduation).
- **Sentinel:** R1-R6 + **R7 news-impact ladder** (block high, 0.5×
  medium); `risk_scale` enforced end-to-end (v0.36).
- **Platform (`next-gen`, read-only):** `scripts/serve_platform.py`,
  hub (v0.38 KPI-strip redesign) + /v1 live view (v0.40 excursion
  pills) + /v2 squad pitch (v0.39 UX pass + v0.40 workspace panel /
  LIVE-only connection pill / replay-transport hide / `.live-dot`
  pulse / second-precision countdown / `.tooltip-panel` shared).
  New route `GET /api/v2/live/workspace`. Runbook §7b/§7b.5/§7b.6.
- **Workspace snapshot:** `agent/squad/engine.py` writes
  `workspace_snapshot.json` on every `on_bar()` (cap 60, atomic
  tmp+replace); every `tick_summary` event carries a compact
  `thoughts_top5` array so historical replays render the same panel.
  Reader: `agent.platform.paper_loop.live_workspace()`.
- **Data cache:** `data/parquet/` — EURUSD / GBPUSD / USDCAD +
  **USDJPY / USDCHF new** (17,706 H4 + 3,436 D1 each, 2015 → 2026-07-20).
- **Observability:** daily logs, heartbeat, vaults, weekly bundle,
  rejection-review digest. **686 tests pass.**

## 2) Key file paths

| Area | Files |
|---|---|
| Strategy | `agent/alphas/concepts/{zone_alpha,_htf}.py`, `agent/alphas/zone_routing.py` |
| Live (`main`) | `scripts/run_live.py`, `agent/live/*.py`, `agent/risk/*.py` |
| Squad (`next-gen`) | `agent/squad/{engine,sentinel,roster,paper_broker,aggregator,workspace,lot_intent,types}.py`, `agent/squad/agents/a0[1-9]_*.py` + `a10_kunigami.py`, `scripts/run_squad_live.py` |
| Karasu + Sae | `agent/squad/agents/a0{8,9}_*.py`, `agent/squad/{news,sae}_config.py`, `agent/news/calendar.py` |
| Platform | `agent/platform/*.py`, `scripts/{serve_platform,run_squad_paper,build_dashboard,weekly_report}.py` |
| Data | `agent/data/*.py`, `data/parquet/*.parquet` |
| Tests | `tests/test_squad_*.py`, `tests/squad/test_engine_{risk_scale,tick_summary,workspace_snapshot}.py`, `tests/platform/{test_squad_events_parsing,test_hub_page,test_v2_page,test_paper_loop_live_workspace,test_v1_excursion_rendering,test_v2_live_workspace_endpoint}.py` (v0.40 additions), `tests/test_platform_*.py` |
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
