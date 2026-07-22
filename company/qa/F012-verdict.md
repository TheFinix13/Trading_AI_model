# F012 — QA verdict

**Verdict:** GREEN — ready for merge.

## Coverage

| Layer  | Tests | File |
|--------|-------|------|
| Module (risk_budget) | 10 | `tests/platform/test_risk_budget_module.py` |
| Module (broker_health) | 7 | `tests/platform/test_broker_health_module.py` |
| Page   | 9 | `tests/platform/test_risk_page.py` |
| API    | 12 | `tests/platform/test_risk_api.py` |
| **Total** | **38** | — |

Spec asked for 25; shipped 38.

## What was verified

- **Three-tier cap enforcement:** `can_send_order` refuses when
  per-day, per-symbol or per-strategy cap is exceeded. Wins do NOT
  restore headroom (pinned by test).
- **UTC-day rollover:** budget accounting slices by UTC date.
- **State persistence:** `record_fill` appends JSONL that survives
  process restarts. `reset_state` clears the ledger for tests.
- **30-second cache:** broker health probe is called at most once per
  TTL window. Custom `cache_ttl=0` forces refetch.
- **Password never in return payload:** `test_password_scrubbed`
  passes even when the raw password contains high-entropy strings.
- **`list_health_states` matches configured aliases:** unprobed
  aliases render `reason="not yet probed"`.
- **API contracts:** GET `/api/risk/state`, GET/POST `/api/risk/budgets`.
- **Auth gate on POST:** `POST /api/risk/budgets` returns 401 when
  install-token enforcement is on and no token is presented; config is
  NOT mutated.
- **Page shape:** three sections (Live exposure / Budget headroom /
  Broker connections), 30 s poll interval, mobile media-query
  collapses grid, Sprint 2 caveat visible.
- **Restricted-directory quarantine:** neither module imports from
  `agent/live`, `agent/risk`, or `agent/squad`. `broker_health` reuses
  the existing `broker_connection` MT5 probe (Sprint 1 module) via
  monkeypatchable indirection.

## Live-mode-off invariant

F012 is the THIRD of four live-mode-off gates. Its
`can_send_order(symbol, strategy, worst_case_loss)` returns
`(False, "<reason>")` whenever any cap would be breached. The
end-to-end invariant test lives in F013's
`test_live_mode_off_invariant.py`.

## Deferred / not in scope

- Amber "headroom low" colour palette bump (deferred to F013).
- In-UI budget editor (deferred; API-only in Sprint 2).
- Wins-credit-against-cap (asymmetric by design; requires Legal
  review to change).
- Real broker probe under load (mocked in tests).

## Sign-off

QA → CPO: **APPROVED**.
