# 06 — Learning Journal & Observability

> ⚠️ **PARTLY HISTORICAL.** The v1 `LiveJournal` + online performance memory
> (`agent/journal/live_journal.py`, `performance_memory.py`) were **burned in the
> 2026-06-09 reset**. The v2 stack below is what runs live today. Strategy
> changes happen only through the ablation / walk-forward gates — not from
> mid-flight conviction adaptation. See [CHECKPOINT.md](CHECKPOINT.md).

> Part of the numbered docs — start at [00 — Overview](00-overview.md).
> Trades are sized per [05 — Position Sizing & Risk](05-position-sizing-and-risk.md).

---

## What's live today (2026-06-24)

| Layer | Code / path | Purpose |
|---|---|---|
| Daily rolling log | `{log_root}/{SYMBOL}/YYYY-MM-DD.log` | Bracketed events: `[SIGNAL]`, `[TRADE OPENED]`, `[LADDER]`, `[TRADE CLOSED]`, etc. UTC rollover, 30 days kept |
| Near-miss vault | `{log_root}/{SYMBOL}/vaults/near_misses.jsonl` + PNG | Setups rejected by gates — observation only |
| Loss vault | `{log_root}/{SYMBOL}/vaults/losses.jsonl` + PNG | Closed losers with chart snapshot |
| Target ladder | `{log_root}/{SYMBOL}/ladders/events.jsonl` | Structural rungs beyond 1.5R TP — observation only |
| State sidecar | `{log_root}/{SYMBOL}/state.json` | Crash-resilient monitor / guard / bar-time persistence |
| Daily summary | `scripts/daily_summary.py` | Walks logs + vaults + state; auto-saves to `{log-dir}/summaries/` |
| Near-miss resolver | `scripts/resolve_near_misses.py` | Hypothetical outcome scoring for vault entries |

Vault and ladder stats **never move a gate**. Gate changes require the full
validation pipeline (grid → holdout → walk-forward).

---

## 06.1 Daily log format

Every fill logs pip distances and TP R-multiple inline:

```
[TRADE OPENED] … soft_sl=P (Np) catastrophe_sl=P (Np) tp_mech=P (X.XR, +Np)
[LADDER] … mirror of ladders/events.jsonl
```

On restart, `[POSITION ADOPTED|RESTORED]` uses the same shape; soft-stop inference
rebuilds ctx from broker SL when none was persisted.

---

## 06.2 Vault chart snapshots

**Code:** `agent/journal/chart_snapshot.py`, written by `agent/journal/vault.py`.

Near-miss and loss vaults store JSONL records plus PNG snapshots: solid entry,
dashed SL/TP, zone rectangle coloured by side, rejection detail in caption.

---

## 06.3 Target ladder (observation-only)

**Code:** `agent/journal/target_ladder.py`.

Structural rungs (swing, zone edge, trendline, fib ext, daily level) beyond the
1.5R TP are journaled and scored against realised MFE at close. Report:
`scripts/report_target_ladders.py --symbol <SYM>`.

---

## 06.4 Daily summary report

**Code:** `scripts/daily_summary.py`.

One paste-friendly block per run: window activity + cumulative vault stats
(ladder reach rates, near-miss resolution counts). Pure observation.

---

## v1 historical — LiveJournal & performance memory (burned)

> The sections below described `agent/journal/live_journal.py` and
> `agent/journal/performance_memory.py`. Neither module is imported by the live
> loop. Preserved in [`archive/06-learning-journal-v1-body.md`](archive/reaction_and_learning.md)
> via the old combined doc; do not wire these patterns back without explicit
> validation.

The v1 journal wrote dual-layer markdown + JSONL per day with win/loss
attribution, counterfactual MAE/MFE analysis, declined-setup tracking, daily
roll-up calibration, and an online performance memory that adjusted conviction
from realised signature stats. That mid-flight adaptation path was eliminated
because it violates the validated pipeline's no post-hoc tuning rule.
