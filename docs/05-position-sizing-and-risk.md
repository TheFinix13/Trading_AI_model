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

## 05.3 Legacy lot tiers (fixed-lot fallback)

If you bypass the adaptive sizer with a fixed `--lot`, the historical hard caps
still protect a small account: 0.01 lot under $300, 0.10 under $1,000, 1.0 above.
With the adaptive sizer enabled, `--lot` acts only as an **upper cap** on the
risk-based size.
