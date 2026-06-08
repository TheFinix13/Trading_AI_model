# Key Decisions & Rationale

**Last updated:** 2026-05-13

Every major architectural, strategic, and trading decision with the reasoning behind it. Reference this to understand **why** things are the way they are.

---

## Trading Framework Decisions

### Why ICT concepts as the foundation

**Decision (Apr 28):** Use ICT (Inner Circle Trader) concepts — supply/demand zones, BOS, FVG, Fibonacci, daily levels, liquidity sweeps — as the primary detection framework.

**Rationale:**
- The user's trading style is already ICT-based. Building on concepts they understand means they can validate and improve the agent's logic.
- ICT concepts are structurally sound: they're based on institutional order flow, liquidity pools, and market structure — not arbitrary indicator crossovers.
- The 3-year audit confirmed the framework works when properly gated: `fvg + zone` = 80-89% WR, `fvg + phase_distribution + zone` = 90% WR, `fib_382 + fvg + zone` = 100% WR.
- The problem was never ICT itself — it was letting low-quality ICT signals (bare zone, bare BOS) through without requiring displacement evidence.

**Alternative rejected:** Purely ML-driven pattern discovery without ICT framing. Rejected because (a) the user can't validate black-box patterns, (b) interpretability matters for a trading partner, (c) ICT patterns have clear stop/TP logic built in.

### Why H4/D1 are bias-only, not entry timeframes

**Decision (Apr 28):** D1 and H4 generate bias tags (`htf_bias_long`, `htf_bias_short`, `htf_zone_*`) but never produce trade entries.

**Rationale:**
- D1 structural stops are 80-150+ pips wide. At 1% risk on a $100 account with 0.01 lots, max stop is ~30 pips. D1 stops literally don't fit.
- H4 stops are 40-80 pips — marginal on a small account.
- The user's edge is in intraday/swing setups on H1 (and experimentally M15), not position trades.
- HTF bias as a filter for LTF entries adds value without the sizing constraint.

### Why M15 underperforms vs H1

**Discovery (May 3, confirmed May 13):** M15 achieves 50% WR vs H1's 91.7% WR in 2026 data. Walk-forward: M15 = 2/3 folds profitable (+$126), H1 = 3/3 folds (+$1,454).

**Explanation:**
- M15 is noisier: more false breakouts, smaller moves get clipped by spread.
- The detectors were calibrated for H1-scale patterns. M15 patterns are structurally different (faster formation, shorter lifespan).
- M15 needs a stricter scorer threshold (0.40 vs H1's 0.30) to compensate, which reduces trade count to near-zero in some quarters.
- **Decision:** H1 is the production engine. M15 stays experimental until we have more data or a better model class.

### User's trading style and identified edge

**Documented (May 13) from W18-W19 journal ingestion:**

- **Style:** Scalper, 0.01 lots (capital preservation phase), 89% WR on 28 trades in W19.
- **Edge:** Liquidity zones from wicks → Fibonacci entries (38.2% and 61.8% levels) → PD (prior day) range for directional bias.
- **Multi-entry:** Opens multiple positions at different fib levels within the same zone.
- **Best fib levels:** 38.2% and 61.8% (confirmed by both user's journal and 3-year audit data).
- **No-trade rule:** Consolidation days (open ≈ close on D1) are skipped — no directional bias available.

---

## Technical Architecture Decisions

### Why Ollama for local LLM

**Decision (May 1):** Use Ollama for all LLM tasks instead of OpenAI/Anthropic APIs.

**Rationale:**
- **Privacy:** The journal contains real account balances, trade history, and personal trading style. Not data to send to third-party APIs.
- **Cost:** Zero ongoing per-request cost. The user's M4 Mac can run 7B-14B models comfortably.
- **User's preference:** Explicitly requested local-only processing.
- **Offline capability:** Agent works without internet (graceful fallback when Ollama is down).
- **Models chosen:** `qwen2.5:7b-instruct` for chat (fast interactive responses), `qwen2.5:14b-instruct` for extraction (better JSON-mode compliance at this size). `llama3.2-vision:11b` for chart reading.

### Why precision gates were added

**Decision (May 3, morning):** Add `require_precision_partner`, `blocked_session_tags`, and `require_fvg_or_sweep_with_bos` gates.

**Trigger:** The W18 detector audit showed catastrophic bleed from specific signal types:
- `session_london_ny_overlap` alone: 20% WR / -153 pips / 10 trades
- `bos`-only entries: 39% WR / -144 pips / 18 trades
- `zone`-only entries: 47% WR / -84 pips / 38 trades

**Rationale:** A "precision partner" (FVG or tagged liquidity sweep) proves price has *committed* to a direction. A zone alone just says "there's a level here." A BOS alone says "structure broke" but doesn't confirm re-entry timing. The partner tag converts a passive level into an active opportunity.

**Result:** W18 went from -$608 (38 trades) → +$41 (7 trades) → +$580 (5 trades, with direction-aware sweeps + H1 min_conf=3).

### Why direction-aware sweeps

**Decision (May 3, afternoon):** Enforce `HIGH-type → SHORT only`, `LOW-type → LONG only`, `MID-type → dropped`.

**Trigger:** H1 audit on W18 showed semantically incorrect sweep classifications:
- When EUR/USD fell below PWL, the detector classified PWL as an "upper target" (mathematically correct — it's above price). A wick through PWL emitted `sweep_PWL direction=SHORT`. This was mathematically right but ICT-semantically wrong.
- Mid-level sweeps (`sweep_PDM`, `sweep_PWM`) were 0/3 wins, -25 pips.

**Fix:** The rules engine now enforces ICT semantics regardless of what the detector emits:
- PDH/PWH/swing_high/equal_highs can only partner with SHORT setups (buyside liquidity → sell).
- PDL/PWL/swing_low/equal_lows can only partner with LONG setups (sellside liquidity → buy).
- PDM/PWM are dropped entirely (not real liquidity pools).

### Why the zone detector uses local rolling median

**Decision (May 3, evening):** Replace global `median_body` with a per-impulse local rolling median.

**Bug:** The original detector computed `median_body` from the LAST 200 bars of the entire series. In a 3-year backtest, every 2023 impulse was judged against 2026 volatility. If 2026 was less volatile, 2023 impulses looked relatively strong and passed; if more volatile, they got suppressed.

**Fix:** Window of 200 bars *centered on the impulse bar*, clamped to series boundaries. Each impulse is judged against its own local volatility context.

### Why zone age filter was moved from detection to evaluation time

**Decision (May 3, evening):** Age filtering happens in `evaluate_precomputed()` and `fresh_zones()`, not in `detect_zones()`.

**Bug:** `detect_zones()` pruned with `(len(bars) - 1 - z.created_bar_index) <= max_age_bars`. On a 75,000-bar M15 series with `max_age_bars=500`, only zones from the last 500 bars survived. Bar 1,000 saw zero zones because they'd all been pruned relative to bar 75,000.

**Fix:** `detect_zones()` returns ALL zones. Age is checked relative to `at_index` at query time:
```python
zones = [z for z in ctx.zones
         if z.created_bar_index <= at_index
         and (at_index - z.created_bar_index) <= max_age_bars]
```

This means bar 1,000 correctly sees zones from bars 500-999.

### Why the structural anchor gate

**Decision (May 3, evening):** Require fib retrace OR range phase (distribution) OR NY session label, in addition to the precision partner.

**Data:** The 3-year audit showed every profitable combo had at least one structural anchor:
- `fvg + phase_distribution + zone`: 90% WR / +473 pips
- `fib_382 + sweep_swing_high + zone`: 54% WR / +343 pips
- `fib_382 + fvg + zone`: 100% WR / +321 pips

Setups with a precision partner but NO anchor (bare zone + FVG in random market) were the biggest bleed contributors.

**Rationale:** The anchor proves the trigger is occurring at a *meaningful structural location*, not random noise. A fib retrace means price pulled back to a key level. Distribution phase means smart money is offloading. NY session means institutional flow is active.

---

## UX Decisions

### Why voice defaults to off

**Decision (May 13):** Voice auto-play disabled by default.

**Trigger:** User found constant agent talking "annoying" during normal chart review.

**Rationale:** Voice is useful for hands-free journal entry and occasional queries, but the agent narrating every analysis is distracting during active trading. User can opt-in via the microphone button when they want spoken interaction.

### Why agent annotations default to off

**Decision (May 13):** Agent detector overlays hidden by default, shown via "Show AI Analysis" toggle.

**Trigger:** User said many agent annotations were "rubbish" — low-quality zone/BOS markings cluttering the chart.

**Rationale:** The detectors produce many signals; only the gated, high-confluence ones are worth trading. Showing every detection overwhelms the chart. The toggle lets the user opt in when they want the agent's perspective, rather than fighting against unwanted visual noise.

### Why the "trading partner" personality

**Decision (May 13):** Rewrote the agent's system prompt to be a genuine trading partner — direct, honest, challenges bad setups.

**Rationale:** The original prompt produced a "yes-man" that agreed with everything the user said. A trading partner should:
- Push back when a setup looks weak.
- Point out when the user is overtrading or ignoring their own rules.
- Give honest post-trade analysis, not just validation.
- Use ICT terminology naturally (not explain basics every time).

---

## Infrastructure Decisions

### Why per-TF scorers

**Decision (May 3, late evening):** Train separate ML models for H1 and M15 instead of one global scorer.

**Data:** The single global scorer was trained on mixed H1+M15 data. H1 patterns (wider zones, longer-lasting FVGs, slower BOS) are fundamentally different from M15 patterns. The global model underfit both.

**Result:** Per-TF scorers (M15@0.40 threshold, H1@0.30) lifted the 3-year backtest from -37.6% (v6) to +5.1% (v10). Walk-forward confirmed: H1 alone = +$1,454 / 3/3 folds positive.

### Why walk-forward validation matters

**Decision (May 3):** Never ship a scorer without walk-forward validation.

**Discovery:** A scorer trained on 2021-2024 and frozen gave -9.3% on 2025-2026. The same architecture with per-fold retraining gave +5%. Static scorers don't generalize — the forex regime drifts.

**Solution:** `scripts/retrain_scorers.py` retrains quarterly with promotion gates. `scripts/walk_forward.py` validates before any deployment.

### Why Docker is dashboard-only

**Decision (May 3):** The Docker container runs the dashboard but NOT the live trading loop.

**Rationale:** MetaTrader5 is Windows-only. Live trading requires a Windows VPS with MT5 installed. The Docker image serves the dashboard/journal for users on macOS/Linux who want to review trades without setting up a Windows environment. Backtests can run in Docker too.

---

## Blocked Hours (NY Time)

**Decision (May 3):** Block trading during NY hours 03, 04, 12, and 13.

**Data from 3-year audit (2023-05 → 2026-05):**
- NY 03:00 (London open chop): 44.9% WR / -448 pips / 69 trades
- NY 04:00 (London early): 45.5% WR / -214 pips / 55 trades
- NY 12:00 (London close): 44.5% WR / -402 pips / 146 trades
- NY 13:00 (NY pre-close chop): 32.9% WR / -857 pips / 70 trades

Combined: -1,921 pips across 340 trades. All four are statistically significant losing windows.

---

*Add new decisions with the date, what was decided, what triggered the decision, and the data/reasoning behind it.*
