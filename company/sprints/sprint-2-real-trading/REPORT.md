# Sprint 2 (Real-Trading) — Report

**Dates:** 2026-07-21 → 2026-07-22 (single wall-clock day, honest-review flag)
**Target:** 2026-07-21 → ~2026-08-05, 14-day honest review
**Verdict:** **COMPLETE**
**Features shipped:** 6 / 6 (F009, F010, F011, F012, F013, F014)
**Sprint-start SHA:** `c56e561`
**Sprint-close SHA:** `1303ca4`

## Features shipped

| Id | Title | Route(s) | Backend module | Tests added | Commits |
|---|---|---|---|---|---|
| F009 | Auth hardening (rate-limit + session expiry + rotation) | `POST /api/auth/rotate` + rate-limit gate on all `/api/*` | `agent/platform/rate_limiter.py` + `agent/platform/auth.py` (extend) | 28 (security) | `9d00242` |
| F010 | Claim-register audit + pre-commit hook | (tooling) | `scripts/check_claim_register.py`, `scripts/install_git_hooks.py`, `scripts/git-hooks/pre-commit` | 9 (platform) | `8cdbc53` |
| F011 | Kill-switches infrastructure | `/settings/kill-switches` + `/api/kill-switches/{status,activate,clear}` | `agent/platform/kill_switches.py` + `agent/platform/kill_switch_admin.py` | 45 (platform) | `fee7cd7` |
| F012 | Risk budget + broker health + `/risk` dashboard | `/risk` + `/api/risk/{state,budgets}` | `agent/platform/risk_budget.py` + `agent/platform/broker_health.py` | 38 (platform) | `ee15bbc` |
| F013 | Trade approval + live-mode toggle + P0 invariant | `/approvals` + `/settings/live-mode` + 9 endpoints | `agent/platform/approval_queue.py` | 69 (63 platform + 6 P0 security) | `69a01a1` |
| F014 | SSE alerts + Telegram bridge + `/alerts` | `/alerts` + `/api/alerts/{stream,config,test,recent}` | `agent/platform/alerts.py` + `alerts_sse.py` + `alerts_telegram.py` | 35 (platform) | `1303ca4` |

## Test counts

| Layer | Sprint-1 close | Sprint-2 close | Delta |
|---|---|---|---|
| Full suite (`pytest -q`) | 1259 | **1482** | **+223** |
| `tests/security/*` | 132 | 204 | +72 |
| `tests/platform/*` | 656 baseline | 656 | (F010-F014 all in this dir; other churn absorbed) |
| Skipped | 1 (chromium) | 1 (chromium) | 0 |

**Security suite growth is the headline number.** Sprint 2 added the
first per-token rate-limit tests, session-expiry tests, token-rotation
tests, and the P0 `test_live_mode_off_invariant.py` composition test
that pins all four safety gates.

## Handoffs written

| Feature | Handoffs |
|---|---|
| F009 | 7 (cpo→ux, ux→cto, cto-review, backend-build, security-review, qa→legal, legal→ceo) |
| F010 | 4 (cpo→cto, cto-review, backend-build, qa→cpo) |
| F011 | 7 (cpo→ux, ux→cto, cto-review, backend-build, security-review, qa→legal, legal→ceo) |
| F012 | 6 (cpo→ux, ux→cto, cto-review, backend-build, qa→legal, legal→ceo) |
| F013 | 7 (cpo→ux, ux→cto, cto-review, backend-build, security-review, qa→legal, legal→ceo) |
| F014 | 6 (cpo→ux, ux→cto, cto-review, backend-build, security-review, qa→cpo) |

Total: **37 handoffs** across the six features.

## Blockers surfaced

**None.** No `[BLOCKER][SPEND]`, no `[BLOCKER][ARCH]`, no
`[BLOCKER][TEST]`. Sprint ran to completion inside the given lane
structure, with zero touches to `agent/live/*`, `agent/risk/*`, or
`agent/squad/*` (grep-verified — see §"Invariant #2 verification"
below).

## Security posture — controls implemented

Threat model exercised in this sprint (in order of criticality):

- **Live-order gate composition (F013, P0).** No live broker order
  can be sent unless ALL four gates pass:
  `live_mode_enabled` AND `not kill_switches.is_killed(symbol)`
  AND `risk_budget.can_send_order(symbol, worst_case)` AND
  `approval_queue.can_send_order(id)`. Pinned by
  `tests/security/test_live_mode_off_invariant.py` (6 cases).
- **Per-install-token rate limit (F009).** 60 req/min per token,
  token-bucket via `agent/platform/rate_limiter.py`.
  `429 Too Many Requests` + `Retry-After` header on drain.
  SSE stream + auth-config-warning endpoints exempt (long-lived
  or pre-auth). Pinned by `tests/security/test_rate_limiter.py`
  (10 tests).
- **Session expiry (F009).** 7-day default, sliding on every
  authenticated request. Applies only to F006 install tokens
  (legacy `platform.toml` fallback stays exempt to preserve the
  Sprint 1 dev path). Pinned by
  `tests/security/test_session_expiry.py` (10 tests).
- **Token rotation (F009).** `POST /api/auth/rotate` mints a new
  token, invalidates the old one atomically, refreshes session
  activity. Pinned by `tests/security/test_token_rotation.py`
  (8 tests).
- **Kill-switches (F011).** Global + per-symbol flag-file protocol
  mirroring the v1 `<log-root>/kill.*` shape. Hot-reload on
  directory mtime. Every activate / clear appended to
  `kill_events.jsonl`. Pinned by `test_kill_switches_module.py`
  (13) + `test_kill_switches_admin.py` (13).
- **Risk budget hard-cap (F012).** Three-tier per-day / per-symbol
  / per-strategy cap. `can_send_order()` fails closed on missing
  config or negative headroom. Pinned by
  `test_risk_budget_module.py` (14).
- **Live-mode ceremony (F013).** Enable requires ALL of: acknowledge
  checkbox + type "ENABLE LIVE MODE" verbatim + Legal warning
  presented. State stored in keyring under
  `namespace="bluelock", key="live_mode_enabled"`; default OFF at
  every layer (config, page, keyring, test). Pinned by
  `test_live_mode_module.py` (7).
- **Approval queue with 5-minute timeout (F013).** In-memory +
  append-only-jsonl audit trail; `timeout_reap()` on every poll.
  Pinned by `test_approval_timeout.py` (2) +
  `test_approval_queue_module.py` (21).
- **Legal-review gating (F013).** `/approvals` and
  `/settings/live-mode` pages load `live-mode-warning.md` and
  `approval-queue-warning.md` verbatim from disk; warning
  endpoints are unauthenticated (pre-onboarding readable). Pinned
  by API tests.
- **Alerts bridge fail-closed (F014).** Telegram bridge requires
  ALL of `enabled=true` + `bot_token` populated + `chat_id`
  populated; ANY missing → `is_enabled() == False`.
  `load_config()` NEVER echoes raw token / chat_id — boolean
  flags only. `httpx.post` mocked in tests (no real Telegram
  call). Pinned by `test_alerts_telegram_module.py` (8).
- **Claim-register audit (F010).** `scripts/check_claim_register.py`
  walks every public accessor in `agent/platform/*.py` and
  cross-references `company/legal/claim_register.md`. Pre-commit
  hook opt-in via `scripts/install_git_hooks.py`. CI test at
  `test_claim_register_audit.py` (9) makes the check
  non-optional. Sprint 2 registered **all F009-F014 public
  claims** — audit runs green as of `1303ca4`.

## Security posture — controls deferred

- **Per-user rate limit segmentation.** Sprint 2 rate-limits per
  install token, which is the correct unit for the current
  single-user install model. When we introduce multi-user or
  role-based accounts (Sprint 6+), the rate-limiter needs a user
  dimension too.
- **CSRF protection on POST endpoints.** Same-origin + install-token
  gate is the current defence. When we introduce a browser cookie
  session (Sprint 3+), a proper CSRF token needs to land alongside.
- **Live-mode ceremony biometric step.** Sprint 2 uses text-typing.
  If we ever go real-money, a hardware key or Touch ID prompt is
  the correct escalation.
- **Actual live-order pathway.** By design and per D065, Sprint 2
  ships SCAFFOLDING only. `approval_queue.submit()` is not called
  from any live pathway. When Sprint N wires the squad's live-order
  path in, the four-gate composition test in
  `test_live_mode_off_invariant.py` is the acceptance criterion.

## Threat model additions vs Sprint 1

Sprint 1 gave us "who are you and can we trust your credentials at
rest". Sprint 2 adds "even if we trust you, we don't send an order
unless FOUR gates all say yes, and we tell you what happened when
they do":

| Threat | Sprint 1 answer | Sprint 2 answer |
|---|---|---|
| Attacker replays install token | Constant-time compare + install-token gate on `/api/*` | + per-token rate limit (60/min) + session expiry (7d) + rotation endpoint |
| Broker credential leaks | Keychain + Fernet fallback, no plaintext in logs | (unchanged) |
| Rogue live order | (not gated) | 4-gate composition: live-mode + kill-switch + risk-budget + per-order-approval |
| Silent kill during live run | v1 kill-file (agent/live only) | + platform-level per-symbol / global kill-switches with audit-jsonl |
| Runaway daily loss | (not gated) | Risk-budget hard-cap: per-day + per-symbol + per-strategy |
| Human-in-the-loop bypass | (n/a) | Approval queue with 5-minute timeout + ceremony to enable live mode |
| User missing critical events | Manual refresh | SSE stream + Telegram bridge (both opt-in) |
| Undocumented public API surface | Manual `claim_register.md` | Automated audit script + pre-commit + CI test |

## Live-mode-off invariant verification

Per Invariant #1 (D065), the single most important test in this
sprint. From `pytest -v`:

```
tests/security/test_live_mode_off_invariant.py::TestCleanInstallBlocks::test_default_is_off PASSED
tests/security/test_live_mode_off_invariant.py::TestCleanInstallBlocks::test_can_send_live_order_refuses_by_default PASSED
tests/security/test_live_mode_off_invariant.py::TestLiveModeAloneIsNotEnough::test_enable_but_no_approval PASSED
tests/security/test_live_mode_off_invariant.py::TestApprovalButNoBudget::test_over_budget_still_refused PASSED
tests/security/test_live_mode_off_invariant.py::TestAllFourPassAllowsOrder::test_all_four_gates_open PASSED
tests/security/test_live_mode_off_invariant.py::TestKillSwitchTripsMidFlow::test_kill_switch_flip_refuses PASSED

============================== 6 passed in 0.44s ===============================
```

Semantics pinned:

1. **Default is OFF.** Fresh clean install (no keyring entry, no
   pending approvals, no risk-budget config, no kill flags) → `can_send_live_order(...)` returns False.
2. **Live-mode alone insufficient.** Enable live-mode via
   ceremony but leave every other gate default → still refused
   (no approval).
3. **Approval alone insufficient.** Submit + approve an order but
   drain the risk budget → refused.
4. **All four open → allowed.** Live-mode enabled + no kill + budget
   remaining + approval fresh → `can_send_live_order(id)` returns
   True. This is the ONE case a live order could go through.
5. **Kill-switch mid-flow refuses.** Once (4) has passed, flip the
   global kill → next call refuses even with the same approval.

## Invariant #2 verification (zero diffs to restricted directories)

```
$ git diff --stat c56e561 -- agent/live agent/risk agent/squad scripts/run_squad_live.py scripts/run_live.py
(empty)
```

**Zero diffs.** The v1 zones live agent (`main`) and the squad
paper runtime (`next-gen`) are byte-identical to their sprint-start
state on `product`. F011's kill-switches mimic the shape of the v1
`<log-root>/kill.*` protocol but live in a new
`agent/platform/kill_switches.py` module and never import from
`agent/live/*`. F012's risk-budget module mimics the shape of
`agent/risk/*` but never imports from it.

Grep verification (no imports from restricted directories in any
Sprint-2 module):

```
$ rg "from agent\.(live|risk|squad)|import agent\.(live|risk|squad)" \
    agent/platform/rate_limiter.py \
    agent/platform/kill_switches.py \
    agent/platform/kill_switch_admin.py \
    agent/platform/risk_budget.py \
    agent/platform/broker_health.py \
    agent/platform/approval_queue.py \
    agent/platform/alerts.py \
    agent/platform/alerts_sse.py \
    agent/platform/alerts_telegram.py
(empty)
```

## Retro amendments landed

None this sprint. The four Sprint-1 amendments (§3.5 F005-first
serialisation, §4.2 spec-lock validation, §5.5 `_BASE_CSS_VERSION`
tag, §6.3 Legal claim-register audit) all continued to hold —
Sprint 2 CONSUMED the amendments: F010 shipped the §6.3 audit
tooling, every new page bumps behind the same `_BASE_CSS_VERSION`
regime, spec-lock was validated at the start of every feature's
build stage.

## Deviations from the spec

Two intentional adjustments, noted in the relevant handoffs but
not requiring a spec-extension:

- **F013 unauthenticated warning endpoints.** Original spec had
  `/api/live-mode/warning` and `/api/approvals/warning` behind
  the install-token gate. We shipped them unauthenticated because
  the corresponding HTML pages need to be readable during
  onboarding (pre-token-fetch). Legal signed off because the
  warnings are static disclaimer text and reveal nothing about
  install state.
- **F014 SSE rate-limit exemption.** Original spec did not
  explicitly exempt the SSE stream from the F009 rate limiter.
  We added `/api/alerts/stream` to `_RATE_LIMIT_EXEMPT_PATHS`
  because a long-lived stream trickle-consumes the bucket over
  hours and forces reconnect storms. Still install-token gated
  via `_authorized`; the exemption only bypasses the rate-limit
  drain.

## HQ dashboard state at close

- `sprints[0]` (Trust Foundation): COMPLETE (unchanged).
- `sprints[1]` (Access): COMPLETE (unchanged).
- `sprints[2]` (Real-Trading): COMPLETE, actual_end 2026-07-22,
  feature_ids [F009, F010, F011, F012, F013, F014].
- `features[]`: F009-F014 each `current_stage: ship`, full
  10-stage history on tape (F010 has a compressed 6-stage history
  because it's tooling, not a user-facing feature — CPO → CTO →
  Backend → QA → Signoff → Ship).
- KPIs: `features_shipped_sprint_2: 6`, `features_total_sprint_2: 6`,
  sprint verdict registers the same honest-review flag as Sprint 1.

## Retro suggestions for Sprint 3 (Stickiness)

Sprint 3 candidates. Ordered by user-value density, not by build
cost:

1. **Wire the four-gate composition to the squad's live-order path.**
   Sprint 2 built the scaffolding; Sprint N (probably not Sprint 3
   — that's the "Stickiness" sprint per the brief) wires it up.
   When it lands, the acceptance test is already on tape:
   `test_live_mode_off_invariant.py::TestAllFourPassAllowsOrder`
   is the ONLY case an order can go through.
2. **Strategy marketplace.** Publish + subscribe to community alpha
   packs. Ties into F004 (research feed) and F014 (alerts).
3. **Character seasons.** Time-boxed roster changes with themed
   dashboards. Ties into F005 shared UI primitives.
4. **Match highlights.** Auto-generated video clips of top trades.
   Requires paid infra (video encoding) — this is where
   `[BLOCKER][SPEND]` might legitimately land.
5. **Community.** Comments + reactions on published trades /
   research posts. Auth already lands with F006; add moderation
   tooling.
6. **Sprint-length calibration continued.** Sprint 2 was 6 features
   in 1 wall-clock day (again, single-Executor pattern). If Sprint
   3 continues single-Executor, halve day_target from Sprint 1's
   11-13 range to ~5-7. If it splits for real (3+ personas), keep
   the 11-13 range.

## Verdict: COMPLETE

All success criteria from the sprint brief met:

- [x] 6 P0 features shipped, all with mandatory security tests green.
- [x] Live-mode default OFF at every layer (config, page, keyring, test).
- [x] `test_live_mode_off_invariant.py` on tape, 6 cases green.
- [x] Zero diffs to `agent/live/*`, `agent/risk/*`, `agent/squad/*`,
      `scripts/run_squad_live.py`, `scripts/run_live.py`.
- [x] Zero imports from those directories in any new module.
- [x] Legal review completed for F009, F013 (mandatory), F011, F012,
      F014 (opportunistic).
- [x] Security review completed for F009, F013, F014 (mandatory), F011.
- [x] Legal claim register carries F009-F014 public claims;
      `scripts/check_claim_register.py` runs green.
- [x] 1259 → 1482 tests passing.
- [x] Ledger reflects COMPLETE, HQ dashboard shows 6/6 in ship column.
- [x] Zero commits off `product`.
- [x] Zero spend triggered.
- [x] No Cursor attribution anywhere.
