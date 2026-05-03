# Status — Sunday 2026-05-03 (evening)

You asked: "is everything running as we want?" Honest answer: **no, but we found out why.**

## What's running ✅

| Service                          | Endpoint / Detail                            | Status |
| -------------------------------- | -------------------------------------------- | ------ |
| Ollama daemon                    | `http://127.0.0.1:11434`                     | up     |
| Chat model                       | `qwen2.5:14b-instruct`, `qwen2.5:7b-instruct`| ready  |
| Vision model                     | `llama3.2-vision:11b` (production grade)     | ready  |
| Vision model (fallback)          | `llava-phi3:latest` (small, hallucinates)    | ready  |
| Dashboard                        | `http://127.0.0.1:8000` (use `/chat` for vision) | up |
| Test suite                       | 109 / 109 passing                            | green  |

**Vision live-test on your image_001.png** with llama3.2-vision:11b returned:
- Timeframe: H1 ✓
- Current price ≈ 1.16799 (chart shows 1.17207, vision OCR'd within ~30 pips)
- Heavy Confluence zone @ 1.169 ✓
- Support trendline @ 1.16799 ✓
- Coherent narrative + trade idea

**The vision feature is genuinely useful** — drop a chart screenshot into `/chat` and the agent will read it. (The smaller llava-phi3 hallucinates prices badly; we now warn about that in the UI.)

## What we discovered ⚠

While running the full historical backtest, the audit on `signals` showed only 40 entries across the entire 3-year window — all in April 2026. That made me dig into the detector pipeline and find **two compounding bugs in `agent/detectors/zones.py`**:

1. The post-detection prune `[z for z in zones if (len(bars) - 1 - z.created_bar_index) <= max_age_bars]` discarded every zone whose creation index was more than `max_age_bars` (default 500) bars from the END of the input series. On a 75 000-bar M15 history that left only the last 500 bars (~5 days) of zones detected.
2. `median_body` was computed from the LAST 200 bars of the entire series and used as a global filter. Every historical impulse was judged against recent volatility.

**Effect:** the W18 backtest only saw zones from late April 2026 — the same week the user gave us. It looked like the gates were perfect because they were tuned to the only week the detector was producing zones in.

**Fix landed in this session** (commit-ready): zone detector now returns all zones with a per-impulse local median; age filtering happens at use-time in `evaluate_precomputed`. New test `tests/test_zones_historical_distribution.py` (3 tests) pins the behaviour.

## What the agent's REAL out-of-sample edge is now

3 years (2023-05-01 → 2026-05-01), M15 + H1 merged portfolio, $10 000 starting balance:

| Build                                        | Trades | WR    | PF   | Return  | Max DD  | Verdict                                |
| -------------------------------------------- | ------ | ----- | ---- | ------- | ------- | -------------------------------------- |
| v4 (W18-tuned, with zone bug)                | 22     | 71%   | 2.75 | +5.9%   | 1.2%    | ❌ artificial — detector silently dropped 99% of zones |
| **v5** (zone bug fixed, no hour-blocks)      | 573    | 42.1% | 0.78 | -61.9%  | 62.6%   | ❌ catastrophic — gates don't generalize |
| **v6** (v5 + NY hour blocks 03/04/12/13)     | 463    | 43.6% | 0.84 | -37.6%  | 37.6%   | ❌ better, still negative              |
| Target before live deployment                | ≥100   | ≥55%  | ≥1.3 | positive| ≤20%    | needs scorer + tighter gates           |

**This is the truth the bug was hiding.** The W18 +$580 result was coincidence.

## What's actually working (good news from the audit)

The 3-year audit on 573 trades (`tmp/audit_3yr_v5.json`) gives us real, statistically-meaningful signal-quality data. Top combos that ARE profitable:

| Combo                                    | n   | WR    | Total pips |
| ---------------------------------------- | --- | ----- | ---------- |
| `fvg + phase_distribution + zone`        | 10  | 90%   | +473.8     |
| `fib_382 + sweep_swing_high + zone`      | 57  | 54%   | +343.5     |
| `fib_382 + fvg + zone`                   | 6   | 100%  | +321.6     |
| `fvg + sweep_equal_lows + zone`          | 5   | 100%  | +320.3     |
| `fib_382 + session_ny + zone`            | 54  | 50%   | +400.8     |

Worst hours-of-day (NY local time) found in audit:
- **NY 13:00** (NY pre-close): 33% WR, **-857 pips / 70 trades** — biggest single bleed
- NY 03:00 (London open chop): 45% WR, -448 pips / 69 trades
- NY 12:00 (London close): 45% WR, -402 pips / 146 trades
- NY 04:00: 46% WR, -214 pips

Already added to `cfg.rules.blocked_hours_ny = [3, 4, 12, 13]`.

## Recommendation BEFORE proceeding to roadmap items

You asked to backtest the entire chart with the new method *before* moving on. Doing that surfaced the bug that was hiding the truth. **We should not push more roadmap features until the agent is profitable on 3-year OOS data.** Adding voice/Telegram/Docker on top of a -37% system would be polishing a bleeding hull.

Concrete next session priorities, in order:

1. **Train H1 + M15 scorers on the v6 dataset** (573 trades is enough). Apply at threshold 0.55-0.65, re-run 3-year. Goal: lift WR to 55%+.
2. **Tighten precision_partner_tags** to whitelist only the combos that the audit shows as profitable (`fvg + phase_distribution`, `fvg + sweep_*`, `fib_382 + sweep_*`). Drop bare `bos` and bare `near_*`.
3. **Reduce R:R requirement** from 1:1.5 to 1:1.0 only when scorer confidence > 0.7 (high-conviction quick scalps). Many losing trades hit SL before TP — TP is too greedy.
4. **Walk-forward validation**: split 3 years into 3×1-year windows. Train on year 1, test on year 2, etc. If PF drops between windows, the gates are overfit.
5. **Only after** PF ≥ 1.3 on walk-forward across all 3 years, return to roadmap items (voice, Telegram, Docker, etc.).

## Files written this session

- `agent/llm/vision.py` — chart-vision adapter (Ollama)
- `agent/dashboard/app.py` — `POST /api/chart_analyze` endpoint
- `agent/dashboard/templates/chat.html` — file-upload UI
- `agent/detectors/zones.py` — bug fixes (rolling median + use-time age filter)
- `agent/rules/engine.py` — direction-aware sweeps + `blocked_hours_ny` + age filter at use time
- `agent/config.py` — `min_confluences_per_tf`, `blocked_hours_ny=[3,4,12,13]`
- `scripts/audit_detectors.py` — `--per-hour` slicing, NY local time
- `tests/test_zones_historical_distribution.py` — 3 new regression tests for the zone bug
- `tests/test_vision.py` — 5 vision-adapter tests
- `tests/test_precision_gates.py` — 8 gate-behaviour tests
- `data/agent_3yr_v5_M15H1.db` — full 3-year journal (573 trades, the truth)
- `data/agent_3yr_v6_M15H1.db` — same with hour blocks (463 trades)
- `tmp/audit_3yr_v5.json` — full per-tag / per-combo / per-hour audit
- `models/scorer_EURUSD_H1_v6.joblib` — scorer trained on the new dataset (Brier 0.21)
