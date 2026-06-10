# EURUSD AI Agent — a validation-first FX zone-fade portfolio

A trading agent that runs **one statistically validated strategy** across three
FX majors, instead of an ensemble of indicators. It began as a codified
discretionary ICT system with seven stacked concepts; that version produced
impressive in-sample numbers and noise out of sample, so it was burned and
rebuilt around a strict rule: **every concept must earn its place alone, with
bootstrap p-values and multiple-testing correction, before it touches live
money**. One concept survived — supply/demand zones — and one configuration of
it passed holdout, walk-forward, and frozen cross-pair validation. That is what
trades today, on a demo account. This is a research-discipline project, not a
"profitable bot" pitch.

## The validated strategy

`zone_d1_against`: an H4 supply/demand zone touch **faded against the D1
trend** (the zone edge is mean-reversion — trading it *with* the higher-TF
trend destroys it). The same logic, byte-for-byte, is deployed on three
symbols via a routing table (`agent/alphas/zone_routing.py`):

| Symbol | Cell | risk_scale | Evidence | Key numbers |
|---|---|---|---|---|
| EURUSD | H4 / all sessions | 1.0 | full pipeline + 7-window walk-forward | 7/7 OOS windows positive, median +11.34 pips/trade, ~66 trades/yr |
| GBPUSD | H4 / all sessions | 0.5 | frozen cross-pair, zero re-tuning, costs ×1.5 | +10.24/trade, Sharpe 2.42, p=0.001, 11/11 positive years (n=1,161) |
| USDCAD | H4 / all sessions | 0.5 | frozen cross-pair, zero re-tuning, costs ×1.8 | +4.63/trade, Sharpe 1.16, p=0.028, 10/11 positive years (n=858) |

AUDUSD and NZDUSD were tested the same frozen way and **excluded** (8/11 and
6/11 positive years; below the deployment rubric). EURUSD D1 is a tracked
candidate, not deployed. Half-risk slots are promoted only when live results
confirm the backtest distribution.

A sealed Jan–Jun 2026 first look on EURUSD showed 16 trades, +7.75/trade,
p=0.29 — directionally consistent but statistically inconclusive, exactly what
a small sample should look like. It is monitored, not celebrated.

## How it was validated

```
7 concepts → ablation + BH-FDR → holdout → walk-forward → frozen cross-pair → 3 deployments
```

1. **Single-concept ablation** — each v1 concept (FVG, BOS, order blocks,
   fibs, momentum, liquidity sweeps, zones) tested ALONE across 5 timeframes ×
   5 sessions with bootstrap p-values and Benjamini-Hochberg FDR at 5% across
   the whole grid. Six concepts died; zones survived.
2. **Holdout (IS 2015–2022 / OOS 2023–2025)** — of 8 in-sample survivors, only
   1 validated out of sample. The big D1 cells collapsed (+25 → +1/trade).
3. **Walk-forward (7 rolling 4yr-IS / 1yr-OOS windows)** — exposed the
   holdout's session restriction as selection bias; H4/all-sessions posted
   positive OOS expectancy in 7/7 windows and became the deployed cell.
4. **Frozen cross-pair tests** — the deployed config run byte-for-byte, zero
   re-tuning, with costs scaled UP, on pairs the pipeline had never touched.
   Nothing was fit to those pairs, so their entire 2015–2025 history is
   out-of-sample: this evidence cannot be overfitting. GBPUSD and USDCAD
   passed; AUDUSD and NZDUSD did not.

The full narrative — including the two selection-bias lessons the project paid
for — is in [docs/00-journey.md](docs/00-journey.md). Raw evidence lives in
dated, never-edited write-ups under [docs/reviews/](docs/reviews/).

## Quickstart

Requires Python 3.11.

```bash
pip install -r requirements.txt

# Paper trading (no broker, works on macOS):
python scripts/run_live.py --broker paper

# Live/demo (MT5/Exness, Windows): one process per deployed symbol
python scripts/run_live.py --broker exness --symbol EURUSD --verbose
python scripts/run_live.py --broker exness --symbol GBPUSD --verbose
python scripts/run_live.py --broker exness --symbol USDCAD --verbose
```

The runner defaults to the routing table: it fixes the alpha, the H4
timeframe, and the `risk_scale` fed into position sizing (conviction band
0.5–2% of balance × the cell's risk_scale, margin-aware). Undeployed symbols
refuse to start. The old `ReactionAlpha` survives only behind an explicit
`--alpha reaction` experimental flag — unvalidated, never for funded accounts.

Full Windows VM / MT5 setup (credentials, expected startup lines, trade
frequency, stopping safely): [docs/runbooks/vmware-windows.md](docs/runbooks/vmware-windows.md).

## Observability

- **Per-symbol daily logs** — `{SYMBOL}_{YYYY-MM-DD}.log` under
  `~/Documents/TradingAgentLogs/{SYMBOL}/`, one file per UTC day, 30 days kept.
- **Heartbeats** every 15 minutes (balance, equity, open positions, next H4
  close) and an explicit "evaluated, no setup" line at every H4 close — so a
  quiet log is provably alive, not silently broken.
- **Near-miss and loss vaults** — observation-only JSONL + chart-snapshot PNGs
  beside the logs: zone touches rejected by the HTF gate, signals dropped by
  guards/risk/sizing, and every losing close with its trade lifetime.
- **Weekly resolver** — `scripts/resolve_near_misses.py --symbol <SYM>` scores
  each hypothetical (SL-first tie-break, conservative) and prints a per-reason
  summary. Vault output is hypothesis-generating only; gates change only
  through the validation pipeline.

## Repo map

| Path | What's there |
|---|---|
| `agent/alphas/` | the zone strategy, the deployment router, the ablation grid harness |
| `agent/live/` | broker bridge, signal loop, position sizer, router wiring |
| `agent/detectors/` | zones, BOS, FVG, swings, ATR, liquidity primitives |
| `scripts/` | research pipeline (ablation, holdout, walk-forward, cross-pair) + `run_live.py` + the vault resolver |
| `docs/` | [journey](docs/00-journey.md), [checkpoint](docs/CHECKPOINT.md), [reviews](docs/reviews/) (evidence record), [runbooks](docs/runbooks/) |
| `tests/` | 259 tests, including routing-table contract tests |

## Project principles

- **Observation before adaptation.** Vaults and live monitoring record what
  the agent *didn't* do; nothing acts on those observations until they
  graduate through the full statistical pipeline.
- **Every gate must earn its keep.** A filter, session restriction, or
  threshold exists only if removing it measurably hurts validated results.
- **Peeked data is burned data.** Looking at a sealed window spends it; each
  look is recorded in a dated review. The v1 reset deleted everything the old
  process had implicitly trained on.
- **The strongest evidence is the test you couldn't have rigged.** Frozen
  cross-pair runs with zero re-tuning and scaled-up costs cannot overfit —
  nothing was fit.
- **Consistency over significance at small n.** Positive OOS expectancy across
  every walk-forward window is the robustness signal; per-window p-values at
  ~15 trades/yr are underpowered.

## Status

Checkpoint **2026-06-10** — 3 deployed cells, demo stage, **259 tests
passing**. Current deployed table, evidence summary, methodology gates, and
parked work: [docs/CHECKPOINT.md](docs/CHECKPOINT.md).

## License

MIT.
