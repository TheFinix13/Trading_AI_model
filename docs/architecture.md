# System Architecture

**Last updated:** 2026-05-13

This document describes the full architecture of the EURUSD AI Trading Agent — from raw price data to trade execution, including the ML scoring layer, dashboard, LLM integration, and voice system.

---

## 1. High-Level Overview

The agent is a **confluence-based trading system** that detects ICT (Inner Circle Trader) patterns on EURUSD, scores them with calibrated ML models, and surfaces trade setups through a web dashboard. It operates as a **trading partner** — not a fully autonomous bot — designed to learn from the user's discretionary trading style and provide analysis, not blind execution.

```
Raw Data (yfinance / MT5 / Dukascopy)
        │
        ▼
  Parquet Cache (data/parquet/)
        │
        ▼
  Detector Suite (agent/detectors/)
  ├── zones.py         — Supply/demand zones
  ├── fvg.py           — Fair value gaps
  ├── bos.py           — Break of structure
  ├── fib.py           — Fibonacci retracements
  ├── daily_levels.py  — PDH/PDL/PDM/PWH/PWL/PWM
  ├── liquidity_sweep.py — Tagged liquidity sweeps
  ├── sessions.py      — Session labels (Asia/London/NY)
  ├── range_phase.py   — ICT Power of Three phases
  ├── trendlines.py    — Automatic trendline fitting
  ├── liquidity.py     — Liquidity wick detection
  ├── swings.py        — Swing high/low detection
  └── atr.py           — Average True Range
        │
        ▼
  Rules Engine (agent/rules/engine.py)
  ├── Confluence counting + required factors
  ├── Precision gates (require FVG/sweep partner)
  ├── Structural anchor gate (fib/phase/session)
  ├── Direction-aware sweep semantics
  ├── Per-TF confluence minimums
  ├── Time-of-day blocks (NY hours 03/04/12/13)
  ├── Session blocklist (London-NY overlap)
  ├── HTF bias filter (D1/H4 advisory or strict)
  ├── Candle-close confirmation gate
  └── False-breakout filter
        │
        ▼
  ML Scorer (agent/model/scorer.py)
  ├── Per-TF XGBoost models (H1@0.30, M15@0.40)
  ├── Isotonic regression calibration
  └── Anti-hallucination guard
        │
        ▼
  Risk Manager (agent/risk/)
  ├── manager.py  — 1% target / 3% floor, daily DD halt
  └── sizing.py   — Lot sizing tiers ($100/$300/$1000)
        │
        ▼
  Backtester / Live Executor
  ├── agent/backtest/multi_tf.py   — Multi-TF merged portfolio
  ├── agent/backtest/engine.py     — Single-TF backtest core
  ├── agent/backtest/walkforward.py — Walk-forward validation
  └── agent/execution/executor.py  — MT5 live execution
        │
        ▼
  Dashboard (agent/dashboard/app.py)
  ├── Interactive chart (Lightweight Charts v4)
  ├── Trade journal viewer
  ├── Chat interface (Ollama LLM)
  ├── Voice chat (Whisper STT + edge-TTS)
  ├── Chart vision (llama3.2-vision)
  ├── Weekly log viewer
  └── Agent feedback panel
```

---

## 2. Module Map

### `agent/` — Core Library

| Module | Purpose |
|--------|---------|
| `config.py` | Pydantic config: YAML + `.env` merging. All tunable parameters live here. |
| `types.py` | Core data types: `Bar`, `Zone`, `FVG`, `Setup`, `Direction`, `Timeframe`, etc. |
| `utils.py` | Utility helpers (pip conversion, formatting). |
| `cli.py` | CLI entry point for the agent. |

### `agent/detectors/` — Pattern Detection

Each detector is a pure function: `list[Bar] → list[Detection]`. No side effects, no state.

| File | What It Detects |
|------|-----------------|
| `zones.py` | Supply/demand zones via base + impulse rule. Rolling local median for adaptive thresholds. |
| `fvg.py` | Fair value gaps (unfilled 3-candle imbalances). |
| `bos.py` | Break of structure (swing high/low violations). |
| `fib.py` | Fibonacci retracement levels from the last significant swing. |
| `daily_levels.py` | Prior-day high/low/mid, prior-week high/low/mid — no look-ahead. |
| `liquidity_sweep.py` | Tagged sweeps: names what was swept (PDH, swing_high, equal_lows, etc.). |
| `sessions.py` | Labels each bar with its session (Asia/London/NY/overlap). DST-aware. |
| `range_phase.py` | ICT Power of Three: accumulation → manipulation → distribution. |
| `trendlines.py` | Auto-fit trendlines from swing points. |
| `liquidity.py` | Liquidity wick detection (long wick rejections). |
| `swings.py` | Swing high/low identification with configurable lookback. |
| `atr.py` | Rolling ATR for volatility-aware tolerance. |

### `agent/rules/` — Entry Logic

| File | Purpose |
|------|---------|
| `engine.py` | The core `RuleEngine` class. Two modes: `evaluate()` (slow, from-scratch) and `evaluate_precomputed()` (fast, for backtests). Applies all precision gates, structural anchors, session blocks, and HTF bias filters. |
| `filters.py` | No-trade window and no-trade day filters. |
| `htf_bias.py` | Higher-timeframe bias computer (D1/H4 trend + zone alignment). |
| `news_filter.py` | News event filter (scaffolded, not yet wired into the live path). |

### `agent/model/` — ML Layer

| File | Purpose |
|------|---------|
| `scorer.py` | XGBoost probability scorer with isotonic calibration, anti-hallucination guard, SHAP attribution. |
| `discoverer.py` | Feature-importance driven pattern discovery. |
| `retrainer.py` | Automated scorer retraining with promotion gates. |

### `agent/backtest/` — Backtesting Framework

| File | Purpose |
|------|---------|
| `engine.py` | Single-TF backtest: bar-by-bar simulation with one-position-at-a-time, spread/commission/slippage, breakeven stop management. |
| `multi_tf.py` | Multi-TF merged portfolio: runs M15 + H1 (+ others) and merges trades chronologically with position deconfliction. |
| `walkforward.py` | Walk-forward validation: train/test splits with fresh scorers per fold. |
| `metrics.py` | PF, WR, max DD, Sharpe, and other performance metrics. |
| `discoverer_runner.py` | Runner for ML-driven pattern discovery backtests. |

### `agent/risk/` — Risk Management

| File | Purpose |
|------|---------|
| `manager.py` | Position sizing (1% target / 3% floor), daily DD halt (3%), kill switch. |
| `sizing.py` | Lot sizing tiers: hard cap at 0.01 under $300, 0.10 under $1000, 1.0 above. |

### `agent/llm/` — Local LLM Integration

| File | Purpose |
|------|---------|
| `ollama.py` | Ollama HTTP client with graceful offline fallback. |
| `chat.py` | Chat service: system prompt + history + streaming responses. |
| `extractor.py` | Lesson extractor: free-form trader paragraph → typed `TradeLesson` via JSON mode. |
| `vision.py` | Chart vision adapter: Ollama vision model → structured `ChartReading`. |
| `weekly.py` | Weekly trading log models: `WeeklyTradingLog`, `DailyReview`, `WeeklyTrade`. |
| `voice.py` | Voice integration: Whisper STT + edge-TTS for the dashboard. |

### `agent/conversation/` — Contextual Chat

| File | Purpose |
|------|---------|
| `context.py` | Builds LLM context from journal/live data. Handles `trade #42` / `lesson 7` references. Injects live price snapshots. |
| `replay.py` | `ReplayDiffer`: walks cached bars and compares agent's setup at a lesson's timestamp to the human's actual trade. |

### `agent/journal/` — Trade Journal

| File | Purpose |
|------|---------|
| `db.py` | SQLite journal with batched writes. Tables: `signals`, `trades`, `equity_curve`, `model_versions`, `human_lessons`, `agent_disagreements`, `weekly_retrospectives`, `chat_sessions`, `chat_messages`, `weekly_logs`. |

### `agent/dashboard/` — Web Dashboard

| File | Purpose |
|------|---------|
| `app.py` | FastAPI app (~1000 lines). Routes: `/` (overview), `/trades`, `/trade/{id}`, `/lessons`, `/lesson/{id}`, `/weekly`, `/weekly/{id}`, `/chat`, `/api/chart_analyze`, chart API endpoints, voice endpoints. |
| `chart_data.py` | Loads parquet data, runs detectors, returns JSON for Lightweight Charts. |

### `agent/regime/` — Regime Detection (Scaffolded)

| File | Purpose |
|------|---------|
| `detector.py` | Cheap-feature classifier: trending_up/down, chop, low_vol, high_vol. Based on 50-bar slope + ATR14/ATR50 ratio. |

### `agent/strategy/` — Strategy Router (Scaffolded)

| File | Purpose |
|------|---------|
| `base.py` | Strategy ABC: `name`, `compatible_regimes`, `min_confluences`, `evaluate()`. |
| `registry.py` | `StrategyRegistry` + `StrategyRouter` with `select_best()`. |
| `strategies/` | Thin shims: `LiquidityGrabReversal`, `FVGRetest`, `BOSContinuation`, `FibRetracement`, `SDZoneRetest`. |

### `agent/news/` — News System

| File | Purpose |
|------|---------|
| `calendar.py` | Forex Factory calendar scraper/parser. |
| `blackout.py` | News blackout window computation. |

### `agent/notifications/` — Alerts

| File | Purpose |
|------|---------|
| `telegram.py` | Telegram bot notifications: trade open/close, DD halt, milestones. Fails open (never crashes the trading loop). |

### `agent/features/` — Feature Engineering

| File | Purpose |
|------|---------|
| `extractor.py` | Feature vector extraction for the ML scorer from raw bar data + detector outputs. |

### `agent/analysis/` — Post-Trade Analysis

| File | Purpose |
|------|---------|
| `explain.py` | Plain-English trade narrative generator. |
| `calibration.py` | Probability calibration (isotonic regression, Brier score, ECE). |
| `losses.py` | Loss analysis tools. |

### `scripts/` — CLI Tools

| Script | Purpose |
|--------|---------|
| `run_backtest.py` | Single-TF backtest runner. |
| `run_multitf.py` | Multi-TF merged portfolio backtest. |
| `run_live.py` | Live/paper trading loop. |
| `train_model.py` | Train ML scorer. |
| `train_scorer.py` | Train per-TF scorers with calibration. |
| `retrain_scorers.py` | Production retrain pipeline with promotion gates. |
| `walk_forward.py` | Walk-forward validation runner. |
| `download_data.py` | Download OHLCV data from yfinance/Dukascopy. |
| `check_gate.py` | Pre-deployment gate check (PF, DD, trade count). |
| `audit_detectors.py` | Per-tag and per-combo precision audit with per-hour slicing. |
| `journal_query.py` | CLI journal query tool (by TF, hour, day, winners/losers). |
| `teach.py` | Interactive lesson ingestion (file/stdin/voice). |
| `ask.py` | Chat REPL with the agent. |
| `retrospective.py` | Weekly retrospective generator. |
| `extract_docx.py` | Parse user's Word doc weekly review. |
| `ingest_docx.py` | Deterministic parser + LLM enrichment for docx journals. |
| `import_csv.py` | Import trades from broker CSV. |
| `import_backtest_journal.py` | Import backtest journal into the DB. |
| `explain.py` | Generate trade explanations. |
| `analyze_losses.py` | Analyze losing trade patterns. |
| `iterate.py` | Iterative parameter optimization. |
| `visual_sanity.py` | Visual sanity check for detector outputs. |
| `smoke_test.py` | MT5 connection smoke test. |
| `notify_telegram.py` | One-off Telegram notification sender. |
| `weekly_retrain.py` | Scheduled weekly retrain trigger. |

---

## 3. Data Flow: Bar → Signal → Trade

### Step 1: Data Ingestion
```
yfinance / Dukascopy / MT5 API
  → download_data.py
  → data/parquet/EURUSD_{TF}.parquet
```
Parquet files store OHLCV bars indexed by UTC timestamp. Multiple timeframes cached independently (D1, H4, H1, M15, M5).

### Step 2: Detector Pass
```
Parquet bars → precompute(bars, cfg) → PrecomputedContext
```
`precompute()` in `engine.py` runs all detectors once over the full bar series. Output: zones, FVGs, BOS events, fibs, trendlines, wicks, daily levels, sweeps, sessions, range phases, ATR. This is the fast path for backtests — O(n) detector work, not O(n²).

### Step 3: Per-Bar Evaluation
```
for each bar i in the series:
    RuleEngine.evaluate_precomputed(ctx, i)
    → filter detections to "as-of bar i" (no look-ahead)
    → count confluences per direction (LONG/SHORT)
    → apply precision gates, structural anchors, session blocks
    → apply per-TF confluence minimums
    → apply time-of-day blocks
    → compute entry/stop/TP from zone + ATR
    → check stop size bounds and R:R minimum
    → apply HTF bias filter
    → return Setup or None
```

### Step 4: ML Scoring
```
Setup → feature_extractor → feature_vector → scorer.predict_proba()
    → if score < threshold (H1: 0.30, M15: 0.40): reject
    → else: pass to risk manager
```

### Step 5: Risk Management
```
Setup → risk_manager.size(balance, stop_pips)
    → lot size (1% risk target, 3% floor, tier caps)
    → daily DD check (3% halt)
    → position count check (max 1 open)
    → if blocked: skip trade
```

### Step 6: Execution
```
Backtest: engine fills at next-bar open, manages stop/TP/breakeven.
Live: executor.py sends MT5 order, polls for fill, manages trailing.
```

### Step 7: Journal + Dashboard
```
Trade result → journal.db (SQLite)
    → Dashboard reads journal + parquet
    → Renders equity curve, trade list, per-trade narrative
    → Interactive chart with detector overlays
```

---

## 4. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Pure-function detectors** | No state, no side effects. Easy to test, easy to precompute once for backtests. |
| **Age filter at use-time, not detection-time** | The zone detector bug taught us: filtering zones by age at detection time silently drops zones from historical bars in multi-year backtests. Age must be relative to the current `at_index`. |
| **Rolling local median in zone detector** | A global median computed from the last 200 bars biases against historical impulses when volatility changes over time. |
| **Two evaluation modes** | `evaluate()` for live (detects from scratch on latest bars). `evaluate_precomputed()` for backtests (runs detectors once, slices by index — 100x faster). |
| **Per-TF scorers** | H1 and M15 have fundamentally different pattern characteristics. A single global scorer was undertrained on H1. Per-TF models improved WR from 43.6% to 54.3%. |
| **Confluence-based gating** | No single pattern is reliable alone. Requiring multiple confluences (zone + FVG + fib, etc.) dramatically reduces false signals. |
| **Config-driven gates** | All precision gates, session blocks, hour blocks, and thresholds are in `RulesConfig`. Tuning doesn't require code changes. |
| **Local-only LLM** | Ollama runs locally. No API keys, no data leakage, no per-request costs. User chose this for privacy. |

---

## 5. Infrastructure

| Component | Technology |
|-----------|------------|
| Language | Python 3.11 |
| Web framework | FastAPI + Jinja2 templates |
| Charting | Lightweight Charts v4 (TradingView) |
| Database | SQLite (journal, lessons, chat history) |
| Data format | Parquet (OHLCV bars) |
| ML | XGBoost + scikit-learn (isotonic calibration) |
| LLM | Ollama (qwen2.5:7b for chat, qwen2.5:14b for extraction) |
| Vision | llama3.2-vision:11b via Ollama |
| Voice | Whisper (STT) + edge-TTS (synthesis) |
| Config | YAML + .env (Pydantic validation) |
| Broker | Exness MT5 (Windows-only for live) |
| Container | Docker + docker-compose (dashboard only) |
| Notifications | Telegram bot |
| Tests | pytest (100+ tests) |

---

*This document should be updated whenever a new major module is added or the data flow changes.*
