# CHECKPOINT — current state of the system

A living snapshot, re-issued at every major divergence in the project's path.
The narrative of how we got here lives in [00-journey.md](00-journey.md); the raw
evidence lives in [`reviews/`](reviews/). Newest checkpoint on top.

---

## Checkpoint 2026-06-10

### Deployed strategy table

All cells run the SAME validated logic — `zone_d1_against`: an H4 supply/demand
zone touch faded **against** the D1 trend (`htf_align="D1"`, mode `"against"`,
lookback 10, min move 60 pips). Router: `agent/alphas/zone_routing.py`.

| Slot | Symbol | Cell | risk_scale | Evidence source | Key numbers |
|---|---|---|---|---|---|
| #1 | EURUSD | zone_d1_against / H4 / all | **1.0** | full pipeline + walk-forward | 7/7 OOS windows positive, median +11.34/trade, ~66 trades/yr |
| #2 | GBPUSD | zone_d1_against / H4 / all | **0.5** | frozen cross-pair (zero re-tuning, ×1.5 costs) | +10.24/trade, Sharpe 2.42, p=0.001, 11/11 positive years |
| #3 | USDCAD | zone_d1_against / H4 / all | **0.5** | frozen cross-pair (zero re-tuning, ×1.8 costs) | +4.63/trade, Sharpe 1.16, p=0.028, 10/11 positive years |

Half-risk slots are promoted to full risk only when live results confirm the
backtest distribution.

### Evidence summary

| Stage | Script | Result |
|---|---|---|
| Definitive zone grid (2015–2025) | `scripts/run_zone_all_tfs.py` | 13 BH-significant cells (in-sample to selection) |
| Holdout IS 2015-2022 / OOS 2023-2025 | `scripts/run_holdout_validation.py` | 1 of 8 IS-survivors validated; big D1 cells collapsed (+25 → +1) |
| Walk-forward, 7 rolling windows | `scripts/run_walk_forward.py` + `scripts/analyze_walk_forward.py` | H4/all: 7/7 windows positive OOS; Asia-only restriction exposed as selection bias |
| Sealed 2026 first look (Jan–Jun) | per `EvalConfig` | 16 trades, +7.75/trade, +124 total, p=0.29 — consistent, inconclusive |
| Frozen cross-pair (GBPUSD, USDCAD) | `scripts/run_cross_pair_frozen.py` | GBPUSD 11/11 yrs p=0.001; USDCAD 10/11 yrs p=0.028 — edge is structural |
| Frozen similar pairs (AUDUSD, NZDUSD) | `scripts/run_cross_pair_frozen.py` | AUDUSD MODERATE (8/11, p=0.032), NZDUSD WEAK (6/11, p=0.096) — both excluded |

Raw evidence: [`reviews/walk_forward_raw.json`](reviews/walk_forward_raw.json) and
the dated write-ups in [`reviews/`](reviews/).

### Validation methodology gates (what it takes to deploy a cell)

1. **Stage-1 ablation** — the concept must show a BH-FDR-significant cell (5%
   across the full grid) tested ALONE, with realistic per-TF costs.
2. **Holdout** — survive an IS/OOS split it was not selected on.
3. **Walk-forward** — consistently positive OOS expectancy across rolling windows
   (consistency, not per-window p-values, is the gate at small n).
4. **For new symbols: frozen transfer** — the deployed config byte-for-byte, zero
   re-tuning, costs scaled UP; rubric: p≤0.05 AND ≥9/11 positive years AND
   positive expectancy.
5. **Live confirmation** — new deployments start at half risk until live results
   match the backtest distribution.
6. **Sealed data is spent deliberately** — one look burns it; record the look in
   a dated review.

### Live wiring

- `scripts/run_live.py` defaults to the router (`--alpha router`); the routing
  table fixes the alpha, the H4 timeframe, and the `risk_scale` applied inside
  `PositionSizer`. Undeployed symbols refuse to start.
- One process per symbol (`SYMBOL` env var): EURUSD, GBPUSD, USDCAD.
- `--alpha reaction` is an explicit, unvalidated/experimental escape hatch.
- Sizing: conviction band 0.5–2% of live balance × cell `risk_scale`,
  margin/leverage aware.
- **$100-account caveat:** H4 structural stops at the broker minimum lot can
  exceed the risk band; the sizer then skips trades. Recommend **$500+ demo
  balance** so min-lot trades fit inside the band.
- Test suite: **220 passing** (`.venv/bin/python -m pytest tests/`).

### Parked

| Item | Why parked | Unpark condition |
|---|---|---|
| EURUSD D1/all promotion (`CANDIDATE_CELLS`) | 71% positive OOS windows; D1 weak in cross-pair tests | ~2 more years of OOS evidence clearing the walk-forward gates |
| "Vault" (hypothesis archive + regime-similarity recall) | idea stage | design doc; must graduate via the full gate stack, never auto-deployed, never on EURUSD's exhausted data |
| FVG / liquidity-sweep as confluence filters | deferred to preserve fresh-pair data budget | live portfolio needs more breadth AND fresh symbol data is available |
| AUDUSD / NZDUSD observations (baseline-zone strength, AUDUSD D1) | post-hoc observations from a frozen test — acting on them is the selection bias we just escaped | own pre-registered walk-forward |

### What's next

1. Live trade journal + **live-vs-backtest distribution monitor** (detect drift
   between live fills and the validated distribution).
   - Shipped first piece: **near-miss & loss vaults** — observation-only JSONL +
     chart snapshots under `~/Documents/TradingAgentLogs/{SYMBOL}/near_misses/`
     and `/losses/` (HTF-gate rejections via an inert alpha hook; guard / risk /
     sizing rejections via SignalLoop; losing closes with trade lifetime).
     Weekly: `scripts/resolve_near_misses.py --symbol <SYM>` scores the
     hypotheticals (SL-first tie-break) and prints a per-reason summary —
     hypothesis-generating only, gates change only via the validation pipeline.
2. **Portfolio USD-exposure manager** — the 3 pairs are correlated (EURUSD long +
   GBPUSD long + USDCAD short ≈ one "USD down" bet, ~4% worst-case combined
   risk); today bounded only by per-trade caps + the shared 3% daily-DD guard.
3. Accumulate sealed-2026 / live evidence toward the EURUSD D1 candidate and the
   GBPUSD/USDCAD half→full risk promotions.

### Open questions

- GBPUSD H4 **baseline** zone produced zero trades 2017–2021 (flagged in the
  cross-pair review) — investigate before ever deploying a baseline-mode cell on
  GBPUSD.
- How should the USD-exposure manager treat simultaneous signals: scale each, or
  cap net USD delta?
- When (and how) to spend the next sealed-window look on EURUSD 2026 data.

---

## THE ROUTINE — run this at every major divergence

A "divergence" is any change of deployment, methodology, or direction: a new
cell deployed/retired, a validation stage added, a concept eliminated/revived, a
reset. When one happens:

1. **Update the journey** — append the divergence to
   [00-journey.md](00-journey.md) (what changed, what was eliminated/added, why,
   with numbers). Update the diagrams if the path forked.
2. **Snapshot current state** — add a new dated section at the TOP of this file:
   deployed table, evidence summary, gates, parked list, what's next, open
   questions.
3. **Write the evidence review** — a dated file in [`reviews/`](reviews/) with
   the raw numbers (never delete or edit old reviews — they are the evidence
   record).
4. **Sync the stale docs** — any doc describing the superseded world gets a
   HISTORICAL banner pointing here; fix actively-misleading statements about
   what trades live.
5. **Prune stale artifacts** — one-off logs, orphaned scripts, dead code.
   Be conservative: never touch `docs/reviews/*`, journey-named scripts
   (reproducibility record), or anything tests cover.
6. **Verify** — full test suite green (record the count here), routing table
   contract tests pass, run_live starts (paper) for every deployed symbol.
7. **Record open questions** — anything observed but deliberately not acted on
   (post-hoc observations stay observations until pre-registered).
