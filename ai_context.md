# AI Context — brain dump (updated 2026-08-04, v0.29)

> v0.29 — **E031/E032 research verdicts (lab-side only, zero agent
> change).** Both weekly-review candidates were pre-registered, built
> and run to verdict in `finance-research-experiments` (`main`,
> commits `c838b28`→`7478f5e`) and both STOPPED-DEAD at Stage-1
> go/no-go on 2015–2021 screens, zero OOS cost. **E031 slot-blocking:**
> the live 6/6 blocked-winner pattern does NOT generalise — 741–1,212
> slot conflicts/symbol over 7y, yet cap=2/cap=3/replace-losing arms
> all land NEGATIVE ΔSharpe (−0.10…−0.33); replacement crystallizes
> losses the fade recovers. `max_open_positions=1` stays; verdict:
> protective, not a leak. **E032 with-trend breakout cell:** 0/12
> cells (all means positive, monotone in impulse size, but best raw
> p 0.034 vs BH 0.0042) — v1 stays fade-only; "missing the big moves"
> closed with evidence. Weekly reviews keep tracking the blocked-
> winner counterfactual line, but re-opening needs a different
> mechanism.
>
> v0.28 — **Weekly review Jul 28 → Aug 3 (analysis only, no code change).**
> `docs/reviews/2026-08-04_week_review.md` + ledger row. Realized
> **+34.34** (balance 969.54 → **1003.88**, first close above $1,000):
> 3/3 new entries TP'd — GBPUSD +1.50R and +1.49R (+122p, biggest pip
> win of the run), EURUSD **first live trade ever** +1.73R — while both
> carried pre-window longs soft-SL'd at the inferred stops the Jul 28
> review predicted (−1.34R / −1.17R). Sum +2.21R; external/unexplained
> $0 (I016 fix holding). Resolver pass (fresh Dukascopy through Aug 3):
> htf_gate protective again in all three buckets; GBPUSD max_positions
> blocks 4/4 winners → **6/6 cumulative, pre-reg research candidate**
> (no config change from n=6). **Aug 3 incident:** VM lost DNS 10:26
> UTC (healthchecks.io DOWN alerts fired correctly ~10:46), agents ran
> healthy but signal-blind for 3.5h, then hard VM death 14:07 UTC (logs
> end mid-poll, no shutdown) — host-level, agent code blameless, zero
> exposure (book flat since Jul 31). Nothing self-restarted because the
> autologon + Task Scheduler watchdog setup (docs/08) is STILL pending
> since Jul 6 → now top ops priority. Also found: VM logs are UK local
> (UTC+1) while weekly_report labels them UTC (+1h skew), and a
> scheduled H4 close is skipped silently when the terminal has no fresh
> bar — both intake candidates, observation-tooling only.
>
> v0.27 — **Trading-agent production fixes cherry-picked from next-gen
> (2026-07-14). No strategy change — reliability + observability only.**
> Three commits (c59a3b3, ca8b455, 4f12b94) selectively brought across
> from the next-gen platform line, preserving main as the trading branch:
>
> 1. **Telegram audit + healthcheck accuracy** (c59a3b3) — every live
>    message now leads with the symbol (`*SYMBOL | Event*`); trade
>    CLOSED reports R against the original entry-time soft stop (fixes
>    the +0.00R confusion after BE moves); TRADING HALTED is
>    rate-limited to 1 msg/10 min per process; healthcheck retries 3×
>    with backoff on DNS failures and annotates halted pings as
>    alive-but-halted (success, not /fail) so intentional halts no
>    longer flag the check DOWN. 23 new tests.
>
> 2. **One-command weekly review bundle** (ca8b455) — `scripts/weekly_report.py`
>    produces a single zip with per-symbol REPORT.md, uptime/downtime
>    timeline, cross-symbol cascade detection, active parameter
>    snapshot, and near-miss/loss vault artifacts. Run on VM:
>    `python scripts\weekly_report.py --days 7`. Replaces
>    paste-a-dozen-files-into-chat weekly reviews. 13 new tests.
>
> 3. **Daily-DD kill-switch self-recovery** (4f12b94) — clean
>    `Auto-kill: Daily DD halt...` files now auto-clear at the next UTC
>    rollover (aligned with `RiskManager.on_new_day`) in BOTH the running
>    loop AND `run_live.py::_preflight_kill_switch` startup path, so a VM
>    restart across midnight also self-recovers with no human deletion.
>    Protective close on the DD event is unchanged; master
>    `kill_switch_file`, manual kills, and non-DD auto-kills
>    (catastrophe/broker-misread/consecutive-error) stay STICKY forever;
>    3-consecutive-DD-day thrash guard escalates to a sticky halt +
>    Telegram page. Counter persisted non-day-scoped in state.json.
>    26 new tests. `docs/VM_SCRIPTS.md` also added — the practical
>    catalog of every script the VM runs.
>
> Full suite on `main`: **489 pass, 0 failures**. Next-gen platform
> commits (dashboards, squad UI, platform.toml, session-claim
> scaffolding) were deliberately NOT cherry-picked — they belong on the
> v2 line, not the trading agent. VM safe to `git fetch; git reset --hard
> origin/main` and restart watchdog tasks.
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
- **Branches:** `main` = production; `m001-development` = pre-M001 baseline for
  future M001 graduation; tag `v2-zone-d1-against-stable-2026-06-24` at
  `6f1cc75` for rollback.

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
| Vaults / ladder / reports | `agent/journal/vault.py`, `agent/journal/target_ladder.py`, `agent/reports/rejection_review.py`, `scripts/daily_summary.py` |
| Validation | `scripts/run_zone_all_tfs.py`, `scripts/run_ablation.py`, `scripts/run_walk_forward.py` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-overview.md`, `docs/archive/`, `docs/audits/` |
| M001 pointer | `docs/research/multi-agent-ensemble/README.md` |
| Workspace setup | `.cursor/workspace-tips.md` (multi-root: this repo + research + brain-box) |

## 3) Next immediate goal

**Top ops priority (2026-08-04): execute the VM self-healing setup —
now a one-script job.** `scripts/setup_self_healing.ps1` (new, with
companion `verify_self_healing.ps1`) automates everything that's been
pending since Jul 6: MT5-in-Startup shortcut, the 3 Task Scheduler
`AtLogOn` watchdog tasks, and the Windows Update policy (weekend-only
installs Sat 22:00 + NoAutoRebootWithLoggedOnUsers — likely root cause
of the recurring VM deaths; Jul 28 and Aug 3 both needed manual
recovery). VM procedure: turn it on → agents safe to restart (flat
book, no kill files, PLG sidecars stale-day-discard on load) →
`git pull` → run setup script ELEVATED → fix its autologon WARN by
running Sysinternals Autologon once (interactive password entry; the
script only detects) → run verify script → hands-off reboot; success =
3 `Agent ONLINE` Telegram messages unattended. Scripts + docs/08 +
VM_SCRIPTS.md edits are UNCOMMITTED on the Mac (no agent-repo branch
declared 2026-08-04) — commit to `main` and pull on the VM first.

Queued from the 2026-08-04 review: (a) ~~pre-registered research-lane
study on relaxing `max_open_positions=1` / queue-replacement~~ —
**DONE same day: E031 (and companion E032 with-trend cell) both
STOPPED-DEAD at Stage 1 in the research repo; cap stays 1, book stays
fade-only (see v0.29 note above)**; (b) intake items still open:
WARNING on silently skipped H4 close, weekly_report timezone
normalization (VM logs are UK local, report labels them UTC).

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

Liquidity-structure research verdicts (2026-07-28, research repo E027–E030):
valid-liquidity striker DEAD, Po3 striker DEAD both directions; **E029
pool-window timing primitive ALIVE at sealed** (equal-highs-pool windows as
a when-filter, +0.10 ATR lift). Nothing lands here — a production timing
gate on the deployed entry would need its own study + full agent
validation chain first.
