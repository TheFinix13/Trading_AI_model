# AI Context — brain dump (updated 2026-07-24, v0.48)

> v0.48 — **Product hardening night** 2026-07-24 (D105–D108 on
> `product`). **Ops-Telegram split** (D105): `[alerts.telegram.ops]`
> second bot/chat; `OPS_EVENTS` (watchdog_alert) → ops with primary
> FALLBACK; `DUAL_ROUTE_EVENTS` (kill_switch_trip, platform_down) →
> BOTH; trading → primary; no-token-echo pin extended; runbook 7b.7.
> **Audit fixes** (D106): A005 approvals — reap-before-resolve +
> `approved_ttl_seconds` (300 s) + `approval_expired` status, P0 pin
> extended +5 (23 cases); A006 credentials — atomic tmp+`os.replace`
> bag write + `_BAG_LOCK` on RMW; A007 risk gate — `_today_losses`
> cached on (path, mtime_ns, size, UTC day). **Audit filed** (D107,
> D108): `reviews/audits/2026-07-24-full-system-audit.md`, intake
> I005–I012 (KPI 3→11), `pandas>=2.2,<3` pinned (VM venv holds 3.0.3
> — REBUILD, runbook sec 4), quarterly-audit cadence pending CEO
> ratification. Tests 1691 → **1720**. v0.47 detail below.

> v0.47 — **Sprint 2b Live Readiness COMPLETE** 2026-07-24
> (D097–D104 on `product`). **F017 Ops Watchdog** (79 tests):
> `watchdog.py` 7-check registry (runtime_heartbeat, calendar_feed,
> broker_health, risk_state, intake_sla, sprint_pulse, ledger_drift);
> `watchdog_alert` = 7th bus event (Legal D100), published on state
> TRANSITIONS only; `GET /api/watchdog/status`, `/hq` chip strip,
> `run_watchdog.py` (exit 0/1/2, `--loop` + heartbeat). **F018
> demo-order executor** (71 tests): the four Sprint-2 gates' ONE
> caller — `execute_approved` re-runs `can_send_live_order` fresh;
> DEMO-ONLY guard in code (literal `demo_only=true` ack +
> case-sensitive `*Trial*/*Demo*/*demo*` allowlist vs the
> ACTUALLY-connected server, fail-closed); 0.01-lot cap;
> default-disabled (gate #5); single-use approvals persisted in
> `executions.jsonl`; no auto-retry; `Mt5OrderAdapter` seam (MT5
> lazy-imported, Fake for tests); `/approvals` Execute button; Legal
> D102; runbook 7c = V2 Platform demo account (436983644 /
> Exness-MT5Trial9, password keyring-only) + ceremony + kill drill.
> P0: live-mode-off pin UNTOUCHED +12 extensions; zero-diff vs
> `c56e561` empty. v0.46 detail: [docs/00-journey.md](docs/00-journey.md).

Read this first in a fresh chat. Deeper history: `docs/00-journey.md`
+ `docs/CHECKPOINT.md`. **Branches:** `main` = live demo agent;
`next-gen` = v2 platform + squad paper; **`product` = commercial
lane** (Sprint 0–2 + charter elevation). Research on
`finance-research-experiments::multi-agent-ensemble`. Demo only.

## 1) What is built and working

- **Blue Lock Trading Co. (`product`):** 19-role company; review
  chain spec → research → design → architecture → build → qa →
  security\* → 7b research\* → legal\* → signoff → ship
  (\* = conditional). Sprint 0+1+2+2b COMPLETE (5/5+3/3+6/6+2/2).
- **Real-Trading stack (default-OFF at every layer):** four-gate
  composition pinned by
  `tests/security/test_live_mode_off_invariant.py` (18 tests:
  Sprint-2 pin + 2b extensions). F009 auth, F010 claim-audit, F011
  kill-switches, F012 risk+broker-health, F013 approval+live-mode,
  F014 SSE alerts + Telegram, **F017 watchdog, F018 demo executor**
  (DEMO-only in code; enable via `[live_executor]` in platform.toml
  + live-mode ceremony; see runbook 7c).
- **R&D loop validated (cycle 1 PASS):** intake I001 resolved,
  I002–I004 routed (queue depth 3); first finding published (Phase
  AC honest negative, on `/research` manifest); W30 rollup on tape.
- **Public routes:** `/performance`, `/players[/:id]`, `/research`,
  `/onboarding`, `/settings/{broker,live-mode,kill-switches,reset-install}`,
  `/risk`, `/approvals`, `/alerts`, `/hq` (R&D pulse + F015 Org &
  Flow via `/api/hq/org`). F005 `withStates()` +
  `_BASE_CSS_VERSION = "1.1.0"`.
- **Dogfood cast (F016):** 6 personas + `scripts/dogfood_personas.py`
  (in-process server, keychain-safe, no live mode by construction);
  first run 113/113 across onboarding/broker/kill/approvals/alerts.
- **Live (`main`) + Squad (`next-gen`):** unchanged; zero diffs.
- **Tests:** **1720 pass** (P0 invariant 23 cases; claim audit
  green, 19 modules).

## 2) Key file paths

| Area | Files |
|---|---|
| Charter + R&D | `company/protocols/{review-chain,escalation,rd-loop,literature-standards}.md`, `company/roles/{cto,cpo,ceo,research_lead,user_advocate}.md`, `company/rd/{README,intake/{TEMPLATE,I001–I004},findings/2026-07-phase-ac-pitch-assignment.md,personas/,loop-validation.md}`, `company/strategy/sellability-gaps.md`, `company/ledger/{company_state.json (108 D### + 19 roles + intake×12 + experiments),decisions_log.md}` |
| Sprint 2b live readiness | `agent/platform/{watchdog,live_executor}.py`, `scripts/run_watchdog.py`, `company/sprints/sprint-2b-live-readiness/{README,F017-ops-watchdog,F018-demo-order-executor,REPORT}.md`, `company/legal/{F017,F018}-review.md` + `executor-demo-warning.md`, `docs/RUNBOOK_demo_launch.md` sec 7c, tests `tests/platform/test_{watchdog_*,run_watchdog_script,live_executor_module,executor_api}.py` |
| Sprint 2 real-trading | `agent/platform/{rate_limiter,kill_switches,kill_switch_admin,risk_budget,broker_health,approval_queue,alerts,alerts_sse,alerts_telegram,auth}.py`, `agent/platform/pages.py` (KILL_SWITCHES / RISK / APPROVALS / LIVE_MODE_TOGGLE / ALERTS + HQ R&D pulse), `scripts/{serve_platform,check_claim_register,install_git_hooks}.py`, `scripts/git-hooks/pre-commit`, `company/legal/{live-mode,approval-queue}-warning.md` + `claim_register.md` |
| Sprint 0/1 backend | `agent/platform/{performance,players,research,hq (R&D pulse extension),credentials,broker_connection,onboarding}.py` |
| Tests | `tests/security/test_live_mode_off_invariant.py`, `tests/platform/{test_hq_org,test_dogfood_personas,test_hq_page_rd_pulse}.py` |
| Org web + dogfood | `agent/platform/hq.py` (`org_state()`), `agent/platform/pages.py` (HQ Org & Flow), `scripts/dogfood_personas.py`, `company/rd/personas/` |
| Strategy / Live / Squad | `agent/alphas/{concepts/{zone_alpha,_htf},zone_routing}.py`; **off-limits:** `agent/{live,risk,squad}/*`, `scripts/run_{live,squad_live}.py` |
| Docs | `docs/{CHECKPOINT,00-journey,RUNBOOK_demo_launch}.md` |

## 3) Next immediate goal

**Start the shadow clock (D095 step 2, now unblocked by D104):** the
CEO runs runbook 7c on the VM — store V2 Platform creds via
`/settings/broker`, enable `[live_executor]` + ceremony, execute a
test order, run the kill-switch drill — then wire
`scripts/run_watchdog.py --loop` into Task Scheduler so the 30–90 day
shadow window is observable from day one. In parallel: charter the
install-token → multi-user auth migration; Sprint 3 scoping picks up
I002 (/v2 silence, next-gen lane) + I003 (broker dead-end copy);
cycle-2 R&D drain (I002–I004 open).

**Parked (no start without discussion):** wiring four-gate composition
to squad's real-order path; Sprint 4 `/feedback` route (D084 defers —
F013/F014 signals drain via User Advocate + CPO Monday triage);
external peer-review budget (Sprint 6+ whitepaper); squad → real
broker orders; v1 zones live-path rewrite; any touch of
`agent/{live,risk,squad}/*` from a non-integration sprint; enabling
Sae before AC verdict; PLG cooldown retune (E013 f/u); any spend
(Finance zero-authority).
