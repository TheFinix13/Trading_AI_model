# 06 — Learning Journal & Performance Memory

> Part of the numbered docs — start at [00 — Overview](00-overview.md). The trades
> recorded here come from [04 — Reaction Engine](04-reaction-engine.md) /
> [02 — Strategies](02-strategies.md) and are sized per
> [05 — Position Sizing & Risk](05-position-sizing-and-risk.md). The history-replay
> version that writes the same records day-by-day is the
> [learning backtest (07.2)](07-backtesting.md#072-learning-backtest).

The agent keeps a **present-time** journal — it learns from when it runs *now* — and
a lightweight **online performance memory** that feeds results back into conviction.

---

## 06.1 Fresh present-time journal

**Code:** `agent/journal/live_journal.py` (`LiveJournal`).

On startup with `--reset-journal`, any existing live-journal files are moved aside
into `data/journal/archive/` (history is never deleted) and a fresh store is started
under `data/journal/live/`.

Every record is **dual-layer**: a human-readable prose narrative in the markdown
**and** structured machine fields in the JSONL sidecar — readable by a person,
aggregable by the agent. One file per calendar day
(`data/journal/live/YYYY-MM-DD.md` + `.jsonl`):

- **Market read at the open** — HTF bias, anticipated vs reactive view, active zones.
- **Intraday notes** — moves, levels taken, flips.
- **Every trade** — entry/stop/TP, R:R, lot, conviction (+ band), setup signature,
  the full sizing math, and the rationale.
- **Every exit** — win/loss, P&L, pips, R-multiple, MAE/MFE, **attribution**,
  **counterfactual**, and a loss-focused reflection.
- **Declined setups** — detected-but-not-taken signals (light).
- **Daily roll-up** — conviction calibration + anticipated-vs-reactive scorecard.
- A **full feature snapshot at entry** is written to the JSONL sidecar for later
  scorer retraining.

---

## 06.2 Win/loss attribution (per closed trade)

Every exit is attributed to one of four categories, derived from conviction at
entry vs the outcome — because the two failure types need *opposite* fixes:

| Attribution | Meaning | Fix |
| --- | --- | --- |
| `good_setup_won` | High conviction, won | repeat the signature |
| `marginal_win` | Low/med conviction, won | fine, but don't over-weight |
| `good_setup_failed` | High conviction, lost to variance | accept it — process was right |
| `bad_setup` | Low/med conviction, lost | tighten the filter — shouldn't have fired |

Thresholds (`agent/journal/live_journal.py`): high conviction ≥ `HIGH_CONVICTION`
(0.66); calibration bands split low/med/high at `BAND_LOW` (0.55) / `BAND_HIGH`
(0.70). Attribution is stored as a JSONL field **and** surfaced in the prose
reflection (`[good_setup_failed] …`).

---

## 06.3 Counterfactual (from MAE/MFE)

Each exit computes whether a different stop/target would have changed the result,
stored as `mae_r`, `mfe_r`, `gave_back_r`, `alt_tp_would_have_helped`,
`alt_stop_would_have_helped`, plus a one-line note, e.g.:

- loss: *"stopped out but MFE was +1.4R — TP too far / exit too late"*
- win: *"winner but MAE was −0.9R — entry early / stop nearly hit"*
- win: *"gave back 2.0R after peak — consider a trailing stop / partial"*

A closed-trade block reads like this (note attribution + counterfactual):

```
- **Closed #1:** 2025-11-05 23:00 @ 1.14964 (sl) — **LOSS ❌** -2.50 (-24p, -1.07R)
- **Attribution:** `good_setup_failed` | conviction 0.73
- **Excursion:** MAE 23p (-1.0R) / MFE 5p (+0.2R)
- **Counterfactual:** never worked (MFE only +0.2R) — entry likely against true momentum
- **Lesson:** [good_setup_failed] never worked ... wait for stronger commitment.
```

---

## 06.4 Declined setups (the over-strict-filter detector)

When a setup is detected but **not** taken (gate failed, conviction below
threshold), it is logged lightly: signature, why declined, conviction. In **live**
mode that's all (cheap). In the **backtest**, a `would_have_won` verdict is computed
by walking the next N bars (`--decline-lookahead`, default 24) against a nominal ATR
stop and the fallback-R:R target — so an over-strict filter shows up directly. Detail
lines are capped per day (`max_decline_detail_per_day`); every decline is still in
the JSONL.

```
- `declined` (reaction) `Reaction|long|london|htfNA|reaction` conv=0.37: conviction 0.37 < 0.58 — would-have: win next 24b (+2.06R/-0.07R)
```

---

## 06.5 Daily roll-up: conviction calibration + scorecard

At each day rollover the journal writes a roll-up:

- **Conviction calibration** — the day's (and rolling) trades bucketed by conviction
  band with realised win-rate + expectancy per band. If high-conviction trades don't
  actually win more than low-conviction ones it prints `⚠️ MISCALIBRATED` — the key
  "is it really learning like a quant" diagnostic.
- **Anticipated-vs-reactive scorecard** — per perspective: how many were *marked*
  (detected) vs *acted* (taken), the win-rate/expectancy of those acted, declined
  count, and (backtest) how many declined would have won — plus which perspective
  paid the most.

```
## Daily Roll-up
- **Trades:** 2 | wins 1 | expectancy +0.47R
- **Attribution:** bad_setup=1, good_setup_won=1
- **Conviction calibration (today):**
  | band | n | win% | expectancy R |
  | --- | --- | --- | --- |
  | high | 2 | 50% | +0.47 |
- **Calibration verdict (rolling, n=37):** ⚠️ MISCALIBRATED — high-conviction trades are NOT outperforming ...
- **Anticipated vs reactive scorecard:**
  - **reaction:** marked 11 / acted 2 / declined 9 | win 50% | exp +0.47R | declined-would-have-won 3
  - **Paid the most:** reaction
- **Declined setups:** 9 (of which 3 would have won — filter may be too strict)
```

---

## 06.6 Online performance memory (the learning loop)

**Code:** `agent/journal/performance_memory.py` (`PerformanceMemory`,
`make_signature`).

Each trade is keyed by a **setup signature**:

```
strategy | direction | session | htf_aligned | source(reaction|anticipation)
```

The memory tracks realised **win-rate** and **expectancy (R)** per signature and
returns a bounded **conviction adjustment** (±`max_adjustment`, ramped by sample
size, requires ≥ `min_samples` trades). That adjustment is added to a setup's
conviction *before* sizing — so the agent leans into the signatures that have been
working and de-weights the ones that haven't, without waiting for a heavy offline
retrain. State persists to JSON and survives restarts.

The feedback prints on every close:

```
LEARN: Reaction|short|london|htfNA|reaction -> -1.07R | signature n=4 wr=0% exp=-0.33R next-adj=-0.013
```

> The heavier follow-on — periodic full ML-scorer retraining on the captured
> feature snapshots — is intentionally separate. The journal captures exactly the
> data that retrain needs; this online memory is the always-on, day-to-day
> adaptation.
