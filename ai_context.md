# AI Context — brain dump (updated 2026-07-20, v0.37)

> v0.37 — **Two /v2 dashboard reliability fixes on `next-gen` for this
> week's live shadow-paper watch.** **(A) per-poll heartbeat** (commit
> `5ba01ec`): `run_squad_live` atomically rewrites `poll_heartbeat.txt`
> each outer-loop iteration; `paper_loop.live_status` now treats
> state.json OR poll_heartbeat.txt as the running signal, so the /v2
> badge stops false-flashing "MARKET STREAM IDLE" between H4 bar closes
> (~99 % of clock time). Adds `poll_heartbeat_age_seconds` on the status
> payload; `state_age_seconds` unchanged for backwards compat.
> **(B) per-tick summary events** (commit `762d7d8`): engine emits one
> `tick_summary` row per `on_bar` to a new `events.jsonl`
> (`players_evaluated / players_who_proposed / proposal_count /
> post_sentinel_count / workspace_thought_count`); /v2 ticker renders
> muted "⋯ N players evaluated, 0 proposals" rows on quiet bars.
> `squad_events` reads `events.jsonl` (optional); `event_schema` treats
> `tick_summary` as agent-optional; per-agent tallies unchanged; new
> "hide silent ticks" checkbox. **619 tests pass** (was 604), 1
> pre-existing playwright skip.
>
> v0.36 (2026-07-20): Karasu A8 + Sae A9, R7 news-impact ladder,
> `risk_scale` enforced on fills, USDJPY / USDCHF cache pulled — see
> `git log 5de1e8c^..5de1e8c` and `docs/00-journey.md`. Landmarks:
> **v0.35** live-market squad paper; **v0.27** `next-gen` split;
> **v0.25** live-agent reliability.

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
  /v1 live view + /v2 squad pitch tailing paper JSONL; runbook
  §7b/§7b.5/§7b.6. v0.37 heartbeat + tick_summary fixes above.
- **Data cache:** `data/parquet/` — EURUSD / GBPUSD / USDCAD +
  **USDJPY / USDCHF new** (17,706 H4 + 3,436 D1 each, 2015 → 2026-07-20).
- **Observability:** daily logs, heartbeat, vaults, weekly bundle,
  rejection-review digest. **619 tests pass.**

## 2) Key file paths

| Area | Files |
|---|---|
| Strategy | `agent/alphas/concepts/{zone_alpha,_htf}.py`, `agent/alphas/zone_routing.py` |
| Live (`main`) | `scripts/run_live.py`, `agent/live/*.py`, `agent/risk/*.py` |
| Squad (`next-gen`) | `agent/squad/{engine,sentinel,roster,paper_broker,aggregator,workspace,lot_intent,types}.py`, `agent/squad/agents/a0[1-9]_*.py` + `a10_kunigami.py`, `scripts/run_squad_live.py` |
| Karasu + Sae | `agent/squad/agents/a0{8,9}_*.py`, `agent/squad/{news,sae}_config.py`, `agent/news/calendar.py` |
| Platform | `agent/platform/*.py`, `scripts/{serve_platform,run_squad_paper,build_dashboard,weekly_report}.py` |
| Data | `agent/data/*.py`, `data/parquet/*.parquet` |
| Tests | `tests/test_squad_*.py`, `tests/squad/test_engine_{risk_scale,tick_summary}.py`, `tests/platform/test_squad_events_parsing.py` (new v0.37), `tests/test_platform_*.py` |
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
