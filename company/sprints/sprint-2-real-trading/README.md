# Sprint 2 — Real-Trading

- **Sprint:** sprint-2-real-trading
- **Started:** 2026-07-21
- **Target end:** ~2026-08-04 (11–13 day honest-review window)
- **Verdict (in-flight):** _in_progress_
- **Owner (executor):** Sprint 2 Executor (single worker, six safety-first
  feature lanes per D064 — F009 → F010 → F011 → F012 → F013 → F014)
- **Kickoff decisions:** D062 (retro carry-overs), D063 (kick-off gate),
  D064 (scope + safety-first ordering), D065 (SCAFFOLDING-only invariant).

## Goal

Ship the **scaffolding** that would allow a Blue Lock user to eventually
graduate from paper-shadow to live-order placement, **without connecting
anything to a real broker order path in this sprint**. Every safety
layer (kill-switches, risk budget, approval queue, alerts) lands as new
`product`-branch code running **default-OFF**. The user must explicitly
flip a live-mode toggle in the UI to enable order-sending; even after
that toggle, orders route through the 4-check gate (`live_mode_enabled
AND kill_switches.is_killed()==False AND risk_budget.can_send_order()
AND approval_queue.can_send_order()`).

Sprint 2 also settles the three security controls Sprint 1 flagged as
carry-overs (D062): per-install-token rate limit, session expiry +
token rotation, and the automated claim-register audit.

## The two hard invariants (D065)

1. **Scaffolding-only.** No live broker order can send from a clean
   install without the explicit user toggle. Pinned by
   `tests/security/test_live_mode_off_invariant.py` — the single most
   important test in the sprint.
2. **Zero diffs on v1 live path.** `agent/live/*`, `agent/risk/*`, and
   `agent/squad/*` do not change in this sprint. Sprint 2's safety
   layer is new `agent/platform/*` code that a future integration
   sprint will wire to the squad's proposal path — that future
   integration is out of scope for Sprint 2.

## In scope — P0 features (safety-first ordering)

| ID | Title | Lane |
|---|---|---|
| F009 | Auth hardening — per-token rate limit + session expiry + rotation | Sprint 1 carry-over (D062) |
| F010 | Claim-register audit pre-commit hook | Sprint 1 carry-over (D062) |
| F011 | Kill-switches infrastructure (per-symbol + global, hot-reload) | Safety primitive |
| F012 | Risk budget hard-cap + broker connection health + `/risk` dashboard | Safety primitive |
| F013 | Trade approval mode + `/approvals` + live-mode toggle | **Central Real-Trading feature** |
| F014 | SSE alerts stream + Telegram bridge | Enhances F013 |

Build order is **strictly serial**: F009 → F010 → F011 → F012 → F013 →
F014. Design stages may overlap with the previous lane's build.

## Out of scope

- Any change to `agent/live/*`, `agent/risk/*`, `agent/squad/*`
  (D065 hard invariant).
- Connecting the squad's proposal path to F013's approval queue
  (future integration sprint after CEO ratification).
- Any real broker order sent from the platform (default OFF; opt-in
  toggle is the only path, and integration to wire the squad to it
  is out of this sprint).
- Multi-user / multi-tenant (Sprint 5+, per D052).
- Paid SaaS anywhere (Finance stays dormant per D064.3).

## Exit gates

- 6 P0 features shipped (F009 → F014) with all handoffs on tape.
- `tests/security/test_live_mode_off_invariant.py` exists, passes, and
  is linked from `REPORT.md`.
- `tests/security/*` grows with `test_rate_limiter.py`,
  `test_session_expiry.py`, `test_token_rotation.py`,
  `test_live_mode_off_invariant.py`.
- Every new public field in `agent/platform/*.py` has a matching entry
  in `company/legal/claim_register.md` (and F010's audit script proves
  it — the audit test in `tests/platform/test_claim_register_audit.py`
  passes end-to-end).
- Full test suite green (1259 baseline + n).
- Ledger `sprints[2].verdict = "COMPLETE"`; HQ dashboard reflects
  6 / 6 features in ship column.
- **`git diff <starting-sha> -- agent/live/ agent/risk/ agent/squad/`
  reports zero diff.**
- Zero commits off `product`. Zero real credentials or MT5 calls in
  tests. Zero real Telegram calls in tests. Zero spend triggered.

## Feature dependency graph

```
F009 (auth hardening) ─── unblocks better security testing on rest
      │
      ▼
F010 (claim-register audit) ─── catches misses in F011-F014
      │
      ▼
F011 (kill-switches)    ─┐
                         │
F012 (risk + health)    ─┤
                         │
                         ▼
                       F013 (trade approval mode) ── central feature
                                │
                                ▼
                              F014 (SSE alerts) ── enhances F013
```

## Personas active

Same 12 as Sprint 1 close. Security stays active (F009, F013, F014
are auth-adjacent). Legal reviews F009 (rate-limit + session-expiry
claims) and F013 (live-mode-warning + approval-queue-warning) — Legal
handoff BEFORE QA per D048. Finance stays parked per D064.3.

## Retro amendments from Sprint 1

None re-open Sprint 1's amendments; §3.5 / §4.2 / §5.5 / §6.3 stand.
Sprint 2 puts §6.3 into working code (F010 audit script).

## See also

- `../sprint-1-access/REPORT.md` — post-mortem that fed retro
  carry-overs (D062).
- `../../ledger/decisions_log.md` — D061–D065 for kickoff context;
  D066+ for in-sprint decisions.
- `../../protocols/review-chain.md` — §3.5 / §4.2 / §5.5 / §6.3 stand.
