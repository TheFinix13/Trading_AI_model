# AI Context — brain dump (updated 2026-07-21, v0.43)

> v0.43 — **Sprint 1 (Access) shipped** in a single autonomous
> executor session on `product`, one wall-clock day. All 3 P0
> features landed:
>
> - **F006** (Encrypted credential storage + install-scoped auth) —
>   `agent/platform/credentials.py` (keyring + Fernet fallback,
>   PBKDF2-SHA256-200k) + `agent/platform/auth.py` (install token,
>   fingerprint, constant-time compare, `RedactingFilter`) +
>   `/api/auth/status` + install-token gate on `/api/*` non-localhost.
>   117 tests, D057.
> - **F007** (MT5 broker connection wizard) —
>   `agent/platform/broker_connection.py` (ALLOWED_SERVERS allow-list,
>   alias regex, 5/min/process rate-limit, Windows-only MT5 short-circuit)
>   + `BROKER_WIZARD_PAGE` at `/settings/broker` + `/api/broker/{list,
>   save,test-connection,live-warning}` + `DELETE /api/broker/<alias>`.
>   Live save requires ack checkbox + typed LIVE. 89 tests, D058.
> - **F008** (First-time setup / onboarding flow) —
>   `agent/platform/onboarding.py` + `ONBOARDING_PAGE` at `/onboarding`
>   + `RESET_INSTALL_PAGE` at `/settings/reset-install` + 5 API routes
>   + opt-in first-visit HTML redirect gate. Passphrase >=12 chars
>   when keychain absent. 79 tests, D059.
>
> Retro amendments landed FIRST per D047: review-chain §3.5 (F005-first
> serialisation), §4.2 (spec-lock validation), §5.5 (`_BASE_CSS_VERSION`
> tag = "1.0.0"), §6.3 (automated Legal claim-register audit).
> `company/legal/claim_register.md` seeded with F001-F003 + F006-F008
> public fields.
>
> **1259 platform tests pass** (974 → 1259, +285). Security suite now
> populated (132 tests). Ledger `company_state.json` carries 60 D###
> decisions, 2 sprint-verdict rows (both COMPLETE). Zero blockers
> surfaced, zero spend, zero Cursor attribution, zero commits off
> `product`. Sprint verdict registers the honest-review flag: 1
> wall-clock day is only possible because the Executor persona ran
> every lane serially; a real 3-persona split would take longer.
>
> Prior landmarks preserved on `next-gen`: v0.40 (`2e04eac`)
> workspace panel + LIVE controls + v1 excursion. v0.39 (`f5ef13b`)
> /v2 UX pass. v0.38 (`8dd2669`) hub redesign. v0.37 (`762d7d8`)
> heartbeat + `tick_summary`. v0.36 Karasu / Sae + `risk_scale`.
> Full history: `docs/00-journey.md`.

Read this first in a fresh chat. Deeper history: `docs/00-journey.md`
and `docs/CHECKPOINT.md`. **Active branches:** `main` = live demo
agent; `next-gen` = v2 platform + squad paper runtime; **`product` =
commercial shipping lane** (Sprint 0 + Sprint 1 live here). Research
at `finance-research-experiments` on `multi-agent-ensemble`. Live
trading on demo only.

## 1) What is built and working

- **Blue Lock Trading Co. (`product`):** 17-role company-of-agents
  around the platform. Every feature flows through the canonical
  review chain (spec → research → design → architecture → build →
  security → qa → legal → signoff → ship). Sprint 0 + Sprint 1
  verdicts on the ledger = **COMPLETE**;
  `features_shipped_sprint_0: 5/5`, `features_shipped_sprint_1: 3/3`.
- **Public routes shipped in Sprint 0:** `/performance`, `/players`,
  `/players/<id>`, `/research`, plus the underlying APIs and F005
  `withStates()` primitive. Mobile-ready at 375 px.
- **Sprint 1 routes shipped:**
  - `/api/auth/status` (F006) — probe whether the install has a
    token. Never leaks the token itself; returns fingerprint only.
  - Install-token gate on every `/api/*` non-localhost (F006).
    `X-Bluelock-Token` / `Authorization: Bearer` / cookie / query
    all accepted; constant-time compare via `hmac.compare_digest`.
    Localhost single-user dev stays open per D052.
  - `/settings/broker` (F007) — 5-step wizard: account type →
    credentials → live confirmation → test → save. Password
    field is `type=password` + `autocomplete=off` + no default
    value; server input backed by a `<datalist>` of allow-listed
    prefixes.
  - `/api/broker/{list,save,test-connection,live-warning}` +
    `DELETE /api/broker/<alias>` (F007). MT5 SDK is Windows-only;
    macOS / Linux short-circuits with a friendly failed payload.
  - `/onboarding` (F008) — 5-step wizard: welcome → passphrase →
    broker → pairs → confirm. Legal agreement verbatim on Welcome.
  - `/settings/reset-install` (F008) — destructive reset page;
    sweeps both `bluelock` and `broker_mt5` namespaces.
  - `/api/onboarding/{state,passphrase,pairs,complete,reset}` (F008).
  - **First-visit HTML redirect gate (F008):** opt-in via
    `enforce_onboarding_gate` on `make_handler` (default False so
    Sprint 0 tests keep contract); `main()` flips it on for
    non-localhost binds.
- **Shared UI primitives (F005):** `withStates()` skeleton lifecycle
  + `_ERROR_COPY_JS` friendly-error helper consumed by every wizard
  page. `_BASE_CSS_VERSION = "1.0.0"` pinned by
  `tests/platform/test_pages_shared_states.py::TestBaseCssVersion`.
- **`/hq` dashboard (v0.41):** live over `company_state.json`.
  Reads the same file that F006/F007/F008 stage transitions wrote.
- **Live (`main`):** unchanged. `zone_d1_against` H4, router
  EURUSD @ 1.0 / GBPUSD @ 0.5 / USDCAD @ 0.5; risk 0.5-2 % ×
  `risk_scale`, 5 % portfolio open-risk cap, per-symbol kill files.
- **Squad paper runtime (`next-gen`):** unchanged. Roster A1-A7 + A8
  Karasu (R7 news) + A9 Sae (off) + A10 Kunigami (R5).
- **Observability:** daily logs, heartbeat, vaults, weekly bundle,
  rejection-review digest. **1259 platform tests pass.**

## 2) Key file paths

| Area | Files |
|---|---|
| Sprint 1 backend (`product`) | `agent/platform/{credentials,auth,broker_connection,onboarding}.py`, `agent/platform/pages.py` (constants added: `BROKER_WIZARD_PAGE`, `ONBOARDING_PAGE`, `RESET_INSTALL_PAGE`, `_BASE_CSS_VERSION = "1.0.0"`), `scripts/serve_platform.py` (new routes + gates) |
| Sprint 0 backend (`product`) | `agent/platform/{performance,players,research,hq}.py`, `agent/platform/pages.py` (Sprint 0 constants), `scripts/serve_platform.py` (Sprint 0 routes) |
| Sprint 1 tests | `tests/security/{test_credentials,test_auth,test_broker_connection,test_onboarding}.py`, `tests/platform/test_{credentials_module,auth_module,auth_api,broker_connection_module,broker_api,broker_wizard_page,onboarding_module,onboarding_api,onboarding_page}.py` |
| Sprint 0 tests | `tests/platform/test_{pages_shared_states,performance_*,players_*,research_*,mobile_responsive,hq_*}.py` |
| Company | `company/protocols/review-chain.md` (with §3.5/§4.2/§5.5/§6.3 amendments), `company/ledger/{company_state.json,decisions_log.md}` (60 D### entries + 2 sprint verdicts), `company/sprints/sprint-1-access/{README,F006-*,F007-*,F008-*,REPORT}.md`, `company/legal/{claim_register,F006-secrets-at-rest,live-broker-warning,F008-onboarding-agreement}.md`, `company/brand/copy.md` (§F006/§F007/§F008), `company/research/F00{6,7,8}-user-journey.md`, `company/design/F00{6,7,8}-mocks.md`, `company/qa/F00{6,7,8}-verdict.md`, `company/handoffs/F00{6,7,8}-*.json` (24 handoffs) |
| Strategy | `agent/alphas/concepts/{zone_alpha,_htf}.py`, `agent/alphas/zone_routing.py` |
| Live (`main`) | `scripts/run_live.py`, `agent/live/*.py`, `agent/risk/*.py` |
| Squad (`next-gen`) | `agent/squad/*`, `agent/squad/agents/a0[1-9]_*.py` + `a10_kunigami.py` |
| Data | `agent/data/*.py`, `data/parquet/*.parquet` |
| Docs | `docs/CHECKPOINT.md`, `docs/00-journey.md`, `docs/RUNBOOK_demo_launch.md`, `docs/08-live-trading-and-deployment.md` |

## 3) Next immediate goal

**Sprint 2 (Real-Trading) — see `company/sprints/sprint-1-access/REPORT.md`
"Retro suggestions".** Sprint 2 candidates surfaced by the Sprint 1 retro:

1. **Trade approval mode.** Human-in-the-loop confirmation before the
   live-trade path sends an order to a real broker account. Ties
   into F007's live-broker warning as the moral layer.
2. **Risk UI parity with `/performance`.** Pre-trade exposure /
   margin / worst-case-loss surface. Extend `agent/risk/*` to emit
   without touching the live-path modules.
3. **Alerts.** Push notifications for trade closes, stop hits,
   platform-down. Cheapest version: server-sent events on
   `/api/alerts/stream`.
4. **Automate the claim-register audit** (§6.3 hook script deferred
   from Sprint 1).
5. **Sprint-length calibration.** Sprint 1's 1-day compression is an
   artefact of the Executor persona owning every lane; Sprint 2 either
   adjusts day_target down or splits for real.

**Parked (do not start without discussion):** deploying §7b.6 market
paper on the VM platform clone; graduating the squad to real broker
orders; rewriting v1 zones live path; touching `agent/live/` or
`agent/risk/` from a concurrent session's WIP; enabling Sae by
default before the AC verdict; PLG cooldown retune (E013 follow-up);
any spend of money (Finance stays at zero-authority-spend until
Sprint 2 forces the first shopping list).
