# 05 — Position Sizing & Risk

> ⚠️ **PARTLY CURRENT.** Sections **05.1–05.5** describe live machinery.
> Sections **05.6–05.8** are **historical v1 studies** — their backing modules
> (`managed_exit.py`, `portfolio.py`, `run_learning_backtest.py`) were burned in
> the v2 reset. Signals now come from the **validated zone router**
> (`agent/alphas/zone_routing.py`); see [CHECKPOINT.md](CHECKPOINT.md) and
> [08 — Live Trading](08-live-trading-and-deployment.md).

> Part of the numbered docs — start at [00 — Overview](00-overview.md).

---

## 05.1 Adaptive / risk-based position sizing

**Code:** `agent/live/position_sizer.py` (`PositionSizer`) and
`agent/risk/sizing.py` (`position_size` — final min-lot / pct-floor gate in
`risk/manager.py` before the conviction sizer runs).

The sizer computes the lot that risks a chosen % of live balance:

```
lot = (balance × risk_pct) / (stop_distance_pips × pip_value)
```

then rounds down to the broker lot step, clamps to `[min_lot, max_lot]`, respects
free margin under leverage, and optionally caps at a manual `--lot` override.

**Conviction scaling (current):** `risk_pct` interpolates within
`--risk-min`…`--risk-max` (default 0.5%–2.0%) from the zone signal's conviction
score. The deployment router's per-cell **`risk_scale`** multiplies this before
sizing (GBPUSD/USDCAD deploy at 0.5×). There is no ML scorer or reaction composite
on the live path.

**Oversize hard cap:** no single trade may risk more than `max_trade_risk_pct`
(default **2%**). Logs show `capped_by=max_risk_hard` when the clamp fires.

Live balance, free margin and leverage come from the broker on every trade.

---

## 05.2 Risk controls

Hard gates in `agent/risk/manager.py` and `config/default.yaml`:

| Control | Behaviour |
|---------|-----------|
| **Daily drawdown halt** | Stops new trades when the day's loss hits 3% of day-open balance. |
| **One position at a time** | No stacking or martingale. |
| **Breakeven at 1R** | Stop moves to entry (or entry + `be_lock_r`) once price moves 1× stop in favour. |
| **Stop bounds** | ATR-aware min/max stop size. |
| **R:R minimum** | Setups whose target doesn't clear `min_rr` are rejected. |
| **Kill switch** | `kill.txt` in the project root halts all new trades. Delete to resume. |

These caps are never overridden by vault stats or observation scripts.

---

## 05.3 Mandatory SL/TP enforcement

**Code:** `agent/live/broker.py` (`validate_sltp`) +
`SignalLoop._ensure_sl_tp`.

Every order must carry structural SL and TP on the correct side of price. Missing
brackets are derived or the trade is refused (`skip_no_sltp`). No code path opens
a naked position.

---

## 05.4 Post-loss cooldown / no-revenge guard

**Code:** `agent/risk/post_loss_guard.py` (`PostLossGuard`), wired into
`SignalLoop`.

| Guard | Default | Behaviour |
|-------|---------|-----------|
| **Cooldown after a loss** | 60 min | No new entry until elapsed. |
| **Size reduction after a loss** | ×0.5 | Next trade at half risk until a win. |
| **Consecutive-loss circuit breaker** | 3 | Halt new entries for the rest of the session. |
| **Stop-out halt** | 10% of balance | Single catastrophic loss halts the session. |
| **Re-deposit guard** | — | State keyed on UTC day + outcomes, not balance. |

State persists via `agent/live/state_store.py` (`state.json` sidecar).

---

## 05.5 Synthetic ("soft") stop

**Code:** `agent/live/soft_stop.py`, managed by `PositionMonitor`.

Two-layer stop: a **soft stop** (agent memory, bar-close confirmation) defines
real risk; a **catastrophe stop** (broker resting order at 2.5× soft distance)
is offline insurance only. On restart, adopted positions without persisted ctx get
a synthetic ctx from the broker SL (see `ai_context.md` v0.11).

---

## 05.6–05.8 — Historical v1 studies

> **HISTORICAL.** The gate-loosening sweep (05.6), managed-exit A/B (05.7), and
> portfolio pyramiding study (05.8) measured the v1 reaction engine and modules
> that no longer exist. Findings are preserved in
> [`archive/10-quant-validation-and-modular-overhaul.md`](archive/10-quant-validation-and-modular-overhaul.md).
> Do not treat 05.6–05.8 as describing live behaviour.

**05.9 Legacy lot tiers:** fixed `--lot` bypass still respects historical hard
caps (0.01 under $300, etc.); with the adaptive sizer, `--lot` is an upper cap only.
