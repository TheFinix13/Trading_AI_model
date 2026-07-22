# F013 — Legal review

**Verdict:** APPROVED — with rolling constraints logged.

## Documents reviewed

- `company/legal/live-mode-warning.md` (new) -- verbatim body served
  via `GET /api/live-mode/warning`.
- `company/legal/approval-queue-warning.md` (new) -- verbatim body
  rendered above the `/approvals` pending list.
- `agent/platform/approval_queue.py` -- public API surface,
  registered in `company/legal/claim_register.md` under
  "F013 — `agent/platform/approval_queue.py`".
- The UI ceremonies at `/settings/live-mode` and `/approvals`.

## Substantiated claims

- **"Default OFF"** — the module returns False on missing keyring
  entry AND on any keyring exception. Test-pinned by
  `TestCleanInstallBlocks::test_default_is_off`.
- **"Ceremony requires acknowledgement + typed confirmation"** —
  `enable_ceremony` refuses if EITHER check fails. Test-pinned by
  `test_live_mode_module.TestCeremony` (three cases).
- **"5-minute default timeout"** — `DEFAULT_TIMEOUT_SECONDS = 300`.
  Rolling constraint: any change must strike the claim wherever
  cited.
- **"Rejection has zero market side-effect"** — `reject()` only
  writes to the audit log and mutates in-memory state; it does not
  call any broker interface. Grep-verified.
- **"Every state change is audit-logged"** — the JSONL at
  `<config_dir>/approvals.jsonl` receives an event on `submit`,
  `approved`, `rejected`, `timed_out`, and `live_mode`.
- **"The 4-check pathway is the only pathway a future live-order
  flow can travel"** — `can_send_live_order` composes all four
  checks. P0 test `tests/security/test_live_mode_off_invariant.py`
  pins that no combination of three-out-of-four gates open lets a
  fourth-gate-blocked order through.

## Rolling constraints

- **Ceremony-strictness constraint:** the exact confirmation phrase
  is `ENABLE LIVE MODE`. Case-insensitive or partial-match
  regressions must trigger a fresh Legal review because they
  materially change the safety claim.
- **Fail-closed constraint:** any keyring exception in
  `is_live_mode_enabled` returns False. Removing the try/except
  would flip the default to True on any keyring outage.
- **"No live wiring in Sprint 2"** — Sprint 2 does NOT call
  `approval_queue.submit(...)` from any pathway. If a future
  commit adds that call, it MUST land under a fresh sprint with
  fresh security + legal reviews (D065 hard invariant).
- **"5-minute default"** — verbatim tied to
  `DEFAULT_TIMEOUT_SECONDS == 300`.
- **"Internal-only submit endpoint"** — `POST /api/approvals/submit`
  fails closed on empty `[internal].token`. The token is deliberately
  absent from the shipped `platform.toml.example`.

## Claim register diff

+ F013 -- `agent/platform/approval_queue.py` block (15 accessors +
  6 module constants + rolling constraints).

## Handoff

Legal -> CEO: **APPROVED**. Ready for CPO sign-off.
