# V2 reset — audit + execution summary

The v1 codebase was audited end-to-end against four buckets — KEEP-INFRA,
KEEP-PERCEPTION, REDUCE, BURN — and reset on 2026-06-09. This file is the
single surviving record of what landed; the seven per-area subagent reports
(`01-detectors.md` … `07-core-data-scripts-tests-artefacts.md`) plus the
synthesis deliverables (`preservation_list.md`, `redundancy_map.md`) have been
collapsed into this README to keep maintenance cheap.

## Why we reset

The Phase A/B/C/D evaluations told us the same story four times:

- only one alpha (`reaction + ERL/IRL`) showed measurable edge,
- every elaboration on top of it (partial scaling, deep HTF draws, multi-
  position) was net-neutral-to-negative on the locked dev span,
- the codebase had accumulated overlapping detectors, fitted gate profiles,
  trained scorers, and dev-span-shaped configs that bias every future test.

The v2 reset trades that pile for per-strategy isolation, a 224-cell ablation
grid (7 strategies × 8 timeframes × 4 session buckets), realistic per-TF
costs, FDR-controlled scorecards, and a Stage-2 contextual-clustering loop in
place of failure-driven combo search.

## Five critical bugs fixed first

| # | Where | What it was | Fix |
|---|---|---|---|
| 1 | `agent/detectors/fvg.py` | `_update_fill_tracking` scanned the full series, leaking future fill state into any back-test that read `ctx.fvgs` | `detect_fvgs` now accepts `up_to_index`; the alpha backtester additionally runs `_CausalFVGTracker` to re-derive state one bar at a time. |
| 2 | `agent/detectors/trendlines.py` | `_validate` precomputed `tl.valid` using all bars | Removed `_validate`; added a causal `is_valid_at(tl, bars, at_index)` helper. |
| 3 | `agent/detectors/liquidity_sweep.py` | `_wait_for_reverse` filtered the detector batch by future reversal (survivor bias) | `detect_liquidity_sweeps` defaults to fully-causal; a per-bar `confirm_reversal_at` helper is exposed for strategies that need it. |
| 4 | `agent/news/blackout.py` | `is_all_day_blackout` returned `False` regardless of input | Function deleted. |
| 5 | `agent/backtest/metrics.py` | Sharpe annualised per-trade PnL with a 252-day factor | Replaced with a daily-equity-curve Sharpe (`_daily_equity_sharpe`). |

Plus three numeric resets to neutral priors:

- `ReactionConfig.conviction_threshold` 0.50 → 0.40
- `HTFConfig.htf_alignment_boost` / `htf_misalignment_penalty` → 0.0
- `ReactionConfig.session_aware` → False + `_session_bias` removed
  (session is now an explicit ablation AXIS, not a built-in conviction
  modifier)

## What survives — the v2 roster

### `agent/` (package layout)

```
agent/
  alphas/        base.py, backtest.py, allocator.py, reaction_alpha.py
  backtest/      metrics.py   (compute_metrics, bootstrap_ci, make_scorecard,
                                scorecard_by_session, MIN_TRADES_FOR_EDGE)
  context/       htf_context.py, htf_draws.py
  data/          loader.py, source.py, dukascopy.py, csv_import.py, synthetic.py
  detectors/     atr.py, bos.py, daily_levels.py, fib.py, fvg.py,
                 liquidity_magnet.py, liquidity_sweep.py, liquidity_zones.py,
                 pd_array.py, range_phase.py, sessions.py, swings.py,
                 trendlines.py, zones.py
  journal/       db.py        (signals / trades / equity / model_versions only)
                 live_journal.py (per-day markdown + JSONL roll-up)
  live/          broker.py, config.py, monitor.py, position_sizer.py,
                 signal_loop.py, soft_stop.py
  news/          blackout.py, calendar.py
  notifications/ telegram.py
  reaction/      components.py, engine.py
  regime/        detector.py
  risk/          manager.py, post_loss_guard.py, sizing.py
  rules/         engine.py    (PrecomputedContext + precompute only)
  cli.py, config.py, types.py, utils.py
```

### `scripts/`

| Script | Purpose |
|---|---|
| `download_data.py` | Primary data ingestion (use `--source dukascopy` for >2y spans). |
| `evaluate.py` | V2 alpha evaluation over the locked dev span (rebuild target — wires the 224-cell grid as it lands). |
| `evaluate_alphas.py` | Thin wrapper around `evaluate.py` reserved for the alpha-grid entry point. |
| `run_live.py` | V2 live loop launcher (paper / MT5 / Exness). |
| `smoke_test.py` | Offline E2E synthetic CI gate. |

### `tests/` (114 tests, all green)

`test_alphas.py`, `test_eval_protocol.py`, `test_fvg.py`,
`test_htf_context.py`, `test_htf_draws.py`, `test_liquidity_magnet.py`,
`test_metrics.py`, `test_position_sizer.py`, `test_post_loss_guard.py`,
`test_reaction_engine.py`, `test_risk_manager.py`, `test_sizing.py`,
`test_swings.py`.

## What was burned

### Packages (whole-directory deletes)

`agent/strategy/`, `agent/optimizer/`, `agent/ranking/`,
`agent/execution/`, `agent/features/`, `agent/discovery/`,
`agent/dashboard/`, `agent/conversation/`, `agent/model/`, `agent/llm/`,
`agent/analysis/`.

### Files

`agent/alphas/registry.py`, `agent/alphas/strategy_alpha.py`,
`agent/alphas/portfolio_backtest.py`, `agent/backtest/engine.py`,
`agent/backtest/multi_tf.py`, `agent/backtest/discoverer_runner.py`,
`agent/backtest/walkforward.py`, `agent/detectors/fvg_retest.py`,
`agent/detectors/zone_retest.py`, `agent/detectors/liquidity.py`,
`agent/journal/performance_memory.py`, `agent/live/explainer.py`,
`agent/live/chart_drawer.py`, `agent/risk/portfolio.py`,
`agent/risk/managed_exit.py`, `agent/rules/htf_bias.py`,
`agent/rules/news_filter.py`.

### Scripts

`diagnose_live.py`, `run_learning_backtest.py`, `simulate_week.py`,
`run_confluence_optimizer.py`, `validate_fvg_quality.py`, `run_multitf.py`,
`train_lzi_scorer.py`, `run_rankings.py`, `ingest_docx.py`,
`retrain_scorers.py`, `train_scorer.py`, `walk_forward.py`,
`retrospective.py`, `ask.py`, `teach.py`, `journal_query.py`, `iterate.py`,
`explain.py`, `analyze_losses.py`, `check_gate.py`, `visual_sanity.py`,
`weekly_retrain.py`, `train_model.py`, `run_backtest.py`, `extract_docx.py`,
`import_csv.py`, `import_backtest_journal.py`, `notify_telegram.py`,
`audit_detectors.py`.

### Config (`agent/config.py`)

`GateProfile`, `GATE_PROFILE_DEFAULT`, `GATE_PROFILE_LZI`, `GATE_PROFILE_FVG`,
`GATE_PROFILE_SD_ZONE`, `GATE_PROFILES`, `RulesConfig`, `MLConfig`,
`RankingConfig`, `LiquidityConfig`, `LiveTradingConfig`, `DemoConfig`,
`BacktestGateConfig`.

### Live config (`agent/live/config.py`)

`mode`, all `portfolio_*` fields, `min_room_rr`.

### Dev-span artefacts (~300 MB)

19 SQLite back-test DBs under `data/`, the root `journal.db`,
`data/journal/` (78 MB of back-test / archive logs), `data/optimizer/`,
`data/rankings/`, `data/chart_screenshots/`, the 2 LZI training CSVs, every
`models/*.joblib` (8 fitted scorers + the discoverer model),
`models/iterate_summary.json`, `models/last_retrain.json`. **`data/parquet/`
(~16 MB) was preserved** — it is the only irreplaceable artefact.

## Verified end-state

```
$ .venv/bin/python -m pytest tests/ -q
114 passed in ~1.1s

$ PYTHONPATH=. .venv/bin/python scripts/smoke_test.py
detectors → 594 swings / 34 bos / 244 fvgs / 10 zones / 0 trendlines
v2 alpha backtest → 361 closed trades, scorecard "noise" (synthetic)
journal → 5 trades logged
OK
```

## Recommended next step

The 224-cell ablation grid (7 strategies × 8 timeframes × 4 sessions) plugs
in via `scripts/evaluate.py::_default_alphas` and the chunked harness already
in `agent/alphas/backtest.py`. The reaction alpha is the v2 baseline; the
remaining six concepts (liquidity, BOS, S/D, FVG, orderblocks, momentum, fibs)
re-introduce themselves through the same `Alpha` interface.
