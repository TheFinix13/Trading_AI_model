# Development Session Log

**Last updated:** 2026-05-13

A chronological record of what was built, discovered, and decided across all development sessions. Read this first for full project context.

---

## Session 1 — Apr 28-29, 2026 (Day 1-2)

**Theme:** Initial build — from zero to a working multi-TF backtester with ML scoring.

### What was built

- **Rules engine** (`agent/rules/engine.py`): confluence-based entry validation with zone as required factor, configurable min_confluences, R:R checks, stop size bounds.
- **Detector suite** (`agent/detectors/`): zones, FVGs, BOS, Fibonacci, trendlines, liquidity wicks, swing highs/lows, ATR — all as pure functions taking `list[Bar]`.
- **Multi-TF backtester** (`agent/backtest/`): bar-by-bar simulation with one-position-at-a-time, spread/commission/slippage modeling, breakeven stop management.
- **ML scorer** (`agent/model/scorer.py`): XGBoost probability scorer with isotonic calibration, Brier score, ECE metrics, SHAP feature attribution, anti-hallucination guard.
- **Dashboard** (`agent/dashboard/app.py`): FastAPI web UI with trade list, per-trade detail pages with plain-English narrative, equity curve, NY-time display.
- **Data pipeline**: yfinance + Dukascopy + MT5 data sources → parquet caching in `data/parquet/`.
- **Risk manager** (`agent/risk/`): 1% target / 3% floor, daily DD halt at 3%, lot sizing tiers.
- **Journal** (`agent/journal/db.py`): SQLite with batched writes — signals, trades, equity_curve, model_versions tables.
- **CLI tools**: `journal_query.py`, `run_backtest.py`, `train_model.py`, `check_gate.py`.
- **Walk-forward framework** (`agent/backtest/walkforward.py`): train/test splits for honest validation.
- **HTF bias filter**: D1/H4 trend alignment for LTF setups (advisory or strict mode).
- **Quality gates**: candle-close confirmation, false-breakout filter, D1+H4 bias-only (no entries on HTF), `min_confluences: 2` default.
- **Tests**: 62 unit tests covering calibration, HTF bias, no-trade days, date filters, entry gates.
- **Documentation**: README (350+ lines), `docs/live_trading.md`, `docs/data_sources.md`.
- **Data leakage fix**: added `--start-date` / `--end-date` CLI flags to eliminate training data contamination.
- **GitHub**: initial push to repository.

### Key results

- First backtest showed promise but needed gating refinement.
- D1 removed from entry timeframes per trader feedback (bias-only).
- `min_confluences` raised 1 → 2 (killed 60% of H4 zone-only noise entries).
- Candle-close confirmation gate: WR jumped 51% → 68%, trade count dropped 51 → 25.

---

## Session 2 — May 1-3, 2026 (Day 3-7)

**Theme:** Trading partner pivot — from autonomous bot to collaborative learning system.

### May 1-2: LLM & Journal Integration

- **Pivot decision**: from "trading bot" to "trading partner that learns from your teaching."
- **Ollama integration** (`agent/llm/`): HTTP client with graceful offline fallback. Models: `qwen2.5:7b-instruct` (chat), `qwen2.5:14b-instruct` (extraction).
- **Lesson extractor** (`agent/llm/extractor.py`): free-form trader text → typed `TradeLesson` via JSON mode.
- **Chat service** (`agent/llm/chat.py`): system prompt + history + streaming responses.
- **Conversation layer** (`agent/conversation/`): context builder injects journal/live data per question; `ReplayDiffer` compares agent vs human at each lesson's timestamp.
- **Journal extension**: new tables — `human_lessons`, `agent_disagreements`, `weekly_retrospectives`, `chat_sessions`, `chat_messages`.
- **Docx ingestion pipeline** (`scripts/extract_docx.py`, `scripts/ingest_docx.py`): parses user's Word doc weekly reviews into structured markdown + JSON, journals trades as `human_lessons`, runs replay diffs.
- **W18 journal ingestion**: user's first trading log (Apr 27 → May 1). 5 trades, 5 wins, +138.1 pips ingested with replay diffs (3 agree / 2 no_signal).
- **Dashboard pages**: `/lessons`, `/lesson/{id}`, `/chat` (text + history), `/weekly`, `/weekly/{id}`.
- **CLIs**: `teach.py` (interactive/file/stdin/voice ingestion), `ask.py` (REPL chat), `retrospective.py`.
- **31 new tests** (93 total passing).

### May 3 (morning): ICT Detectors

- **Four new ICT detectors**:
  - `sessions.py` — Asia/London/NY/overlap, DST-aware via `zoneinfo`.
  - `daily_levels.py` — PDH/PDL/PDM/PWH/PWL/PWM, no look-ahead.
  - `liquidity_sweep.py` — tagged sweeps naming what was swept.
  - `range_phase.py` — accumulation/manipulation/distribution (ICT Power of Three).
- All four wired into `engine.py` as new confluence tags with TF attribution.
- **Detector audit** (`scripts/audit_detectors.py`): per-tag and per-combo precision analysis. Found the noise tags (bare zone, bare BOS, London-NY overlap) vs the gold signatures (FVG + zone, sweep + zone).

### May 3 (afternoon): Precision Gates

- **Precision gates added** to `RulesConfig`:
  - `require_precision_partner`: need FVG or sweep alongside zone/BOS.
  - `blocked_session_tags`: block `session_london_ny_overlap` (-153 pips / 10 trades).
  - `require_fvg_or_sweep_with_bos`: BOS-only entries bled -144 pips.
- **Direction-aware sweeps**: HIGH-type (PDH/PWH/swing_high) → SHORT only; LOW-type → LONG only; MID-type dropped entirely (0/3 wins, -25 pips).
- **H1 fix**: `min_confluences_per_tf: {"H1": 3}` lifted H1 from 33% WR / -$378 → 100% WR / +$141 on W18.
- **W18 backtest progression**: v1 = -$608 (38 trades) → v3 = +$41 (7 trades) → v4 = +$580 (5 trades, 100% WR).
- **Tests**: `test_precision_gates.py` pinned gate behavior.

### May 3 (afternoon-evening): Zone Bug Discovery

- **Critical zone detector bug found and fixed** in `agent/detectors/zones.py`:
  1. Global age pruning: `(len(bars) - 1 - z.created_bar_index) <= max_age_bars` discarded zones >500 bars from the END of input. On a 75,000-bar M15 series, only the last ~5 days had zones.
  2. Global `median_body`: computed from the LAST 200 bars, biasing all historical impulses against recent volatility.
- **Fix**: rolling local median per impulse bar; age filtering moved to use-time in `fresh_zones()` and `evaluate_precomputed()`.
- **Post-fix honest assessment**: 3-year OOS went to -37.6% / 463 trades / 43.6% WR. The W18 +$580 had been artificially inflated by the bug.
- **Regression tests**: `test_zones_historical_distribution.py` (3 tests).

### May 3 (evening): Vision + Edge Recovery

- **Chart vision** (`agent/llm/vision.py`): Ollama vision model adapter. Supports `llava-phi3` (small, hallucinates prices) and `llama3.2-vision:11b` (production-grade). Wired into `/chat` page with file upload.
- **Per-TF scorers**: trained separate H1 and M15 models. Combined with structural anchor gate → v10: 81 trades, 54.3% WR, +5.1% return (vs v6 baseline of -37.6%).
- **Structural anchor gate**: require fib/phase/session alongside precision partner. Every profitable 3-year combo had at least one of these.
- **Walk-forward validation** (`scripts/walk_forward.py`): 3/3 H1 folds positive, 140 trades, 55.7% WR, +$1,454 OOS over 1.5 years. **Edge proven.**
- **Retrain pipeline** (`scripts/retrain_scorers.py`): quarterly retrain with promotion gates.
- **News blackout system** (`agent/news/`): calendar scraper + blackout window computation.
- **Regime router scaffold** (`agent/regime/`, `agent/strategy/`): modules exist, not yet wired into live path.
- **Docker**: `Dockerfile` + `docker-compose.yml` for dashboard deployment.
- **Telegram**: `agent/notifications/telegram.py` + `scripts/notify_telegram.py`.
- **Blocked hours**: NY hours 03, 04, 12, 13 blocked (from per-hour audit: combined -1,921 pips).
- **Live price injection**: chat + chart_analyze context gets fresh parquet price snapshots.
- **Tests**: 109 total passing.

---

## Session 3 — May 11, 2026

**Theme:** Dashboard UX overhaul — interactive chart, drawing tools, voice chat.

### What was built

- **Directory cleanup**: removed 34MB of unnecessary cached/temp files.
- **May 4-8 backtest**: agent scored 3/3 wins, +$234.97 on the week.
- **Interactive chart** (Lightweight Charts v4):
  - Candle chart with agent detector overlays (zones, BOS markers, FVG boxes, daily levels).
  - Timeframe selector (M5/M15/H1/H4/D1).
  - Agent annotation system (colored overlays showing detected patterns).
- **Human drawing tools**:
  - Line tool, box tool, trendline tool, text label tool, eraser tool.
  - Toolbar with active-tool highlighting.
  - All drawings persist during the session.
- **Voice chat integration**:
  - Whisper STT for speech-to-text input.
  - edge-TTS for agent response synthesis.
  - Microphone button in the chat interface.
  - Auto-play for TTS responses.
- **Agent feedback panel**: positioned beside the chart, showing the agent's analysis of current price action.
- **Chart data module** (`agent/dashboard/chart_data.py`): bridges parquet files and detector suite, returns JSON for Lightweight Charts.

---

## Session 4 — May 13, 2026

**Theme:** UX polish, personality rewrite, W19 ingestion, 2026 backtest.

### What was built

- **Agent annotations default off** + "Show AI Analysis" toggle: many annotations were low-quality per user feedback ("rubbish"). Now opt-in.
- **Agent personality rewrite**: rewrote the system prompt for a genuine trading partner personality — direct, honest, challenges bad trades, not a yes-man.
- **W19 journal ingestion** (May 4-8):
  - 17 trades ingested from user's weekly docx.
  - 28 trades imported from broker CSV via `scripts/import_csv.py`.
  - User's actual results: 25/28 wins (89.3% WR), +$19.22 on 0.01 lots.
- **2026 YTD backtest**: 18 trades, 77.8% WR, +$818 (+227 pips). Strongest validation yet.
- **Chart UX improvements**:
  - Zoom fix (scroll zoom was broken).
  - Delete agent annotations (clear button).
  - Fibonacci drawing tool added to the toolbar.
- **Voice auto-play fix**: auto-play now defaults to OFF (user found constant talking annoying).
- **Key discovery**: H1 achieves 91.7% WR vs M15 at 50% in 2026 data — strong confirmation of H1-first strategy.
- **Best confluence combos identified**: zone + fib_382 + FVG + near_PDH is the highest-conviction setup.

---

## Session 5 — May 13, 2026 (Evening)

**Theme:** Cloud vision integration, multi-timeframe visual analysis, SDK migrations.

### What was built

- **Cloud vision providers** (`agent/llm/cloud_vision.py`):
  - Claude Sonnet 4.6 (`claude-sonnet-4-6`) as primary vision provider.
  - Gemini 2.5 Flash (`gemini-2.5-flash`) as secondary provider.
  - Full fallback chain: Claude → Gemini → Local Ollama (llava-phi3).
  - If one provider fails (billing, quota, model error), automatically tries the next.
- **Gemini SDK migration**: replaced deprecated `google-generativeai` with `google-genai` v2.2.0.
  - Updated `pyproject.toml` dependency accordingly.
  - Rewrote GeminiVision to use `genai.Client` + `client.models.generate_content()`.
- **Model name fixes**: updated stale model identifiers:
  - Claude: `claude-sonnet-4-20250514` → `claude-sonnet-4-6`
  - Gemini: `gemini-2.0-flash` → `gemini-2.5-flash`
- **Timeframe misidentification fix**:
  - Removed forced timeframe injection from frontend — the JS was sending the webapp's active TF (M15) as "The user confirms this is the M15 timeframe", overriding what the vision model saw in the screenshot.
  - Enhanced SYSTEM_PROMPT with explicit TradingView header format examples ("Euro / U.S. Dollar · 1D · FXCM") and "NEVER default to M15" instruction.
- **Gemini JSON parsing fix**: rewrote `_parse()` with a 4-strategy extraction pipeline (fence-with-prose regex → full-fence strip → direct parse → greedy extraction).
- **Multi-timeframe screenshot analysis** (new feature):
  - New `POST /api/chart_analyze_multi` endpoint accepting 2-5 images.
  - `analyse_multi()` methods on both ClaudeVision and GeminiVision.
  - Sends all images in a single API call with cross-TF confluence prompt.
  - Frontend updated: drop zone accepts 1-5 images, routes single vs multi automatically.
  - New `MULTI_TF_SYSTEM_PROMPT` / `MULTI_TF_USER_PROMPT` / `MultiTimeframeReading` dataclass.
  - Output includes per-chart analysis + cross-timeframe confluences with significance ratings.
  - For local Ollama: sequential single-image analysis with synthetic confluence detection.
- **Vision provider selector**: dropdown in the chat panel to choose auto/claude/gemini/local.
- **Previous analyses journal**: collapsible section showing historical chart analyses with screenshots.

### Key findings

- Claude Sonnet 4.6 provides significantly better chart reading than Gemini 2.5 Flash — correctly identifies timeframes, zones, and provides actionable trade ideas.
- Gemini tends to misread timeframes and return less structured output, but works as a free fallback.
- The forced timeframe injection was the root cause of M15 misidentification — not the vision models themselves.
- User confirmed Claude's zone identification and psychology explanations are on-point, though trade entries need work when timeframe context is wrong.

### Decisions

- Claude is the preferred vision provider for chart analysis quality.
- Frontend no longer forces timeframe context — vision models must read it from the chart header.
- Multi-TF stacking (D1→H4→H1→M15) is the path forward for intelligent cross-timeframe confluence detection.

### Status at checkpoint

- Cloud vision working (Claude confirmed, Gemini as fallback).
- Multi-TF upload built but not yet tested by user.
- User will test and provide feedback in next session.

---

## Session 6 — May 27, 2026

**Theme:** Strategy rebuild — two-phase entries, per-strategy ML, confluence optimizer, unified backtest.

### What was built

- **Strategy Quality Score (SQS) ranking system** (`agent/strategy/ranking.py`):
  - Per-trade scoring (0–100) across five dimensions: risk-reward (30 pts), execution efficiency (25 pts), zone respect (20 pts), timing (15 pts), regime fit (10 pts).
  - Tracks strategy/TF/session performance over time.
  - Configurable thresholds in `RankingConfig`.

- **LZI two-phase rebuild** (`agent/strategy/strategies/liquidity_grab_reversal.py`):
  - Phase 1: sweep detection → mark Liquidity Zone of Interest → DO NOT TRADE.
  - Phase 2: wait for retest → consumption (3+ bars in zone) → displacement candle → ENTER.
  - PD Array targeting for opposite-side unswept liquidity TPs.
  - Dedicated LZI ML scorer with 15 LZI-specific features (sweep type, consumption count, displacement metrics).
  - Relaxed gate profile (self-validates with six-step internal logic).

- **FVG quality grading + reaction confirmation**:
  - Quality scoring (0–100): size, creation aggressiveness, session timing, fill tracking.
  - Minimum quality threshold of 40 to consider an FVG for entry.
  - Depletion: FVGs visited 3+ times or 80%+ filled are removed.
  - Relaxed gate profile — FVG IS the precision partner.

- **BOS context-only upgrade**:
  - BOS demoted from entry trigger to context-only booster.
  - Quality scored: body break > wick break, recent > ancient.
  - Only enhances primary strategies (FVG + BOS = high conviction).
  - BOS-only entries had bled -144 pips in detector audit — now impossible.

- **SD Zone order-block precision**:
  - Zone boundary = last opposing candle before impulse (the order block).
  - Quality scoring: origin type, base tightness, departure strength, session, FVG left behind.
  - Depletion tracking: each revisit depletes the zone.
  - Relaxed gate profile with reaction confirmation.

- **Fibonacci OTE zone + invalidation**:
  - OTE zone (61.8%–71.0%) = highest weight.
  - 78.6% retracement treated as INVALIDATION (trend is dead, not a deeper entry).
  - Minimum impulse quality of 35 and minimum 20 pips to draw fibs.
  - Never trades alone — must accompany a primary strategy.

- **Confluence optimizer** (`agent/strategy/confluence_optimizer.py`):
  - Measures per-booster marginal lift per strategy.
  - Tests pairwise combinations for additivity vs redundancy.
  - Real-time optimal booster subset selection.
  - Alignment checking (boosters must point at same price).
  - Online learning: updates scores after each trade.

- **Gate profiles** (`agent/config.py`):
  - Per-strategy quality gate overrides (GateProfile class).
  - Default (all gates active), LZI (relaxed, self-validates), FVG (relaxed), SD Zone (relaxed).
  - GATE_PROFILES dict for strategy-name lookup.

- **LZI-specific ML scorer**:
  - Separate XGBoost model for LZI setups with 15 domain-specific features.
  - Threshold: 0.40 (relaxed vs generic 0.55 — internal validation is the primary filter).
  - Configured in `MLConfig.lzi_scorer_path` / `lzi_score_threshold`.

- **Caution day adjustment**:
  - Thursday moved from hard-blocked (`no_trade_days`) to caution (`caution_days`).
  - Both Thursday and Friday require elevated score threshold (+0.15).
  - `no_trade_days` now empty — human partner can always trade any day.

- **Comprehensive strategy documentation** (`docs/strategy_guide.md`):
  - Complete system playbook covering all strategies, boosters, meta-layer, config philosophy, and performance.

### Key results

- **Unified backtest (OOS 2024–2026):** 92 trades, 33.7% WR, PF 1.12, Sharpe 0.72, +10.4% return.
- **Development trajectory:** -9.6% (v7 baseline) → +10.4% (v8 with two-phase + LZI scorer + optimizer).
- **LZI dominance:** 26.4% WR at 4.37:1 R:R — low WR but extreme R:R drives profitability.
- **Best day:** Monday (40.7% WR). Thursday/Friday weakest — hence caution-day designation.
- **Max drawdown:** 13.1% — within acceptable bounds for a $100 live account.

### Decisions

- Thursday is a caution day, not a blocked day. The system can trade but requires higher conviction (+0.15 score boost).
- LZI Retest is the primary edge driver — it gets its own ML scorer and relaxed gates.
- BOS is context-only — never triggers entries independently.
- M15 remains dormant (28.6% WR OOS) but continues learning.
- H1 is the active primary timeframe (proven 62.5% WR OOS edge).

---

*Update this log at the end of each development session.*
