# AI Context — brain dump (updated 2026-06-16)

Read this first in a fresh chat. Strictly technical state summary.
Deeper history: docs/00-journey.md. Current-state snapshot: docs/CHECKPOINT.md.

## 1) What is built and working

- **Validated strategy (the only one):** `zone_d1_against` —
  SupplyDemandAlpha, H4 zone touch faded AGAINST the D1 trend. Locked:
  `htf_align="D1", htf_align_mode="against", htf_lookback=10,
  htf_min_move_pips=60.0`. Mean-reversion edge; with-trend kills it.
  Validation evidence (full chain in docs/00-journey.md): walk-forward
  H4/all 7/7 positive OOS median +11.34p; frozen cross-pair GBPUSD
  +10.24 p=0.001, USDCAD +4.63 p=0.028; AUDUSD/NZDUSD EXCLUDED. Sealed
  2026 H1: 16 trades +7.75/trade p=0.29 — monitoring.
- **Deployment router:** (symbol, TF, session) → RouteEntry(mode,
  risk_scale, evidence). Deployed: EURUSD/H4/all @1.0, GBPUSD/H4/all @0.5,
  USDCAD/H4/all @0.5. Candidate: EURUSD/D1/all. Unknown cells fail-safe
  skip; contract tests lock params + evidence gates.
- **Live runner:** one process per symbol; router is default alpha;
  TF=H4; conviction-scaled risk 0.5–2% × risk_scale, margin/leverage
  aware, min-lot guards. Flags: `--symbol`, `--log-dir`, `--broker`.
- **Observability:** daily logs `~/Documents/TradingAgentLogs/{SYM}/`
  (UTC rollover, 30 kept); 15-min heartbeat; "no setup" per H4 close;
  bracketed event tags (`[SIGNAL]`, `[TRADE OPENED]`, `[LADDER]`,
  `[POSITION ADOPTED|RESTORED]`, `[SOFT SL ARMED|SL]`, `[TRADE CLOSED]`).
  Near-miss + loss vaults: JSONL + PNG beside logs; observation-only
  (regression test guards byte-identical trading output).
- **Extension-target ladder (observation-only):** structural levels
  beyond the 1.5R TP (swing / zone_edge / trendline / fib_ext /
  daily_level) journaled to `ladders/events.jsonl` AND mirrored on the
  daily log as `[LADDER]`; rungs scored vs realised MFE at close. Report:
  `scripts/report_target_ladders.py --symbol <SYM>`. NOTE: `target_rr=1.5`
  was never grid-swept; validation is conditional on it.
- **Deployed:** Windows VMware, Exness demo ($1000), 3 PowerShell tabs.
  VM update: `git fetch && git reset --hard origin/main && pip install
  -r requirements.txt` (never push from VM).
- **Crash-resilient state persistence:** `agent/live/state_store.py` —
  atomic JSON sidecar `{log_root}/{SYMBOL}/state.json`. On restart:
  `PositionMonitor` ctx/BE/partial/excursion restored; `PostLossGuard`
  and `RiskManager` restored only when persisted day == today UTC;
  `SignalLoop._last_bar_times` restored if < 2 days old. Writes via
  tmp + os.replace; save errors swallowed.
- **Daily-log enrichment + adopted soft-SL inference (2026-06-16):**
  `[TRADE OPENED]` now prints pip distances + TP R-multiple inline
  (`soft_sl=P (Np) catastrophe_sl=P (Np) tp_mech=P (X.XR, +Np)`); every
  fill emits a follow-up `[LADDER]` line mirroring `ladders/events.jsonl`.
  `[POSITION ADOPTED]` / `[POSITION RESTORED]` use the same shape. On
  restart, an open position with no persisted ctx gets a synthetic one
  built from the broker SL — `soft_stop = entry ± broker_dist /
  catastrophe_mult` (default 2.5 from `LiveConfig`). Soft-stop / BE /
  trailing / R-math come back online; degenerate inputs (no broker SL,
  distance < 4p) preserve the honest `soft_sl=unknown (adopted)` path. An
  already-breached soft level at adoption emits `[ADOPTED — SOFT SL
  ALREADY BREACHED]` and closes immediately with cause
  `soft_sl_inferred_overshoot`. Synthetic ctx is persisted on the first
  cycle so subsequent restarts reuse it.
- **Near-miss chart upgrade (2026-06-16):** `chart_snapshot.render_snapshot`
  draws solid blue entry, dashed red SL, dashed green TP with right-edge
  price labels; zone rectangle coloured by side (long=green, short=red);
  title carries reason + direction; bottom-right caption shows the
  rejection detail (HTF bias / risk-manager message).
- **Tests:** 333 passing. (Git history rewritten 2026-06-10 to strip
  Co-authored-by Cursor trailers — VM must hard-reset on update.)

## 2) Key file paths

| Area | Files |
|---|---|
| Strategy | `agent/alphas/concepts/zone_alpha.py`, `agent/alphas/concepts/_htf.py` |
| Router | `agent/alphas/zone_routing.py` (+ `tests/test_zone_routing.py`) |
| Research harness | `agent/alphas/grid.py`, `agent/alphas/backtest.py`, `agent/backtest/metrics.py` |
| Live | `scripts/run_live.py`, `agent/live/router_wiring.py`, `agent/live/signal_loop.py`, `agent/live/position_sizer.py`, `agent/live/monitor.py`, `agent/live/broker.py`, `agent/live/state_store.py` |
| Vaults | `agent/journal/vault.py`, `agent/journal/chart_snapshot.py`, `agent/journal/resolver.py`, `scripts/resolve_near_misses.py` |
| Target ladder | `agent/journal/target_ladder.py`, `scripts/report_target_ladders.py` (+ `tests/test_target_ladder.py`) |
| Validation scripts | `scripts/run_zone_all_tfs.py`, `scripts/run_holdout_validation.py`, `scripts/run_walk_forward.py`, `scripts/analyze_walk_forward.py`, `scripts/run_cross_pair_frozen.py` |
| Config | `agent/config.py` (EvalConfig: dev 2015→2025-12-01, sealed 2025-12-01→2026-06-09) |
| Docs | `docs/00-journey.md`, `docs/CHECKPOINT.md`, `docs/ROADMAP.md` (parked/future work), `docs/reviews/` (evidence, never edit), `docs/runbooks/vmware-windows.md` |
| Live tests | `tests/test_live_router_wiring.py`, `tests/test_run_live_cli.py`, `tests/test_vaults.py`, `tests/test_heartbeat_logging.py`, `tests/test_state_store.py` |

## 3) Next immediate goal

**Monitor the demo + verify the new log format.** VM must `git fetch &&
git reset --hard origin/main`. On the next live fill, confirm
`[TRADE OPENED] … soft_sl=P (Np) catastrophe_sl=P (Np) tp_mech=P (X.XR,
+Np)` and a follow-up `[LADDER]` line. On the next restart, confirm any
adopted ticket emits `[SOFT SL ARMED]` and (if mid-trade) responds to
the soft level.

1. Weekly: `python scripts/resolve_near_misses.py --symbol <SYM>` per
   pair; review per-gate would-have-won rates. Gates change ONLY via the
   full validation pipeline (grid → holdout → walk-forward).
2. As live n grows, compare live trade distribution vs backtest
   expectancy (EURUSD ~+11/trade, ~50% WR, ~66 trades/yr; full portfolio
   ~250/yr).

Parked (see **docs/ROADMAP.md**): target_rr/structural-TP study (after
~50 ladder trades); laddered partial-TP (`partial_exit_enabled` stays
OFF); USD-exposure manager; EURUSD D1 promotion; autonomy ladder.
