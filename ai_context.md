# AI Context — brain dump (updated 2026-07-24, v0.51)

> v0.51 — **Chartering session** 2026-07-24 (D113–D115, docs only, no
> code). **Cycle-2 triage (D113):** I005+I006 RESOLVED via the D110
> merge; I002 → awaiting-verification (closes at VM cutover); queue
> 12 → 10 open; `experiments_in_flight` semantics locked (open
> panel/scheduled compute only). **Sprint 3 "Stickiness" scope-locked
> (D114), build gated on CEO charter review:** F019 wizard recovery
> path (+I004 seam), F020 match highlights (/highlights from
> events.jsonl), F021 player form guide (incl. Sae "benched — AE
> FAIL" surface) = P0; F022 leaderboard groundwork, F023 alerts
> sink+SSE cap (I010), F024 watchdog YAML parser (I011) = P1. All
> read-only over runtime artifacts; charter at
> `company/sprints/sprint-3-stickiness/`. **Auth migration charter
> (D115)** at `company/strategy/auth-migration-charter.md`: owner/
> viewer accounts, per-account keyring namespaces, P0 invariant binds
> to OWNER ACCOUNT not install, zero-step VM adoption, Phase 2
> (hosted) needs legal review + pen test first; implementation is its
> own sprint.

> v0.50 — **Phase AE verdict: FAIL** 2026-07-24 (D111–D112). Sae's
> event mechanics validated against a frozen 349-event NFP/CPI/FOMC
> calendar (2015–2025, primary sources): AE1 PASS (54 OOS trades)
> but **AE2 FAIL** — OOS mean TQS 0.097, CI [0.042, 0.162] vs
> 0.30/0.20 floors; 28.7% wins at 1.5R (breakeven 40%); both
> mechanics negative. AE4 clean (max incumbent delta +0.001).
> **`sae_enabled` stays False — no Aug 7 NFP arming;** hour-13 bleed
> = "avoidable, not tradable"; Karasu (Phase AD) is the only
> event-window lever. No retuning against this panel; Sae v2 needs
> fresh pre-reg. Published to `/research` (manifest + condensed
> finding). Research commits `dfe5ce1`→`2b3ef4b` on
> `finance-research-experiments::multi-agent-ensemble`.

> v0.49 — **Reconciliation merge** 2026-07-24 (D110, merge commit
> `c97e8f7`): `next-gen` merged into `product`; **`product` is the
> single serving branch** (A001/A002 P0 drift closed). Brings in the
> warm-up seeding fix (200-bar gate now seeds from history + 2-bar
> burn-in), Sae hydration (gated behind `--enable-sae`, default OFF
> pending Phase AE pre-reg), calendar cache repo-root anchor (A003)
> + fetch-failure visibility, and the I002 /v2 legibility fixes
> (quiet_reason, warm-up progress, upcoming-USD-events panel,
> Sae/Karasu on the pitch). Conflicts: `serve_platform.py` (product
> handler wins, `upcoming_events` endpoint ported inside token gate),
> RUNBOOK (union; redeploy = sec 7b.8, retargeted at `product`).
> Suite **1784 pass + 1 env-skip**; P0 23/23; claim audit green.
> D109 = secret-hygiene sweep (no secret-shaped literals in tests,
> `tests/CONVENTIONS.md`). VM cutover pending (runbook 7b.8).

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
**`product` = the single serving branch** (v2 platform + squad paper
+ commercial lane, post-D110 merge); `next-gen` retired as a serving
branch (feature branches → `product` from now on). Research on
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
- **Live (`main`):** unchanged. **Squad runtime:** now served from
  `product` (post-merge); warm-up seeds from history, Sae hydrated
  but OFF, calendar failures visible on /v2.
- **Tests:** **1784 pass + 1 env-skip** (P0 invariant 23 cases;
  claim audit green, 19 modules).

## 2) Key file paths

| Area | Files |
|---|---|
| Charter + R&D | `company/protocols/{review-chain,escalation,rd-loop,literature-standards}.md`, `company/roles/{cto,cpo,ceo,research_lead,user_advocate}.md`, `company/rd/{README,intake/{TEMPLATE,I001–I013,2026-W30-cycle2-triage.md},findings/,personas/,loop-validation.md}`, `company/strategy/{sellability-gaps,auth-migration-charter}.md`, `company/ledger/{company_state.json (115 D### + 19 roles + intake×13 + experiments),decisions_log.md}` |
| Sprint 3 (chartered, not built) | `company/sprints/sprint-3-stickiness/{README,F019…F024}.md`, `company/handoffs/F019–F024-cpo-to-build_executor.json` |
| Sprint 2b live readiness | `agent/platform/{watchdog,live_executor}.py`, `scripts/run_watchdog.py`, `company/sprints/sprint-2b-live-readiness/{README,F017-ops-watchdog,F018-demo-order-executor,REPORT}.md`, `company/legal/{F017,F018}-review.md` + `executor-demo-warning.md`, `docs/RUNBOOK_demo_launch.md` sec 7c, tests `tests/platform/test_{watchdog_*,run_watchdog_script,live_executor_module,executor_api}.py` |
| Sprint 2 real-trading | `agent/platform/{rate_limiter,kill_switches,kill_switch_admin,risk_budget,broker_health,approval_queue,alerts,alerts_sse,alerts_telegram,auth}.py`, `agent/platform/pages.py` (KILL_SWITCHES / RISK / APPROVALS / LIVE_MODE_TOGGLE / ALERTS + HQ R&D pulse), `scripts/{serve_platform,check_claim_register,install_git_hooks}.py`, `scripts/git-hooks/pre-commit`, `company/legal/{live-mode,approval-queue}-warning.md` + `claim_register.md` |
| Sprint 0/1 backend | `agent/platform/{performance,players,research,hq (R&D pulse extension),credentials,broker_connection,onboarding}.py` |
| Tests | `tests/security/test_live_mode_off_invariant.py`, `tests/platform/{test_hq_org,test_dogfood_personas,test_hq_page_rd_pulse}.py` |
| Org web + dogfood | `agent/platform/hq.py` (`org_state()`), `agent/platform/pages.py` (HQ Org & Flow), `scripts/dogfood_personas.py`, `company/rd/personas/` |
| Strategy / Live / Squad | `agent/alphas/{concepts/{zone_alpha,_htf},zone_routing}.py`; **off-limits:** `agent/{live,risk,squad}/*`, `scripts/run_{live,squad_live}.py` |
| Docs | `docs/{CHECKPOINT,00-journey,RUNBOOK_demo_launch}.md` |

## 3) Next immediate goal

**1) CEO reviews the two charters** (Sprint 3 at
`company/sprints/sprint-3-stickiness/README.md`, auth migration at
`company/strategy/auth-migration-charter.md`) — the build executor
starts F019→F024 only after that sign-off. **2) VM cutover to
`product` (runbook 7b.8), then start the shadow clock (D095 step
2):** redeploy VM clones onto `product` (venv REBUILD for the
pandas<3 pin — closes I009), verify /v2 legibility (closes I002),
run runbook 7c ceremony + kill drill, wire `run_watchdog.py --loop`
into Task Scheduler. One ops session advances I002/I007/I009. A004
tz verify-then-fix waits on a live event (FOMC Jul 28–29). Post-triage
queue: 10 open (I002–I004, I007–I013).

**Parked (no start without discussion):** wiring four-gate composition
to squad's real-order path; Sprint 4 `/feedback` route (D084 defers —
F013/F014 signals drain via User Advocate + CPO Monday triage);
external peer-review budget (Sprint 6+ whitepaper); squad → real
broker orders; v1 zones live-path rewrite; any touch of
`agent/{live,risk,squad}/*` from a non-integration sprint; enabling
Sae AT ALL (Phase AE FAIL — v2 needs fresh pre-reg, D111); PLG
cooldown retune (E013 f/u); any spend
(Finance zero-authority).
