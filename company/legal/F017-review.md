# F017 — Legal review (incl. F014 event-type whitelist re-review)

**Verdict:** APPROVED — with rolling constraints logged.

## Why this review fired

The F014 rolling constraint in `company/legal/claim_register.md`
says the alerts-bus event types are a closed whitelist and "adding a
new event type materially changes the alerts claim ... and requires a
Legal re-review AND a per_event default in `alerts_telegram`." F017
adds `watchdog_alert`. This document is that re-review, done inline
before ship per the Sprint 2b charter.

## Documents / surfaces reviewed

- `agent/platform/watchdog.py` — the 7-check registry, the
  state-transition publisher, the cached snapshot.
- `agent/platform/alerts.py` — `EVENT_TYPES` gains `watchdog_alert`.
- `agent/platform/alerts_telegram.py` — `_DEFAULT_PER_EVENT` gains
  `watchdog_alert: True`.
- `GET /api/watchdog/status`, the `/hq` status strip, and
  `scripts/run_watchdog.py`.

## Substantiated claims

- **"Notified of irregular behaviors, not spammed"** — publishing is
  state-transition-only: a check must CHANGE into warn/alarm (or
  recover out of it) to emit an event. Steady-state polling emits
  nothing. Last-known state persists at
  `<config_dir>/watchdog_state.json` so restarts don't re-fire.
  Test-pinned by `test_watchdog_transitions.py`.
- **"Observe, never mutate"** — no check writes to the system it
  watches; the module's only write is its own state file. The runner
  docstring carries the same rule.
- **"Covers the company loop too"** — `intake_sla`, `sprint_pulse`,
  and `ledger_drift` read `company/rd/intake/` front matter and the
  company ledger only. No intake BODY text (which may contain user
  contact info) is ever emitted — details carry item IDs + ages only.
- **"Never a 500"** — every check degrades to `alarm` (descriptive
  detail) or `na`; the one deliberate raise is `run_check` on an
  unknown id (caller bug).

## Payload privacy check

`watchdog_alert` payloads carry: `check` (id), `status`, `previous`,
`detail` (a short operational string: ages, counts, filenames),
`recovered`. No credentials, no tokens, no user contact info, no
intake body text can reach the payload — `detail` strings are built
exclusively from artefact ages/counts and item IDs.

## Rolling constraints

- **Whitelist is now SEVEN types** (`trade_fill`, `stop_hit`,
  `kill_switch_trip`, `risk_budget_breach`, `approval_submitted`,
  `platform_down`, `watchdog_alert`). Any further addition repeats
  this re-review.
- **Transition-only constraint:** if a future change publishes on
  every poll (removing the state-file comparison), the "you can trust
  the alert stream not to nag" claim dies and Legal must re-review —
  alert fatigue is a safety regression for a trading product.
- **Detail-string constraint:** `detail` must remain built from
  artefact metadata (ages, counts, IDs, filenames). Piping file
  CONTENTS (intake bodies, ledger context strings) into `detail`
  requires a fresh review.

## Claim register diff

+ F017 — `agent/platform/watchdog.py` block (12 accessors + module
  constants + rolling constraints).
~ F014 — `alerts.py` rolling constraint updated six → seven types,
  citing this review.

## Handoff

Legal -> CEO: **APPROVED**. `watchdog_alert` may ship.
