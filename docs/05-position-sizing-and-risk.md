# 05 — Position Sizing & Risk

> Part of the numbered docs — start at [00 — Overview](00-overview.md). The signals
> being sized come from [02 — Strategies](02-strategies.md) and
> [04 — Reaction Engine](04-reaction-engine.md).

---

## 05.1 Adaptive / risk-based position sizing

**Code:** `agent/live/position_sizer.py` (`PositionSizer`, `SymbolConstraints`,
`SizingResult`).

The legacy `--lot` hard-coded one size regardless of stop distance. The sizer
instead computes the lot that risks **exactly** a chosen % of live balance:

```
lot = (balance × risk_pct) / (stop_distance_pips × pip_value)
```

then:

- rounds **down** to the broker lot step (never exceeds the risk budget),
- clamps to `[min_lot, max_lot]` (snaps a tiny account up to min lot only if the
  resulting risk stays within band),
- never exceeds free margin under leverage
  (`margin_per_lot = contract_size × price / leverage`),
- optionally caps at a manual `--lot` override.

**Conviction scaling:** `risk_pct` is interpolated within a band
(`--risk-min`…`--risk-max`, default 0.5%–2.0%) by signal conviction — a blend of
HTF alignment + ML score + setup quality for anticipation, and the reaction
composite for reaction trades. High conviction → more size; marginal → less.

**Oversize hard cap:** independent of the conviction band, no single trade may
risk more than `max_trade_risk_pct` (default **2%**, `--max-trade-risk`). Any
computed/override lot above that is **clamped down** to the 2%-risk lot — but
never below the broker minimum, so a small account can still trade its smallest
size. This is what turns a 1.0-lot-on-$100 intent into a 0.01-lot trade
(`capped_by=max_risk_hard`). See 05.5 for how this maps to the Jun 2 disaster.

Live balance, free margin and leverage are pulled from the broker (`account_info`)
on every trade. The full math is surfaced in the logs:

```
SIZING: balance=$100.00 | conviction=0.73 -> risk=1.59% ($2.28) | stop=23p
        | lot=0.01 | margin=$1.15/$100.00 free | capped:min_lot
```

The sizing band maps to config: `--risk-min` / `--risk-max` (CLI) →
`LiveConfig.risk_min_pct` / `risk_max_pct`.

---

## 05.2 Risk controls

These hard gates apply to **every** trade regardless of source (anticipation,
reaction, or flip). They live in `agent/risk/manager.py` and `config/default.yaml`.

| Control | Behaviour |
|---------|-----------|
| **Daily drawdown halt** | Stops all new trades when the day's loss hits 3% of the day-open balance. |
| **One position at a time** | No stacking, no martingale, no scaling in — each trade gets full risk allocation. |
| **Breakeven at 1R** | Once price moves 1× the stop distance in favour, the stop moves to entry (or entry + `be_lock_r`). Kills the "went 3R then stopped at −1R" scenario. |
| **Stop bounds** | ATR-aware min/max stop size; optional `enforce_live_stop_cap` for tiny accounts. |
| **R:R minimum** | Setups whose structural target doesn't clear `min_rr` are rejected. |
| **Kill switch** | Writing `kill.txt` in the project root (or clicking it in the dashboard) halts all new trades immediately. Delete it to resume. |

Everything here is configurable in `config/default.yaml`. The online performance
memory in [06](06-learning-journal.md) adjusts *conviction* (and therefore size via
05.1) but never overrides these hard caps.

---

## 05.3 Mandatory SL/TP enforcement

**Code:** `agent/live/broker.py` (`BrokerConnection.validate_sltp`, called inside
both `MT5Broker.place_order` and `PaperBroker.place_order`) +
`SignalLoop._ensure_sl_tp` in `agent/live/signal_loop.py`.

Every order the agent sends **must** carry a structural stop loss and a take
profit on the correct side of price. Enforcement is two-layered:

1. **Derive-or-refuse (signal loop).** Before sizing, `_ensure_sl_tp` checks the
   setup. If a stop or target is missing/invalid it derives one — an ATR-based
   structural stop (`reaction.stop_atr_mult` + `stop_buffer_pips`) and an R:R
   target (`max(min_rr, fallback_rr)`). If a valid bracket still can't be formed,
   the trade is **refused** (`skip_no_sltp`).
2. **Hard broker invariant.** `validate_sltp` runs at the top of *both*
   `place_order` paths and rejects any order with a zero/None SL or TP, or an
   SL/TP on the wrong side of price. There is **no code path that opens a naked
   position** — the post-mortem found the user traded naked on 10 of 11 trades;
   that is now structurally impossible.

```
Order REFUSED (SL/TP guard): missing SL/TP (naked order refused) [EURUSD long lot=0.10]
```

---

## 05.4 Post-loss cooldown / no-revenge guard

**Code:** `agent/risk/post_loss_guard.py` (`PostLossGuard`, `GuardConfig`), wired
into `SignalLoop._execute_signal` (pre-trade check + size reduction) and
`SignalLoop._on_trade_closed` (outcome recording).

A small state machine consulted **before every entry**. It reacts to the
*sequence* of recent outcomes — the layer the codebase was missing.

| Guard | Default | Behaviour |
|-------|---------|-----------|
| **Cooldown after a loss** | 60 min / 2 bars | No new entry for `post_loss_cooldown_minutes` (or `_bars`). Kills the instant revenge re-entry. |
| **Size reduction after a loss** | ×0.5 | Next trade's `risk_pct` is multiplied by `post_loss_risk_multiplier` until a **win** restores full size. Stops "sizing up to win it back". |
| **Consecutive-loss circuit breaker** | 3 | After `max_consecutive_losses` in a row, **halt new entries for the rest of the session/day** (separate from the daily-DD halt). |
| **Stop-out halt** | 10% of balance | A single loss ≥ `catastrophic_loss_frac` of balance (or a broker margin stop-out) halts the session immediately. |
| **Re-deposit guard** | — | State is keyed on the UTC trading day and on trade *outcomes only*, **never on balance** — re-funding a blown account does NOT clear a halt. |

All thresholds are configurable (`LiveTradingConfig` / `LiveConfig`) with CLI
flags: `--no-revenge-guard`, `--cooldown-minutes`, `--max-consecutive-losses`,
`--max-trade-risk`. Every action is logged in the verbose explainer (a
`STEP 0: RISK GUARD` block) and written to the journal so the user SEES it work:

```
BLOCKED by post-loss guard: post-loss cooldown active — 42 min remaining (until 11:13 UTC)
GUARD size reduction: risk x0.50 after 1 consecutive loss(es) (1.59% -> 0.80%)
Post-loss guard: circuit breaker — 3 consecutive losses; halting session
```

### How these map to the Jun 2 / Jun 5 disaster

| Real mistake (week review) | Guard that now prevents it |
|---|---|
| 1.0-lot BUY on a ~$100 account (margin stop-out, −$124) | **Oversize hard cap (05.1)** clamps it to 0.01 min lot; **mandatory SL (05.3)** means no naked margin stop-out — a −$124 becomes ~−$1–2. |
| Six revenge trades in ~24h after the blow-up | **Cooldown** blocks the immediate re-entry; the **catastrophic-loss / stop-out halt** stops the session after the −$124; the **re-deposit guard** keeps it halted after the $72 re-deposit. |
| Sizing 0.4 → 0.2 → 0.3 to "win it back" | **Size reduction ×0.5 after a loss** until a win. |
| Jun 5 0.3-lot naked BUY into the double top (−$58) | **Mandatory SL/TP** + the next-day reset still sized small under the guard. |

---

## 05.5 Gate-loosening study (Jun 2026)

The learning backtest ([07](07-backtesting.md)) showed ~32% of *declined* setups
would have won — evidence the gates were too strict. Using
`scripts/run_learning_backtest.py --conviction-threshold X` as the harness over a
2-year H1 window (start $100, 1:1000), we swept the reaction conviction gate:

| `conviction_threshold` | Trades | Profit factor | Expectancy | Max drawdown |
|---|---|---|---|---|
| 0.58 (old) | 36 | 0.63 | −0.184 R | 27.4% |
| **0.54 (new)** | 46 | **0.66** | **−0.135 R** | **26.2%** |
| 0.50 | 89 | 0.88 | −0.025 R | 30.9% |

**Decision:** lowered the default `conviction_threshold` **0.58 → 0.54**. It
improves profit factor and expectancy *and* lowers max drawdown — a conservative,
data-justified step. Going to 0.50 improved PF/expectancy further but pushed
drawdown to 30.9%, so we stopped at the conservative point per the "don't blow up
drawdown" rule. Re-run the sweep as more data lands.

---

## 05.6 Legacy lot tiers (fixed-lot fallback)

If you bypass the adaptive sizer with a fixed `--lot`, the historical hard caps
still protect a small account: 0.01 lot under $300, 0.10 under $1,000, 1.0 above.
With the adaptive sizer enabled, `--lot` acts only as an **upper cap** on the
risk-based size (and the 05.1 oversize hard cap still applies on top).
