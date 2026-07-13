# AI Context — brain dump (updated 2026-07-13, v0.30)

> v0.30 — **Telegram notification audit + healthcheck accuracy fixes
> (observability layer only — zero trading-logic change).** Every live
> Telegram message now leads with the symbol (`*SYMBOL | <event>*`) via
> pure `build_*` formatters in `agent/notifications/telegram.py` — with 3
> processes in one group the user could previously only infer the pair
> from price magnitude. Trade OPENED adds ticket, TP R-multiple, $ risk
> amount and balance; Trade CLOSED reports R **vs the original entry-time
> soft stop** (`original_soft_stop` snapshotted in
> `PositionMonitor.register_entry`; the post-BE stop had been producing a
> confusing `+0.00R` on winners — now says "risk-free after BE"), plus
> time held, plain-words exit cause (`format_exit_reason`), and balance
> after. **TRADING HALTED** (was EMERGENCY CLOSE) carries symbol +
> plain-words reason + "agent still running" note; rate-limited to one
> Telegram + one annotated healthcheck **success** ping per 10 min per
> process (never `/fail` on intentional halts — that was causing
> healthchecks.io false DOWN alerts). Trade OPENED also shows
> `route_scale` and splits extension-ladder rungs across lines for
> phone readability. Healthcheck: root-caused the July 11-12 false DOWN
> slack, plus VM DNS blips `getaddrinfo failed` with no retry — one
> dropped ping blew the window). `HealthcheckPinger` now retries 3
> attempts with 2s/4s linear backoff (fail-open preserved); the heartbeat
> ping was confirmed to fire during kill-switch halts (loop-level, not in
> the skip path) and now annotates halted pings with a
> `SYMBOL HALTED by kill switch - process alive` body so the dashboard
> distinguishes halted from dead. Recommended healthchecks.io settings
> (user must apply in web UI): **Period 20 min / Grace 15 min**. Docs/08
> updated (message-format + healthcheck-accuracy sections). 23 new tests
> across `test_telegram_notifier.py`, `test_healthcheck.py`,
> `test_monitor_reliability.py`, `test_heartbeat_logging.py`.
> **461 tests pass.**
>
> v0.29 — **`scripts/weekly_report.py` — the ONE-COMMAND weekly bundle
> (observation-only, no live-path change).** Supersedes
> `compile_review_bundle.py` as the weekly entry point (that script stays
> for ad-hoc single-symbol deep-dives; a pointer note was added to its
> docstring). Run on the VM: `python scripts\weekly_report.py --days 7`
> (also `--start/--end`, `--symbols A,B,C`, `--log-root`, `--out`; symbols
> default to auto-discovery under the log root, broker suffix stripped).
> Emits `weekly_report_<start>_to_<end>.zip` under `<log-root>/reviews/`
> containing a markdown `REPORT.md` (exec summary; per-symbol trade table
> with ticket/side/lots/entry/exit/SLs/TP/risk%/pnl/R/exit-tag, signals-vs-
> rejections breakdown with `risk_manager` re-bucketed to `max_positions`
> when the detail says so, near-miss vault metadata table with computed
> R:R + zone age, H4 coverage estimate, downtime windows incl. kill.txt
> content, per-day balance curve, state.json snapshot; cross-symbol
> account view: merged heartbeat timeline, EXTERNAL/manual equity-move
> detection via balance-delta-vs-agent-closes residual > $0.50, agent-vs-
> external P&L split, kill-switch cascades = halt starts on >=2 symbols
> within 30 min; parameter snapshot from `zone_routing.survivors()` +
> `load_config().risk` + `LiveConfig()` defaults; auto-flagged review
> checklist: risk% > 2.0% abs or 1.5x week median, downtime > 12h, broker
> rejects, DD halts, soft-SL panics, missing days/symbols, kill.txt
> present) + raw daily logs + date-filtered near-miss/loss/ladder JSONLs
> and PNGs + state.json + kill.txt per symbol. Missing anything degrades
> to a MISSING note, never a crash; console output is plain ASCII
> (Windows cp1252). Reuses `daily_summary.py` regexes + `compile_review_
> bundle.py` downtime scanner; adds a fuller close regex covering ALL
> `classify_exit_tag` tags (MARGIN STOP-OUT etc., which daily_summary's
> misses). 13 new tests (`tests/test_weekly_report.py`: multi-symbol
> aggregation, external-move flagging, downtime + reason, cascade
> grouping, window filtering of vault evidence, empty-root graceful run);
> docs/08 gained a "Weekly review bundle" section. **436 tests pass.**
>
> v0.28 — **GBPUSD weekly forensic review (2026-07-01→12) + new
> `scripts/compile_review_bundle.py` tool. No code-behaviour change shipped
> yet — one open design question flagged, not decided.** User supplied 12
> daily GBPUSD logs + both vault `events.jsonl` files; root-caused why the
> week was "terrible": **not the strategy — uptime.** GBPUSD was
> kill-switch-halted for ~143.6h of the ~288h (12-day) window (**~50%
> downtime**), in two episodes: (1) 2026-07-02 19:29 → 07-06 15:52 (92.4h) —
> the OLD shared-root `kill.txt` bug from before the v0.25 per-symbol fix
> landed, sitting un-cleared for 4 days; (2) 2026-07-10 03:15 → at least
> 07-12 06:11 (50.9h, **still active** at the end of the provided logs) —
> a legitimate 3.0% daily-DD auto-halt that, by design, requires a human to
> delete `kill.txt` to resume, and nobody did for 2+ days. Only 2 real
> GBPUSD trades fired all week (both SHORT, 07-08 13:00 entry 1.33361 →
> soft-stop panic exit -14.38 USD/-72p/-2.04R at 18:20 same day when price
> blew past the soft-stop by its full 1.0× panic margin before a candle
> close confirmed it; 07-08 21:00 entry 1.34016 → force-closed at -4.76 USD
> by the same 07-10 DD halt, likely triggered mainly by a much larger same-
> day EURUSD loss on the shared account — EURUSD/USDCAD logs not supplied
> this session, flagged as a follow-up). Also found: one 07-01 signal
> rejected at the MT5 terminal itself (`AutoTrading disabled by client` —
> not a code bug, the AutoTrading toggle was off in the terminal); 5
> `risk_manager: skip_max_positions` near-misses (07-08/09, all the same
> short-the-top idea repeated at ~1.3388-1.3404 while `max_open_positions=1`
> already had a ticket open); 2 healthcheck DNS-resolution failures on
> 07-11 (`getaddrinfo failed` — VM-side network blip, not addressed).
> Independent read (no fresh OHLC cache — local parquet ends 07-01, flagged
> honestly as a real limitation): D1 stayed bullish the whole window per
> every `htf_gate` rejection; the two shorts were a legitimate fade-the-top
> idea at a multi-week high, but the second short chasing the same zone
> higher hours after the first got stopped (not blocked by PLG — its
> 60-min cooldown had already expired) is the kind of same-idea re-entry a
> discretionary process would want price-action confirmation for, not just
> a repeat H4 zone touch.
>
> **New tool:** `scripts/compile_review_bundle.py` — run ON the VM, bundles
> N days × M symbols (default all 3, default 7 days) into ONE zip: a
> `REPORT.md` (reuses `daily_summary.py`'s per-symbol stats + a NEW
> **uptime/downtime timeline** — every kill-switch halt's start, end,
> reason, and cleared-or-still-active status, plus AutoTrading-rejects /
> DD-halts / soft-SL-panics / healthcheck-fails / broker-disconnect tallies)
> + the raw daily `.log` files + the near-miss/loss vault PNGs and JSONL
> records that fall inside the window + `state.json`. Replaces "paste a
> dozen individual files into chat" with one attachment. Tested end-to-end
> against the supplied GBPUSD logs (staged into a scratch
> `TradingAgentLogs/`-shaped folder) — correctly reconstructed both
> downtime episodes above; not yet run against the real EURUSD/USDCAD VM
> folders.
>
> **Open question, not decided:** should a *daily*-DD kill-switch halt
> auto-clear at the next UTC day rollover (since the limit itself is
> literally "3% **per day**") instead of requiring a human to delete
> `kill.txt` indefinitely? Current behaviour let one bad day (07-10) erase
> 2+ trading days afterward. Flagged to the user as a real reliability
> question, not implemented.
>
> v0.27 — **`next-gen` branch split + progress dashboard + demo-launch
> runbook (additive only — zero agent-behaviour change).** New branch
> **`next-gen`** (forked from `main` @ `052515a`) is the next-generation
> platform line: dashboards, runbooks, and future platform work land
> here, fully separate from `main`, which the VM agent runs and which
> stays uncontaminated; the intent is to graduate research-validated
> strategies onto next-gen for heavier trading later. Shipped on it:
> (1) `scripts/build_dashboard.py` — stdlib-only generator for a
> self-contained dark-theme `reports/dashboard.html` (live-agent panel
> from `zone_routing.survivors()` + `RiskConfig` defaults + ROADMAP +
> test status; research panel parsing the M001 phi5-arm4 verdict JSONs +
> `EXPERIMENTS.md` read-only from `../finance-research-experiments`, no
> lab-code imports; a validated-vs-SIM-ONLY separation panel stating the
> M001 ensemble is not trading). Regen:
> `./.venv/bin/python scripts/build_dashboard.py && open reports/dashboard.html`.
> Env handling: key NAMES only, never values. Missing research artifacts
> degrade to "artifact not found" panels. (2)
> `docs/RUNBOOK_demo_launch.md` — demo-MT5 launch/verify runbook
> (entrypoint wiring, .env key names, VM Task-Scheduler/autologon
> deployment, preflight checklist incl. both kill files + 5% portfolio
> cap, aliveness table, paper dry-run, emergency stop; honest note that
> `agent/news/` blackout exists but is NOT wired into the live loop).
> Audit at branch time: 423/423 tests pass; `main` HEAD `052515a`
> (TG multi-chat fan-out).
>
> v0.26 — **Near-miss vault chart redesign (observation tooling only, no
> live-path change).** `agent/journal/chart_snapshot.py` rewritten: custom
> TradingView-esque mplfinance style (was plain "yahoo"), auto-hiding
> volume panel (skipped when the feed's tick volume is flat/zero rather
> than rendering a dead grey strip), a legend for entry/SL/TP/zone, a
> plain-English one-line reason (`REASON_LABELS`) next to the existing raw
> tag, and a bottom-left stats box (risk/reward pips, R:R, zone width,
> zone age at touch). `VaultRecorder._render` now threads `zone.created_at`
> / `zone.impulse_pips` through for the stats box. Triggered by reviewing
> the user's own near-miss PNGs (EURUSD/GBPUSD/USDCAD, 2026-07-01/02):
> confirmed all of them are `htf_gate` rejections of the SAME already-
> stale, weak-impulse (16–50p) zones re-touched 3-4× over ~24h with D1 bias
> flip-flopping down→neutral→up — textbook zone erosion, consistent with
> the user's own read that only the 07-02 NFP-driven breakout signals
> (EURUSD/GBPUSD long, USDCAD short skipped on `risk_manager: skip_max_
> positions`) would plausibly have won. Local parquet cache ends exactly
> 2026-07-01T00:00 UTC, so `scripts/resolve_near_misses.py` can't
> mechanically score any event after that without a cache refresh from the
> VM (MT5-only data source) — flagged as a follow-up, not run this
> session. 404 tests still pass (`tests/test_vaults.py` unchanged/green).
>
> v0.25 — **Live-agent reliability fixes from a week of VM logs
> (2026-06-30 → 2026-07-06) cross-checked against the user's actual MT5
> trade history.** Three real production bugs found and fixed (all in
> `agent/live/`, no strategy/parameter change — same research-first rule
> as always):
> 1. **Broker misread → false 100% drawdown → stuck kill switch.**
>    `MT5Broker.get_account_info` fabricated an all-zero `AccountInfo`
>    whenever `mt5.account_info()` returned `None` (an Exness scheduled-
>    maintenance disconnect on 2026-07-02). The daily-DD check read that
>    as a 100% drawdown, panic-closed everything, and wrote a kill file
>    that survived VM/script restarts because (2) it was a bare relative
>    `kill.txt` shared by all three symbol processes' CWD. Fixed: broker
>    now raises `BrokerReadError` (caller skips the cycle, retries in a
>    few seconds) instead of faking zero; `_check_daily_dd` also got an
>    independent sanity floor (skip on non-positive balance/equity or an
>    implausible >60% single-cycle drawdown); kill file is now scoped
>    per-symbol under `{log_root}/{SYMBOL}/kill.txt`; both the monitor
>    and `run_live.py` startup now read + log the kill file's own
>    recorded reason instead of a silent "skipping iteration" forever.
> 2. **A real take-profit was logged as a loss.** USDCAD ticket
>    `2915834625` (2026-07-02, NFP): user's MT5 history shows Close=
>    1.41963 (== TP), Reason=Take Profit, P/L=+2.98. The agent's own log
>    said `[CATASTROPHE SL] pnl=-0.87`. Root cause: when the BROKER closes
>    a position on its own (a TP/SL order filling between two ~5s polls)
>    the monitor had no `close_result` of its own and fell back to the
>    last-polled tick — stale by up to one cycle, long enough during a
>    fast news move to still show a small floating loss moments before
>    the real fill. Fixed: new `BrokerConnection.get_closed_trade()` /
>    `MT5Broker` impl queries MT5's own trade history
>    (`history_deals_get`) for the authoritative fill and is now the
>    first-priority source in `_handle_close`; the old "guess tp/sl from
>    pnl sign" fallback is gone — an unresolved cause now honestly stays
>    `"manual"` (tag `CLOSED (cause unconfirmed)`) instead of being
>    dressed up as a confirmed stop-loss.
> 3. **VM "freezes and restarts every ~3 days"** — logs show no agent
>    process restarts / crashes in the window; almost certainly an
>    OS-level cause (Windows Update auto-reboot is the most likely single
>    culprit) rather than the agent or MT5 overloading the VM. Discussed,
>    not a code fix. Telegram vs WhatsApp/iMessage notification question
>    also discussed (Telegram already wired; WhatsApp/iMessage have no
>    equivalent low-friction bot API for this use case).
>
> 27 new regression tests (`tests/test_broker_reliability.py`,
> `tests/test_monitor_reliability.py`, `tests/test_kill_switch_reliability.py`)
> including a direct reproduction of the USDCAD mislabel. All 404 tests
> pass.
>
> v0.24 — **M001 v1/v2 reframe day** (in `finance-research-experiments` on
> `multi-agent-ensemble` branch). No production repo changes today; every
> line of research below lives in the research repo. User directive drove
> a squad-wide reclassification: v1 = squad-tested checkpoint (not
> initial implementation); v2 = architectural upgrade that trumps v1.
> Session delivered: doctrine v0.5 + roster v0.8; 6 evolution-ledger
> RELABEL rows reclassifying prior "v2 mechanics" as v1 iterations;
> **G7 pre-registered protocol** (squad-level v1-checkpoint gate); F19
> `lot_intent` + F20 `risk_intent` + F21 `read_workspace` primitives on
> BaseStriker with per-playstyle dispatch; all 8 v1 agents wired
> (playstyle + tier); engine threads F21 workspace snapshot into
> `intend()`; Bachira consumes Isagi peer confluence (+0.05 lift, 10
> chemistry tests); G7 harness scaffolded (C1/C5/C6 live, C2/C3/C4
> pending full 7-window batch); Sentinel Φ4.1 physical rerun landed
> 5,236 trades / 28,830 proposals / 336,707 thoughts at
> `sentinel_blocks=True` (side-by-side vs sealed 0.2922 audit report
> pending F17-arm completion). 396 sim tests passing. **No production
> code touched, no live-account impact, no strategy change.**
>
> v0.23 — **Research-pipeline sweep E011-E016 complete + two production adds
> (rejection-review + portfolio 5 % risk cap).** Six pre-registered studies
> fired in `finance-research-experiments`; only E013 has an `alive_*` verdict
> and it validates the EXISTING production posture (all safety layers ON, no
> change needed). Two non-strategy production-code adds shipped: weekly
> rejection-review report (`agent/reports/rejection_review.py`) + portfolio-
> wide 5 % open-risk ceiling (`RiskConfig.portfolio_max_open_risk_pct`
> defaulting to `0.05`; hard-blocks any new ticket that would push aggregate
> broker-open risk above 5 %). All 377 tests pass. Verdict summary: E011
> `stopped_at_stage_1` (expectancy bucket-agnostic; kills E012); E013
> `combined_alive` (Δ combined +0.80 Sharpe, wick +0.75, BE ~0), PLG
> `plg_earns_keep` (protocol's own label for "PLG is expensive"; blocks
> 64 % winners vs 33 % losers, +23.5 median would-be
> pips — follow-up study needed to retune); E014 `parked_low_yield` (real
> edge at θ=70 but 12 % of baseline volume; kills E015 + E016). No strategy
> change shipped this session; all changes require a fresh pre-reg study.
>
> v0.22 — **M001 Φ4.1 expanded squad gate FAIL @ 0.92× + Isagi v2 arc FAIL +
> methodology lock + regime redesign + round-1 + round-2 v2 backlog
> resolutions.** Production repo untouched today (R&D lives in
> `finance-research-experiments` on `multi-agent-ensemble` branch). The
> headline numbers below are the locked Φ4.1 telemetry. **Φ4.1 FAIL** at
> squad TQS **0.2922** vs Isagi-alone **0.3175** (0.92×). Predicate
> starvation diagnosis **confirmed + fixed**: Nagi confluence-firing
> thoughts went 0 → **34,302** between Φ4 and Φ4.1, producing mean
> **TQS 0.349 (HIGHEST per-agent TQS in the 8-agent squad)**. But a new
> failure mode surfaced — **structural crowding-out**: Isagi 0 trades,
> Barou 0 trades, both slot-cannibalised by Bachira's `+0.10` rebel-lift
> on the same baseline-zone primitive. **Isagi v1→v2 evolution arc
> FAIL** (single-agent arc, 2026-06-24) — v1 stays canonical, v2 archived
> at `sim/agents/a01_isagi_v2.py`. **Regime classifier redesign:**
> `vol_spike` + `news` RETIRED on structural grounds (OHLCV cannot
> detect news; vol-spike has no clean separation from non-news vol);
> live-classes-only `{trending, chop}` macro F1 = 0.971 (was 0.496).
> **Methodology lock:** `docs/methodology/gate_verdict_registry.md` v0.1
> binds per-gate locked statistic; `07-research-standards.md` v0.4 §11
> forbids post-hoc statistic swaps. **v2 backlog resolutions** (round-1
> 2026-06-25 + round-2 2026-06-30): Nagi RETIRED (v1 floor empirically
> correct); Barou REDESIGN-hybrid-A+B (user decision 2026-06-30: closed-
> loss replay USDCAD + symbol expansion to EURUSD/GBPUSD/USDCAD);
> Kunigami DEFERRED pending Sentinel R1–R5; Bachira REFINE-to-peer-
> silence; Rin REFINE-regime+peer-disagreement; Chigiri REFINE-multi-TF-
> ADX+ATR-percentile; Reo ADVANCE-coupled-to-Φ5-multi-position.
> Doctrine v0.4 / roster v0.7. **Architectural insight:** the single-
> position-per-symbol queue with conviction-only ranking is the binding
> constraint (Φ4.1 and Isagi v2 converged on this diagnosis); **Φ5 lever
> is the aggregator** (HRP + TQS-floor + same-direction merge + multi-
> position), NOT more strikers. 358 sim tests passing. **VM impact:**
> none — production untouched; demo $100 / 1:1000 profile unchanged.
> Live trading not reactivated.
>
> v0.21.1 / v0.21 / v0.20 — production repo split (M001 R&D migrated to
> `finance-research-experiments`), Wave 1 + Wave 2 cleanup, `m001-development`
> branch + `v2-zone-d1-against-stable-2026-06-24` rollback tag, allocator.py
> kept as M001 seed (KEEP-AND-INHERIT). Full detail in git history of this
> file + `docs/00-journey.md`.
>

Read this first in a fresh chat. Strictly technical state summary.
Deeper history: `docs/00-journey.md`. Snapshot: `docs/CHECKPOINT.md`.
**Active R&D:** `finance-research-experiments` /
`programs/M001_multi_agent_ensemble/` (branch `multi-agent-ensemble`,
doctrine v0.5 / roster v0.8). Pointer:
`docs/research/multi-agent-ensemble/README.md`. M001 latest verdicts:
**Φ3 PASS · Φ4 FAIL @ 0.98× · Φ4.1 FAIL @ 0.92× · Isagi v2 arc FAIL**
(v1 canonical) · **G7 pre-registered 2026-07-01** (no verdict yet;
full-panel batch pending). Live trading on demo only; production code
untouched.

## 1) What is built and working

- **Validated strategy:** `zone_d1_against` — SupplyDemandAlpha, H4 zone touch
  faded AGAINST D1 trend. Locked: `htf_align="D1", htf_align_mode="against",
  htf_lookback=10, htf_min_move_pips=60.0`. Evidence chain in
  `docs/00-journey.md` / `docs/reviews/`.
- **Deployment router:** EURUSD/H4/all @1.0, GBPUSD/H4/all @0.5, USDCAD/H4/all
  @0.5. Unknown cells fail-safe skip; contract tests in
  `tests/test_zone_routing.py`.
- **Live runner:** one process per symbol; router default; conviction-scaled
  risk 0.5–2% × risk_scale. `scripts/run_live.py --symbol --log-dir --broker`.
- **Observability:** daily logs, 15-min heartbeat, bracketed tags, near-miss/loss
  vaults (JSONL+PNG), target ladder (observation-only), `daily_summary.py`,
  `state.json` sidecar, **weekly rejection-review digest**
  (`python -m agent.reports.rejection_review --days 7` → markdown + CSV
  grouped by symbol · rejection_reason · stop-bucket, with walk-forward-
  resolved would-be outcomes; observation-only per `PROTOCOL_DISCIPLINE.md` §7).
  377 tests passing.
- **Portfolio risk ceiling (Wave 2.2, 2026-07-01):** `RiskConfig.portfolio_
  max_open_risk_pct = 0.05` — sum of `abs(open_price - stop_loss) * volume *
  pip_value_per_lot` across ALL open tickets (all symbols on this account,
  queried via `broker.get_open_positions(None)`) must not exceed 5 % of
  balance AFTER adding a freshly-sized ticket. Wired in
  `SignalLoop._route_signal` after sizing / before order placement; rejection
  emits `_record_near_miss("portfolio_risk_cap", ...)`.
- **Deployed:** Windows VMware, Exness demo ($100 / 1:1000), 3 PowerShell tabs.
  VM update: `git fetch && git reset --hard origin/main && pip install -r requirements.txt`.
- **Live-agent reliability (v0.25, 2026-07-06):** kill file per-symbol
  (`{log_root}/{SYMBOL}/kill.txt`, not a shared `kill.txt`); broker read
  failures raise instead of faking a $0 account; daily-DD sanity floor;
  exit-reason resolution now queries MT5 trade history first
  (`get_closed_trade`) before ever guessing from a stale tick or pnl
  sign. 404 tests passing.
- **Branches:** `main` = production (the VM agent — never contaminate);
  `next-gen` = next-generation platform line (dashboard, runbooks, future
  research-validated heavier trading; forked from `main` @ `052515a`);
  `m001-development` = pre-M001 baseline for future M001 graduation; tag
  `v2-zone-d1-against-stable-2026-06-24` at `6f1cc75` for rollback.

## 2) Key file paths

| Area | Files |
|---|---|
| Strategy | `agent/alphas/concepts/zone_alpha.py`, `agent/alphas/concepts/_htf.py` |
| Router | `agent/alphas/zone_routing.py` |
| M001 seed (keep) | `agent/alphas/allocator.py` — Ledoit-Wolf, long-only weights |
| Live | `scripts/run_live.py`, `agent/live/signal_loop.py`, `agent/live/state_store.py`, `agent/live/monitor.py`, `agent/live/broker.py` (`ClosedTrade`, `BrokerReadError`) |
| Deployment | `scripts/watchdog_agent.ps1` (per-symbol restart loop, Task Scheduler-launched), `scripts/deploy_windows.ps1`, `docs/08-live-trading-and-deployment.md` |
| Notifications | `agent/notifications/telegram.py`, `agent/notifications/healthcheck.py` (external dead-man's-switch), `scripts/notify_telegram.py`, `scripts/ping_healthcheck.py` |
| Risk | `agent/risk/manager.py` (per-symbol + portfolio ceiling), `agent/risk/sizing.py`, `agent/risk/post_loss_guard.py`, `agent/config.py::RiskConfig` |
| Vaults / ladder / reports | `agent/journal/vault.py`, `agent/journal/target_ladder.py`, `agent/reports/rejection_review.py`, `scripts/daily_summary.py`, `scripts/weekly_report.py` (THE weekly one-command zip: REPORT.md + logs + vault evidence + params + checklist), `scripts/compile_review_bundle.py` (ad-hoc deep-dives) |
| Validation | `scripts/run_zone_all_tfs.py`, `scripts/run_ablation.py`, `scripts/run_walk_forward.py` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-overview.md`, `docs/archive/`, `docs/audits/` |
| Platform (next-gen) | `scripts/build_dashboard.py` → `reports/dashboard.html`, `docs/RUNBOOK_demo_launch.md` |
| M001 pointer | `docs/research/multi-agent-ensemble/README.md` |
| Workspace setup | `.cursor/workspace-tips.md` (multi-root: this repo + research + brain-box) |

## 3) Next immediate goal

**2026-07-13 GBPUSD weekly review — pending user decisions:** (1) run
`python scripts\weekly_report.py --days 7` on the VM (now the one-command
multi-symbol bundle, v0.29) so the 07-10 DD-halt cascade can be attributed
properly across all three symbols — its cross-symbol section detects
exactly this (cascades + external equity moves); (2) decide whether the daily-DD
kill-switch should auto-clear at UTC day rollover instead of needing a
manual `kill.txt` delete (currently cost GBPUSD 50.9h+ and counting); (3)
manually clear the still-active GBPUSD `kill.txt` on the VM if the user
wants it trading again before that design question is settled.

**2026-07-06 live-agent reliability fixes — code shipped + verified live on
VM.** All five code-fix items from the user's original list are live: VM
pulled `main`, restarted all 3 symbol processes, logs confirm per-symbol
kill files (`{log_root}/{SYMBOL}/kill.txt`, no shared-root bleed anymore),
no stale kill-switch refusals, and daily state resets working. Item 6
(Telegram) is also confirmed working end-to-end: `TG_BOT_TOKEN`/`TG_CHAT_ID`
set in the VM's `.env`, `scripts/notify_telegram.py` smoke test sent
successfully, and all 3 processes posted `Agent ONLINE` to the bot on
restart (screenshotted by user). Notifier already covers trade open/close,
ladder events (partial scale-out, BE move, soft-stop exit), emergency
close, and consecutive-error halts — the one known gap was a genuine hard
VM freeze/crash, which can't send its own "going offline" message. Closed:
added `agent/notifications/healthcheck.py` (`HealthcheckPinger`, mirrors
`TelegramNotifier`'s fail-open contract) pinging an external
healthchecks.io-compatible URL once per 15-min heartbeat
(`SignalLoop._maybe_heartbeat`); `PositionMonitor._emergency_close_all`
and the consecutive-error halt also fire an immediate `/fail` ping instead
of waiting for the grace period. Reads `HEALTHCHECK_URL_<SYMBOL>` (falls
back to shared `HEALTHCHECK_URL`) — unset is a harmless no-op. Smoke test:
`scripts/ping_healthcheck.py` (same pass/fail-exit-code contract as
`notify_telegram.py`). 13 new tests (`tests/test_healthcheck.py`).
`docs/08-live-trading-and-deployment.md` has the healthchecks.io setup
steps. Not yet configured on the VM (user must create the checks and set
the env vars, then smoke-test).

Item 7 (self-healing after reboot) turned out to need correcting: **NSSM /
a Windows service will NOT work here** — `MetaTrader5`'s Python API needs
the same interactive desktop session the MT5 terminal runs in, and Windows
services run isolated in Session 0 with no access to that desktop (a known
MT5-automation limitation, confirmed via research, not repo-specific).
Replaced with the standard pattern: Windows Autologon + MT5 in the Startup
folder + one Task Scheduler task per symbol (`AtLogOn`, `LogonType
Interactive`) running `scripts/watchdog_agent.ps1`, which loops
`run_live.py` forever so a crash — not just a reboot — self-heals too.
`docs/08-live-trading-and-deployment.md` rewritten accordingly (the old
NSSM section was untested/aspirational). **Not yet executed on the VM** —
user has the steps, pending: enable autologon, add MT5 to Startup, register
the 3 scheduled tasks, then verify via reboot that all 3 `Agent ONLINE`
messages arrive on Telegram unattended.

**Multi-position-per-symbol question (2026-07-06):** confirmed the
monitor already tracks every open ticket independently (`_entry_ctx`,
`_excursion`, `_close_results`, `_forced_exit_reason` are all keyed by
`ticket`, and `get_closed_trade(ticket, symbol)` resolves each ticket's
own broker history) — this is exactly what let the Jul 2 USDCAD
mislabel fix tell the agent's short and the user's manual buy apart.
But `RiskConfig.max_open_positions = 1` is evaluated per-symbol
(`len(await broker.get_open_positions(symbol))` in `SignalLoop.
_route_signal`), so the agent will never *intentionally* stack a second
ticket of its own on one symbol — a second position only appears when
the user trades manually alongside it. Raising the cap to allow
deliberate multi-ticket scale-ins is a sizing/risk design decision, not
done.

**2026-07-01 research-pipeline sweep — closed.** Six pre-reg studies fired
in `finance-research-experiments` (E011-E016). Verdicts registered in
`finance-research-experiments/EXPERIMENTS.md`:

| Study | Verdict | Production impact |
|---|---|---|
| E011 small-stop subset expectancy | `stopped_at_stage_1` | none — kills E012 |
| E012 pending-limit entry | `cancelled_dep_failed` | none |
| E013 safety-layer contribution | `combined_alive` (Δ +0.80 Sharpe); wick `alive`; BE CI touches 0; PLG `plg_earns_keep` (protocol's label for "PLG is expensive") | validates existing posture; PLG follow-up study needed |
| E014 quality-score entry gate | `parked_low_yield` | none — kills E015 + E016 (12 % of baseline volume) |
| E015 conviction-from-quality | `cancelled_dep_failed` | none |
| E016 re-entry / flip | `cancelled_dep_failed` | none |

**Production adds shipped this session (Wave 2, non-strategy):**

1. `agent/reports/rejection_review.py` — weekly digest of near-miss vault
   events grouped by symbol · reason · stop-bucket, with walk-forward-
   resolved would-be outcomes. CLI: `python -m agent.reports.rejection_review
   --days 7`. Tests: `tests/test_rejection_review.py` (10 tests).
2. `RiskConfig.portfolio_max_open_risk_pct = 0.05` + `RiskManager.
   evaluate_portfolio_ceiling` + `RiskDecision.SKIP_PORTFOLIO_RISK` +
   `SignalLoop._route_signal` wiring. Tests:
   `tests/test_portfolio_risk_cap.py` (9 tests). All 377 tests pass.

**Follow-up study candidate (2026-07 backlog):** PLG cooldown tuning. E013
found PLG blocks 64 % future-winners vs 33 % future-losers on the deployed
cell — median would-be pips per block is +23.5. This is a real production
concern but requires a fresh pre-registered study (`PROTOCOL_DISCIPLINE.md`
§5) before any PLG parameter is changed.

**Active track: M001 multi-agent ensemble (Φ4.1 closed → Φ4.2 + Φ5 in flight)
in research repo.** Phase 6e Φ5 re-sim (Arms 3/4/5) still pending in
`finance-research-experiments` per that repo's `ai_context.md` §3. This
production repo is untouched by M001 work until a graduation gate lands.

**Monitor-only:** `zone_d1_against` on $100/1:1000 demo — no param changes;
collecting live PnL for future DSR gate when A1 Isagi wraps the roster.

Parked: see `docs/ROADMAP.md` (target_rr study, partial TP, USD exposure, D1
promotion, autonomy ladder, **multi-position scale-in / pyramiding per
symbol §1.6 — added 2026-07-06, explicit user decision to hold until M001
wraps or a dedicated branch**). Wave 3 production-repo cleanup still
queued per `docs/audits/2026-06-24_production_repo_audit.md` §5; waits on
M001.
