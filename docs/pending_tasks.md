# Pending Tasks

**Last updated:** 2026-05-13

Outstanding work organized by priority. Check items off as they're completed and add new tasks as they emerge.

---

## HIGH Priority

These directly affect trading edge or are blocking next milestones.

### Train H1 + M15 scorers on v6 dataset
- **Why:** Current scorers were trained during the walk-forward validation cycle. Need fresh per-TF models on the latest data with the full gate stack active.
- **Acceptance:** H1 PF ≥ 1.10, WR ≥ 50%, ≥5 val trades, DD ≤ 10%. M15 PF ≥ 1.00, WR ≥ 45%.
- **Tool:** `scripts/retrain_scorers.py`
- **Estimate:** 30 minutes (mostly waiting for training).

### Tighten precision_partner_tags whitelist
- **Why:** The current whitelist includes all sweep types. The audit shows some combos are marginal. Restricting to only proven-profitable combos (`fvg + phase_distribution`, `fvg + sweep_*`, `fib_382 + sweep_*`) should improve PF.
- **Config:** `RulesConfig.precision_partner_tags` in `agent/config.py`.
- **Risk:** Reducing trade count further. Must validate that remaining trades have PF > 1.3.
- **Estimate:** 1-2 hours (tune + backtest + validate).

### Walk-forward validation on latest data
- **Why:** The last walk-forward was run on May 3. Two weeks of new data exist. Need to confirm the edge holds with the latest config and retrained scorers.
- **Tool:** `scripts/walk_forward.py`
- **Acceptance:** 3/3 folds profitable, PF ≥ 1.1 in each fold.
- **Estimate:** 1 hour.

---

## MEDIUM Priority

Important but not blocking immediate progress.

### Wire news middleware into engine path
- **Why:** `agent/news/calendar.py` and `agent/news/blackout.py` exist but aren't wired into the live `RuleEngine.evaluate()` path. High-impact USD/EUR news events (NFP, FOMC, ECB) cause spikes that blow through stops.
- **Current state:** Scaffolded. `RegimeLabel.news_window` field exists. `agent/rules/news_filter.py` exists.
- **Work needed:** Add a `news_blackout_minutes` config, check `is_news_blackout()` in `_build()`, add tests.
- **Estimate:** 2-3 hours.

### Wire strategy router for phase-1 instrumentation
- **Why:** `agent/regime/` and `agent/strategy/` are scaffolded but not wired. Phase 1 just tags each trade with a `strategy_name` for attribution — no behavior change.
- **Doc:** `docs/regime_router_design.md` has the full design.
- **Work needed:** Call `StrategyRouter.route()` from the backtester, populate `Setup.strategy_name`, log to journal.
- **Estimate:** 3-4 hours.

### Phase 3: User drawing → agent reaction loop (partially done)
- **Why:** The drawing tools exist and the agent can now analyze screenshots with drawings via cloud vision (Claude/Gemini). But the feedback loop isn't real-time yet — user must take a screenshot and upload it.
- **Current state:** Vision analysis of user drawings works. Multi-TF stacking built but untested. TradingView widget handles drawing natively.
- **Remaining work:** Real-time drawing serialization (without screenshot), persistent drawing storage across sessions, agent auto-commentary on new drawings.
- **Estimate:** 3-4 hours remaining.

### Phase 5: Real-time live data feed
- **Why:** During market hours, the chart shows cached parquet data (updated manually via `download_data.py`). A live feed would auto-update candles and trigger real-time analysis.
- **Options:** MT5 tick stream (Windows only), or a free websocket feed (e.g., from a data provider).
- **Estimate:** 6-8 hours.

### Automated weekly retrain pipeline
- **Why:** `scripts/retrain_scorers.py` exists but must be run manually. Needs a cron trigger or in-process scheduler.
- **Schedule:** `0 6 1 */3 *` (1st of each quarter, 06:00 UTC) for quarterly retrain.
- **Work needed:** Set up Task Scheduler (Windows VPS) or cron (Linux), add Telegram notification on retrain result.
- **Estimate:** 1-2 hours.

---

## LOW Priority

Nice-to-have improvements. Do when higher priorities are clear.

### Dockerfile production hardening
- **Why:** Current Dockerfile works but isn't production-grade.
- **Tasks:**
  - Pin base image SHA (not just `python:3.11-slim`).
  - Add non-root user, switch to `--read-only` rootfs.
  - Wire FastAPI to `gunicorn -k uvicorn.workers.UvicornWorker -w 2`.
  - Add sidecar cron container for nightly retrains.
- **Estimate:** 2-3 hours.

### CI on GitHub Actions
- **Why:** No automated testing on push/PR. Tests run locally only.
- **Tasks:**
  - GitHub Actions workflow: install deps, run pytest, lint.
  - Badge in README.
  - Block merge on failure.
- **Estimate:** 1-2 hours.

### Phase 6: Personality tuning
- **Why:** Agent personality rewrite was done (Session 4) but could be refined based on more user interactions.
- **Tasks:**
  - Tune system prompt based on user feedback.
  - Add personality modes (mentor vs peer vs analyst).
  - Context-dependent verbosity (brief during live trading, detailed in review).
- **Estimate:** 1-2 hours per iteration.

### Multi-symbol pilot (GBPUSD, XAUUSD)
- **Why:** Currently EURUSD-only. The framework is symbol-agnostic in theory but detector thresholds and scorer models are EURUSD-specific.
- **Tasks:**
  - Download data for new symbols.
  - Retune `zone_min_impulse_pips` and other pip-denominated thresholds (XAUUSD is in dollars, not pips).
  - Train per-symbol scorers.
  - Validate with walk-forward.
- **Estimate:** 4-6 hours per symbol.

### Email digest / mobile-responsive CSS / dark theme
- **Why:** Dashboard is functional but desktop-only, light-theme only.
- **Tasks:**
  - Responsive CSS for mobile viewing.
  - Dark/light theme toggle.
  - Weekly email digest of performance.
- **Estimate:** 3-4 hours.

### Parquet → DuckDB migration
- **Why:** Parquet is great for sequential reads but ad-hoc queries (e.g., "show me all H1 bars where ATR > 50 pips in London session") need full file scans. DuckDB would enable SQL queries over bar data.
- **Estimate:** 2-3 hours.

---

## Completed (for reference)

These were previously pending and have been shipped:

- [x] Train per-TF scorers on v6 dataset (v10, May 3)
- [x] Walk-forward validation framework (May 3)
- [x] Zone detector bug fix (May 3)
- [x] Direction-aware sweep semantics (May 3)
- [x] Structural anchor gate (May 3)
- [x] Chart vision (llama3.2-vision, May 3)
- [x] Docker + docker-compose (May 3)
- [x] Telegram notifications (May 3)
- [x] Interactive chart with Lightweight Charts (May 11)
- [x] Human drawing tools (May 11)
- [x] Voice chat (Whisper + edge-TTS, May 11)
- [x] Agent annotations toggle (May 13)
- [x] Agent personality rewrite (May 13)
- [x] W19 journal ingestion (May 13)
- [x] Broker CSV import (May 13)
- [x] 2026 YTD backtest (May 13)
- [x] Fibonacci drawing tool (May 13)
- [x] Cloud vision: Claude Sonnet 4.6 + Gemini 2.5 Flash integration (May 13)
- [x] Gemini SDK migration: google-generativeai → google-genai (May 13)
- [x] Vision fallback chain: Claude → Gemini → Local Ollama (May 13)
- [x] Timeframe misidentification fix (May 13)
- [x] Multi-timeframe screenshot analysis endpoint (May 13)
- [x] Vision provider selector in dashboard (May 13)

---

*Review this list at the start of each session. Move completed items to the bottom. Reprioritize based on latest backtest results and user feedback.*
