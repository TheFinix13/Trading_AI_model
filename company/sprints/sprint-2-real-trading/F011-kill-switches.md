# F011 — Kill-switches infrastructure (per-symbol + global, hot-reload)

- **Sprint:** sprint-2-real-trading
- **Priority:** P0
- **Lane:** Safety primitive. Second of the four live-mode-off checks.
- **Consumes:** F006 (`auth.py` install-token for admin APIs).
- **Consumed by:** F013 — `kill_switches.is_killed()` is the SECOND
  check in the 4-gate live-order pathway (after `live_mode_enabled`).
- **Feature flags:** `auth: true` on admin routes → `security` fires.

## Problem statement

The v1 zones agent (`agent/live/*`) already respects `kill.txt` files
(see `agent/utils.py::kill_switch_active`). Sprint 2's live-order
scaffolding needs an equivalent primitive it can pattern-match against,
**without importing from `agent/live/*`** (D065 hard invariant).

Requirements:

- Same shape as the v1 protocol (file existence = kill), but scoped
  under `<config_dir>/kill/`, not the repo root.
- Global kill AND per-symbol kill (EURUSD / GBPUSD / USDCAD / USDJPY /
  USDCHF for the initial supported set).
- Hot-reload: the platform reads the current state every time
  `is_killed()` is called, with an mtime-based cache to keep it cheap.
- Audit log of activate/clear events.
- Web UI (`/settings/kill-switches`) to toggle from the platform.

## Scope (in)

### `agent/platform/kill_switches.py` (new — read path)

Read-only view over kill state.

Public API:

```python
KILL_DIR_ENV: str = "BLUELOCK_KILL_DIR"
DEFAULT_KILL_DIRNAME: str = "kill"
SUPPORTED_SYMBOLS: tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDCAD", "USDJPY", "USDCHF",
)
GLOBAL_KEY: str = "GLOBAL"

def kill_dir() -> Path
def is_killed(symbol: str | None = None) -> bool
def list_killed() -> list[dict]  # [{scope, reason, activated_at, by}]
def reset_cache_for_tests() -> None
```

Flag file shape: `<kill_dir>/<SYMBOL>.flag` (or `GLOBAL.flag`), body
is JSON: `{"reason": str, "activated_at": iso8601, "by": str}`.
Missing file = not killed. `is_killed(None)` returns True iff the
global kill exists OR the caller has passed no per-symbol filter.
`is_killed("EURUSD")` returns True iff EURUSD's flag OR the global
flag exists.

Cache: keep the last-seen mtime of the dir. Every `is_killed()`
call stats the dir; if mtime changed (or first call), rescan.

### `agent/platform/kill_switch_admin.py` (new — write path)

```python
def activate_kill(symbol: str | None = None,
                  reason: str = "",
                  by: str = "user") -> bool
def clear_kill(symbol: str | None = None) -> bool
def recent_events(limit: int = 20) -> list[dict]
```

Every activate / clear appends a JSON line to
`<config_dir>/kill_events.jsonl`:

```json
{"ts": "2026-07-22T...", "action": "activate", "scope": "EURUSD",
 "reason": "flash spread", "by": "user"}
```

`recent_events(20)` reads the tail. Symbol validated against
`SUPPORTED_SYMBOLS` (or `None` for global).

### `KILL_SWITCHES_PAGE` in `agent/platform/pages.py` (new)

Route: `/settings/kill-switches`. Layout:

- Grid of toggles: `[GLOBAL] [EURUSD] [GBPUSD] [USDCAD] [USDJPY]
  [USDCHF]`. Each cell shows the current state (active in red / inert
  in dim), with a click-to-activate / click-to-clear action.
- Reason textarea (max 200 chars). Required when activating.
- Recent events panel below — last 20 activate/clear entries.
- Consumes `withStates()` from F005 for the load / error state.
- Mobile: media query at 700 px collapses the grid to a single column.

### HTTP APIs (in `scripts/serve_platform.py`)

- `GET /api/kill-switches/status` — `{killed_scopes: [...], events:
  [...]}`.
- `POST /api/kill-switches/activate` — body `{symbol?, reason}`.
- `POST /api/kill-switches/clear` — body `{symbol?}`.

All three are install-token-gated on non-localhost.

### The live-mode-off gate contract

F011 introduces this contract for future integration:

```python
# In a future integration sprint's live pathway:
if not live_mode_enabled():           # F013
    return
if kill_switches.is_killed(symbol):   # F011 — THIS SPRINT
    return
if not risk_budget.can_send_order(symbol, worst_case): return  # F012
if not approval_queue.can_send_order(id): return               # F013
send_order(...)
```

F011 provides the `is_killed()` function. It does not wire it into
any live pathway. That wiring is future-sprint work.

### Tests (20)

- `tests/platform/test_kill_switches_module.py` (8) — is_killed()
  behavior (empty / global / per-symbol), cache invalidation on
  mtime change, SUPPORTED_SYMBOLS validation, kill_dir override
  via env, list_killed() shape, unknown-symbol rejected.
- `tests/platform/test_kill_switches_admin.py` (5) — activate
  writes the flag + audit entry, clear removes flag + audit entry,
  activate w/o reason still logs "no-reason", audit tail bounded,
  activate/clear idempotent.
- `tests/platform/test_kill_switches_page.py` (4) — page emits,
  contains grid + reason textarea, has mobile media query,
  consumes withStates().
- `tests/platform/test_kill_switches_api.py` (3) — status/activate/
  clear endpoints, install-token gate on non-localhost.
- Golden: `test_kill_switches_module.py::test_global_kill_masks_all`
  — activate GLOBAL → every `is_killed(symbol)` returns True.

## Scope (out)

- Wiring into any live-order pathway (D065 invariant).
- Programmatic "expire after N minutes" auto-clear (v1 zones agent
  doesn't have this; F011 mirrors the existing shape).
- Broadcast to multiple installs (single-user model per D052).

## Legal

Adds a claim entry to `claim_register.md`:

- `kill_switches.is_killed` — public safety-primitive claim
  ("global and per-symbol kill switches with hot-reload").

No user-facing legal warning needed (the safety layer is described
in F013's live-mode-warning).

## UX

- `company/research/F011-user-journey.md` — the panic-mode operator's
  journey: broker misbehaving on one pair, want to halt just that
  pair without stopping everything.
- `company/design/F011-mocks.md` — desktop + 375 px mocks of the
  toggle grid, reason input, event log.

## Acceptance

- 20 new tests pass.
- Full suite green.
- Golden-path test proves activating global kill masks every symbol.
- Mobile pass at 375 px.
- Page renders empty-state cleanly (`list_killed() == []`).
- No import from `agent/live/*` or `agent/risk/*` (grep-verified).

## Files touched

New:
- `agent/platform/kill_switches.py`
- `agent/platform/kill_switch_admin.py`
- `tests/platform/test_kill_switches_module.py`
- `tests/platform/test_kill_switches_admin.py`
- `tests/platform/test_kill_switches_page.py`
- `tests/platform/test_kill_switches_api.py`
- `company/research/F011-user-journey.md`
- `company/design/F011-mocks.md`
- `company/qa/F011-verdict.md`
- Handoffs.

Edited:
- `agent/platform/pages.py` — `KILL_SWITCHES_PAGE`
- `scripts/serve_platform.py` — 3 routes
- `company/legal/claim_register.md` — F011 entries
- `company/brand/copy.md` — kill-switch UI strings
- `company/ledger/{company_state.json, decisions_log.md}`
