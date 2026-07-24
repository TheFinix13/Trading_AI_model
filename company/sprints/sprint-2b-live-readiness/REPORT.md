# Sprint 2b (Live Readiness) — Report

- **Charter:** `company/sprints/sprint-2b-live-readiness/README.md` (D097)
- **Scope:** F017 Ops Watchdog + F018 demo-order executor. Nothing else.
- **Duration:** 2026-07-24, single session (target was 2 days).
- **Executor:** solo (review-chain fast-path; specs landed before build).
- **Decisions:** D097 (kickoff), D098/D099 (spec locks), D100 (F017
  Legal), D101 (F017 ship), D102 (F018 Legal), D103 (F018 ship),
  D104 (CEO close-out). JSON↔MD verified 1:1 at every commit.

## Features shipped

### F017 — Ops Watchdog (D098 spec, D100 legal, D101 ship)

The CEO's no-black-boxes directive, in code. `agent/platform/watchdog.py`:

- **7-check registry** covering the trading runtime AND the company
  loop: `runtime_heartbeat` (warn >5 m / alarm >30 m via
  `paper_loop.live_status`), `calendar_feed` (warn >12 h / alarm
  >48 h), `broker_health` (reuses `list_health_states`, never probes),
  `risk_state` (jsonl integrity + future-dating), `intake_sla`
  (P0 4 h alarm / P1 7 d warn / open >30 d warn), `sprint_pulse`
  (in-progress sprint quiet 7 d), `ledger_drift` (the actual
  Sprint-2-close bug, D076–D080).
- **Design rules pinned by tests:** observe-never-mutate; never raise
  (broken artefacts degrade to alarm/na); state-TRANSITION-only
  publishing of `watchdog_alert` (7th whitelisted bus event, D100)
  with last-known state at `<config_dir>/watchdog_state.json` —
  steady state publishes nothing, recovery publishes with
  `recovered: true`.
- **Surfaces:** `GET /api/watchdog/status` (~30 s module cache,
  install-token-gated like every other /api route), `/hq` chip strip
  (green/amber/red per check, 60 s refresh), `scripts/run_watchdog.py`
  (one-shot exit 0/1/2 = ok/warn/alarm for cron/Task-Scheduler, or
  `--loop N` with the standard heartbeat-file pattern, `--json`).

### F018 — Demo-order executor (D099 spec, D102 legal, D103 ship)

The D065-successor: the four Sprint-2 gates finally have exactly ONE
caller. `agent/platform/live_executor.py`:

- **Adapter seam:** `Mt5OrderAdapter` protocol; `RealMt5OrderAdapter`
  lazy-imports MetaTrader5 INSIDE methods (Windows-only package —
  constructing it on macOS is safe, pinned by test);
  `FakeMt5OrderAdapter` exported for tests + dogfood. Adapters get an
  alias only and load credentials themselves via
  `broker_connection.load_credentials`; nothing logs or echoes them.
- **Refusal chain of `execute_approved`** (each step fail-closed,
  each pinned by tests): gate #5 `enabled` (DEFAULT FALSE) → approval
  exists → single-use → `can_send_live_order` re-run FRESH (all four
  Sprint-2 gates, never cached) → alias + stored creds present →
  connect → DEMO-ONLY guard against the server the adapter ACTUALLY
  connected to (`demo_only = true` literal ack + case-sensitive
  fnmatch allowlist) → volume hard-cap (0.01 lots default) → send.
- **Post-send:** fill → `risk_budget.record_fill` + `trade_fill`
  alert; errored send publishes an alert and ALSO consumes the
  approval; consumption persists in `<config_dir>/executions.jsonl`
  and survives restarts; refusals are audited but never consume; no
  automatic retry anywhere.
- **Surfaces:** `POST /api/executor/execute/<id>` (token-gated +
  rate-limited, 409 on refusal), `GET /api/executor/status`
  (state: disabled | not-on-windows | ready; never echoes creds),
  `GET /api/executor/warning` (pre-auth, like the F013 warnings).
  `/approvals` Execute button on approved cards with all three states
  + confirm dialog; Legal warning banner renders when enabled.
- **Runbook:** `docs/RUNBOOK_demo_launch.md` section 7c — V2 Platform
  demo account wiring (login 436983644 / Exness-MT5Trial9; password
  keyring-only), the full ceremony order, and the kill-switch drill.

## Test counts

| Suite | Files | Count |
|---|---|---|
| F017 | `test_watchdog_module.py` (44), `test_watchdog_transitions.py` (17), `test_watchdog_api.py` (6), `test_run_watchdog_script.py` (12) | **79** (target ≥35) |
| F018 | `test_live_executor_module.py` (47), `test_executor_api.py` (12), P0 invariant extensions (+12) | **71** (target ≥45) |
| Full suite before sprint | | 1541 passed |
| Full suite at close | | 1691 passed, 0 failed |

An honest aside that doubles as validation: the first close-out suite
run had ONE failure — `TestLedgerDrift::test_real_repo_ledger_is_in_sync`,
the watchdog's own dogfood test, which ran in the seconds between
D104 landing in `decisions_log.md` and landing in
`company_state.json`. The check caught a real transient JSON↔MD
drift, exactly the Sprint-2-close failure mode it was built for. It
passed on the clean rerun once both files were in sync.

Claim audit: `OK -- claim register is in sync.` (19 modules audited,
19 exemptions, zero unregistered accessors; F017 + F018 sections added
to `company/legal/claim_register.md`).

## P0 invariant evidence

**Invariant #2 — the live-mode-off pin, unweakened and extended.**
The Sprint-2 pin (6 tests) is byte-identical above the extension
marker; 12 F018 cases were APPENDED below it:

```
tests/security/test_live_mode_off_invariant.py
  TestCleanInstallBlocks (2)              # Sprint 2, untouched
  TestLiveModeAloneIsNotEnough (1)        # Sprint 2, untouched
  TestApprovalButNoBudget (1)             # Sprint 2, untouched
  TestAllFourPassAllowsOrder (1)          # Sprint 2, untouched
  TestKillSwitchTripsMidFlow (1)          # Sprint 2, untouched
  --- Sprint 2b extensions ---
  TestExecutorDisabledByDefault (3)       # gate #5 pin incl. junk values
  TestExecutorRefusesOnAnyGateFailure (4) # each gate closes the adapter off
  TestExecutorRefusesWithoutBrokerCreds (2)
  TestDemoOnlyGuard (3)                   # real server refused, ack required
18 passed
```

**Invariant #1 — zero diffs on restricted paths.** Verified at close:

```
$ git diff --stat c56e561 -- agent/live agent/risk agent/squad \
    scripts/run_squad_live.py scripts/run_live.py
(empty)
```

**Demo-guard behaviour pinned:** `Exness-MT5Real8` and
`ICMarkets-Live04` refused; `EXNESS-MT5TRIAL9` (uppercase) refused —
case-sensitivity is deliberate and its loosening is a Legal-review
trigger (D102 rolling constraint); blank server refused; missing
`demo_only` ack refused even for a genuine demo server.

## Deviations from the spec

1. `/api/watchdog/status` is install-token-gated, NOT pre-auth. The
   charter said "cheap, cacheable"; it did not demand pre-auth, and
   ops detail strings (intake IDs, ledger counts) don't belong in
   front of the token on non-localhost binds. Fail-closed wins.
2. Executor error alerts reuse the `trade_fill` event type with
   `status: "error"` rather than adding an eighth event type — one
   Legal review per new event type per the F014 rolling constraint,
   and a failed execution IS fill-stream news. Documented in D103.
3. `config.py`'s `[live_executor]` block and the F018 claim-register
   section landed one commit early (with F017) because the spec lock
   pre-registered them; the audit treats orphaned register entries as
   warnings (exit 0) and went fully green when `live_executor.py`
   landed.

## What the CEO must do on the VM (condensed from runbook 7c)

1. `/settings/broker` → save alias `v2-demo` (login 436983644,
   server Exness-MT5Trial9, password typed in, never committed) →
   probe green.
2. `platform.toml` → `[live_executor] enabled = true`,
   `demo_only = true`, `broker_alias = "v2-demo"` → restart service.
3. `/settings/live-mode` → ceremony (`ENABLE LIVE MODE`).
4. Submit a test proposal via `/api/approvals/submit` (internal
   token) → approve on `/approvals` within 5 min → click Execute →
   expect `filled: ticket <n>` + position in the MT5 terminal.
5. Run the kill-switch drill (runbook 7c.3) once before trusting it.

## Deferred / out of scope (honest list)

- **Squad → approval_queue submission wiring** — explicitly out of
  scope (next-gen lane + a future integration decision). Confirmed
  untouched: no diff outside the platform layer; proposals still only
  enter via the internal-token endpoint.
- Watchdog scheduling is manual (cron/Task-Scheduler or `--loop`);
  no auto-start service definition was written.
- `close_position` exists on the adapter seam but has no HTTP
  surface; closing demo positions is manual (MT5 terminal) this
  sprint.
- Realised-pnl updates to `risk_budget` after position close are not
  wired (fills record pnl 0.0 at fill time); the caps therefore bind
  on worst-case-loss asks and post-close bookkeeping is future work.
- F015/F016 ledger entries referenced by earlier sprints were not
  found in `company_state.json` features[] — noted for a future
  ledger-hygiene pass, not this sprint's scope.

## Verdict: COMPLETE

Both mandated features shipped same-day with 150 new tests
(79 + 71 vs targets 35 + 45), all suites green, claim audit green,
both P0 invariants verified, five rolling Legal constraints on tape
(D100, D102).
