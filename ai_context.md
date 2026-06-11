# AI Context — brain dump (updated 2026-06-11)

Read this first in a fresh chat. Strictly technical state summary.
Deeper history: docs/00-journey.md. Current-state snapshot: docs/CHECKPOINT.md.

## 1) What is built and working

- **Validated strategy (the only one):** `zone_d1_against` — SupplyDemandAlpha,
  H4 supply/demand zone touch faded AGAINST the D1 trend.
  Locked params: `htf_align="D1", htf_align_mode="against", htf_lookback=10,
  htf_min_move_pips=60.0`. Mean-reversion edge; with-trend kills it.
- **Validation chain:** 7 ICT concepts → single-concept ablation w/ bootstrap
  p-values + BH-FDR 5% (6 died) → holdout IS 2015-22 / OOS 2023-25 →
  walk-forward 7×(4yr IS/1yr OOS): H4/all 7/7 positive OOS windows, median
  +11.34 pips/trade → frozen cross-pair (zero re-tuning, costs scaled up):
  GBPUSD +10.24/trade p=0.001 11/11 yrs; USDCAD +4.63 p=0.028 10/11 yrs;
  AUDUSD/NZDUSD tested and EXCLUDED. Sealed 2026 look (Jan–Jun): 16 trades,
  +7.75/trade, p=0.29 — inconclusive, monitoring.
- **Deployment router:** (symbol, TF, session) → RouteEntry(mode, risk_scale,
  evidence w/ source tag). Deployed: EURUSD/H4/all @ 1.0, GBPUSD/H4/all @ 0.5,
  USDCAD/H4/all @ 0.5. Candidate (not deployed): EURUSD/D1/all. Unknown cells
  fail-safe to skip. Contract tests lock params + evidence gates.
- **Live runner:** one process per symbol; router is default alpha source;
  fixes TF=H4; risk_scale flows into adaptive sizing (conviction band 0.5–2%
  of live balance × scale, margin/leverage aware, min-lot guards); refuses
  undeployed symbols; old ReactionAlpha only via `--alpha reaction`
  (experimental). Flags: `--symbol`, `--log-dir`, `--broker paper|mt5|exness`.
- **Observability:** daily logs `~/Documents/TradingAgentLogs/{SYM}/{SYM}_{YYYY-MM-DD}.log`
  (UTC rollover, 30 kept); heartbeat every 15 min (balance/equity/positions/
  next H4 close); explicit "no setup" line each H4 close. Near-miss vault
  (htf_gate / post_loss_guard / risk_manager / sizing_skip rejections) + loss
  vault: JSONL + mplfinance PNG snapshots beside logs. Observation-only —
  regression test proves trading output identical with recorders attached.
  Resolver scores hypotheticals (SL-first tie-break) per reason tag.
- **Deployed:** Windows VMware, Exness demo ($1000), 3 PowerShell tabs.
  VM update ritual: `git fetch origin && git reset --hard origin/main &&
  pip install -r requirements.txt` (never pull/push from VM).
- **Tests:** 259 passing. Git history rewritten 2026-06-10 to strip
  Co-authored-by Cursor trailers (force-pushed; VM must hard-reset).

## 2) Key file paths

| Area | Files |
|---|---|
| Strategy | `agent/alphas/concepts/zone_alpha.py`, `agent/alphas/concepts/_htf.py` |
| Router | `agent/alphas/zone_routing.py` (+ `tests/test_zone_routing.py`) |
| Research harness | `agent/alphas/grid.py`, `agent/alphas/backtest.py`, `agent/backtest/metrics.py` |
| Live | `scripts/run_live.py`, `agent/live/router_wiring.py`, `agent/live/signal_loop.py`, `agent/live/position_sizer.py`, `agent/live/monitor.py`, `agent/live/broker.py` |
| Vaults | `agent/journal/vault.py`, `agent/journal/chart_snapshot.py`, `agent/journal/resolver.py`, `scripts/resolve_near_misses.py` |
| Validation scripts | `scripts/run_zone_all_tfs.py`, `scripts/run_holdout_validation.py`, `scripts/run_walk_forward.py`, `scripts/analyze_walk_forward.py`, `scripts/run_cross_pair_frozen.py` |
| Config | `agent/config.py` (EvalConfig: dev 2015→2025-12-01, sealed 2025-12-01→2026-06-09) |
| Docs | `docs/00-journey.md`, `docs/CHECKPOINT.md`, `docs/reviews/` (evidence, never edit), `docs/runbooks/vmware-windows.md` |
| Live tests | `tests/test_live_router_wiring.py`, `tests/test_run_live_cli.py`, `tests/test_vaults.py`, `tests/test_heartbeat_logging.py` |

## 3) Next immediate goal

**Monitor the demo deployment and accumulate live evidence.** Concretely:

1. User pastes daily log files / vault PNGs into chat for review; check
   heartbeats present, routed cells correct, trades match backtest behavior.
2. Weekly: `python scripts/resolve_near_misses.py --symbol <SYM>` per pair;
   review per-gate would-have-won rates. Vault output is hypothesis-only;
   gates change ONLY via the full validation pipeline (grid → holdout →
   walk-forward).
3. As live n grows, compare live trade distribution vs backtest expectancy
   (EURUSD ~+11/trade, ~50% WR, ~66 trades/yr full portfolio ~250/yr).

Parked (do not start without discussion): portfolio USD-exposure manager
(3 pairs ≈ one correlated USD bet, ~4% worst-case combined risk today);
EURUSD D1 candidate promotion (needs more OOS years); vault-hypothesis →
new-cell pipeline; FVG/liquidity-sweep confluence ideas (fresh pairs only,
EURUSD data is exhausted). Checkpoint routine: docs/CHECKPOINT.md "THE
ROUTINE" — run it at every major divergence.
