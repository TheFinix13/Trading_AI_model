# AI Context — brain dump (updated 2026-06-30, v0.22)

> v0.22 — **M001 Φ4.1 expanded squad gate FAIL @ 0.92× + Isagi v2 arc FAIL +
> methodology lock + regime redesign + round-1 + round-2 v2 backlog
> resolutions.** Production repo untouched today (R&D lives in
> `finance-research-experiments` on `multi-agent-ensemble` branch). The
> headline numbers below are the locked Φ4.1 telemetry. **Φ4.1 FAIL** at
> squad TQS **0.2922** vs Isagi-alone **0.3175** (0.92×). Predicate
> starvation diagnosis **confirmed + fixed**: Nagi confluence-firing
> thoughts went 0 → **34,302** between Φ4 and Φ4.1, producing mean
> **TQS 0.349 (HIGHEST per-agent TQS in the 8-agent squad)**. But a new
> failure mode surfaced — **structural crowding-out**: Isagi 0 trades,
> Barou 0 trades, both slot-cannibalised by Bachira's `+0.10` rebel-lift
> on the same baseline-zone primitive. **Isagi v1→v2 evolution arc
> FAIL** (single-agent arc, 2026-06-24) — v1 stays canonical, v2 archived
> at `sim/agents/a01_isagi_v2.py`. **Regime classifier redesign:**
> `vol_spike` + `news` RETIRED on structural grounds (OHLCV cannot
> detect news; vol-spike has no clean separation from non-news vol);
> live-classes-only `{trending, chop}` macro F1 = 0.971 (was 0.496).
> **Methodology lock:** `docs/methodology/gate_verdict_registry.md` v0.1
> binds per-gate locked statistic; `07-research-standards.md` v0.4 §11
> forbids post-hoc statistic swaps. **v2 backlog resolutions** (round-1
> 2026-06-25 + round-2 2026-06-30): Nagi RETIRED (v1 floor empirically
> correct); Barou REDESIGN-hybrid-A+B (user decision 2026-06-30: closed-
> loss replay USDCAD + symbol expansion to EURUSD/GBPUSD/USDCAD);
> Kunigami DEFERRED pending Sentinel R1–R5; Bachira REFINE-to-peer-
> silence; Rin REFINE-regime+peer-disagreement; Chigiri REFINE-multi-TF-
> ADX+ATR-percentile; Reo ADVANCE-coupled-to-Φ5-multi-position.
> Doctrine v0.4 / roster v0.7. **Architectural insight:** the single-
> position-per-symbol queue with conviction-only ranking is the binding
> constraint (Φ4.1 and Isagi v2 converged on this diagnosis); **Φ5 lever
> is the aggregator** (HRP + TQS-floor + same-direction merge + multi-
> position), NOT more strikers. 358 sim tests passing. **VM impact:**
> none — production untouched; demo $100 / 1:1000 profile unchanged.
> Live trading not reactivated.
>
> v0.21.1 / v0.21 / v0.20 — production repo split (M001 R&D migrated to
> `finance-research-experiments`), Wave 1 + Wave 2 cleanup, `m001-development`
> branch + `v2-zone-d1-against-stable-2026-06-24` rollback tag, allocator.py
> kept as M001 seed (KEEP-AND-INHERIT). Full detail in git history of this
> file + `docs/00-journey.md`.
>

Read this first in a fresh chat. Strictly technical state summary.
Deeper history: `docs/00-journey.md`. Snapshot: `docs/CHECKPOINT.md`.
**Active R&D:** `finance-research-experiments` /
`programs/M001_multi_agent_ensemble/` (branch `multi-agent-ensemble`,
commit `53628fc`, doctrine v0.4 / roster v0.7). Pointer:
`docs/research/multi-agent-ensemble/README.md`. M001 latest verdicts:
**Φ3 PASS · Φ4 FAIL @ 0.98× · Φ4.1 FAIL @ 0.92× · Isagi v2 arc FAIL**
(v1 canonical). Live trading on demo only; production code untouched.

## 1) What is built and working

- **Validated strategy:** `zone_d1_against` — SupplyDemandAlpha, H4 zone touch
  faded AGAINST D1 trend. Locked: `htf_align="D1", htf_align_mode="against",
  htf_lookback=10, htf_min_move_pips=60.0`. Evidence chain in
  `docs/00-journey.md` / `docs/reviews/`.
- **Deployment router:** EURUSD/H4/all @1.0, GBPUSD/H4/all @0.5, USDCAD/H4/all
  @0.5. Unknown cells fail-safe skip; contract tests in
  `tests/test_zone_routing.py`.
- **Live runner:** one process per symbol; router default; conviction-scaled
  risk 0.5–2% × risk_scale. `scripts/run_live.py --symbol --log-dir --broker`.
- **Observability:** daily logs, 15-min heartbeat, bracketed tags, near-miss/loss
  vaults (JSONL+PNG), target ladder (observation-only), `daily_summary.py`,
  `state.json` sidecar. 349 tests passing.
- **Deployed:** Windows VMware, Exness demo ($100 / 1:1000), 3 PowerShell tabs.
  VM update: `git fetch && git reset --hard origin/main && pip install -r requirements.txt`.
- **Branches:** `main` = production; `m001-development` = pre-M001 baseline for
  future M001 graduation; tag `v2-zone-d1-against-stable-2026-06-24` at
  `6f1cc75` for rollback.

## 2) Key file paths

| Area | Files |
|---|---|
| Strategy | `agent/alphas/concepts/zone_alpha.py`, `agent/alphas/concepts/_htf.py` |
| Router | `agent/alphas/zone_routing.py` |
| M001 seed (keep) | `agent/alphas/allocator.py` — Ledoit-Wolf, long-only weights |
| Live | `scripts/run_live.py`, `agent/live/signal_loop.py`, `agent/live/state_store.py` |
| Vaults / ladder | `agent/journal/vault.py`, `agent/journal/target_ladder.py`, `scripts/daily_summary.py` |
| Validation | `scripts/run_zone_all_tfs.py`, `scripts/run_ablation.py`, `scripts/run_walk_forward.py` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-overview.md`, `docs/archive/`, `docs/audits/` |
| M001 pointer | `docs/research/multi-agent-ensemble/README.md` |
| Workspace setup | `.cursor/workspace-tips.md` (multi-root: this repo + research + brain-box) |

## 3) Next immediate goal

**Active track: M001 multi-agent ensemble (Φ4.1 closed → Φ4.2 + Φ5 in flight)
in research repo.** Today's (2026-06-30) implementation sprint: Sentinel R1–R5
wiring (un-blocks Kunigami v2 + Φ5 Arm 4); news calendar wiring (Dukascopy
primary, multi-source fallback, 2007 backfill); Φ5 aggregator selection (5
arms); v2 agent implementations (Barou hybrid A+B, Bachira/Rin/Chigiri/Reo
refines). Sequenced per
`finance-research-experiments/programs/M001_multi_agent_ensemble/prep/2026-06-25_session_kickoff.md`.

**Production repo (this):** no changes pending. Wave 3 still queued per
`docs/audits/2026-06-24_production_repo_audit.md` §5 (dead-code delete +
`_archive/` sweep + dep purge + Docker/MT5 archive); waits on M001 verdict to
avoid touching code paths that may need to inherit from M001 outputs.

**Monitor-only:** `zone_d1_against` on $100/1:1000 demo — no param changes;
collecting live PnL for future DSR gate when A1 Isagi wraps the roster.

Parked: see `docs/ROADMAP.md` (target_rr study, partial TP, USD exposure, D1
promotion, autonomy ladder).
