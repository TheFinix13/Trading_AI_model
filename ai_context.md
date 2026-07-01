# AI Context — brain dump (updated 2026-07-01, v0.24)

> v0.24 — **M001 v1/v2 reframe day** (in `finance-research-experiments` on
> `multi-agent-ensemble` branch). No production repo changes today; every
> line of research below lives in the research repo. User directive drove
> a squad-wide reclassification: v1 = squad-tested checkpoint (not
> initial implementation); v2 = architectural upgrade that trumps v1.
> Session delivered: doctrine v0.5 + roster v0.8; 6 evolution-ledger
> RELABEL rows reclassifying prior "v2 mechanics" as v1 iterations;
> **G7 pre-registered protocol** (squad-level v1-checkpoint gate); F19
> `lot_intent` + F20 `risk_intent` + F21 `read_workspace` primitives on
> BaseStriker with per-playstyle dispatch; all 8 v1 agents wired
> (playstyle + tier); engine threads F21 workspace snapshot into
> `intend()`; Bachira consumes Isagi peer confluence (+0.05 lift, 10
> chemistry tests); G7 harness scaffolded (C1/C5/C6 live, C2/C3/C4
> pending full 7-window batch); Sentinel Φ4.1 physical rerun landed
> 5,236 trades / 28,830 proposals / 336,707 thoughts at
> `sentinel_blocks=True` (side-by-side vs sealed 0.2922 audit report
> pending F17-arm completion). 396 sim tests passing. **No production
> code touched, no live-account impact, no strategy change.**
>
> v0.23 — **Research-pipeline sweep E011-E016 complete + two production adds
> (rejection-review + portfolio 5 % risk cap).** Six pre-registered studies
> fired in `finance-research-experiments`; only E013 has an `alive_*` verdict
> and it validates the EXISTING production posture (all safety layers ON, no
> change needed). Two non-strategy production-code adds shipped: weekly
> rejection-review report (`agent/reports/rejection_review.py`) + portfolio-
> wide 5 % open-risk ceiling (`RiskConfig.portfolio_max_open_risk_pct`
> defaulting to `0.05`; hard-blocks any new ticket that would push aggregate
> broker-open risk above 5 %). All 377 tests pass. Verdict summary: E011
> `stopped_at_stage_1` (expectancy bucket-agnostic; kills E012); E013
> `combined_alive` (Δ combined +0.80 Sharpe, wick +0.75, BE ~0), PLG
> `plg_expensive` (blocks 64 % winners vs 33 % losers, +23.5 median would-be
> pips — follow-up study needed to retune); E014 `parked_low_yield` (real
> edge at θ=70 but 12 % of baseline volume; kills E015 + E016). No strategy
> change shipped this session; all changes require a fresh pre-reg study.
>
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
doctrine v0.5 / roster v0.8). Pointer:
`docs/research/multi-agent-ensemble/README.md`. M001 latest verdicts:
**Φ3 PASS · Φ4 FAIL @ 0.98× · Φ4.1 FAIL @ 0.92× · Isagi v2 arc FAIL**
(v1 canonical) · **G7 pre-registered 2026-07-01** (no verdict yet;
full-panel batch pending). Live trading on demo only; production code
untouched.

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
  `state.json` sidecar, **weekly rejection-review digest**
  (`python -m agent.reports.rejection_review --days 7` → markdown + CSV
  grouped by symbol · rejection_reason · stop-bucket, with walk-forward-
  resolved would-be outcomes; observation-only per `PROTOCOL_DISCIPLINE.md` §7).
  377 tests passing.
- **Portfolio risk ceiling (Wave 2.2, 2026-07-01):** `RiskConfig.portfolio_
  max_open_risk_pct = 0.05` — sum of `abs(open_price - stop_loss) * volume *
  pip_value_per_lot` across ALL open tickets (all symbols on this account,
  queried via `broker.get_open_positions(None)`) must not exceed 5 % of
  balance AFTER adding a freshly-sized ticket. Wired in
  `SignalLoop._route_signal` after sizing / before order placement; rejection
  emits `_record_near_miss("portfolio_risk_cap", ...)`.
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
| Risk | `agent/risk/manager.py` (per-symbol + portfolio ceiling), `agent/risk/sizing.py`, `agent/risk/post_loss_guard.py`, `agent/config.py::RiskConfig` |
| Vaults / ladder / reports | `agent/journal/vault.py`, `agent/journal/target_ladder.py`, `agent/reports/rejection_review.py`, `scripts/daily_summary.py` |
| Validation | `scripts/run_zone_all_tfs.py`, `scripts/run_ablation.py`, `scripts/run_walk_forward.py` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-overview.md`, `docs/archive/`, `docs/audits/` |
| M001 pointer | `docs/research/multi-agent-ensemble/README.md` |
| Workspace setup | `.cursor/workspace-tips.md` (multi-root: this repo + research + brain-box) |

## 3) Next immediate goal

**2026-07-01 research-pipeline sweep — closed.** Six pre-reg studies fired
in `finance-research-experiments` (E011-E016). Verdicts registered in
`finance-research-experiments/EXPERIMENTS.md`:

| Study | Verdict | Production impact |
|---|---|---|
| E011 small-stop subset expectancy | `stopped_at_stage_1` | none — kills E012 |
| E012 pending-limit entry | `cancelled_dep_failed` | none |
| E013 safety-layer contribution | `combined_alive` (Δ +0.80 Sharpe); wick `alive`; BE CI touches 0; PLG `plg_expensive` | validates existing posture; PLG follow-up study needed |
| E014 quality-score entry gate | `parked_low_yield` | none — kills E015 + E016 (12 % of baseline volume) |
| E015 conviction-from-quality | `cancelled_dep_failed` | none |
| E016 re-entry / flip | `cancelled_dep_failed` | none |

**Production adds shipped this session (Wave 2, non-strategy):**

1. `agent/reports/rejection_review.py` — weekly digest of near-miss vault
   events grouped by symbol · reason · stop-bucket, with walk-forward-
   resolved would-be outcomes. CLI: `python -m agent.reports.rejection_review
   --days 7`. Tests: `tests/test_rejection_review.py` (10 tests).
2. `RiskConfig.portfolio_max_open_risk_pct = 0.05` + `RiskManager.
   evaluate_portfolio_ceiling` + `RiskDecision.SKIP_PORTFOLIO_RISK` +
   `SignalLoop._route_signal` wiring. Tests:
   `tests/test_portfolio_risk_cap.py` (9 tests). All 377 tests pass.

**Follow-up study candidate (2026-07 backlog):** PLG cooldown tuning. E013
found PLG blocks 64 % future-winners vs 33 % future-losers on the deployed
cell — median would-be pips per block is +23.5. This is a real production
concern but requires a fresh pre-registered study (`PROTOCOL_DISCIPLINE.md`
§5) before any PLG parameter is changed.

**Active track: M001 multi-agent ensemble (Φ4.1 closed → Φ4.2 + Φ5 in flight)
in research repo.** Phase 6e Φ5 re-sim (Arms 3/4/5) still pending in
`finance-research-experiments` per that repo's `ai_context.md` §3. This
production repo is untouched by M001 work until a graduation gate lands.

**Monitor-only:** `zone_d1_against` on $100/1:1000 demo — no param changes;
collecting live PnL for future DSR gate when A1 Isagi wraps the roster.

Parked: see `docs/ROADMAP.md` (target_rr study, partial TP, USD exposure, D1
promotion, autonomy ladder). Wave 3 production-repo cleanup still queued
per `docs/audits/2026-06-24_production_repo_audit.md` §5; waits on M001.
