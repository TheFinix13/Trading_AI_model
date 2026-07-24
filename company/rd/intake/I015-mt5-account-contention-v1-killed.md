---
id: I015
source: ceo
submitter: user_advocate
submitted_at: 2026-07-24T13:42:00Z
classification: BUG
priority: P0
status: resolved
route: engineering
linked_features: ["F007", "F018"]
linked_decisions: ["D124"]
linked_experiments: []
contact: internal (CEO hit it live right after the 2026-07-24 VM cutover)
resolved_at: 2026-07-24T15:30:00Z
history:
  - stage: filed
    at: 2026-07-24T14:00:00Z
    by: user_advocate
    note: "CEO reported v1 kill.txt + 'unconfirmed' closures while trades were still open on MT5; hub numbers read as mixed v1/v2."
  - stage: resolved
    at: 2026-07-24T15:30:00Z
    by: engineering
    note: "Same-day fix under D124: [broker] terminal_path pin + dual-terminal runbook. v1 recovery steps handed to CEO."
---

# I015 — Single MT5 terminal shared by two accounts: the V2 broker probe switched v1's account and tripped its kill switch

## What happened

The VM runs ONE MT5 terminal. During V2 onboarding, the broker-wizard
probe (`F007 test_connection`) called `mt5.initialize(login=436983644,
...)` for the new "V2 Platform" demo account — which switched the
single terminal's logged-in account out from under the v1 zones agent.
v1 saw equity fall from ~$969 to the new account's $500 in one poll,
concluded catastrophic drawdown, wrote `kill.txt`, and attempted an
emergency close of positions that no longer existed on the newly
connected account (hence "unconfirmed" closures). The v1 trades remain
open, untouched, on the original account server-side.

The hub then showed v1's card reporting the V2 account's balance,
which read as "both feeds mixed together". The feeds were never mixed
— v1 was genuinely reporting the wrong account.

## Impact

- v1 halted (correctly, by its own safety layer) — real demo orders
  suspended until manual recovery.
- CEO trust hit: dashboard appeared to conflate the two products.

## Root cause

Architecture, not code: one terminal cannot serve two accounts. Any
`mt5.initialize(login=...)` from the platform side (probe, F018
executor) mutates the shared terminal's session globally.

## Resolution (D124)

- `[broker] terminal_path` + `portable` in `platform.toml`
  (`agent/platform/config.py`); resolver
  `broker_connection.terminal_launch_args()`.
- Probe (`broker_connection.test_connection`) and executor
  (`live_executor.RealMt5OrderAdapter.connect`) now pass the pin
  positionally to `mt5.initialize` — every platform-side MT5 session
  targets the dedicated second portable terminal; unset key keeps the
  historic single-terminal behaviour byte-identical.
- v2's bar feed was already non-interfering: it logs in read-only with
  v1's OWN credentials, re-asserting (never switching) terminal A.
- Ops guide: `docs/runbooks/dual-mt5-terminals.md` — second portable
  terminal setup, v1 recovery (restore account in terminal A, delete
  `kill.txt`, restart), and the separation-verification checklist.
- Hub subtitle now states each agent runs on its own account and the
  cards never mix.
- Invariant going forward: any new MT5 call site in `agent/platform/*`
  MUST route through `terminal_launch_args()`.
