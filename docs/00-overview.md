# 00 — Overview & Documentation Index

The EURUSD AI Trading Agent codifies a discretionary ICT trading style into an
audited, backtestable, ML-augmented system that runs live on Exness MT5. It is not a
black box: every trade can be opened up and explained in plain English.

These docs are numbered so you can read the build top-to-bottom — from how the market
is read, through the strategies and the present-time reaction engine, to sizing,
learning, backtesting, and live deployment.

## Numbered index

| # | Doc | What's inside |
|---|-----|---------------|
| 00 | **Overview** (this file) | The numbered table of contents and build-phase map. |
| 01 | [Strategy Architecture](01-strategy-architecture.md) | End-to-end pipeline. **01.1** detectors · **01.2** gate profiles · **01.3** confluence optimizer (+ SQS rankings, regime router). |
| 02 | [Strategies](02-strategies.md) | **02.1** LZI retest · **02.2** FVG retest · **02.3** SD zones · **02.4** BOS · **02.5** Fibs. |
| 03 | [HTF Context & Pattern Mechanics](03-htf-context-and-pattern-mechanics.md) | How each ICT concept is detected and when it's valid; HTF bias, sweeps, sessions, Power of Three. |
| 04 | [Reaction Engine & Anticipation→Reaction Flip](04-reaction-engine.md) | Present-time commitment engine, the flip, and `--mode`. |
| 05 | [Position Sizing & Risk](05-position-sizing-and-risk.md) | Conviction-scaled risk-based sizing + hard risk controls. |
| 06 | [Learning Journal & Performance Memory](06-learning-journal.md) | Per-day logs, attribution, counterfactual, calibration, declined setups, online memory. |
| 07 | [Backtesting](07-backtesting.md) | **07.1** standard portfolio backtest · **07.2** learning backtest (+ data sources). |
| 08 | [Live Trading & Deployment](08-live-trading-and-deployment.md) | **08.1** Windows/VM · **08.2** Exness/MT5 connection · **08.3** MT5 chart overlay EA. |
| 09 | [Dashboard](09-dashboard.md) | FastAPI dashboard routes, API, and related CLIs. |

## Build phases (read in order)

1. **Read the market** — [03](03-htf-context-and-pattern-mechanics.md) (mechanics) →
   [01](01-strategy-architecture.md) (architecture).
2. **Find setups** — [02](02-strategies.md) (anticipation strategies) +
   [04](04-reaction-engine.md) (present-time reaction).
3. **Commit risk** — [05](05-position-sizing-and-risk.md) (sizing + risk gates).
4. **Learn** — [06](06-learning-journal.md) (journal + online performance memory).
5. **Validate** — [07](07-backtesting.md) (standard + learning backtests).
6. **Deploy** — [08](08-live-trading-and-deployment.md) (Windows/Exness/MT5) +
   [09](09-dashboard.md) (monitoring).

## Archived docs

Earlier status reports, roadmaps, and superseded guides are preserved (not deleted)
under [`archive/`](archive/) — see [`archive/README.md`](archive/README.md) for what
moved where.
