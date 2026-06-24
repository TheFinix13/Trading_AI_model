# AI Context — brain dump (updated 2026-06-24, v0.20)

> v0.20 — **Repo split.** M001 multi-agent ensemble R&D migrated to
> the separate `finance-research-experiments` repo (branch
> `multi-agent-ensemble`, folder `programs/M001_multi_agent_ensemble/`,
> commit `11cdde4`). This `multi-pair-trading-agent` repo now keeps:
> (a) the v2 `zone_d1_against` strategy in monitor-only posture,
> (b) production code that M001 will graduate into later (on a future
> `m001-development` branch), and (c) a single-file pointer at
> `docs/research/multi-agent-ensemble/README.md`. Stable v2 state
> tagged here as `v2-zone-d1-against-stable-2026-06-24`
> (HEAD `18546af`). Pre-migration M001 docs were untracked when the
> tag was cut and survive only in the research repo at `11cdde4`. New
> `07-research-standards.md` (461 lines) defines branching, evaluation
> hygiene (five-baseline cohort: Kaiser/Loki/Median/Random/Frozen-Sae),
> reproducibility, the Thought Ledger schema (forward-declared:
> `schema_version`, `decision_horizon`, `ttl_ticks`), and acknowledged
> research debt (June 2026 contaminated by post-hoc design;
> blood-test discipline deferred to Φ4). Legacy-artifact audit at
> `docs/audits/2026-06-24_production_repo_audit.md`. New
> `.cursor/workspace-tips.md` documents the recommended multi-root
> Cursor setup (this repo + research repo + brain-box). Doctrine v0.2
> (Thought Ledger as first-class object, observe/intend split, F17
> ΔInfo for empirical Tier-2/3 assignment, F18 regime-conditional
> KPIs, canon-role vs information-tier separation, Sentinel rules for
> the $100/1:1000 account, Streamlit dashboard scaffold) queued as
> the next research-repo deliverable, blocked on this v0.1 landing.
>
> v0.19 — Blue Lock doctrine landed. Multi-agent R&D now has a
> philosophical spine (`06-blue-lock-doctrine.md`) + a 10-striker cast
> (`05-agent-roster-v0.md` v0.2: Isagi / Bachira / Rin / Chigiri / Reo /
> Nagi / Barou / Yukimiya / Aoshi / Kunigami + Ego coach + Kaiser /
> Loki / Sae as opponents). Foundations extended with F11 (confluence-OR
> conviction) / F12 (Trade Quality Score) / F13 (coordinate overlap) /
> F14 (adversarial validation). Lit plan §1.6 adds Population-Based
> Training, AlphaStar leagues, intrinsic motivation, DIAYN, COMA,
> asymmetric self-play. New account profile: **$100 starting equity at
> 1:1000 leverage** (replaces $1000 demo). New charter gate **C6:
> beat the human user on TQS over a rolling 12-week window**
> (Coverage ≥ 0.6, PnL_HH ≥ 0).
>
> v0.18 — production agent is now in *monitor-only* posture; active R&D track
> has pivoted to a multi-agent ensemble architecture (late-fusion roster of
> specialists). Foundation docs live under
> `docs/research/multi-agent-ensemble/` (charter, archive, lit plan, arch
> sketch, quant foundations, agent roster v0). Live demo blew on
> 2026-06-19 (Exness real $72.41 → −$144.30, full archive in
> `docs/research/multi-agent-ensemble/01-week-2026-06-15-archive.md`).
>
> v0.17 — brain-box + ai_context synced to June observability pass (349 tests);
> daily_summary auto-saves to `{log-dir}/summaries/`. Brain-box node:
> `brain-box/life/finance-research/multi-pair-trading-agent.md`.

Read this first in a fresh chat. Strictly technical state summary.
Deeper history: docs/00-journey.md. Current-state snapshot: docs/CHECKPOINT.md.
**Active R&D:** `finance-research-experiments` /
`programs/M001_multi_agent_ensemble/` (branch `multi-agent-ensemble`,
commit `11cdde4`). Pointer in this repo:
`docs/research/multi-agent-ensemble/README.md`.

## 1) What is built and working

- **Validated strategy (the only one):** `zone_d1_against` —
  SupplyDemandAlpha, H4 zone touch faded AGAINST the D1 trend. Locked:
  `htf_align="D1", htf_align_mode="against", htf_lookback=10,
  htf_min_move_pips=60.0`. Mean-reversion edge; with-trend kills it.
  Validation evidence (full chain in docs/00-journey.md): walk-forward
  H4/all 7/7 positive OOS median +11.34p; frozen cross-pair GBPUSD
  +10.24 p=0.001, USDCAD +4.63 p=0.028; AUDUSD/NZDUSD EXCLUDED. Sealed
  2026 H1: 16 trades +7.75/trade p=0.29 — monitoring.
- **Deployment router:** (symbol, TF, session) → RouteEntry(mode,
  risk_scale, evidence). Deployed: EURUSD/H4/all @1.0, GBPUSD/H4/all @0.5,
  USDCAD/H4/all @0.5. Candidate: EURUSD/D1/all. Unknown cells fail-safe
  skip; contract tests lock params + evidence gates.
- **Live runner:** one process per symbol; router is default alpha;
  TF=H4; conviction-scaled risk 0.5–2% × risk_scale, margin/leverage
  aware, min-lot guards. Flags: `--symbol`, `--log-dir`, `--broker`.
- **Observability:** daily logs `~/Documents/TradingAgentLogs/{SYM}/`
  (UTC rollover, 30 kept); 15-min heartbeat; "no setup" per H4 close;
  bracketed event tags (`[SIGNAL]`, `[TRADE OPENED]`, `[LADDER]`,
  `[POSITION ADOPTED|RESTORED]`, `[SOFT SL ARMED|SL]`, `[TRADE CLOSED]`).
  Near-miss + loss vaults: JSONL + PNG beside logs; observation-only
  (regression test guards byte-identical trading output).
- **Extension-target ladder (observation-only):** structural levels
  beyond the 1.5R TP (swing / zone_edge / trendline / fib_ext /
  daily_level) journaled to `ladders/events.jsonl` AND mirrored on the
  daily log as `[LADDER]`; rungs scored vs realised MFE at close. Report:
  `scripts/report_target_ladders.py --symbol <SYM>`. NOTE: `target_rr=1.5`
  was never grid-swept; validation is conditional on it.
- **Deployed:** Windows VMware, Exness demo ($1000), 3 PowerShell tabs.
  VM update: `git fetch && git reset --hard origin/main && pip install
  -r requirements.txt` (never push from VM).
- **Crash-resilient state persistence:** `agent/live/state_store.py` —
  atomic JSON sidecar `{log_root}/{SYMBOL}/state.json`. On restart:
  `PositionMonitor` ctx/BE/partial/excursion restored; `PostLossGuard`
  and `RiskManager` restored only when persisted day == today UTC;
  `SignalLoop._last_bar_times` restored if < 2 days old. Writes via
  tmp + os.replace; save errors swallowed.
- **Daily-log enrichment + adopted soft-SL inference (2026-06-16):**
  `[TRADE OPENED]` now prints pip distances + TP R-multiple inline
  (`soft_sl=P (Np) catastrophe_sl=P (Np) tp_mech=P (X.XR, +Np)`); every
  fill emits a follow-up `[LADDER]` line mirroring `ladders/events.jsonl`.
  `[POSITION ADOPTED]` / `[POSITION RESTORED]` use the same shape. On
  restart, an open position with no persisted ctx gets a synthetic one
  built from the broker SL — `soft_stop = entry ± broker_dist /
  catastrophe_mult` (default 2.5 from `LiveConfig`). Soft-stop / BE /
  trailing / R-math come back online; degenerate inputs (no broker SL,
  distance < 4p) preserve the honest `soft_sl=unknown (adopted)` path. An
  already-breached soft level at adoption emits `[ADOPTED — SOFT SL
  ALREADY BREACHED]` and closes immediately with cause
  `soft_sl_inferred_overshoot`. Synthetic ctx is persisted on the first
  cycle so subsequent restarts reuse it.
- **Near-miss chart upgrade (2026-06-16):** `chart_snapshot.render_snapshot`
  draws solid blue entry, dashed red SL, dashed green TP with right-edge
  price labels; zone rectangle coloured by side (long=green, short=red);
  title carries reason + direction; bottom-right caption shows the
  rejection detail (HTF bias / risk-manager message).
- **Overshoot close emits real fill / pnl (2026-06-16):** the
  `soft_sl_inferred_overshoot` path now stashes the broker's actual
  `OrderResult.fill_price` (or, as a fallback, the latest tick — never
  the entry) into `monitor._close_results`, and `_handle_close` prefers
  it over the stale excursion. Fixes the bug where the close log showed
  `exit=entry pnl=+0.00 (+0p, +0.00R)`. Applies to the regular
  soft-stop close path too.
- **Daily summary report (2026-06-16):** `python scripts/daily_summary.py
  [--days N] [--symbol …] [--log-dir …]` walks the daily log lines + vault
  JSONLs + state.json sidecar for every deployed symbol and prints one
  paste-friendly block (window activity + cumulative all-time vault stats
  including ladder reach rates and near-miss resolution counts). Auto-saves
  to `{log-dir}/summaries/summary_<range>.txt` (`--out` override,
  `--no-save` to disable). Pure observation — never moves a gate.
- **Tests:** 349 passing. (Git history rewritten 2026-06-10 to strip
  Co-authored-by Cursor trailers — VM must hard-reset on update.)
- **[2026-06-16 v0.11] Brain Box restructure** — this repo's primary
  brain-box node now lives under the new `Finance & Research Hub`
  (`life/finance-research/_index.md`) alongside Global Portfolio
  Assistant, Dividend Agent, Portfolio Risk DRL, Finance Research Experiments, the
  three Budget Management nodes and the moved `Fraud XAI Research`.
  No paths in this repo changed; brain-box display-title references
  continue to resolve.
- **[2026-06-16 v0.12] Brain Box v0.12 — Background branch landed.**
  Brain-box now has FOUR top-level branches (Life / School / Work /
  **Background**). Finance & Research Hub trimmed to six active
  children — this agent still lives there. `Home Agent Legacy` (the
  early `~/agent` scaffold this repo replaced) moved to
  `background/old-personal-projects/` as the predecessor lineage of
  this agent. No paths in this repo changed; brain-box references
  continue to resolve.
- **[2026-06-16 v0.13] Brain Box v0.13 — smart consolidation pass.**
  **Trading AI Model folder is no longer a standalone brain-box node**
  — its content was folded into this agent's primary node under a new
  `## Trading AI Model Archive` section. Repoint any
  `trading_ai_model_folder` references to `multi_pair_trading_agent`
  (see v0.14 below). The catch-all `Personal Projects` compound under
  Life Hub was retired entirely; Sub-Agent Recycling Map moved to
  Agents Hub; Shared ML Patterns moved to Finance & Research Hub
  (these are the architecture + cross-finance pattern catalogues this
  agent reuses). AUN BSc surfaced as a visible sub-compound under
  Background. No paths in this repo changed; brain-box graph: 98
  nodes, 493 edges.
- **[2026-06-16 v0.14] Local folder renamed: `eurusd-ai-agent` →
  `multi-pair-trading-agent`.** The repo now lives at
  `/Users/the1finix/Documents/GitHub/multi-pair-trading-agent/`. The
  GitHub remote (`TheFinix13/Trading_AI_model.git`) is deliberately
  unchanged — only the local folder and the brain-box node moved.
  Brain-box node: `life/finance-research/multi-pair-trading-agent.md`
  (v0.16 physical refactor; was `life/personal-projects/…`) with
  `aliases: [eurusd-ai-agent, EURUSD Agent, ...]`. Updated inside
  this repo: `.cursor/rules/*.mdc`, `pyproject.toml` (`name`),
  `Dockerfile`, `docker-compose.yml`, `agent/news/calendar.py`
  (User-Agent). Untouched: `docs/archive/*` (historical), `agent/`
  import root (still `agent`). All research reports also rewritten
  under the Readability-and-Clarity six rules
  (`docs/reports/trading_agent_research_report.tex` rebuilt to 6
  pages; E001–E007 + template + confluence LaTeX rewritten in
  `finance-research-experiments`).

## 2) Key file paths

| Area | Files |
|---|---|
| Strategy | `agent/alphas/concepts/zone_alpha.py`, `agent/alphas/concepts/_htf.py` |
| Router | `agent/alphas/zone_routing.py` (+ `tests/test_zone_routing.py`) |
| Research harness | `agent/alphas/grid.py`, `agent/alphas/backtest.py`, `agent/backtest/metrics.py` |
| Live | `scripts/run_live.py`, `agent/live/router_wiring.py`, `agent/live/signal_loop.py`, `agent/live/position_sizer.py`, `agent/live/monitor.py`, `agent/live/broker.py`, `agent/live/state_store.py` |
| Vaults | `agent/journal/vault.py`, `agent/journal/chart_snapshot.py`, `agent/journal/resolver.py`, `scripts/resolve_near_misses.py`, `scripts/daily_summary.py` |
| Target ladder | `agent/journal/target_ladder.py`, `scripts/report_target_ladders.py` (+ `tests/test_target_ladder.py`) |
| Validation scripts | `scripts/run_zone_all_tfs.py`, `scripts/run_holdout_validation.py`, `scripts/run_walk_forward.py`, `scripts/analyze_walk_forward.py`, `scripts/run_cross_pair_frozen.py` |
| Config | `agent/config.py` (EvalConfig: dev 2015→2025-12-01, sealed 2025-12-01→2026-06-09) |
| Docs | `docs/00-journey.md`, `docs/CHECKPOINT.md`, `docs/ROADMAP.md` (parked/future work), `docs/reviews/` (evidence, never edit), `docs/runbooks/vmware-windows.md` |
| Live tests | `tests/test_live_router_wiring.py`, `tests/test_run_live_cli.py`, `tests/test_vaults.py`, `tests/test_heartbeat_logging.py`, `tests/test_state_store.py` |

## 3) Next immediate goal

**Active track: multi-agent ensemble R&D (Φ0 → Φ1).**

Foundation now lives at `finance-research-experiments` /
`programs/M001_multi_agent_ensemble/` (branch `multi-agent-ensemble`,
v0.1 committed 2026-06-24 at `11cdde4`):

| Doc | What it is |
|---|---|
| `README.md` | Entry point, doc index, kill conditions |
| `00-charter.md` | Mandate, scope, success criteria (C1–C6 incl. C6 human-benchmark gate), kill conditions (K1–K4), phases (Φ0–Φ6), $100/1:1000 account profile (§7) |
| `01-week-2026-06-15-archive.md` | Trade record + post-mortem of the live blowup that triggered the pivot |
| `02-literature-survey-plan.md` | Reading list (6 lineages incl. PBT/AlphaStar/COMA/intrinsic-motivation), formulas to extract (F1–F16) |
| `03-architecture-v0-sketch.md` | Specialist pool → Allocator → Aggregator → Risk Conductor → Execution; AgentProposal contract |
| `04-quant-foundations.md` | F1–F10 baseline (Bates-Granger / risk parity / HRP / Kelly / PBO / DSR / VPIN / gated MoE / stacking / Sharpe-weight); F11 confluence-OR, F12 TQS, F13 coordinate overlap, F14 adversarial validation, F15 devour bonus, F16 Sae composite |
| `05-agent-roster-v0.md` | **Blue Lock cast.** A1 Isagi (liquidity/structure, seeded by zone_d1_against), A2 Bachira (pattern), A3 Rin (Fib/harmonic), A4 Chigiri (breakout), A5 Reo (regime adapter), A6 Nagi (confluence-only), A7 Barou (single-pair specialist), A8 Yukimiya (execution timing), A9 Aoshi (vol-event), A10 Kunigami (anti-tilt). Coach = Ego = Allocator + Risk Conductor. Opponents = Kaiser / Loki / Sae = the user's discretionary trades + synthetic baseline. |
| `06-blue-lock-doctrine.md` | **The doctrine.** Translates ego, weapon, metavision, **Coordinate** (4-D bounding box: price × time × σ × regime), **chemical reaction** (confluence with independent-OR conviction lift), **devour** (competitive capital reweighting), **awakening** (PBT), **TQS** (per-trade fitness), assertion / coexistence / devour-rate KPIs, and the human-as-opponent benchmark into operational primitives. Read before `05`. |
| `07-research-standards.md` | Branching strategy, naming conventions, evaluation hygiene (named windows, five-baseline adversarial cohort, regime-conditional KPIs), reproducibility (seed pinning, manifest, env lock, data ledger), Thought Ledger schema forward-declaration, acknowledged research debt (blood-test deferred, canon ≠ tier), data-plane trajectory (Φ2.5 JSONL+Streamlit → Φ4 +SQLite shadow → Φ6+ WebSocket/Grafana) |

**Next concrete deliverable (Φ1):** `02b-literature-survey.md` — for
each numbered reference, 2–4 sentence summary + the one formula we
borrow + the failure mode + a page-level pointer. No formula enters
`04` without a source-cited entry in `02b`. Reading order in `02 §6`.

**Parallel side-goal (monitor only):** the production
`zone_d1_against` agent stays running on the existing demo — now
re-instantiated on the **$100 / 1:1000 Exness demo** that is the
official pitch for the multi-agent R&D (the prior $1000 demo is
retired). No parameter changes, no new gates — purely to keep
collecting realised-PnL data that will feed the agent-eligibility
gate (DSR / F6) when A1 Isagi is wrapped as the first roster member.
VM update command and verification steps stay as documented in v0.17
below.

**Adversarial benchmark (per F14, charter gate C6).** The user
submits weekly chart analysis + actual trades; they are journalled
as `opponents/kaiser_proposals.jsonl` (high-conviction) and
`opponents/loki_proposals.jsonl` (mid-week revisions). The squad's
TQS distribution is compared head-to-head against the user's TQS
over a rolling 12-week window. Promotion to live capital requires
PnL_HH ≥ 0 *and* Coverage ≥ 0.6 *and* beating the Sae synthetic
baseline.

VM steps (do first):
```powershell
git fetch && git reset --hard origin/main && pip install -r requirements.txt
# restart all 3 symbol tabs
python scripts/daily_summary.py --days 7 --log-dir D:\TradingAgentLogs
```

Verify on next live fill: `[TRADE OPENED] … soft_sl=P (Np) catastrophe_sl=P
(Np) tp_mech=P (X.XR, +Np)` plus a follow-up `[LADDER]` line. On next
restart with an open ticket: `[POSITION ADOPTED|RESTORED]` same shape →
`[SOFT SL ARMED]`; mid-trade soft level must respond. Paste the
auto-saved summary file (or stdout) here for drift review.

1. Weekly: `python scripts/resolve_near_misses.py --symbol <SYM>` per
   pair; review per-gate would-have-won rates. Gates change ONLY via the
   full validation pipeline (grid → holdout → walk-forward).
2. As live n grows, compare live trade distribution vs backtest
   expectancy (EURUSD ~+11/trade, ~50% WR, ~66 trades/yr; full portfolio
   ~250/yr).

Parked (see **docs/ROADMAP.md**): target_rr/structural-TP study (after
~50 ladder trades); laddered partial-TP (`partial_exit_enabled` stays
OFF); USD-exposure manager; EURUSD D1 promotion; autonomy ladder.
