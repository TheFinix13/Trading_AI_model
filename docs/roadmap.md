# Trading-AI-model — Roadmap & Progress

A living checklist. Cross items off as you complete them, add status notes inline.
Sections are ordered by priority — top is highest impact, bottom is exploratory.

**Last updated:** 2026-04-28
**Current branch:** `main` (5 commits, 62 tests passing)
**Latest OOS proof point:** 25 trades over 1.5 years (Oct 2024 – Apr 2026), 68.0% WR, PF 1.09, +1.2%, max DD 6.6%

---

## ✅ Already shipped (Day 1 — 2026-04-28)

The foundation is in place. Everything below is built, tested, and committed.

### Core engine
- [x] Multi-timeframe backtester with one-position-at-a-time merging
- [x] Detector library: zones, FVGs, BOS, Fib, trendlines, liquidity wicks
- [x] Rule engine with confluence-based entry validation
- [x] Risk manager (1% target / 3% floor, daily DD halt, lot sizing tiers)
- [x] Walk-forward validation framework
- [x] HTF bias filter (D1/H4 trend + zone alignment for LTF setups)
- [x] No-trade-day filter (block specific weekdays)

### ML layer
- [x] D1 calibrated scorer (XGBoost / sklearn fallback) — PF 1.29 OOS
- [x] Probability calibration (isotonic regression + Brier score + ECE)
- [x] Anti-hallucination guard — overconfident models blocked from being crowned champion
- [x] SHAP feature attribution for ML-driven setups

### Quality gates (driven by trader feedback)
- [x] **Candle-close confirmation gate** — wait for next bar to close in trade direction
- [x] **False-breakout filter** — reject setups where detection bar wicked beyond zone but closed back inside
- [x] **D1 + H4 are bias-only by default** (entries only on M5/M15/H1)
- [x] **Per-confluence TF tagging** — every confluence shows its source TF (e.g. `zone (M15)`, `htf_bias_long (D1)`)
- [x] `min_confluences: 2` default (kills zone-only entries)

### Journal & explainability
- [x] SQLite journal with batched writes (signals, trades, equity, model versions)
- [x] CLI query tool (`scripts/journal_query.py`) — by TF, hour, day-of-week, winners/losers, narrative
- [x] FastAPI dashboard with NY-time display, force-closed trade marking
- [x] Per-trade `/trade/{id}` page with rich plain-English narrative
- [x] CLI report layout matches dashboard (terminal ↔ browser parity)
- [x] **Entry-confirmation block** in narrative — shows which bar acted as confirmation, candle direction, and verdict

### Data & ops
- [x] Yfinance + Dukascopy + MT5 data sources, parquet caching
- [x] `--start-date` / `--end-date` CLI flags (eliminates training-data leakage)
- [x] `.gitignore` correctly excludes data/, models/, journals/, .env
- [x] Comprehensive `README.md` (350+ lines) and `docs/live_trading.md`
- [x] 62 unit tests covering calibration, HTF bias, no-trade days, date filters, entry gates

---

## 🔴 Tomorrow's plan (Day 2 — 2026-04-29)

Target: end the day with a publicly pushed repo and a measurably stronger edge.

### Morning block (~3 hours)

#### 1. Train M15 + H1 scorers
- [ ] **Train M15 scorer** on full historical data (~37k bars)
  - Status: not started
  - Owner: agent
  - Deliverable: `models/scorer_EURUSD_M15.joblib` + calibration report
  - Acceptance: Brier < 0.20, ECE < 0.05, OOS WR uplift ≥ 5pp vs no-scorer baseline
- [ ] **Train H1 scorer** on full historical data (~9k bars)
  - Status: not started
  - Owner: agent
  - Deliverable: `models/scorer_EURUSD_H1.joblib` + calibration report
  - Acceptance: same gates as M15
- [ ] **Re-run OOS backtest with both scorers active**
  - Status: not started
  - Acceptance: PF ≥ 1.4 on the same 2024-10-28+ window
  - If PF < 1.4 → tune threshold, document best-case
- [ ] **Decision point:** per-TF scorers (current plan) OR unified scorer with TF as a feature?
  - Status: needs your input — leave a comment in this checklist
  - Recommendation: per-TF, simpler to validate

#### 2. Tighter candle-close confirmation
- [ ] **Add three opt-in sub-gates** to `rules.require_close_confirmation`:
  - [ ] `min_body_pct_of_range: float = 0.0` — kills doji confirmations (suggested 0.3)
  - [ ] `require_close_beyond_zone: bool = False` — confirm-bar close must clear the zone for longs
  - [ ] `min_displacement_atr_pct: float = 0.0` — confirm-bar range ≥ X × ATR14 (suggested 0.5)
- [ ] **Backtest each sub-gate independently** — measure WR / PF impact
- [ ] **Choose default** based on best-balance (likely just `min_body_pct_of_range = 0.3`)
- [ ] **Update narrative** to show which sub-gates were applied

#### 3. Push to GitHub
- [ ] **You: install `gh` CLI** (`sudo chown -R $(whoami) /opt/homebrew && brew install gh`)
  - Status: blocked on you
- [ ] **You: authenticate** (`gh auth login`)
- [ ] **Agent: push the repo** (`gh repo create Trading-AI-model --public --source=. --push`)
- [ ] **Verify:** repo is browsable at `github.com/<you>/Trading-AI-model`
- [ ] **Add repo URL** to README badge

### Afternoon block (~2-3 hours)

#### 4. Better journal browser (dashboard upgrade)
- [ ] **Add filter bar** at top of `/` route: TF / confluence-type / win-loss / ML-score range / day-of-week
- [ ] **New `/skipped` page** showing rejected signals with reasons (false_breakout, no_confirmation, ml_below_threshold, daily_halt)
- [ ] **Equity curve chart** with drawdown bands (use Chart.js or Plotly)
- [ ] **Confluence breakdown table** — winrate per confluence combination
- [ ] Acceptance: can spot-check 30 trades in <10 min instead of one at a time

#### 5. Replay mode polish
- [ ] **Test existing `scripts/explain.py --replay`** with the new TF tagging + entry confirmation
- [ ] **Add `--show-rejected` flag** — surface rejection reasons even when no setup was approved
- [ ] **Add `--htf-context` flag** — print the D1/H4 bias snapshot for the requested timestamp
- [ ] Acceptance: you can paste a chart timestamp and immediately see "yes/no, here's why"

---

## 🟡 This week (Day 3-7)

### Going-live preparation

#### Forward paper-trading mode (Day 3)
- [ ] Build `scripts/paper_forward.py` — runs the agent in real time on rolling yfinance/dukascopy data
- [ ] Simulated $100 account, journals every decision, no MT5 connection
- [ ] Heartbeat output every minute showing balance, open positions, last setup considered
- [ ] Acceptance: can run for 1 trading day without crashing, journal matches expectations

#### Live $100 risk validation (Day 3 — quick win)
- [ ] Flip `cfg.rules.enforce_live_stop_cap = True`
- [ ] Re-run OOS backtest with `cfg.backtest.initial_balance = 100.0`
- [ ] Document: "Of N detected setups, X% were rejected for stop-too-wide on $100 account"
- [ ] If rejection rate > 50% → decision: tighten stops, scale up min capital, or change TF mix

#### Exness MT5 demo connection (Day 4-5)
- [ ] Provision Windows VPS (or test Wine on Mac first)
- [ ] Install MT5 + Exness demo account credentials
- [ ] Test the live executor stub:
  - [ ] Account info fetch
  - [ ] Open BUY position with stop + TP
  - [ ] Modify stop (breakeven snap)
  - [ ] Close position by ticket
- [ ] Run paper-forward mode pointed at the demo account for 1 trading day
- [ ] Acceptance: 0 errors in 24h, all trades match journal

#### Demo-account ladder (Day 5+)
- [ ] Run the agent on the Exness demo for 1 week → 1 month
- [ ] Monitor: kill-switch responds, daily-DD-halt triggers correctly, trades reconcile with broker statements
- [ ] Decision gate: live $100 account requires demo to have grown $100 → $200+ with no critical errors

### Strategy refinement

- [ ] **Risk-adjusted lot sizing** (Kelly-fraction post-warmup, capped at 2x base size)
- [ ] **Confluence-combo backtest** — print PF per `{zone, fvg, fib_618, htf_bias_long}` combination, prune the losers
- [ ] **Session optimisation** — journal already shows Wed is weak; check hour-of-day too
- [ ] **Multi-symbol pilot** — port the strategy to GBPUSD and XAUUSD, see if the edge transfers

---

## 🟢 Future / nice-to-have

These are not blocked on anything; pull from this list whenever the urgent stack is empty.

### UX
- [ ] Telegram bot integration — push trade-open / trade-close / daily-DD-halt notifications
- [ ] Email digest — daily P&L summary + trade list
- [ ] Mobile-responsive dashboard CSS
- [ ] Dark/light theme toggle

### Strategy
- [ ] Pattern-discovery layer — let the ML model find new confluences from raw OHLC
- [ ] Order-flow proxy features (delta, imbalance) when available
- [ ] News-event blackouts (high-impact USD/EUR releases)
- [ ] Volatility-regime switching — different rules in chop vs trending periods

### Engineering
- [ ] Containerise (Docker) for reproducible deployment
- [ ] CI on GitHub Actions (run tests + lint on every PR)
- [ ] Automated weekly retrain pipeline (Airflow or cron)
- [ ] Parquet → DuckDB for faster ad-hoc analysis

### Robustness
- [ ] Slippage stress test (3x normal slippage — does the edge survive?)
- [ ] Spread blowup test (10x normal spread during news)
- [ ] Connection-loss recovery test (drop network mid-trade, verify state reconciliation)

---

## Decision log

Use this section when you make a strategic call so future-you remembers why.

- **2026-04-28:** Removed D1 from entry timeframes per trader feedback. Lost the dollar edge from D1 scorer; will be rebuilt on M15/H1 (Day 2 task #1).
- **2026-04-28:** `min_confluences` raised from 1 → 2 by default. Killed 60% of H4 zone-only entries that were noise.
- **2026-04-28:** Candle-close confirmation gate enabled by default. WR jumped from 51% → 68%. Trade count dropped from 51 → 25.

---

## How to update this file

When you finish a task:
1. Change `[ ]` to `[x]`
2. Add a status note inline (e.g. "PF 1.42 with both scorers")
3. Commit with the same commit that ships the work

When you discover a new task:
1. Add it under the correct priority section
2. Include: deliverable, acceptance criteria, estimated time

When priorities change:
1. Move tasks between sections
2. Add to the decision log explaining why

---

*Backed by:* `main@HEAD`, last sync 2026-04-28
