# F013 — QA verdict

**Verdict:** GREEN — ready for merge.

## Coverage

| Layer                | Tests | File |
|----------------------|------:|------|
| Module (approval_queue) | 21 | `tests/platform/test_approval_queue_module.py` |
| Module (live-mode)      |  7 | `tests/platform/test_live_mode_module.py` |
| Module (timeout)        |  2 | `tests/platform/test_approval_timeout.py` |
| Page (/approvals)       | 10 | `tests/platform/test_approvals_page.py` |
| Page (/settings/live-mode) | 9 | `tests/platform/test_live_mode_page.py` |
| API                     | 14 | `tests/platform/test_approvals_api.py` |
| **P0 INVARIANT**        |  6 | `tests/security/test_live_mode_off_invariant.py` |
| **Total**               | **69** | — |

Spec asked for 30; shipped 69.

## P0 invariant verification

`tests/security/test_live_mode_off_invariant.py` composes all four
gates and pins every branch of the truth table that matters:

1. **Clean install refuses** — `test_default_is_off` and
   `test_can_send_live_order_refuses_by_default`.
2. **Live-mode alone isn't enough** — `test_enable_but_no_approval`
   (approval not granted).
3. **Approval alone isn't enough** — `test_over_budget_still_refused`
   (risk-budget gate refuses even after approval).
4. **ALL FOUR pass -> order allowed** — `test_all_four_gates_open`.
5. **Kill-switch trip mid-flow -> refuses** —
   `test_kill_switch_flip_refuses`.

Full test output:

```
tests/security/test_live_mode_off_invariant.py::
  TestCleanInstallBlocks::test_default_is_off                       PASSED
  TestCleanInstallBlocks::test_can_send_live_order_refuses_by_default PASSED
  TestLiveModeAloneIsNotEnough::test_enable_but_no_approval         PASSED
  TestApprovalButNoBudget::test_over_budget_still_refused           PASSED
  TestAllFourPassAllowsOrder::test_all_four_gates_open              PASSED
  TestKillSwitchTripsMidFlow::test_kill_switch_flip_refuses         PASSED
============================== 6 passed in 0.48s ===============================
```

## What else was verified

- **Timeout cleanliness:** `test_approval_timeout.py` pins that a
  timed-out entry cannot be approved (idempotency of state
  transitions) and that `can_send_order` reaps stale entries before
  answering.
- **Entry validation:** submit rejects malformed payloads (missing
  fields, invalid `side`, non-positive numerics, malformed
  `risk_snapshot`).
- **Audit trail:** every state transition appends to
  `<config_dir>/approvals.jsonl`. `reset_state` clears both memory
  and file for tests.
- **Ceremony strictness:** `enable_ceremony` refuses without both
  checks. Case-sensitive confirmation.
- **Fail-closed on keyring errors:** `is_live_mode_enabled` returns
  False on any exception path (grep-verified + test).
- **API contracts:** GET `/api/approvals/list`, POST
  `/api/approvals/<id>/{approve,reject}`, POST `/api/approvals/submit`
  (internal-token gated, fails closed on empty token), GET
  `/api/live-mode/{status,warning}`, POST `/api/live-mode/{enable,disable}`.
- **Auth gate on user-facing writes:** POST endpoints under
  `/api/approvals/*` and `/api/live-mode/*` return 401 when the
  install-token gate is enforced and no token is presented.
- **Warning endpoints readable pre-auth:** `/api/live-mode/warning`
  and `/api/approvals/warning` in
  `_UNAUTHENTICATED_API_PATHS` -- the ceremony can render before
  the user has a token.
- **Restricted-directory quarantine:** neither `approval_queue.py`
  nor either new page imports from `agent/live`, `agent/risk`, or
  `agent/squad`. `can_send_live_order` reaches into
  `agent.platform.kill_switches` and `agent.platform.risk_budget`
  (both product-branch modules, Sprint 2 additions).
- **Cold-install renderable:** `/approvals` shows empty state,
  `/settings/live-mode` shows OFF banner. No error banners.
- **Mobile 700px:** approvals grid collapses to `1fr`; ceremony
  buttons stack column-wise.

## Sprint suite delta

Full suite pre-F013: 1378 passed.
Full suite post-F013: **1447 passed** (+69 exactly).

## Deferred / not in scope (D065)

- Wiring `approval_queue.submit(...)` into the squad's proposal
  path (future integration sprint).
- Multi-user approval (single-user install per D052).
- SMS / push channels (F014 handles Telegram + SSE only).

## Sign-off

QA → Legal → CEO: **APPROVED**.
