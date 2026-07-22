# AI Context — brain dump (updated 2026-07-22, v0.44)

> v0.44 — **Sprint 2 (Real-Trading) shipped** in a single autonomous
> executor session on `product`, one wall-clock day. All 6 P0 features
> landed as SCAFFOLDING (default-OFF per D065; no live pathway wired):
>
> - **F009** (Auth hardening) — `agent/platform/rate_limiter.py`
>   (60 req/min per install-token, token-bucket, `429 + Retry-After`)
>   + `agent/platform/auth.py` extended with 7-day sliding session
>   expiry + `POST /api/auth/rotate`. 28 security tests, D073.
> - **F010** (Claim-register audit) — `scripts/check_claim_register.py`
>   + `scripts/git-hooks/pre-commit` template + opt-in installer
>   `scripts/install_git_hooks.py` + CI test at
>   `tests/platform/test_claim_register_audit.py` (9 tests). D074.
> - **F011** (Kill-switches) — `agent/platform/kill_switches.py`
>   (read path with hot-reload) + `kill_switch_admin.py` (write path
>   with JSONL audit) + `/settings/kill-switches` +
>   `/api/kill-switches/{status,activate,clear}`. Mimics v1
>   `<log-root>/kill.*` shape but lives in platform module. 45 tests,
>   D075.
> - **F012** (Risk budget + broker health) —
>   `agent/platform/risk_budget.py` (3-tier per-day/per-symbol/
>   per-strategy cap, JSONL state) + `broker_health.py` (30s cached
>   probe) + `/risk` dashboard + `/api/risk/{state,budgets}`. 38
>   tests, D076-D077.
> - **F013** (Trade approval + live-mode) —
>   `agent/platform/approval_queue.py` (in-memory + JSONL audit,
>   5-min timeout) + `/approvals` (SSE-or-poll) + `/settings/live-mode`
>   (3-part ceremony: acknowledge + type "ENABLE LIVE MODE" + Legal
>   warning) + 9 endpoints. 69 tests including the P0
>   `test_live_mode_off_invariant.py` (6 cases). D078.
> - **F014** (SSE alerts + Telegram bridge) —
>   `agent/platform/alerts.py` (in-process bus, 6-event whitelist,
>   100-event ring buffer) + `alerts_sse.py` (WHATWG frames) +
>   `alerts_telegram.py` (reuses existing `[telegram]` bot_token,
>   fail-closed) + `/alerts` + 4 endpoints. 35 tests. D079.
>
> **The P0 invariant is on tape:**
> `tests/security/test_live_mode_off_invariant.py` composes all four
> gates and pins that no live order can go through unless
> `live_mode_enabled AND not kill_switches.is_killed() AND
> risk_budget.can_send_order() AND approval_queue.can_send_order()`.
>
> **1482 platform tests pass** (1259 → 1482, +223). Security suite
> 132 → 204 (+72). Ledger `company_state.json` carries 79 D### entries
> and 3 sprint-verdict rows (all COMPLETE). Zero blockers surfaced,
> zero spend, zero Cursor attribution, zero commits off `product`,
> and — the D065 Invariant #2 gate — **zero diffs vs sprint-start SHA
> `c56e561` in `agent/live/*`, `agent/risk/*`, `agent/squad/*`,
> `scripts/run_squad_live.py`, `scripts/run_live.py`.**
>
> Prior landmarks preserved on `next-gen`: v0.40 (`2e04eac`)
> workspace panel + LIVE controls + v1 excursion. v0.39 (`f5ef13b`)
> /v2 UX pass. v0.38 (`8dd2669`) hub redesign. v0.37 (`762d7d8`)
> heartbeat + `tick_summary`. v0.36 Karasu / Sae + `risk_scale`.
> Full history: `docs/00-journey.md`.

Read this first in a fresh chat. Deeper history: `docs/00-journey.md`
and `docs/CHECKPOINT.md`. **Active branches:** `main` = live demo
agent; `next-gen` = v2 platform + squad paper runtime; **`product` =
commercial shipping lane** (Sprint 0 + Sprint 1 + Sprint 2 live here).
Research at `finance-research-experiments` on `multi-agent-ensemble`.
Live trading on demo only.

## 1) What is built and working

- **Blue Lock Trading Co. (`product`):** 17-role company-of-agents
  around the platform. Every feature flows through the canonical
  review chain (spec → research → design → architecture → build →
  security → qa → legal → signoff → ship). Sprint 0 + Sprint 1 +
  Sprint 2 verdicts on the ledger = **COMPLETE**;
  `features_shipped_sprint_0: 5/5`, `features_shipped_sprint_1: 3/3`,
  `features_shipped_sprint_2: 6/6`.
- **Real-Trading scaffolding (Sprint 2, default-OFF):**
  - **Four-gate live-order composition** — no live order can go
    through unless `live_mode_enabled AND not kill_switches.is_killed()
    AND risk_budget.can_send_order() AND approval_queue.can_send_order()`.
    Pinned by `tests/security/test_live_mode_off_invariant.py`.
  - **Auth hardening (F009):** 60 req/min per install-token +
    7-day sliding session expiry + `POST /api/auth/rotate`.
  - **Claim-register audit (F010):** `scripts/check_claim_register.py`
    + opt-in pre-commit + CI test.
  - **Kill-switches (F011):** `/settings/kill-switches` with grid
    of Global + 5 symbols, textarea reason, last-20-events log.
    Hot-reload on directory mtime; every write appended to
    `<config_dir>/kill_events.jsonl`.
  - **Risk budget (F012):** `/risk` dashboard with exposure +
    margin + per-day/per-symbol/per-strategy headroom + broker
    health per alias. 30s polling via F005 `withStates()`.
  - **Trade approval (F013):** `/approvals` queue with big Approve /
    Reject buttons + countdown timer; `/settings/live-mode` with
    3-part ceremony (checkbox + type "ENABLE LIVE MODE" + Legal
    warning). Default OFF at every layer.
  - **SSE alerts (F014):** `/alerts` with EventSource + 6 filter
    chips + test button. Telegram bridge reuses existing
    `[telegram]` credentials; disabled by default; `load_config()`
    returns boolean flags only, never raw token / chat_id.
- **Public routes shipped in Sprint 0:** `/performance`, `/players`,
  `/players/<id>`, `/research`, plus APIs and F005 `withStates()`.
- **Sprint 1 routes:** `/api/auth/status`, `/settings/broker`,
  `/onboarding`, `/settings/reset-install`, install-token gate on
  `/api/*` non-localhost, F008 first-visit HTML redirect gate.
- **Shared UI primitives (F005):** `withStates()` + `_ERROR_COPY_JS`
  + `_BASE_CSS_VERSION = "1.0.0"` (unchanged this sprint).
- **`/hq` dashboard (v0.41):** live over `company_state.json`;
  now shows 6 Sprint-2 feature cards in ship column.
- **Live (`main`):** unchanged. `zone_d1_against` H4, router
  EURUSD @ 1.0 / GBPUSD @ 0.5 / USDCAD @ 0.5; risk 0.5-2 % ×
  `risk_scale`, 5 % portfolio open-risk cap, per-symbol kill files.
  **Zero diffs from Sprint 2.**
- **Squad paper runtime (`next-gen`):** unchanged. Roster A1-A7 + A8
  Karasu (R7 news) + A9 Sae (off) + A10 Kunigami (R5). **Zero
  diffs from Sprint 2.**
- **Observability:** daily logs, heartbeat, vaults, weekly bundle,
  rejection-review digest. **1482 platform tests pass** (204 in
  the security suite).

## 2) Key file paths

| Area | Files |
|---|---|
| Sprint 2 real-trading scaffolding (`product`) | `agent/platform/{rate_limiter,kill_switches,kill_switch_admin,risk_budget,broker_health,approval_queue,alerts,alerts_sse,alerts_telegram}.py`, `agent/platform/auth.py` (session + rotation extensions), `agent/platform/pages.py` (KILL_SWITCHES_PAGE, RISK_PAGE, APPROVALS_PAGE, LIVE_MODE_TOGGLE_PAGE, ALERTS_PAGE), `agent/platform/config.py` ([internal] + [alerts.telegram] blocks), `scripts/serve_platform.py` (15+ new routes), `scripts/check_claim_register.py`, `scripts/install_git_hooks.py`, `scripts/git-hooks/pre-commit` |
| Sprint 2 legal / warnings | `company/legal/{live-mode-warning,approval-queue-warning}.md`, `company/legal/claim_register.md` (F009-F014 additions) |
| Sprint 2 tests | `tests/security/{test_rate_limiter,test_session_expiry,test_token_rotation,test_live_mode_off_invariant}.py`, `tests/platform/test_{claim_register_audit,kill_switches_module,kill_switches_admin,kill_switches_page,kill_switches_api,risk_budget_module,broker_health_module,risk_page,risk_api,approval_queue_module,live_mode_module,approval_timeout,approvals_page,live_mode_page,approvals_api,alerts_module,alerts_sse_module,alerts_telegram_module,alerts_page,alerts_api}.py` |
| Sprint 1 backend (`product`) | `agent/platform/{credentials,auth,broker_connection,onboarding}.py`, `agent/platform/pages.py` (`BROKER_WIZARD_PAGE`, `ONBOARDING_PAGE`, `RESET_INSTALL_PAGE`), `scripts/serve_platform.py` |
| Sprint 0 backend (`product`) | `agent/platform/{performance,players,research,hq}.py`, `agent/platform/pages.py` (Sprint 0 constants), `scripts/serve_platform.py` (Sprint 0 routes) |
| Company | `company/protocols/review-chain.md`, `company/ledger/{company_state.json,decisions_log.md}` (79 D### + 3 sprint verdicts), `company/sprints/sprint-2-real-trading/{README,F009-*,F010-*,F011-*,F012-*,F013-*,F014-*,REPORT}.md`, `company/handoffs/F00{9..14}-*.json` (37 handoffs total this sprint), `company/qa/F00{9..14}-verdict.md`, `company/research/F00{9,11..14}-user-journey.md`, `company/design/F0{11..14}-mocks.md` |
| Strategy | `agent/alphas/concepts/{zone_alpha,_htf}.py`, `agent/alphas/zone_routing.py` |
| Live (`main`, off-limits) | `scripts/run_live.py`, `agent/live/*.py`, `agent/risk/*.py` |
| Squad (`next-gen`, off-limits) | `agent/squad/*`, `agent/squad/agents/a0[1-9]_*.py` + `a10_kunigami.py` |
| Data | `agent/data/*.py`, `data/parquet/*.parquet` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-journey.md`, `docs/RUNBOOK_demo_launch.md`, `docs/08-live-trading-and-deployment.md` |

## 3) Next immediate goal

**Sprint 3 (Stickiness) — see `company/sprints/sprint-2-real-trading/REPORT.md`
"Retro suggestions".** Sprint 3 candidates:

1. **Strategy marketplace.** Publish + subscribe to community alpha
   packs. Ties into F004 (research feed) and F014 (alerts).
2. **Character seasons.** Time-boxed roster changes with themed
   dashboards. Ties into F005 shared UI primitives.
3. **Match highlights.** Auto-generated video clips of top trades.
   Requires paid infra (video encoding) — this is where
   `[BLOCKER][SPEND]` might legitimately land.
4. **Community.** Comments + reactions on published trades /
   research posts. Auth already lands with F006; add moderation
   tooling.
5. **Sprint-length calibration continued.** Sprint 2 was 6 features
   in 1 wall-clock day (single-Executor pattern). If Sprint 3
   continues single-Executor, halve day_target from Sprint 1's
   11-13 to ~5-7. If split into 3+ personas, keep 11-13.

**Parked (do not start without discussion):** wiring the four-gate
live-order composition to the squad's real-order path (that's a
future dedicated sprint, not Sprint 3's stickiness lane); deploying
§7b.6 market paper on the VM platform clone; graduating the squad to
real broker orders; rewriting v1 zones live path; touching
`agent/live/`, `agent/risk/`, or `agent/squad/` from any sprint that
isn't the eventual real-order integration sprint; enabling Sae by
default before the AC verdict; PLG cooldown retune (E013 follow-up);
any spend of money (Finance stays at zero-authority-spend until a
sprint forces the first shopping list, likely Sprint 3 Match
Highlights).
