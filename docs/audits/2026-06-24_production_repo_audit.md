# Production repo audit — multi-pair-trading-agent

## §0 — Audit metadata

> **STATUS: report-only, no moves executed.** No files were moved, renamed,
> deleted, or otherwise altered. Action items in §3 are recommendations
> only; the parent must approve and sequence the actual moves.

- **Date:** 2026-06-24
- **Repo:** `/Users/the1finix/Documents/GitHub/multi-pair-trading-agent`
- **Git SHA at audit time:** `6f1cc753bc61c696071f82edc7ba22795def2aeb`
- **Branch:** `main`
- **Working-tree state at audit time:** `M ai_context.md` (in-flight v0.19
  brain-dump from another worker); `?? docs/research/` (in-flight M001
  doctrine drop). Audit reads but does not modify either path.
- **Author:** Audit worker (Cursor sub-agent)
- **Inputs consulted:** `docs/00-overview.md`, `docs/00-journey.md`,
  `docs/CHECKPOINT.md`, `ai_context.md` (v0.19), `docs/audit/README.md`,
  `pyproject.toml`, `requirements.txt`, full `agent/` import graph,
  `scripts/run_live.py` transitive call graph, every `tests/` import set,
  numbered-doc status banners, and the
  `docs/research/multi-agent-ensemble/` README + charter.

## §1 — Executive summary

### Category totals

Counts cover Python modules, scripts, top-level config / packaging files,
notable subdirectories and numbered docs. Auto-generated artefacts (e.g.
PDF / .aux / .log under `docs/reports/`) and `__init__.py` files are
folded into their parent counts.

| Category | Approx. count |
|---|---:|
| KEEP — production (live-VM call graph) | 55 |
| KEEP — shared infrastructure (v2 + M001 reuse) | 25 |
| TRANSITION (active under v2, role flips under M001) | 5 |
| ARCHIVE — historical (banner-marked, wrong folder) | 12 |
| ARCHIVE — superseded (replaced, no current imports) | 24 |
| DELETE — dead code (unreferenced) | 8 |
| DELETE — generated / ephemeral (already gitignored) | 5 dirs |
| STALE-REFERENCE (active file, outdated text) | 10 |
| UNCLEAR (needs parent decision) | 2 |

### Top three risks if archiving were executed naïvely

1. **`agent/detectors/{fvg,bos,liquidity_sweep,daily_levels,trendlines,
   swings,sessions,zones}.py` look like v1 detector cruft but are
   load-bearing.** `agent/rules/engine.py::precompute` runs the entire
   detector battery on every closed bar in the live loop, even though only
   `zones` and `swings` are read by `SupplyDemandAlpha`. Archiving any of
   them breaks the live VM at first bar close.
2. **`agent/risk/sizing.py` looks superseded by `agent/live/position_sizer.py`
   but is not.** `agent/risk/manager.py` (which IS in the live loop) still
   calls `position_size()` from `sizing.py` as the final gate before the
   `PositionSizer` is even invoked. Both sizers run today.
3. **`scripts/deploy_windows.ps1` references the old GitHub remote
   (`TheFinix13/Trading_AI_model`) and is linked from the current
   `docs/08-live-trading-and-deployment.md`.** Renaming the local repo did
   not propagate to the PowerShell installer; pulling fresh on a new VM via
   the documented one-liner would fetch the wrong-named repo path. This is
   stale text in an active codepath — fix in place, do not move.

### Three-line top-level recommendation

The v1-era detritus is concentrated in three islands —
`agent/{reaction,context,news,regime}/`,
`agent/alphas/{reaction_alpha,allocator}.py` +
`agent/journal/{db,live_journal}.py`, and the numbered v1 docs
(`01/02/04/07/09/10`) — and can be archived in three discrete waves with
zero VM coordination needed for the first two. The riskiest single change
is purging the v1 ML / web-server dependencies from `pyproject.toml` and
`requirements.txt` (`scikit-learn`, `xgboost`, `joblib`, `shap`, `fastapi`,
`uvicorn`, `jinja2`, `python-multipart`, `click`, `schedule`, `rich`) —
none are imported by production but the VM has them pinned; coordinate.
M001 striker code does not exist yet; defer the `agent/multi/strikers/`
layout decision until Φ6.

## §2 — Per-directory deep dive

### §2.1 `agent/`

The `agent/` package is the largest single mix of eras. The v2 reset
(`docs/audit/README.md`) burned the most aggressive v1 stuff (`strategy/`,
`optimizer/`, `dashboard/`, `llm/`, `conversation/`, `model/`,
`discovery/`), but it preserved every detector and several support
modules under the rationale of "keep perception, burn confluence." Three
years of that policy has left ~24 modules in `agent/` that no current
import touches.

The live call graph is narrower than the directory suggests. Tracing from
`scripts/run_live.py`:

```
run_live → router_wiring → zone_routing → zone_alpha → _htf
                         → SignalLoop → broker, monitor, position_sizer,
                                        soft_stop, state_store, trade_events,
                                        notifications.telegram, vault,
                                        target_ladder, risk.manager
                                        → risk.sizing (final gate)
                                        risk.post_loss_guard
                                        rules.engine.precompute
                                        → detectors.{swings, bos, fvg,
                                                     trendlines, zones,
                                                     daily_levels,
                                                     liquidity_sweep,
                                                     sessions}
                                        types, utils, config
```

Everything else in `agent/` is either validation-harness infrastructure
(used by `scripts/run_*.py`), or it is not imported at all.

#### Root-level modules

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/config.py` | KEEP — production | live + every script + tests | Same; M001 will extend `Config` for striker pool | v2 reset already trimmed `RulesConfig`, `MLConfig`, `RankingConfig`, etc.; what remains is in use |
| `agent/types.py` | KEEP — production | live + every script + tests | Same; `Bar`, `Direction`, `Timeframe`, `Trade`, etc. are the canonical domain types | — |
| `agent/utils.py` | KEEP — production | live (`kill_switch_active`, `to_pips`) | Same | — |
| `agent/cli.py` | STALE-REFERENCE | `pyproject.toml::[project.scripts] eurusd-agent` | Still works for `live`; needs the `multi-agent` subcommand once strikers exist | Project-script name is `eurusd-agent` (stale repo name); maps `alphas` → `scripts.evaluate_alphas` which is itself a stub; `evaluate` / `alphas` / `smoke` subcommands rebuild-target the v2-reset rebuild that never landed |

#### `agent/alphas/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/alphas/__init__.py` | KEEP — shared infrastructure | concept alphas, tests | Same; exports `Alpha`, `AlphaContext`, `AlphaSignal` |  |
| `agent/alphas/base.py` | KEEP — production | live (`SignalLoop`), every alpha, every backtest | Same; M001 strikers will subclass `Alpha` or use `AgentProposal` per `03-architecture-v0-sketch.md` | The `Alpha` ABC is the contract M001's Isagi v1 will inherit |
| `agent/alphas/zone_routing.py` | KEEP — production | `router_wiring`, `tests/test_zone_routing.py` | Stays; under M001 the router becomes one of N striker entry points | Evidence-locked routing table; contract test in place |
| `agent/alphas/backtest.py` | KEEP — shared infrastructure | every `scripts/run_*.py`, `tests/test_*` | Same; M001 strikers will need the same chunked harness for offline runs |  |
| `agent/alphas/grid.py` | KEEP — shared infrastructure | ablation/walk-forward scripts + tests | Same; M001 Φ4 fusion sweep will reuse the ablation cell harness |  |
| `agent/alphas/allocator.py` | ARCHIVE — superseded | `scripts/evaluate.py` only (and `tests/test_alphas.py`) | Will be REPLACED by the M001 Bates–Granger / risk-parity allocator (F1–F3) | Single live caller is the stub `evaluate.py`; under M001 this is the wrong abstraction (F2/F3 vs naive Sharpe-weight) |
| `agent/alphas/reaction_alpha.py` | ARCHIVE — historical | `scripts/run_live.py` only via `--alpha reaction` escape hatch; `scripts/evaluate.py`; `tests/test_alphas.py` | None; M001 doctrine treats this as a candidate for one of the strikers but rewriting from scratch | `run_live.py` explicitly tags it as "UNVALIDATED experimental ReactionAlpha — never use it on a funded account" |
| `agent/alphas/concepts/__init__.py` | STALE-REFERENCE | concept tests, `run_zone_all_tfs.py`, `run_holdout_validation.py`, `run_ablation.py` | KEEP after textual update | Docstring still narrates v1/v2/v3/v4 cuts (LZI / FVG / momentum / sweep) but the registry now has exactly one entry; the history is fine to keep but should reference `docs/00-journey.md` rather than re-narrate |
| `agent/alphas/concepts/zone_alpha.py` | TRANSITION | live router, contract tests, validation scripts | Becomes the **A1 Isagi v1 seed detector** per `docs/research/multi-agent-ensemble/05-agent-roster-v0.md` | Highest-value transition file: stays in place under v2, gets a header note + future-deprecation flag at Φ6 once it lives inside an M001 striker |
| `agent/alphas/concepts/_htf.py` | KEEP — production | `zone_alpha`, `tests/test_htf_bias.py` | Same; M001 Isagi v1 needs the same HTF-bias helper |  |

#### `agent/backtest/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/backtest/metrics.py` | KEEP — shared infrastructure | every `run_*.py`, `grid.py`, FDR tests, M001 will need it for TQS computation | Same | Houses `compute_metrics`, `bootstrap_ci`, `benjamini_hochberg`, etc. — the validation gauntlet's calculator |

#### `agent/context/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/context/__init__.py` | ARCHIVE — superseded | nobody (re-exports HTFAnalyzer) | None | Only re-exports types that the live loop's `signal_loop.py` docstring lists as **burned** (`HTFAnalyzer`) |
| `agent/context/htf_context.py` | ARCHIVE — superseded | `tests/test_htf_context.py` (the test still exists), indirectly `htf_draws.py` (and the dead `reaction_alpha`) | None; M001 Aoshi (vol-event) will build its own HTF read | 950+ LoC v1 multi-timeframe analysis engine; `signal_loop.py` docstring explicitly calls out HTFAnalyzer as burned |
| `agent/context/htf_draws.py` | ARCHIVE — superseded | `agent/alphas/reaction_alpha.py` (only when `use_htf_draws=True`, never wired), `tests/test_htf_draws.py` | None | Causal deep-zone precompute for the dead `ReactionAlpha.use_htf_draws` branch |

#### `agent/data/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/data/loader.py` | KEEP — shared infrastructure | every script that touches parquet | Same | `BarLoader` + `df_to_bars` |
| `agent/data/source.py` | KEEP — shared infrastructure | `loader.py` (factory) | Same |  |
| `agent/data/dukascopy.py` | KEEP — shared infrastructure | lazy-imported by `source.py` when `prefer="dukascopy"` | Same; M001 will reuse the same ingestion pipeline |  |
| `agent/data/synthetic.py` | KEEP — shared infrastructure | `scripts/smoke_test.py` | Same | OHLC random-walk generator for tests |
| `agent/data/csv_import.py` | DELETE — dead code | nobody | None | No `from agent.data.csv_import` anywhere; safe to drop after a tag-then-delete |

#### `agent/detectors/`

The whole battery is run on every closed bar by `agent/rules/engine.py::precompute`,
even though only `zones` and `swings` are read at the alpha level. Until
`precompute` is slimmed (out of scope for this audit), all eight precompute
detectors are KEEP — production. Detectors NOT in precompute and not
referenced elsewhere are dead.

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/detectors/swings.py` | KEEP — production | precompute + several detectors | Same | First-class primitive |
| `agent/detectors/bos.py` | KEEP — production | precompute, tests | Same; M001 Chigiri breakout will read BOS | — |
| `agent/detectors/daily_levels.py` | KEEP — production | precompute, target ladder, reaction engine | Same |  |
| `agent/detectors/fvg.py` | KEEP — production | precompute, tests | Same; M001 Bachira may read FVGs | No alpha currently consumes the precomputed list, but it's still computed every bar |
| `agent/detectors/liquidity_sweep.py` | KEEP — production | precompute (M1–H1 only), tests | Same; M001 Isagi may read sweeps | — |
| `agent/detectors/sessions.py` | KEEP — production | precompute, zone detector, multiple alphas | Same |  |
| `agent/detectors/trendlines.py` | KEEP — production | precompute, tests | Same; M001 Chigiri / Yukimiya may read trendlines |  |
| `agent/detectors/zones.py` | KEEP — production | precompute, `SupplyDemandAlpha`, target ladder | Same; M001 Isagi v1 seed | The flagship detector |
| `agent/detectors/atr.py` | DELETE — dead code | nobody | None | 24-line file, no `from agent.detectors.atr` anywhere; ATR is recomputed inline in `rules/engine.precompute` |
| `agent/detectors/fib.py` | ARCHIVE — superseded | `scripts/smoke_test.py` only | None; `FibAlpha` was retired in v3 cuts per `agent/rules/engine.py` docstring | 380 LoC, only consumed by a soon-to-be-stale smoke test |
| `agent/detectors/liquidity_magnet.py` | ARCHIVE — superseded | dead `reaction_alpha`, dead `reaction.engine`, `tests/test_liquidity_magnet.py` | None; M001 may resurrect under a different name | ERL/IRL magnets are quarantined in `agent/config.py::ReactionConfig.liquidity_magnet_enabled = False` |
| `agent/detectors/liquidity_zones.py` | DELETE — dead code | nobody (LZI lineage burned in reset) | None | 500+ LoC, the v1 LZI two-phase choreography; `agent/rules/engine.py` docstring confirms `ctx.liquidity_zones` was removed |
| `agent/detectors/pd_array.py` | ARCHIVE — superseded | dead `reaction.engine` only | None | Reaction-engine accessory |
| `agent/detectors/range_phase.py` | DELETE — dead code | nobody (`ctx.range_phases` confirmed burned) | None | Self-imports from `daily_levels` / `sessions` but nothing imports it |

#### `agent/journal/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/journal/chart_snapshot.py` | KEEP — production | `agent/journal/vault.py` | Same; M001 Ego coach will read these for the daily debrief | — |
| `agent/journal/resolver.py` | KEEP — production | `scripts/resolve_near_misses.py`, `tests/test_vaults.py` | Same; M001 Φ3 will reuse for hypothetical-trade scoring |  |
| `agent/journal/target_ladder.py` | KEEP — production | `SignalLoop`, `scripts/report_target_ladders.py`, tests | Same; M001 strikers reuse the rung definitions | — |
| `agent/journal/vault.py` | KEEP — production | `SignalLoop`, `scripts/run_live.py`, scoring scripts | Same; M001 promotes to `opponents/kaiser_proposals.jsonl` + `loki_proposals.jsonl` per charter |  |
| `agent/journal/db.py` | ARCHIVE — superseded | `scripts/smoke_test.py` only | None; M001 uses JSONL + state.json sidecar, not SQLite | The v2-reset trimmed `Journal` to four tables but nothing live uses them; the only caller is the stale smoke test |
| `agent/journal/live_journal.py` | ARCHIVE — superseded | nobody | None; replaced by the daily log + vault JSONL stack | 707 lines, zero imports. The docstring is still pristine and ambitious; reality is that nothing calls it |

#### `agent/live/`

All ten files are in the live VM's hot path; do not move any of them.

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/live/__init__.py` | KEEP — production | external callers | Same |  |
| `agent/live/broker.py` | KEEP — production | live | Same; M001 strikers all share one broker session |  |
| `agent/live/config.py` | KEEP — production | live | Same; will gain striker-pool config |  |
| `agent/live/monitor.py` | KEEP — production | live | Same |  |
| `agent/live/position_sizer.py` | KEEP — production | live | Same; M001 Ego coach delegates final sizing here after applying allocator weights |  |
| `agent/live/router_wiring.py` | KEEP — production | `run_live` | Same; the router becomes a striker source under M001 |  |
| `agent/live/signal_loop.py` | KEEP — production | `run_live` | Same; M001 wraps the loop with the Allocator → Aggregator → Risk Conductor stack per `03-architecture-v0-sketch.md` | Docstring still references burned v1 internals (`StrategyRouter`, `GATE_PROFILES`, `MLConfig.scorer_paths`, `HTFAnalyzer`, `PerformanceMemory`, MQL5 overlay drawer) as a contrast; leave as historical context |
| `agent/live/soft_stop.py` | KEEP — production | live | Same |  |
| `agent/live/state_store.py` | KEEP — production | live | Same; M001 will extend with per-striker state |  |
| `agent/live/trade_events.py` | KEEP — production | live | Same |  |

#### `agent/news/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/news/__init__.py` | ARCHIVE — superseded | nobody | None |  |
| `agent/news/calendar.py` | ARCHIVE — superseded (STALE-REFERENCE) | only `blackout.py` (also dead) | M001 A9 Aoshi (vol-event) will need event awareness, but should build its own ingestion | The v0.14 rename touched only the User-Agent string in this file; everything else is unchanged and unused |
| `agent/news/blackout.py` | ARCHIVE — superseded | nobody (`signal_loop.py` does not consult it) | None |  |

#### `agent/notifications/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/notifications/__init__.py` | KEEP — shared infrastructure | re-exports | Same |  |
| `agent/notifications/telegram.py` | KEEP — production | `SignalLoop`, `PositionMonitor` | Same; M001 strikers share one notifier instance |  |

#### `agent/reaction/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/reaction/__init__.py` | ARCHIVE — historical | `reaction_alpha.py` only (and the package itself) | None | Doc 04 ("Reaction Engine") is HISTORICAL per overview status banner |
| `agent/reaction/components.py` | ARCHIVE — historical | `reaction/engine.py`, `tests/test_reaction_engine.py` | None |  |
| `agent/reaction/engine.py` | ARCHIVE — historical | `reaction_alpha.py`, `tests/test_reaction_engine.py` | None | 500+ LoC; alive only inside the `--alpha reaction` escape hatch |

#### `agent/regime/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/regime/__init__.py` | DELETE — dead code | nobody | None |  |
| `agent/regime/detector.py` | DELETE — dead code | nobody | None; M001 A5 Reo will be the regime adapter, but as a clean re-implementation per `05-agent-roster-v0.md` | 227 LoC; zero imports outside its own `__init__.py` |

#### `agent/risk/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/risk/manager.py` | KEEP — production | live | Same; M001 Risk Conductor sits ABOVE this, doesn't replace it |  |
| `agent/risk/post_loss_guard.py` | KEEP — production | live | Same; M001 A10 Kunigami (anti-tilt) is a richer layer atop the same primitive |  |
| `agent/risk/sizing.py` | KEEP — production | `risk/manager.py` (live, transitively) | Same | Confusingly named — easily mistaken for legacy because `live/position_sizer.py` exists. It is the FINAL min-lot / pct-floor check before the conviction-scaled sizer runs |

#### `agent/rules/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `agent/rules/engine.py` | KEEP — production | live (`precompute`), every backtest | Same; should be slimmed but only after `tests/test_*` are updated | Single source of truth for which detectors run on every closed bar |

### §2.2 `scripts/`

Three eras visible: v2 era operational scripts (`run_live`, `daily_summary`,
`resolve_near_misses`, `report_target_ladders`), v2 validation gauntlet
(`run_walk_forward`, `analyze_walk_forward`, `run_holdout_validation`,
`run_cross_pair_frozen`, `run_zone_all_tfs`, `run_ablation`,
`download_data`), and v2-reset rebuild stubs that never landed
(`evaluate`, `evaluate_alphas`, `smoke_test`). The validation gauntlet is
explicitly load-bearing for M001 Φ4 (`charter §G5: every fusion mechanism
and every agent passes the same evidence bar as zone_d1_against`).

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `scripts/run_live.py` | KEEP — production | the VM | Same; M001 Φ6 will rewire to a strikers entry point |  |
| `scripts/daily_summary.py` | KEEP — production | operator | Same; M001 Ego coach will consume the summary | Auto-saves to `{log-dir}/summaries/` |
| `scripts/resolve_near_misses.py` | KEEP — production | operator | Same; M001 Ego coach reads vault outputs |  |
| `scripts/report_target_ladders.py` | KEEP — production | operator | Same |  |
| `scripts/download_data.py` | KEEP — shared infrastructure | operator + validation harness | Same; M001 ingestion pipeline reuses it |  |
| `scripts/run_walk_forward.py` | KEEP — shared infrastructure | validation gauntlet | Same; M001 Φ4 reuses the rolling-window harness | Named generically enough to host non-zone strategies |
| `scripts/analyze_walk_forward.py` | KEEP — shared infrastructure | validation gauntlet | Same |  |
| `scripts/run_holdout_validation.py` | KEEP — shared infrastructure | validation gauntlet | Same |  |
| `scripts/run_cross_pair_frozen.py` | KEEP — shared infrastructure | validation gauntlet | Same; M001 frozen-transfer gate for new strikers |  |
| `scripts/run_zone_all_tfs.py` | KEEP — shared infrastructure (STALE-REFERENCE) | one-shot grid runner | Per-concept variant of the same harness | Name is zone-specific; a future M001 striker grid script may live beside it under a generic name |
| `scripts/run_ablation.py` | KEEP — shared infrastructure | validation gauntlet | Same; M001 ablation runs reuse it | Already concept-agnostic via `ALL_CONCEPT_ALPHAS` |
| `scripts/evaluate.py` | ARCHIVE — superseded (STALE-REFERENCE) | `evaluate_alphas.py`, `agent/cli.py` (`evaluate` subcommand) | None | Docstring still claims to be the v2 "rebuild target" wiring the 224-cell grid; in practice the grid lives in `run_zone_all_tfs.py` + `run_ablation.py`. The only thing this script tests is `ReactionAlpha` |
| `scripts/evaluate_alphas.py` | ARCHIVE — superseded | `agent/cli.py` (`alphas` subcommand) | None | One-line stub: `from scripts.evaluate import main` |
| `scripts/smoke_test.py` | TRANSITION (STALE-REFERENCE) | `agent/cli.py` (`smoke` subcommand) | Useful as a Φ3 pre-flight; needs rewrite to not import `journal.db`, `detectors.fib` | Imports four archive-candidate modules at top of file; would block their removal |
| `scripts/deploy_windows.ps1` | STALE-REFERENCE | linked from `docs/08-live-trading-and-deployment.md` (current) | Same operator flow under M001 | Header still says "EURUSD AI Agent"; PowerShell URL still points at `TheFinix13/Trading_AI_model` (the v0.14 rename only moved the local folder) |

### §2.3 `tests/`

Total: 30 test files. The v2 reset claimed 114 tests, the live agent now
reports 349 — most growth is in `test_state_store.py`, `test_vaults.py`,
`test_target_ladder.py`, `test_trade_events.py`, `test_daily_summary.py`.
Six tests still cover modules categorised ARCHIVE-superseded or
ARCHIVE-historical above; archiving the production code without archiving
the matching test would surface as 50+ failures.

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `tests/test_state_store.py`, `test_vaults.py`, `test_target_ladder.py`, `test_trade_events.py`, `test_daily_summary.py`, `test_heartbeat_logging.py`, `test_live_router_wiring.py`, `test_run_live_cli.py`, `test_zone_routing.py`, `test_position_sizer.py`, `test_risk_manager.py`, `test_post_loss_guard.py` | KEEP — production | pytest | Same |  |
| `tests/test_htf_bias.py`, `test_swings.py`, `test_fvg.py`, `test_metrics.py`, `test_fdr.py`, `test_eval_protocol.py`, `test_per_tf_costs.py`, `test_ablation_grid.py`, `test_sizing.py`, `test_concept_alphas.py` | KEEP — shared infrastructure | pytest | Same; M001 ablation reuses |  |
| `tests/test_alphas.py` | TRANSITION | pytest | Splits in two under M001 | Currently mixes `Alpha` base smoke + `ReactionAlpha` + `allocator`; the base smoke stays, the ReactionAlpha / allocator parts archive with their production modules |
| `tests/test_bos_speedup.py` | TRANSITION | pytest | Same | BOS detector stays under precompute; the speedup regression test stays |
| `tests/test_liquidity_sweep_speedup.py` | TRANSITION | pytest | Same | Detector stays; the alpha that consumed it (FVG/liquidity-sweep alpha) was retired |
| `tests/test_htf_context.py` | ARCHIVE — superseded | pytest | None | 600+ LoC against burned `HTFAnalyzer` |
| `tests/test_htf_draws.py` | ARCHIVE — superseded | pytest | None | Against burned `htf_draws.py` |
| `tests/test_liquidity_magnet.py` | ARCHIVE — superseded | pytest | None | Against the reaction-era magnet detector |
| `tests/test_reaction_engine.py` | ARCHIVE — historical | pytest | None | Reaction doc is HISTORICAL; alpha is unvalidated escape hatch |

### §2.4 `docs/`

Three eras + the M001 R&D drop. The numbered docs' status banners are
explicit, but `01/02/04/07/09/10` (HISTORICAL) live at `docs/` root rather
than under `docs/archive/`, which is the actual confusing part. Doc
status by banner is taken from `docs/00-overview.md §"Numbered docs —
status key"`.

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `docs/00-overview.md`, `docs/00-journey.md`, `docs/CHECKPOINT.md`, `docs/ROADMAP.md`, `docs/08-live-trading-and-deployment.md` | KEEP — production | every fresh chat | Same; CHECKPOINT will gain a Φ-phase section once Φ1 lands |  |
| `docs/01-strategy-architecture.md` | ARCHIVE — historical | linked from `00-overview` | None | Move to `docs/archive/01-strategy-architecture.md` and update the index |
| `docs/02-strategies.md` | ARCHIVE — historical | linked from `00-overview` | None | Move to `docs/archive/` |
| `docs/04-reaction-engine.md` | ARCHIVE — historical | linked from `00-overview` | None | Move to `docs/archive/` |
| `docs/07-backtesting.md` | ARCHIVE — historical | linked from `00-overview` | None | Move to `docs/archive/` |
| `docs/09-dashboard.md` | ARCHIVE — historical | linked from `00-overview` | None | Dashboard was fully burned in the reset; doc is a record of what was |
| `docs/10-quant-validation-and-modular-overhaul.md` | ARCHIVE — historical | linked from `00-overview` | None | The plan that LED to the reset; superseded |
| `docs/03-htf-context-and-pattern-mechanics.md` | STALE-REFERENCE | linked from `00-overview` | Same after rewrite | Detector mechanics still exist in code, v1 audit framing does not. Rewrite in place |
| `docs/05-position-sizing-and-risk.md` | STALE-REFERENCE | linked from `00-overview` | Same after rewrite | Sizer + guards + soft-stop are current; the v1 study sections must be split out or labelled |
| `docs/06-learning-journal.md` | STALE-REFERENCE | linked from `00-overview` | Same after rewrite | Per-day journal survives; "performance memory" (LLM-extracted) was burned. The doc references `agent/journal/live_journal.py` which itself is dead |
| `docs/archive/` (20 files + README) | KEEP — production | historical lookup | Same | The right destination for the six HISTORICAL banners above. Already curated with a README + provenance table |
| `docs/audit/README.md` | KEEP — production | the reset record | Same | The single sanctioned narrative of what was kept / burned |
| `docs/reports/trading_agent_research_report.{tex,pdf,aux,log,out}` | TRANSITION | external deliverable | Same | LaTeX source + build artefacts. .aux/.log/.out are already in `.gitignore` patterns; verify they aren't actually tracked |
| `docs/reports/BUILD.md` | KEEP — production | builder | Same | Build instructions — tiny |
| `docs/research/multi-agent-ensemble/` (8 files) | KEEP — shared infrastructure | future M001 strikers | The M001 R&D track itself | **IN-FLIGHT MIGRATION** — another worker is actively editing files here (00 charter v0.2 today, 04 quant foundations v0.2 today, 05 roster v0.2 today, 06 doctrine v0.1 today). Audit does not touch this folder. |
| `docs/reviews/` (4 reviews + raw JSON) | KEEP — production | evidence ledger | Same; M001 evidence flows here too per `README.md §"How this folder relates"` | Per `CHECKPOINT.md §"THE ROUTINE"`: "never delete or edit old reviews — they are the evidence record" |
| `docs/runbooks/vmware-windows.md` | KEEP — production | operator | Same |  |
| `docs/.DS_Store` | DELETE — generated / ephemeral | macOS Finder | None | Should be added to repo-level `.gitignore` (currently only matched if `.DS_Store` is at root) — actually it is matched, just not on disk |

### §2.5 `config/`, `data/`, `fixtures/`, `models/`, `tmp/`, `mt5/`

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `config/default.yaml` | KEEP — production | `agent.config.load_config` | Same; M001 will extend | Stale fields possible: `detectors.fib_levels`, `liquidity_wick_min_ratio` aren't consumed by surviving detectors. STALE-REFERENCE candidate, not blocking |
| `data/parquet/*.parquet` (15 files, ~33 MB) | KEEP — shared infrastructure | every script + live | Same; M001 will need them | The audit record explicitly preserved this directory as "the only irreplaceable artefact." `data/` is gitignored, files exist locally only |
| `fixtures/sample_week.txt` | STALE-REFERENCE | only `docs/archive/{trading_partner,roadmap}.md` reference it | None | Old discretionary-trade journal sample; fixtures/ is gitignored anyway |
| `fixtures/news/ff_calendar_sample.xml` | ARCHIVE — superseded | only `agent/news/calendar.py` (itself ARCHIVE) | None | Drops out with the news module |
| `models/` (empty dir) | DELETE — generated / ephemeral | nobody | None | Gitignored. Created lazily by `agent.config.load_config` at startup |
| `tmp/` (empty dir) | DELETE — generated / ephemeral | nobody | None | Gitignored |
| `mt5/README.md` | ARCHIVE — historical | operator (manual) | None | Documents drawing the agent's `agent_drawings.json` output, which was produced by the burned `agent/live/chart_drawer.py` |
| `mt5/TradingPartner_Overlay.mq5` | ARCHIVE — historical | MT5 terminal | None | 15 KB MQL5 overlay; no Python side any more |

### §2.6 Root-level files

| Path | Category | Imported by | Role under M001 | Notes |
|---|---|---|---|---|
| `README.md` | KEEP — production | the world | Same; gets a M001 section at Φ6 | Rewritten under readability-and-clarity rules per `ai_context.md` v0.14 |
| `.gitignore` | KEEP — production | git | Same | Already covers `.env`, `data/`, `models/`, `*.db`, `tmp/`, `.cache/`, `fixtures/`, `*.log`. `.cursor/*` allowlist preserves `.cursor/rules/` |
| `.dockerignore` | STALE-REFERENCE | docker build (which is itself broken) | None until M001 Φ6 | Tied to the broken Dockerfile |
| `.env` | KEEP (gitignored) | live | Same | Contains REAL `GEMINI_API_KEY` and `ANTHROPIC_API_KEY` — properly gitignored, but a fresh `git log -- .env` and `git rev-list --all -- .env` should be sanity-checked to confirm the file was never committed |
| `.env.example` | STALE-REFERENCE | new contributors | None | Title still says "EURUSD AI Agent", advertises Gemini / Anthropic / Ollama for v1 vision/LLM that no longer exists, and omits the real live env vars (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_PATH`, `TG_BOT_TOKEN`, `TG_CHAT_ID` — these are listed in `scripts/run_live.py` docstring) |
| `pyproject.toml` | STALE-REFERENCE | pip / build | KEEP after dep purge | `name = "multi-pair-trading-agent"` is fresh (v0.14), but `[project.scripts] eurusd-agent` is stale. Hard-pinned v1 dependencies with zero production imports: `scikit-learn`, `xgboost`, `joblib`, `shap`, `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `click`, `schedule`, `rich`. Optional `voice` and `cloud-vision` extras are entirely v1. |
| `requirements.txt` | STALE-REFERENCE | VM `pip install -r` | KEEP after dep purge | Mirrors `pyproject.toml`; carries the same dead v1 deps. The VM install would be ~80% smaller without them |
| `Dockerfile` | ARCHIVE — superseded | `docker compose` | None | Hard-codes `CMD ["uvicorn", "agent.dashboard.app:app", "--host", "0.0.0.0", "--port", "8000"]` — `agent.dashboard` was burned in the v2 reset. Image build fails at runtime |
| `docker-compose.yml` | ARCHIVE — superseded | operator | None | References the same broken dashboard image |

## §3 — Action items

Order: lowest VM-risk first.

1. **Move six HISTORICAL numbered docs into `docs/archive/`.** Source:
   `docs/01-strategy-architecture.md`, `02-strategies.md`,
   `04-reaction-engine.md`, `07-backtesting.md`, `09-dashboard.md`,
   `10-quant-validation-and-modular-overhaul.md`. Destination:
   `docs/archive/0{1,2,4,7}-…md`, `docs/archive/09-dashboard.md`,
   `docs/archive/10-quant-validation-and-modular-overhaul.md`. Reason:
   already banner-marked HISTORICAL; living at `docs/` root suggests
   currency they no longer have. Risk: zero — no code or test imports
   docs. Update `docs/00-overview.md` index to point at the new
   locations and update `docs/archive/README.md` provenance table.
2. **Rewrite the three PARTLY-HISTORICAL docs in place.**
   `docs/03-htf-context-and-pattern-mechanics.md`,
   `docs/05-position-sizing-and-risk.md`,
   `docs/06-learning-journal.md`. Reason: each contains active facts
   tangled with v1 framing; status banner is honest but the body is
   confusing. Risk: zero — no code or test imports. Estimated ~2 PRs of
   ~150 lines each.
3. **Fix the deploy-windows installer URL + header.** Source:
   `scripts/deploy_windows.ps1`. Reason: documented one-liner in
   `docs/08-live-trading-and-deployment.md` references a repo path
   (`TheFinix13/Trading_AI_model`) which the v0.14 rename didn't update.
   Risk: low — operator-time only; the VM is already installed.
4. **Update `.env.example`.** Reason: title still says "EURUSD AI
   Agent"; advertises Gemini / Anthropic / Ollama keys for v1 vision
   features that no longer exist; omits the live env vars used by
   `scripts/run_live.py`. Risk: zero — `.env.example` is not consumed
   by any code.
5. **Update `agent/alphas/concepts/__init__.py` docstring.** Reason:
   narrates v1→v4 iteration in detail; should be a one-paragraph pointer
   to `docs/00-journey.md`. Risk: zero — docstring only.
6. **Update `agent/cli.py` to drop stale subcommands and rename script
   entry.** Drop `evaluate` / `alphas` / `smoke` if they're also being
   archived (action 9); rename `eurusd-agent` → `multi-pair-agent`
   (coordinate with anything that installs the wheel). Risk: low —
   updates the `[project.scripts]` entry point.
7. **Add a TRANSITION header note to `agent/alphas/concepts/zone_alpha.py`.**
   Reason: the file's M001 destiny (Isagi v1 seed detector per roster v0)
   is currently only recorded in `docs/research/multi-agent-ensemble/05-agent-roster-v0.md`,
   not in the file's own header. Add a `# UNDER M001 (Φ6+): becomes Isagi
   v1 seed detector — see docs/research/multi-agent-ensemble/05` block
   and a future-deprecation note. Risk: zero — comment only.
8. **DELETE unreferenced dead code (single-PR sweep, tag the SHA first).**
   `agent/data/csv_import.py`, `agent/detectors/atr.py`,
   `agent/detectors/range_phase.py`, `agent/detectors/liquidity_zones.py`,
   `agent/regime/__init__.py`, `agent/regime/detector.py`. Tag-then-delete
   so the git history retains the modules without continuing to ship
   them. Risk: medium — must run full test suite (349) before merging.
9. **ARCHIVE superseded code to `agent/_archive/`** (or repo-level
   `archive/`). One PR each:
   - `agent/_archive/news/` ← `agent/news/`
   - `agent/_archive/context/` ← `agent/context/`
   - `agent/_archive/reaction/` ← `agent/reaction/`
   - `agent/_archive/journal/{db.py,live_journal.py}`
   - `agent/_archive/alphas/{allocator.py,reaction_alpha.py}`
   - `agent/_archive/detectors/{fib.py,liquidity_magnet.py,pd_array.py}`
   - `agent/_archive/scripts/{evaluate.py,evaluate_alphas.py}` (after
     deciding the rebuild target is officially abandoned in favour of
     `run_zone_all_tfs.py` + `run_ablation.py`)
   Also archive the matching tests:
   `tests/_archive/{test_htf_context,test_htf_draws,test_liquidity_magnet,test_reaction_engine}.py`.
   Update `pytest` collection if `_archive/` isn't auto-ignored.
   Risk: medium-high — `scripts/smoke_test.py` imports four of these
   modules (`detectors.fib`, `journal.db`, plus reaction-related via
   `tests/test_alphas.py`). Either rewrite `smoke_test.py` to use only
   surviving primitives, or archive it too. Coordinate a VM update so
   the next `git reset --hard origin/main` still imports cleanly.
10. **Purge dead dependencies from `pyproject.toml` + `requirements.txt`.**
    Drop `scikit-learn`, `xgboost`, `joblib`, `shap`, `fastapi`,
    `uvicorn`, `jinja2`, `python-multipart`, `click`, `schedule`, `rich`,
    optional extras `voice` and `cloud-vision`. Risk: high — must
    coordinate a VM `pip install -r requirements.txt` run; if any of
    these are installed as transitive deps of something we keep, the
    purge will be a no-op there, but if some operator script silently
    imports `click` we will find out only on the VM.
11. **Archive the broken Docker stack.** Move `Dockerfile`,
    `docker-compose.yml`, `.dockerignore` into `archive/docker-v1/` (or
    delete after tag). Reason: image references `agent.dashboard.app`,
    which was burned. Risk: zero on the VM (nothing runs containers
    today). M001 Φ6 may re-introduce a fresh container; that should be
    its own design pass.
12. **Archive `mt5/`.** Move `mt5/{README.md,TradingPartner_Overlay.mq5}`
    to `archive/mt5/`. Reason: the Python side that wrote
    `agent_drawings.json` was burned; the overlay has nothing to read.
    Risk: zero.
13. **`fixtures/news/ff_calendar_sample.xml`.** Delete (it's gitignored
    locally only) or archive with the news module. Risk: zero.

## §4 — Risks and blockers

### What could break the live VM if executed

- **Removing any precompute detector.** Even `fvg.py` and
  `liquidity_sweep.py` look unused at the alpha level, but
  `agent/rules/engine.py::precompute` runs them on every closed bar. The
  VM would crash at first bar close.
- **Renaming `agent/risk/sizing.py`.** Both sizers (`risk.sizing` and
  `live.position_sizer`) are live; `manager.py::evaluate()` calls
  `sizing.position_size()` as the final gate. Pre-move grep on
  `position_size(` is mandatory.
- **Dependency purge.** The VM does `pip install -r requirements.txt` on
  every update; if a purged package was being used as a transitive lock,
  we won't know until the install. Recommend a staged purge: comment-out
  in PR 1, observe one VM cycle, remove in PR 2.
- **`agent/cli.py` rename.** The `[project.scripts] eurusd-agent` entry
  point is the only way the package exposes a CLI; renaming it is a
  breaking change for any operator who shelled into the venv.

### What requires git-history care (tag-then-move vs straight delete)

- **Tag-then-delete** for genuinely unreferenced files (`atr.py`,
  `csv_import.py`, `range_phase.py`, `liquidity_zones.py`,
  `agent/regime/`). Create a lightweight tag `pre-cleanup-2026-06-24`
  pointing at the audited SHA so the modules are easy to retrieve.
- **Move-then-commit** for ARCHIVE items so `git log --follow` keeps the
  history attached to the new path.
- **In-place rewrite** for STALE-REFERENCE so blame stays clean.

### What the M001 migration worker is currently touching

The `docs/research/multi-agent-ensemble/` folder is being actively
written by another worker. Today's edits (all 2026-06-24) cover:
`00-charter.md` (v0.2 — added Blue Lock doctrine references), `04-quant-foundations.md`
(v0.2 — F11–F14), `05-agent-roster-v0.md` (v0.2 — Blue Lock cast),
`06-blue-lock-doctrine.md` (v0.1 — new), `README.md` (doc index sync).
Nothing else in the repo is on that worker's path; this audit's
recommendations do not touch the folder.

The `multi-agent-ensemble` folder is **doctrine-only**: per the charter
(`00-charter.md §"Phases"`), agent code lands at `experiments/multi_agent/`
**to be created** at Φ3, and graduates to `agent/multi/strikers/<id>.py`
**at Φ6**. We are at the start of Φ0. So no M001 Python code exists in
this repo yet — there is no risk that an archive move collides with
in-flight striker work.

## §5 — Recommended sequencing

### Wave 1 — Docs-only (zero VM risk)

Files: action items 1, 2, 4, 5, 7 from §3.

- Move 6 numbered HISTORICAL docs to `docs/archive/` and update the
  `docs/00-overview.md` index + `docs/archive/README.md` table.
- Rewrite 3 PARTLY-HISTORICAL docs in place (`docs/03`, `docs/05`,
  `docs/06`).
- Refresh `.env.example` to match `scripts/run_live.py`'s env-var contract.
- Trim the `agent/alphas/concepts/__init__.py` docstring to a pointer.
- Add the M001 TRANSITION header to `agent/alphas/concepts/zone_alpha.py`.

PR size: ~4 PRs, < 250 lines diff each.

### Wave 2 — Stale references (low risk, operator-time only)

Files: action items 3, 6.

- `scripts/deploy_windows.ps1` URL + title.
- `agent/cli.py` subcommand list + `[project.scripts]` rename.
- Sanity-check `git log -- .env` confirmed clean (one-line operation).

PR size: 1 PR, < 80 lines.

### Wave 3 — Code archiving (VM coordination required)

Files: action items 8, 9, 10, 11, 12, 13.

- DELETE-dead sweep (action 8).
- ARCHIVE-superseded sweep (action 9), including matching tests.
- Dependency purge (action 10).
- Docker / MT5 archive (actions 11, 12).
- Fixture cleanup (action 13).

PR size: 3–5 PRs total, ~1500 lines moved/deleted in aggregate.

VM coordination steps before merging Wave 3:

1. Tag the pre-cleanup SHA: `git tag pre-cleanup-2026-06-24 6f1cc75`.
2. Run the full 349-test suite locally and on the VM after each PR
   (`.venv/bin/python -m pytest tests/`).
3. Stop the three VM PowerShell processes, run the documented update
   one-liner (`git fetch && git reset --hard origin/main && pip install
   -r requirements.txt`), restart, verify `[TRADE OPENED]` and
   `[LADDER]` lines on next fill per the
   `ai_context.md §"VM steps"` checklist.

## §6 — Items needing parent decision

1. **Should the rebuild-target scripts (`scripts/evaluate.py`,
   `scripts/evaluate_alphas.py`) be archived or rebuilt?** They were the
   v2-reset "rebuild target" that never materialised; the 224-cell grid
   ended up in `run_zone_all_tfs.py` + `run_ablation.py` instead. They
   still appear in `agent/cli.py::COMMANDS`. **What I tried:** read both
   scripts; only consumer is `agent/cli.py`. **What would unblock:**
   confirm the rebuild target is officially abandoned (then archive +
   drop CLI subcommands) versus a future M001 deliverable (then keep,
   re-target to the striker grid).
2. **Is `agent/alphas/allocator.py` the future M001 allocator, or
   doomed?** It implements a Sharpe-correlation-aware weight scheme; the
   M001 charter (`04-quant-foundations.md` F1–F3) prescribes
   Bates–Granger / risk parity / HRP, which is strictly broader. Today
   only `scripts/evaluate.py` calls it. **What I tried:** read the file;
   read F1–F3 in the foundations doc. **What would unblock:** confirm
   whether F1–F3 will subsume or coexist with the current allocator.
   Archive if subsumed; STALE-REFERENCE (with header note) if coexist.
