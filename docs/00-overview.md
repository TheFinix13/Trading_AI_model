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
| 01 | [Strategy Architecture](archive/01-strategy-architecture.md) | **HISTORICAL** — archived 2026-06-24; v1 multi-strategy/ML/confluence stack |
| 02 | [Strategies](archive/02-strategies.md) | **HISTORICAL** — archived 2026-06-24; LZI/FVG/SD-zone/BOS/fib playbook |
| 03 | [HTF Context & Pattern Mechanics](03-htf-context-and-pattern-mechanics.md) | **PARTLY CURRENT** — detector mechanics live; v1 HTF context layer burned (rewritten 2026-06-24) |
| 04 | [Reaction Engine](archive/04-reaction-engine.md) | **HISTORICAL** — archived 2026-06-24; experimental escape hatch only |
| 05 | [Position Sizing & Risk](05-position-sizing-and-risk.md) | **PARTLY CURRENT** — 05.1–05.5 live; 05.6–05.8 historical (rewritten 2026-06-24) |
| 06 | [Learning Journal](06-learning-journal.md) | **PARTLY CURRENT** — vault + daily log live; v1 LiveJournal burned (rewritten 2026-06-24) |
| 07 | [Backtesting](archive/07-backtesting.md) | **HISTORICAL** — archived 2026-06-24; see validation scripts in [CHECKPOINT.md](CHECKPOINT.md) |
| 08 | [Live Trading & Deployment](08-live-trading-and-deployment.md) | **current** — updated for the router-based live loop |
| 09 | [Dashboard](archive/09-dashboard.md) | **HISTORICAL** — archived 2026-06-24; dashboard burned in reset |
| 10 | [Quant Validation & Modular Overhaul](archive/10-quant-validation-and-modular-overhaul.md) | **HISTORICAL** — archived 2026-06-24; plan that led to the reset |

## How to validate / deploy anything today

The pipeline of record (detail in [CHECKPOINT.md](CHECKPOINT.md)):

1. Stage-1 ablation grid (`scripts/run_ablation.py`, `scripts/run_zone_all_tfs.py`) — BH-FDR 5%.
2. Holdout (`scripts/run_holdout_validation.py`).
3. Walk-forward (`scripts/run_walk_forward.py` + `scripts/analyze_walk_forward.py`).
4. Frozen cross-pair transfer for new symbols (`scripts/run_cross_pair_frozen.py`).
5. Router entry (`agent/alphas/zone_routing.py`) gated by `tests/test_zone_routing.py`.
6. Live at half risk until live results confirm (`scripts/run_live.py`).

## M001 multi-agent ensemble R&D

Doctrine and simulator work live in `finance-research-experiments` /
`programs/M001_multi_agent_ensemble/` (branch `multi-agent-ensemble`,
commit `11cdde4`). This repo keeps a pointer at
[`research/multi-agent-ensemble/README.md`](research/multi-agent-ensemble/README.md).

## Archived docs

Numbered HISTORICAL docs (01, 02, 04, 07, 09, 10) and earlier status reports
are preserved under [`archive/`](archive/) — see [`archive/README.md`](archive/README.md).
