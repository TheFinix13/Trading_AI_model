# 00 — Overview & Documentation Index

**Current system (2026-06-10):** the agent trades the **validated zone-fade
strategy** (`zone_d1_against`) through a multi-symbol deployment router —
EURUSD/GBPUSD/USDCAD on H4 — after a full reset, single-concept ablation, and a
walk-forward + frozen cross-pair validation gauntlet. Start here:

| Doc | What's inside |
|---|---|
| **[00-journey.md](00-journey.md)** | **The full narrative** — v1 multi-concept era → reset → ablation funnel → zone-only → validation gauntlet → multi-symbol deployment. Diagrams included. |
| **[CHECKPOINT.md](CHECKPOINT.md)** | **Current-state snapshot** — deployed cells, evidence, validation gates, parked work, the checkpoint routine. |
| [audit/README.md](audit/README.md) | The v2 reset record — what was kept, what was burned, why. |
| [reviews/](reviews/) | Dated evidence record (walk-forward, cross-pair tests, week reviews). Never deleted. |

## Numbered docs — status key

Most numbered docs below describe the **v1 world** that the reset and the
ablation pipeline superseded. They are kept as historical context (the concepts
they describe were eliminated with data, and the docs explain what those concepts
were). Each carries a status banner at the top.

| # | Doc | Status |
|---|-----|--------|
| 00 | **Overview** (this file) | current |
| 01 | [Strategy Architecture](01-strategy-architecture.md) | **HISTORICAL** — v1 multi-strategy/ML/confluence stack, burned in the reset |
| 02 | [Strategies](02-strategies.md) | **HISTORICAL** — LZI/FVG/SD-zone/BOS/fib playbook; all but the zone concept eliminated |
| 03 | [HTF Context & Pattern Mechanics](03-htf-context-and-pattern-mechanics.md) | **PARTLY HISTORICAL** — detector mechanics still exist in code; v1 audit claims and ERL/IRL framing superseded |
| 04 | [Reaction Engine](04-reaction-engine.md) | **HISTORICAL** — reaction engine is now an experimental escape hatch only |
| 05 | [Position Sizing & Risk](05-position-sizing-and-risk.md) | **PARTLY CURRENT** — sizer/guards/soft-stop live on; the v1 study sections are historical |
| 06 | [Learning Journal](06-learning-journal.md) | **PARTLY HISTORICAL** — per-day journal survives; online performance memory was burned |
| 07 | [Backtesting](07-backtesting.md) | **HISTORICAL** — v1 backtesters burned; see the validation scripts in [CHECKPOINT.md](CHECKPOINT.md) |
| 08 | [Live Trading & Deployment](08-live-trading-and-deployment.md) | **current** — updated for the router-based live loop |
| 09 | [Dashboard](09-dashboard.md) | **HISTORICAL** — the dashboard was burned in the reset |
| 10 | [Quant Validation & Modular Overhaul](10-quant-validation-and-modular-overhaul.md) | **HISTORICAL** — the plan that led to the reset; its Phase A–D findings are preserved |

## How to validate / deploy anything today

The pipeline of record (detail in [CHECKPOINT.md](CHECKPOINT.md)):

1. Stage-1 ablation grid (`scripts/run_ablation.py`, `scripts/run_zone_all_tfs.py`) — BH-FDR 5%.
2. Holdout (`scripts/run_holdout_validation.py`).
3. Walk-forward (`scripts/run_walk_forward.py` + `scripts/analyze_walk_forward.py`).
4. Frozen cross-pair transfer for new symbols (`scripts/run_cross_pair_frozen.py`).
5. Router entry (`agent/alphas/zone_routing.py`) gated by `tests/test_zone_routing.py`.
6. Live at half risk until live results confirm (`scripts/run_live.py`).

## Archived docs

Earlier status reports, roadmaps, and superseded guides are preserved (not
deleted) under [`archive/`](archive/) — see [`archive/README.md`](archive/README.md).
