# Trading-AI-model — Roadmap & Progress

A living checklist. Cross items off as you complete them, add status notes inline.
Sections are ordered by priority — top is highest impact, bottom is exploratory.

**Last updated:** 2026-05-03 (late evening)
**Current branch:** `main` (109 tests passing — 16 new this session)
**Latest OOS proof point (3-year run 2023-05 → 2026-05, M15+H1 merged):**
**463 trades, 43.6% WR, PF 0.84, -37.6% return** with the v6 build.
This is the agent's REAL edge after the zone-detector bug was fixed.
Earlier W18 results (+$580 / 100% WR) were a sample-of-one fluke caused
by that bug suppressing zones outside the last week of data.

See `docs/status_2026_05_03_evening.md` for the full breakdown.


| Build  | Window | Trades | WR    | PF   | Return | Max DD | Notes                                                               |
| ------ | ------ | ------ | ----- | ---- | ------ | ------ | ------------------------------------------------------------------- |
| v1     | W18    | 38     | 44.7% | 0.86 | -$608  | -      | No gates                                                            |
| v3     | W18    | 7      | 57.1% | 1.12 | +$41   | -      | + precision_partner + blocked_session + bos+sweep                   |
| v4     | W18    | 5      | 100%  | ∞    | +$580  | 0%     | + dir-aware sweeps + H1 min_conf=3 — **but masked by zone bug**     |
| **v5** | 3-year | 573    | 42.1% | 0.78 | -61.9% | 62.6%  | zone bug fixed, NO hour blocks                                      |
| **v6** | 3-year | 463    | 43.6% | 0.84 | -37.6% | 37.6%  | + NY hour blocks [03, 04, 12, 13]                                   |


**Decision point:** the next session must focus on lifting WR above 55% via
ML scorer + tighter gates BEFORE shipping any roadmap UX features. Adding
voice/Telegram/Docker on top of -37% is wasted effort.

---

## ✅ Already shipped (Day 1 — 2026-04-28)

The original foundation. Everything below was built, tested, and committed.

### Core engine

- Multi-timeframe backtester with one-position-at-a-time merging
- Detector library: zones, FVGs, BOS, Fib, trendlines, liquidity wicks
- Rule engine with confluence-based entry validation
- Risk manager (1% target / 3% floor, daily DD halt, lot sizing tiers)
- Walk-forward validation framework
- HTF bias filter (D1/H4 trend + zone alignment for LTF setups)
- No-trade-day filter (block specific weekdays)

### ML layer

- D1 calibrated scorer (XGBoost / sklearn fallback) — PF 1.29 OOS
- Probability calibration (isotonic regression + Brier score + ECE)
- Anti-hallucination guard — overconfident models blocked from being crowned champion
- SHAP feature attribution for ML-driven setups

### Quality gates (driven by trader feedback)

- **Candle-close confirmation gate** — wait for next bar to close in trade direction
- **False-breakout filter** — reject setups where detection bar wicked beyond zone but closed back inside
- **D1 + H4 are bias-only by default** (entries only on M5/M15/H1)
- **Per-confluence TF tagging** — every confluence shows its source TF (e.g. `zone (M15)`, `htf_bias_long (D1)`)
- `min_confluences: 2` default (kills zone-only entries)

### Journal & explainability

- SQLite journal with batched writes (signals, trades, equity, model versions)
- CLI query tool (`scripts/journal_query.py`) — by TF, hour, day-of-week, winners/losers, narrative
- FastAPI dashboard with NY-time display, force-closed trade marking
- Per-trade `/trade/{id}` page with rich plain-English narrative
- CLI report layout matches dashboard (terminal ↔ browser parity)
- **Entry-confirmation block** in narrative — shows which bar acted as confirmation, candle direction, and verdict

### Data & ops

- Yfinance + Dukascopy + MT5 data sources, parquet caching
- `--start-date` / `--end-date` CLI flags (eliminates training-data leakage)
- `.gitignore` correctly excludes data/, models/, journals/, .env
- Comprehensive `README.md` (350+ lines) and `docs/live_trading.md`
- 62 unit tests covering calibration, HTF bias, no-trade days, date filters, entry gates

---

## ✅ Just shipped — Trading-Partner Mode (Day 6 — 2026-05-03)

Pivot from "trading bot" to "trading partner that learns from your teaching."
See `docs/trading_partner.md` for the full guide.

### LLM layer (`agent/llm/`)

- **Ollama HTTP client** with graceful offline fallback (`ollama.py`)
- **Lesson extractor** — free-form trader paragraph → typed `TradeLesson` via JSON mode (`extractor.py`)
- **Chat service** — system prompt + history + streaming (`chat.py`)
- All-Pydantic-validated, deterministic mock for tests when Ollama is offline

### Journal extension

- `**human_lessons` table** — your discretionary trades + reasoning
- `**agent_disagreements` table** — side-by-side replay diffs
- `**weekly_retrospectives` table** — Friday summary clusters
- `**chat_sessions` + `chat_messages`** — persisted dashboard chat history

### New ICT-flavoured detectors

- **Sessions** (Asia / London / NY / overlap / off) — DST-aware via zoneinfo
- **Daily levels** (PDH / PDL / PDM / PWH / PWL / PWM) — no-look-ahead
- **Liquidity sweep** — tagged version that names *what* was swept (PDH vs swing_high vs equal_highs)
- **Range phase** (accumulation / manipulation / distribution per ICT power-of-three)
- All four wired into `agent/rules/engine.py` as new confluence tags with TF attribution
  - `near_PDH (D1)`, `sweep_PWH (M15)`, `phase_distribution (M15)`, `session_ny (M15)`...

### Conversation layer

- `**agent/conversation/context.py`** — context builder injects relevant
journal/live data per question (handles `trade #42` / `lesson 7` refs)
- `**agent/conversation/replay.py`** — `ReplayDiffer` walks cached bars and
compares the agent's setup at a lesson's timestamp to what the human did

### CLIs

- `**scripts/teach.py`** — interactive / file / stdin / voice ingestion
with confirmation prompt + auto-replay diff
- `**scripts/ask.py`** — REPL or one-shot chat with the agent (streaming optional)
- `**scripts/retrospective.py`** — Friday summary; LLM-driven if Ollama is up,
template fallback otherwise

### Dashboard pages

- `**/lessons`** — list view of every lesson you've ingested
- `**/lesson/{id}`** — CLI-style report + agent diff stack
- `**/chat**` — text box + session list + persistent history
- Shared `_nav.html` strip across all pages
- New "My lessons" stat card on `/`

### Tests & docs

- **31 new tests** (LLM extractor, journal humans, conversation, 4 detectors)
- Total **93 tests passing**, 0 failures
- `**docs/trading_partner.md`** — full setup + workflow guide
- Sample week fixture (`fixtures/sample_week.txt`) — ready to ingest

---

## ✅ Today (Day 7 morning — 2026-05-03)

- Installed Ollama + pulled `qwen2.5:7b-instruct` (chat) and
`qwen2.5:14b-instruct` (extraction)
- Refreshed Dukascopy bar data through 2026-05-01 (D1/H4/H1/M15/M5)
- Built `scripts/extract_docx.py` + `scripts/ingest_docx.py` (deterministic
parser + LLM enrichment) — turns the user's Word doc weekly review into a
standardized markdown + JSON, journals every trade as a `human_lessons`
row, and runs the agent replay diff against each one
- Added `weekly_logs` table (+`weekly_log_id` FK on `human_lessons`)
- Added `agent/llm/weekly.py` (`WeeklyTradingLog`, `DailyReview`,
`WeeklyTrade`, `DayOHLC` with `open_close_clustered`)
- Ingested the user's full Apr 27 → May 1 doc — 5 trades, 5 wins,
+138.1 pips, all journalled with replay diffs (3 agree / 2 no_signal)
- Built `scripts/audit_detectors.py` — per-tag and per-combo precision
audit, finds the noise tags vs the gold signatures
- Added precision gates to `agent/rules/engine.py`:
`require_precision_partner` (default True), `blocked_session_tags`
(default blocks `session_london_ny_overlap`),
`require_fvg_or_sweep_with_bos` (default True)
- Re-ran the W18 backtest with gates on → 38 → 7 trades, P&L
-$608 → +$41, PF 0.86 → 1.12 (proof that ICT works; precision gating
was the missing piece)
- New dashboard pages: `/weekly` (list of weekly logs) and
`/weekly/{id}` (standardized markdown viewer + linked lessons)
- Wrote `tmp/weekly_log_2026_W18/comparison.md` (head-to-head report)
- Wrote `docs/answers_W18.md` (answers to user's conceptual questions
on open=close days, daily-range relationships, scaled-entry efficiency,
order flow)

## 🔴 Day 7 afternoon — 2026-05-03 (continuing now)

- **Fix H1 bleed** — H1 was the only TF still negative after gates
(-$378 / 33% WR / 6 trades). Look at `data/agent_week_2026_W18_v3.db`,
filter `signals WHERE timeframe='H1'`, identify the residual losing tag
pattern. Likely needs `min_confluences=3` on H1 or its own block list.
- **Direction-aware sweep partners** — `sweep_PDH` should only count
as a partner for SHORTS, `sweep_PDL` for LONGS, etc. Currently
treated as direction-agnostic, which let some bad shorts through.
Refactor in `agent/rules/engine.py`.
- **Add `tests/test_precision_gates.py`** — pin the gate behaviour
with a synthetic-bar fixture so we can't regress it accidentally.
- **Re-run W18 with the H1 fix** and update the comparison numbers.
- **Train M15 + H1 scorers** on full historical data (deferred from
Day 2 plan). With the gates, we now have a much cleaner positive set
to learn from.
- **Tune sub-gates** for `require_close_confirmation`
(`min_body_pct_of_range`, `require_close_beyond_zone`,
`min_displacement_atr_pct`).

---

## 🟡 This week (Day 8-12)

### Going-live preparation

- Forward paper-trading mode (`scripts/paper_forward.py`)
- Live $100 risk validation (`enforce_live_stop_cap = True`)
- Exness MT5 demo connection (Windows VPS or Wine on Mac)
- Demo-account ladder (1 week → 1 month before live capital)

### Strategy refinement

- Risk-adjusted lot sizing (Kelly-fraction post-warmup, capped at 2x base size)
- Confluence-combo backtest — print PF per `{zone, fvg, fib_618, htf_bias_long}` combination
- Session optimisation — Wed is weak in journal; check hour-of-day too
- Multi-symbol pilot — port to GBPUSD and XAUUSD

---

## 🟢 Future / nice-to-have

### UX

- **Vision input** — ✅ shipped 2026-05-03 evening. `/chat` page now accepts
chart upload via 📷 Chart button. `agent/llm/vision.py` adapts an Ollama
vision model (llava-phi3 quick-start, llama3.2-vision:11b recommended).
`POST /api/chart_analyze` returns structured `ChartReading`.
*Pending:* live-chart watcher (poll a folder every 60s & trigger analysis).
- **Voice round-trip** — Whisper STT + edge-TTS for hands-free chart-watching
- **Real-time MT5 co-pilot** — agent watches live ticks while you trade and pings disagreements
- **Telegram bot** — push trade-open / trade-close / daily-DD-halt notifications
- Email digest, mobile-responsive CSS, dark/light theme toggle

### Strategy

- Pattern-discovery layer — let the ML model find new confluences from raw OHLC
- Order-flow proxy features (delta, imbalance) when available
- News-event blackouts (high-impact USD/EUR releases)
- Volatility-regime switching — different rules in chop vs trending periods

### Engineering

- Containerise (Docker) for reproducible deployment
- CI on GitHub Actions (run tests + lint on every PR)
- Automated weekly retrain pipeline (cron)
- Parquet → DuckDB for faster ad-hoc analysis

---

## Decision log

Use this section when you make a strategic call so future-you remembers why.

- **2026-04-28:** Removed D1 from entry timeframes per trader feedback. Lost the dollar edge from D1 scorer; will be rebuilt on M15/H1 (Day 2 task #1).
- **2026-04-28:** `min_confluences` raised from 1 → 2 by default. Killed 60% of H4 zone-only entries that were noise.
- **2026-04-28:** Candle-close confirmation gate enabled by default. WR jumped from 51% → 68%. Trade count dropped from 51 → 25.
- **2026-05-03:** Pivot from "bot" to "partner". Built local-LLM teaching pipeline, conversational dashboard, and four new ICT-style detectors (sessions, daily levels, tagged liquidity sweeps, range phase). 31 new tests pass. Chose Ollama (privacy + zero API cost) over OpenAI/Anthropic.
- **2026-05-03:** Picked qwen2.5:14b-instruct for extraction (best JSON-mode at this size on M4) and qwen2.5:7b-instruct for chat (interactive latency).
- **2026-05-03 (afternoon):** User asked whether to abandon ICT after the
agent went -$608 on the W18 backtest. The detector audit said the
opposite: the agent's *winning* signatures (`fvg + zone + phase_distribution`, 100% WR / +74p) match exactly the tags the replay
diff flagged on the user's 3 winning Wed/Thu/Fri trades. The losers
were bare-zone, bare-bos, and the London-NY overlap session.
Decision: **keep ICT, add precision gates.** Result: same week went
-$608 → +$41. We will iterate on the gates rather than rip out the
ICT layer.
- **2026-05-03 (evening):** H1 audit revealed two classes of bug. (a) The
liquidity-sweep detector classifies levels as "upper/lower" by current
price position, so when EUR/USD is well below PWL, PWL becomes an upper
target and a wick-through-PWL bar can emit `sweep_PWL` with
direction=SHORT. Mathematically right (stops above PWL got grabbed),
semantically wrong vs ICT framework. (b) Mid-level sweeps (`sweep_PDM`,
`sweep_PWM`) had 0/3 wins and -25p total. Decision: enforce
direction-aware sweep semantics in the rules engine (HIGH-type → SHORT
only, LOW-type → LONG only, drop MID), and tighten H1 with
`min_confluences_per_tf={"H1": 3}`. Result: H1 went 33% WR / -$378 →
100% WR / +$141. Whole-week portfolio went +$41 → +$580.88, matching
the user's 100% WR and beating their dollar return.
- **2026-05-03 (evening):** Shipped chart-vision endpoint
(`POST /api/chart_analyze`) wired into the dashboard `/chat` page.
Tested live with `llava-phi3:latest` on the user's W18 charts —
infrastructure works end-to-end but llava-phi3 hallucinates prices
(saw "1.23" on a 1.17xxx chart). Decision: keep llava-phi3 as the
zero-hassle quick-start and recommend `llama3.2-vision:11b` (~7.8 GB)
for accurate readings. Both are now supported by the same code path.

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

*Backed by:* `main@HEAD`, last sync 2026-05-03