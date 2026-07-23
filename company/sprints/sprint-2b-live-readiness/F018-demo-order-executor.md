# F018 — Demo-order executor: the four gates get their caller

- **Sprint:** sprint-2b-live-readiness
- **Priority:** P0 — the D065-successor step 1 (D095 gap 8).
- **Lane:** Real-Trading integration, DEMO ONLY.
- **Consumes:** F013 `can_send_live_order` (all four gates) +
  approval queue, F012 `risk_budget.record_fill`, F011 kill switches
  (via the composition), F007 `broker_connection.load_credentials`,
  F014 alerts bus, F006 keyring, F009 rate limiter / install token.
- **Consumed by:** the human operator on `/approvals` (Execute
  button). NOT by the squad — squad→submit wiring is explicitly out
  of scope.
- **Feature flags:** `auth: true`, `credentials: true`,
  `security_relevant: true`, `legal_relevant: true`.

## Problem statement

CEO (2026-07-24): "why not connect to mt5 and my exness and use a
demo account." Sprint 2 shipped four composition-tested safety gates
that nothing calls (D065 — correct then; D095 names it the biggest
product gap now). F018 gives them exactly one caller, pointed at a
dedicated Exness DEMO account, default-disabled, structurally unable
to reach a non-demo server.

## Scope (in)

### `agent/platform/live_executor.py` (new)

**Adapter seam** — `Mt5OrderAdapter` protocol:

```python
connect(alias) -> (ok, reason)   # creds via broker_connection.load_credentials; never logged
account_info() -> dict | None    # incl. "server" name for the demo guard
send_market_order(symbol, side, volume, sl, tp) -> {"ticket": int} | {"error": str}
close_position(ticket) -> {"ok": bool, ...}
shutdown() -> None
```

Real implementation (`RealMt5OrderAdapter`) imports MetaTrader5
lazily INSIDE methods (Windows-only), guarded; every test uses a fake
adapter. `adapter_available()` reports whether MetaTrader5 is
importable on this host.

**Config** — `[live_executor]` table in `platform.toml`:

```toml
[live_executor]
enabled = false                 # gate #5; default-disabled
demo_only = true                # REQUIRED acknowledgement; refuse if false/absent
allowed_server_patterns = ["*Trial*", "*Demo*", "*demo*"]
max_volume_lots = 0.01          # hard cap; refuse above
broker_alias = ""               # which stored credential alias to trade through
```

**Execution flow** — `execute_approved(approval_id, adapter, ...)`:

1. Refuse unless `enabled = true` (default false — gate #5).
2. Re-run `can_send_live_order(entry)` — all four gates —
   immediately before send (fresh check, never cached).
3. **DEMO-ONLY guard:** `demo_only` ack must be exactly true, AND the
   adapter's connected server name must match the allowlist
   (fnmatch, fail-closed if missing/blank/unmatched).
4. Volume hard-cap: refuse `size > max_volume_lots`.
5. Refuse when broker alias or stored credentials are absent.
6. Send. On fill: `risk_budget.record_fill`, mark the approval
   CONSUMED (single-use — a second execute of the same approval
   refuses), append to `<config_dir>/executions.jsonl`, publish
   `trade_fill` alert. On error: publish alert, mark approval failed,
   NEVER retry automatically.

Every refusal returns `(False, reason)` and appends an
`executions.jsonl` row — refusals are on tape too.

### Surfaces

- `POST /api/executor/execute/<approval_id>` — install-token-gated +
  rate-limited (standard `/api/*` gate).
- `GET /api/executor/status` — `{enabled, demo_only_ack,
  allowed_server_patterns, max_volume_lots, broker_alias_configured,
  adapter_available, state: disabled|not-on-windows|ready,
  recent_executions}` (last N from executions.jsonl).
- `/approvals` page: an Execute button on approved entries, shown
  armed only when executor status says `ready`; the existing Legal
  warning stays; new executor warning copy drafted via Legal persona
  at `company/legal/executor-demo-warning.md` (F013 pattern), served
  at `GET /api/executor/warning` (unauthenticated read, like the
  other warning routes).

### P0 invariant extensions

`tests/security/test_live_mode_off_invariant.py` is EXTENDED (never
weakened) with:

- `TestExecutorDisabledByDefault` — clean install + all four gates
  open → executor still refuses (gate #5).
- `TestExecutorRefusesOnAnyGateFailure` — each of the four gates
  individually blocking with a fake adapter ready to fill.
- `TestExecutorRefusesWithoutBrokerCreds` — alias absent / creds
  missing → refuse.
- `TestExecutorDemoOnlyGuard` — wrong server name refuses; missing
  `demo_only` ack refuses; `demo_only = false` refuses.

### Runbook

`docs/RUNBOOK_demo_launch.md` new section: connecting the
"V2 Platform" demo account (login 436983644 / Exness-MT5Trial9,
password NEVER in the repo — keyring only) via `/settings/broker` on
the VM, enabling the executor, the full ceremony order (broker creds
→ risk budget → live-mode ceremony → submit test order via
`/api/approvals/submit` → approve on `/approvals` → execute), and
the kill-switch drill.

## Scope (out)

- Squad → `approval_queue.submit` wiring (next-gen + future
  integration decision).
- Real (non-demo) servers — structurally refused; also hard-NO per
  `escalation.md` §5.
- Auto-retry, position management, trailing stops, partial closes.
- Pending/limit orders — market orders only for the first caller.

## Tests (target ≥ 45 incl. the P0 extensions)

`tests/platform/test_live_executor_module.py` — config parsing,
demo-guard matrix, volume cap, single-use approvals, fill →
`record_fill`, error paths, executions.jsonl audit;
`tests/platform/test_executor_api.py` — status + execute endpoints,
auth gate, warning route; `tests/platform/test_approvals_page_executor.py`
— Execute button presence + states; plus the
`tests/security/test_live_mode_off_invariant.py` extensions above.

## Acceptance

- A clean install cannot execute ANYTHING: disabled by default,
  four gates closed, no creds, no ack — four independent refusals.
- With a fake adapter and every gate deliberately opened, execution
  fills exactly once per approval and records the fill.
- Wrong-server fake adapter refuses even with everything else open.
- P0 invariant file green UNWEAKENED (original 6 cases byte-intact).
- Full suite + claim audit green; Legal review on tape.

## Files touched

New: `agent/platform/live_executor.py`,
`company/legal/{executor-demo-warning.md,F018-review.md}`, 3 test
files. Edited: `agent/platform/{config,pages}.py`,
`scripts/serve_platform.py`, `platform.toml.example`,
`tests/security/test_live_mode_off_invariant.py` (extend-only),
`docs/RUNBOOK_demo_launch.md`, `company/legal/claim_register.md`,
`company/ledger/{company_state.json,decisions_log.md}`.
