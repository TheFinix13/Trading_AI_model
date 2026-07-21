# F013 — Trade approval mode + `/approvals` queue + live-mode toggle

- **Sprint:** sprint-2-real-trading
- **Priority:** P0 — **the central Real-Trading feature.**
- **Lane:** Central. Consumes every other Sprint 2 feature.
- **Consumes:** F006 (auth gate), F009 (session freshness on approve),
  F011 (`kill_switches.is_killed()`), F012 (`risk_budget.can_send_order()`).
- **Consumed by:** F014 — `approval_submitted` event on the bus.
  Future integration sprint wires the squad's proposal path to
  `approval_queue.submit(...)`.
- **Feature flags:** `auth: true`, `credentials: true`,
  `legal_relevant: true` → mandatory `security` AND `legal`.

## Problem statement

The user says "let the squad trade for me". Doing that safely
means:

1. An explicit ON-switch (default OFF, requires deliberate friction
   to enable).
2. Every proposed order surfaces for human approval before it hits
   the broker.
3. If the user ignores the approval, the order times out and is
   never sent.
4. The system respects the safety layer even if the user approves
   (kill-switches + risk budget + live-mode-on).

F013 delivers all four.

## The 4-check live-order pathway

This is the invariant Sprint 2 pins:

```python
def can_send_live_order(entry) -> bool:
    if not live_mode_enabled():                            # (1) F013
        return False
    if kill_switches.is_killed(entry.symbol):              # (2) F011
        return False
    if not risk_budget.can_send_order(entry.symbol,
                                      entry.strategy,
                                      entry.worst_case)[0]:  # (3) F012
        return False
    if not approval_queue.can_send_order(entry.approval_id):  # (4) F013
        return False
    return True
```

The single most important test in Sprint 2:
`tests/security/test_live_mode_off_invariant.py` composes these four
checks and pins that **no order can send from a clean install without
all four passing**.

## Scope (in)

### `agent/platform/approval_queue.py` (new)

Public API:

```python
DEFAULT_TIMEOUT_SECONDS: int = 5 * 60  # 5 minutes
STATUSES: tuple[str, ...] = ("pending", "approved", "rejected", "timed_out")

def submit(entry: dict) -> str  # returns approval_id
def approve(approval_id: str, by: str = "user") -> bool
def reject(approval_id: str, reason: str, by: str = "user") -> bool
def timeout_reap(now: float | None = None) -> list[str]  # expired ids
def can_send_order(approval_id: str) -> bool
def list_entries(status: str = "all", limit: int = 100) -> list[dict]
def reset_state() -> None  # test helper
def set_timeout_seconds(seconds: int) -> None
def is_live_mode_enabled() -> bool
def set_live_mode(enabled: bool) -> bool  # keyring-backed
```

Entry shape:

```json
{
  "id": "urn-uuid-...",
  "timestamp": "2026-07-22T00:...",
  "symbol": "EURUSD",
  "side": "buy",
  "size": 0.10,
  "entry": 1.0850,
  "stop": 1.0820,
  "take_profit": 1.0920,
  "rationale": "A1_baseline detected zone rejection at H4",
  "source_agent": "A1_baseline",
  "risk_snapshot": {"worst_case_loss": 30.0},
  "timeout_at": "2026-07-22T00:...",
  "status": "pending",
  "resolved_at": null,
  "resolved_by": null,
  "resolution_reason": null
}
```

Storage:
- In-memory dict for O(1) lookup.
- Append-only jsonl at `<config_dir>/approvals.jsonl` for audit — every
  status transition appends a line.
- `timeout_reap()` runs on every `list_entries()` / `can_send_order()`
  call to expire stale entries.

Live-mode toggle: value stored in keyring
`namespace="bluelock", key="live_mode_enabled"` (`"true"` / `"false"`).
Default missing == disabled (belt-and-braces). Turning ON requires
the ceremony in the UI; the module's `set_live_mode(True)` succeeds
if called directly (test / API), but the UI ceremony gates the API.

### `APPROVALS_PAGE` in `agent/platform/pages.py` (new)

Route: `/approvals`.

Layout:

- Big **PENDING** section at top: one card per pending entry with
  Symbol / Side / Size / Entry / Stop / TP / Rationale / Countdown
  timer / Approve (big green) / Reject (red) buttons + optional
  reason textarea for reject.
- Below: **APPROVED / REJECTED / TIMED-OUT** tail (last 20 each).
- Live update: 3-second poll to `/api/approvals/list?status=pending`
  (SSE upgrade path via F014 when it ships — feature-detect the
  EventSource wire on load).

Live-mode toggle sits at `/settings/live-mode` (own page). Contains:

1. Current state indicator (`OFF` in dim, `ON` in red).
2. When OFF → button "Enable live mode..." opens the ceremony:
   - Checkbox "I understand this will place real orders".
   - Text input requiring exact typed value `ENABLE LIVE MODE`.
   - Verbatim Legal disclaimer body loaded from
     `/api/live-mode/warning` (which reads
     `company/legal/live-mode-warning.md`).
   - Enable button unlocks only when both are satisfied.
3. When ON → button "Turn off live mode" is one-click (no ceremony).

Every state change is logged and appended to the approvals audit.

### HTTP APIs (in `scripts/serve_platform.py`)

Approvals:
- `GET /api/approvals/list?status=<pending|all|approved|rejected|
  timed_out>` — install-token-gated.
- `POST /api/approvals/<id>/approve` — install-token-gated.
- `POST /api/approvals/<id>/reject` — body `{reason}`, install-token-gated.
- `POST /api/approvals/submit` — body = approval entry (validated).
  Gated on an **internal-only token** (a separate config key —
  `[internal]` in `platform.toml`). Sprint 2 does not call this from
  any pathway. Future integration sprint will.

Live-mode:
- `GET /api/live-mode/status` — `{enabled: bool}` — install-token-
  gated.
- `POST /api/live-mode/enable` — body `{acknowledged: bool,
  confirmation: "ENABLE LIVE MODE"}` — install-token-gated.
- `POST /api/live-mode/disable` — install-token-gated.
- `GET /api/live-mode/warning` — verbatim text from
  `company/legal/live-mode-warning.md`. NOT gated (must be readable
  in the ceremony before the user has toggled anything).

### Legal (drafted by Legal)

Two verbatim documents:

- `company/legal/live-mode-warning.md` — the warning body the user
  reads before enabling live-mode. Verbatim from Legal; served via
  `/api/live-mode/warning`.
- `company/legal/approval-queue-warning.md` — the "even approved
  orders can lose money" note rendered above the pending list.

Legal review handoff written BEFORE QA per D048.

### Tests (30+)

- `tests/platform/test_approval_queue_module.py` (12) — submit /
  approve / reject / timeout, can_send_order gating (must be
  approved), reset, list filter, timeout monotone, entry validation
  (missing fields → ValueError), audit jsonl append.
- `tests/platform/test_live_mode_module.py` (5) — is_live_mode_enabled
  default False, set(True) persists, set(False) persists, unauthorized
  set is rejected, keyring round-trip.
- `tests/platform/test_approvals_page.py` (4) — page emits, has
  pending section + approve/reject buttons + countdown JS, mobile
  media query, consumes withStates().
- `tests/platform/test_live_mode_page.py` (3) — page emits, has
  ceremony (checkbox + typed value + disclaimer), one-click disable
  when on.
- `tests/platform/test_approvals_api.py` (6) — list / approve /
  reject / submit-internal / live-mode-status / live-mode-enable
  contract, all install-token-gated, submit-internal rejects without
  internal token.
- **`tests/security/test_live_mode_off_invariant.py` (5)** — the
  4-check composition:
    1. Clean install: `can_send_live_order(any_entry)` = False.
    2. Enable live-mode only: still False (no approval).
    3. Enable + submit + approve, no risk-budget-ok: False.
    4. All 4 pass: True.
    5. Kill-switch trips mid-flow: False again.
- `tests/platform/test_approval_timeout.py` (2) — timeout after 5
  min expires cleanly, can_send_order returns False on timed-out.

## Scope (out)

- Wiring the squad's proposal path to `approval_queue.submit(...)`
  (D065 invariant — future integration sprint).
- Multi-user approval (single-user install per D052).
- SMS / push channels (F014 handles Telegram + SSE only).

## Legal

Two new verbatim documents (drafted by Legal, reviewed BEFORE QA
per D048):

- `company/legal/live-mode-warning.md`
- `company/legal/approval-queue-warning.md`

Claim register entries:
- `approval_queue.can_send_order` — public safety-gate claim.
- `approval_queue.submit` — public "queue proposal" claim.
- `approval_queue.is_live_mode_enabled` — public live-mode-off default.

## UX

- `company/research/F013-user-journey.md` — the "I want to enable
  live but I'm nervous" journey; approval queue as the moral layer.
- `company/design/F013-mocks.md` — approvals page + live-mode page,
  desktop + 375 px.

## Acceptance

- All 30+ new tests pass — **including
  `test_live_mode_off_invariant.py` (P0 blocker if any test in this
  file fails)**.
- Full suite green.
- Cold-install → open `/approvals` shows empty state (no error).
- Cold-install → open `/settings/live-mode` shows OFF state.
- Ceremony blocks Enable until BOTH checkbox and typed-value pass.
- Approval times out cleanly (test enforced).
- No live pathway anywhere in this sprint calls `approval_queue.
  submit(...)` from an integration surface (grep-verified).
- Legal review is on tape at `company/legal/F013-review.md` before
  QA verdict.

## Files touched

New:
- `agent/platform/approval_queue.py`
- `tests/platform/test_approval_queue_module.py`
- `tests/platform/test_live_mode_module.py`
- `tests/platform/test_approvals_page.py`
- `tests/platform/test_live_mode_page.py`
- `tests/platform/test_approvals_api.py`
- `tests/platform/test_approval_timeout.py`
- `tests/security/test_live_mode_off_invariant.py` **(P0 pin)**
- `company/research/F013-user-journey.md`
- `company/design/F013-mocks.md`
- `company/legal/live-mode-warning.md` **(Legal-drafted)**
- `company/legal/approval-queue-warning.md` **(Legal-drafted)**
- `company/legal/F013-review.md`
- `company/qa/F013-verdict.md`
- Handoffs.

Edited:
- `agent/platform/pages.py` — `APPROVALS_PAGE` + `LIVE_MODE_TOGGLE_PAGE`
- `scripts/serve_platform.py` — 8+ new routes
- `company/legal/claim_register.md` — F013 entries
- `company/brand/copy.md` — approvals + live-mode UI strings
- `company/ledger/{company_state.json, decisions_log.md}`
