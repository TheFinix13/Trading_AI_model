# AI Context — brain dump (updated 2026-07-20, v0.36)

> v0.36 — **Karasu (A8, news defender) + Sae (A9, event specialist) landed on
> `next-gen`; Sentinel R7 news-impact ladder wired end-to-end; the historical
> `risk_scale` enforcement gap in the executor is closed.** Karasu never
> proposes — publishes ±minute advisories parsed from the FOMC/ECB calendar
> cache; R7 blocks high-impact windows and returns `risk_scale=0.5` on
> medium-impact (commit `2df58ae`). Sae is EURUSD-only v1, disabled by
> default (commit `a26eba8`); squad `__init__` exports updated
> (commit `38a91b4`). **Engine risk_scale fix (this session, commit
> `3ccc633`):** `SentinelDecision.risk_scale` from R5 loss-streak + R7
> news-medium now multiplies the paper broker's fill lot; sub-MIN_LOT
> scaling SKIPS with a `sentinel_risk_scale_below_min_lot` reject row
> (never rounds up). **USDJPY / USDCHF parquet cache pulled 2026-07-20**
> via Dukascopy — 17,706 H4 + 3,436 D1 bars each, 2015-07-23 → 2026-07-20.
> **605 tests pass** (was 603), 1 pre-existing playwright skip.
>
> Prior versions squashed for line budget — see `docs/00-journey.md`,
> `docs/CHECKPOINT.md`, and git log. Landmarks: **v0.35** live-market
> squad paper runtime (ported v1 core, `scripts/run_squad_live.py`,
> ≈97 % g7retry1-phi41 parity); **v0.33** platform D1-D4;
> **v0.27** `next-gen` branch split; **v0.25** live-agent reliability
> fixes.

Read this first in a fresh chat. Strictly technical state summary.
Deeper history: `docs/00-journey.md`. Snapshot: `docs/CHECKPOINT.md`.
**Active R&D:** `finance-research-experiments` on `multi-agent-ensemble`
— **Phase AC pitch-assignment** (AC.0-v2 fresh-compute + AC.1 / AC.2
conditional arms) firing at session start. Live trading on demo only.

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
  /v1 live view + /v2 squad pitch tailing paper JSONL; runbook §7b/§7b.5/§7b.6.
- **Data cache:** `data/parquet/` — EURUSD / GBPUSD / USDCAD +
  **USDJPY / USDCHF new** (17,706 H4 + 3,436 D1 each, 2015 → 2026-07-20).
- **Observability:** daily logs, heartbeat, vaults, weekly bundle,
  rejection-review digest. **605 tests pass.**

## 2) Key file paths

| Area | Files |
|---|---|
| Strategy | `agent/alphas/concepts/{zone_alpha,_htf}.py`, `agent/alphas/zone_routing.py` |
| Live (`main`) | `scripts/run_live.py`, `agent/live/*.py`, `agent/risk/*.py` |
| Squad (`next-gen`) | `agent/squad/{engine,sentinel,roster,paper_broker,aggregator,workspace,lot_intent,types}.py`, `agent/squad/agents/a0[1-9]_*.py` + `a10_kunigami.py`, `scripts/run_squad_live.py` |
| Karasu + Sae | `agent/squad/agents/a0{8,9}_*.py`, `agent/squad/{news,sae}_config.py`, `agent/news/calendar.py` |
| Platform | `agent/platform/*.py`, `scripts/{serve_platform,run_squad_paper,build_dashboard,weekly_report}.py` |
| Data | `agent/data/*.py`, `data/parquet/*.parquet` |
| Tests | `tests/test_squad_*.py`, `tests/squad/test_engine_risk_scale.py` (new), `tests/test_platform_*.py` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-journey.md`, `docs/RUNBOOK_demo_launch.md`, `docs/08-live-trading-and-deployment.md` |
| M001 pointer | `docs/research/multi-agent-ensemble/README.md` |

## 3) Next immediate goal

**Watch Phase AC campaign land in the research repo.** When AC verdicts
register, decide whether Karasu / Sae get squad-slot changes on
`next-gen`, and whether Sae ships enabled-by-default. Follow-ups (do
not start without discussion): deploy §7b.6 market paper on the VM
platform clone; raise parity floor toward full-panel proposal fidelity;
G7 re-gate before any broker-order path for the squad.

**Parked (do not start without discussion):** graduating the squad to
real broker orders; rewriting v1 zones live path; touching
`agent/live/` or `agent/risk/` from a concurrent session's WIP;
enabling Sae by default before the AC verdict; PLG cooldown retune
(E013 follow-up still requires a fresh pre-registered study).
