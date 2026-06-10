# 05 — Position Sizing & Risk

> ⚠️ **PARTLY CURRENT.** The core machinery here still runs live: the adaptive
> `PositionSizer` (05.1), the hard risk gates (05.2), mandatory SL/TP (05.3),
> the post-loss / no-revenge guard (05.4) and the synthetic soft stop (05.5).
> Two updates: (1) signals now come from the **validated zone router** (not the
> v1 strategies / reaction engine — see [CHECKPOINT.md](CHECKPOINT.md)), and the
> router's per-cell **`risk_scale`** multiplies the conviction-band risk before
> sizing; (2) the studies in 05.6–05.8 (gate loosening, managed exit, portfolio
> pyramiding) are **historical** — their backing modules (`managed_exit.py`,
> `portfolio.py`, `run_learning_backtest.py`) were burned in the v2 reset along
> with the reaction-engine-first model they measured.

> Part of the numbered docs — start at [00 — Overview](00-overview.md). The signals
> being sized come from the zone deployment router
> (`agent/alphas/zone_routing.py`, see [08](08-live-trading-and-deployment.md)).

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
| **Flip override** | conviction ≥ 0.80, opposite side | A strong reaction **opposite** to the losing trade may **bypass the cooldown** — a committed flip into a reversal is not revenge. The circuit breaker / stop-out halt are **never** bypassed, and the flip is still taken at reduced (×0.5) size. |

**Why the flip override matters (the Jun-5 lesson).** The cooldown exists to stop
*revenge* — an emotional, same-side re-entry to win it back. But the Jun-5 break to
the lows was the market proving the long **wrong**: after being stopped on a long, a
0.92-conviction SHORT to the lows is exactly the trade a quant *should* take. A
blanket cooldown would handcuff the agent through the best move of the week.
`cooldown_override_conviction` (default 0.80, opposite-side only) lets that committed
flip through while still blocking same-side revenge and never touching the hard
halts. Config: `post_loss_cooldown_override_conviction`,
`post_loss_cooldown_override_opposite_only`.

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

## 05.5 Synthetic ("soft") stop — the stop-hunt mitigation

**Code:** `agent/live/soft_stop.py` (`evaluate_soft_stop`, `catastrophe_stop`,
`SoftStopConfig`), managed by `PositionMonitor._manage_soft_stop`, placed by
`SignalLoop._execute_signal`.

*Is stop-hunting real?* Partly — liquidity genuinely pools just beyond obvious
swing highs/lows and round numbers, and price often wicks into it to fill size
before reversing (this is the LZI concept). The wrong conclusion is to trade with
**no stop** (what blew the account). The professional answer is a **two-layer
stop**:

| Layer | Where it lives | Purpose |
|-------|----------------|---------|
| **Soft stop** (primary) | The agent's memory + `PositionMonitor` | The real risk level. Only acted on when a bar **closes** beyond it, so a single hunting wick can't take the trade out. Position size is computed from the *soft* distance, so it defines the real money at risk. |
| **Catastrophe stop** (backstop) | A real resting order on the broker | Placed `catastrophe_stop_mult`× (default 2.5×) the soft distance away. Exists only so a dead VM / lost connection can never cause a margin call. It is insurance, not the trade's risk. |
| **Panic exit** | `PositionMonitor` | If price blows clean through the soft level by `soft_stop_panic_mult`× (default 1.0×) the soft distance intrabar, the agent exits immediately instead of waiting for the bar to close. |

This gives the user exactly what they asked for — the "alerts on TradingView,
no resting stop in the pool" idea, but **automated and executed**, plus a disaster
backstop so the account can never be wiped again. Config lives in
`LiveTradingConfig` / `LiveConfig` (`soft_stop_enabled`,
`soft_stop_confirm_on_close`, `catastrophe_stop_mult`, `soft_stop_panic_mult`,
`soft_stop_min_catastrophe_pips`). Logs:

```
Soft stop 1.15780 (22p, real risk) | broker catastrophe backstop 1.15670 (55p, offline-only)
SOFT STOP fired for ticket=12345: bar closed at 1.15760 beyond soft stop 1.15780 — level confirmed broken (survived wicks)
```

**Smart placement still matters.** The soft stop should sit *beyond* the
liquidity pool (past the swing/level), not at the obvious round number — the LZI
detector already knows where those pools are, so stops land on the safe side.

---

## 05.6 Gate-loosening study (Jun 2026)

The learning backtest ([07](07-backtesting.md)) showed ~31% of *declined* setups
would have won — evidence the gates were too strict. Using
`scripts/run_learning_backtest.py --conviction-threshold X` as the harness over a
2-year H1 window (start $100, 1:1000), we swept the reaction conviction gate:

| `conviction_threshold` | Trades | Win% | Expectancy | Profit factor | Return | Max DD |
|---|---|---|---|---|---|---|
| 0.54 (old) | 46 | 21.7% | −0.135 R | 0.66 | −18.0% | 26.2% |
| **0.50 (new)** | 89 | 24.7% | −0.025 R | **0.88** | −11.6% | 30.9% |
| 0.46 | 108 | 25.0% | +0.028 R | 0.97 | −3.8% | 33.4% |

**Reading:** expectancy and profit factor improve *monotonically* as the gate
loosens — the strict gate was filtering out marginally-positive trades along with
the bad ones. But drawdown grows too. **Decision:** lowered the default
`conviction_threshold` **0.54 → 0.50** (most of the expectancy gain for the
smallest drawdown cost). We did **not** go to 0.46 — 33% DD is too deep for a
$100 account.

**Controlling the extra drawdown — HTF directional filter on the reaction path.**
The looser gate admits more trades, so to stop them becoming counter-trend bleed
(the post-mortem's most expensive habit), reactions are now screened for trend in
`SignalLoop._reaction_action`: a reaction that **agrees** with the HTF bias gets a
small conviction boost (`reaction_htf_boost`, +0.05); one that **fights** it gets
a penalty (`reaction_htf_penalty`, −0.12) and is **dropped** if that pushes it
below threshold (flips are exempt). The HTF-blind backtest above does not model
this, so live drawdown should sit below those figures. Re-run the sweep as more
data lands.

---

## 05.7 Managed exit — partial scale-out + delayed-but-decisive entry (Phase C)

The desk reflex on a confirmed impulse is "book a partial, push the rest to
break-even, let the runner chase the demand/supply zone." We built that as a
**measurable** policy (`agent/risk/managed_exit.py`) and A/B'd it before wiring it
live, because variance reduction is only worth it if it doesn't trade the edge
away.

**Finding (the important part).** For the current lead alpha (`reaction + ERL/IRL`)
**partial scaling-out is net-negative**: it halves P&L variance (σ 94 → 63) and
lifts win-rate to ~50%, but it **degrades PF (1.12 → ≤1.03) and turns expectancy
negative**. In the London/NY overlap — the alpha's best window — the baseline
"let the runner reach the draw" stance posts exp +12.9 pips / **Sharpe 2.0**,
and every scale-out variant collapses that toward zero. The edge of this alpha
**is the runner reaching the HTF draw** (the fat right tail); booking ⅔ at 1R and
BE-stopping the rest converts winners into scratches. Full A/B in
[10 §10.5](10-quant-validation-and-modular-overhaul.md); reproduce with
`python scripts/evaluate_alphas.py --manage`.

**What this means for "risk control on the overlap."** It is *not* chopping
winners. It is the stack already documented here — adaptive conviction-scaled
sizing (05.1), the mandatory SL/TP (05.3), the post-loss / consecutive-loss
guards (05.4), and the wick-proof soft stop (05.5) — **plus** routing the overlap
to the reaction engine (session selectivity, [04.2d](04-reaction-engine.md)) and
**letting the runner ride to the draw**.

**Shipped, gated off.** The machinery exists for alphas/regimes whose edge is not
tail-driven, but it stays disabled until a config proves it earns its keep:

| Knob (`LiveConfig`) | Default | Meaning |
|---|---|---|
| `partial_exit_enabled` | `False` | book `partial_fraction` at `partial_at_r` R |
| `partial_fraction` | `0.5` | fraction of the position closed at the partial |
| `partial_at_r` | `1.0` | R-multiple of MFE that triggers the partial |
| `partial_move_to_be` | `True` | push the runner to break-even after the partial |
| `min_room_rr` | `0.0` (off) | **delayed-but-decisive**: skip a late entry unless RR-to-target still clears this floor |

Live plumbing: the broker supports partial closes (`close_position(volume=…)`,
MT5 + paper), the monitor books the partial and moves the runner to BE
(`PositionMonitor._manage_partial_scaleout`), and the signal loop refuses
no-room-left chases when `min_room_rr > 0`. The delayed-decisive guard is the one
piece that is roughly P&L-neutral *and* preserves the overlap edge, so it is the
recommended "decisive entry" discipline to enable first.

## 05.8 Multi-position / pyramiding behind a risk budget (Phase D)

The single-position slot is a *limiter*, and the natural question is whether
lifting it — pyramiding into a winning run, flipping on a committed reversal —
earns more than it risks. We built the policy as a pure, testable
`PortfolioRiskManager` (`agent/risk/portfolio.py`) with four non-negotiable
guardrails, then **measured** it on the equity curve before exposing it.

**Guardrails (always enforced when enabled):**

1. **Aggregate risk cap** — total open risk ≤ `aggregate_risk_cap_pct` of equity.
2. **Max-N concurrent** — never more than `max_concurrent` positions.
3. **Exposure-decaying size** — each add is `base × decay^(open_count)`, then
   clamped to the remaining budget.
4. **Net, don't offset** — an opposite signal **flips** (close the losers, open
   the winner); the agent never holds a hedged long+short pair on one instrument.

**Finding — it fails the gate, so it ships off.** A/B on the lead alpha
(`reaction + ERL/IRL`, equity terms, 1% base risk;
`agent/alphas/portfolio_backtest.py`):

| Mode | return | maxDD | ret/DD |
|---|---|---|---|
| single (baseline) | −4.0% | **24.0%** | −0.17 |
| flip-only | −16.5% | 37.9% | −0.44 |
| pyramid ×2 + flip | −7.9% | 41.8% | −0.19 |

Lifting the slot **balloons drawdown to 38-42%** and worsens return — flips churn
(the reaction engine's opposite signals aren't reliable reversals, so each flip
pays spread to bleed) and pyramiding stacks risk into moves that reverse. So the
**single-position slot stays the default protective limiter.** The genuinely useful
"flip" — a high-conviction committed reversal bypassing the post-loss cooldown —
already lives in 05.4 and needs no concurrent exposure. The portfolio machinery is
wired live behind `LiveConfig.portfolio_enabled` (**default off**) for future
alphas/regimes where concurrency might pay. Detail:
[10 §10.7](10-quant-validation-and-modular-overhaul.md).

## 05.9 Legacy lot tiers (fixed-lot fallback)

If you bypass the adaptive sizer with a fixed `--lot`, the historical hard caps
still protect a small account: 0.01 lot under $300, 0.10 under $1,000, 1.0 above.
With the adaptive sizer enabled, `--lot` acts only as an **upper cap** on the
risk-based size (and the 05.1 oversize hard cap still applies on top).
