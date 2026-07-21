# F012 — Risk budget hard-cap + broker connection health + `/risk` dashboard

- **Sprint:** sprint-2-real-trading
- **Priority:** P0
- **Lane:** Safety primitive. Third of the four live-mode-off checks.
- **Consumes:** F007 (`broker_connection.test_connection`,
  `broker_connection.list_aliases`).
- **Consumed by:** F013 — `risk_budget.can_send_order()` is the THIRD
  check in the 4-gate live-order pathway.
- **Feature flags:** `auth: true` on write routes → `security` fires.

## Problem statement

Sprint 1's retro suggested pre-trade risk parity with `/performance`:
"before you press ENABLE LIVE, show me my current exposure and my
budget headroom". F012 ships the primitive — a max-loss cap at three
scopes (per-day / per-symbol / per-strategy), plus a broker-connection
health probe, plus the `/risk` dashboard that displays both.

Requirements:

- Hard-cap logic in a new module (`risk_budget.py`), no dependency
  on `agent/risk/*` (D065 invariant — mimic the shape but don't
  import).
- 30-second cache on the broker health probe (`test_connection` is
  rate-limited to 5/min/process, so we cannot poll it every second).
- `/risk` dashboard uses `withStates()` from F005 for the load
  lifecycle.

## Scope (in)

### `agent/platform/risk_budget.py` (new)

Three cap scopes:

1. **Per-day** — total realised loss across every live order today.
2. **Per-symbol** — per-symbol daily cap (independent per pair).
3. **Per-strategy** — per source-agent daily cap (`A1_baseline`,
   `A2_widened`, etc.).

Public API:

```python
DEFAULT_PER_DAY_MAX_LOSS: float = 100.0     # in $
DEFAULT_PER_SYMBOL_MAX_LOSS: float = 50.0
DEFAULT_PER_STRATEGY_MAX_LOSS: float = 50.0

def load_config() -> dict            # reads risk_budget.toml
def save_config(payload: dict) -> bool
def record_fill(symbol: str, strategy: str, pnl: float,
                ts: float | None = None) -> bool
def remaining_budget(scope: str) -> dict   # {overall, per_symbol, per_strategy}
def can_send_order(symbol: str, strategy: str,
                   worst_case_loss: float) -> tuple[bool, str]
def reset_state() -> None            # test helper — clears risk_state.jsonl
```

State lives in `<config_dir>/risk_state.jsonl`, one JSON line per
fill: `{"ts": iso8601, "symbol": "EURUSD", "strategy": "A1_baseline",
"pnl": -12.3}`. `remaining_budget()` reads today's UTC-day slice.

Config in `<config_dir>/risk_budget.toml`:

```toml
[per_day]
max_loss = 100.0

[per_symbol]
EURUSD = 50.0
GBPUSD = 50.0
default = 50.0

[per_strategy]
default = 50.0
A1_baseline = 60.0
```

Missing / malformed → defaults. `can_send_order(symbol, strategy,
worst_case_loss)` returns `(True, "ok")` iff every scope has enough
headroom. Otherwise returns `(False, reason)`.

### `agent/platform/broker_health.py` (new)

Live probe on a saved broker alias.

Public API:

```python
CACHE_TTL_SECONDS: float = 30.0

def check_broker_health(user_alias: str,
                        cache_ttl: float | None = None) -> dict
def is_broker_alive(user_alias: str) -> bool
def clear_cache() -> None
def list_health_states() -> list[dict]  # all aliases from F007
```

`check_broker_health(alias)`:

1. Read cache. If fresh, return.
2. Else, `broker_connection.load_credentials(alias)` → if None,
   return `{"alive": False, "reason": "no credentials"}`.
3. Call `broker_connection.test_connection(login, password, server)`.
   Never surface `password` in the return — only `alive` + `reason` +
   `account_type` + `server` + `checked_at`.
4. Store in the cache.

Cache is in-memory per-process.

### `RISK_PAGE` in `agent/platform/pages.py` (new)

Route: `/risk`.

Sections:

1. **Live exposure** — for each broker alias: open positions × lot ×
   current price (Sprint 2 renders zeros — no live positions yet by
   D065 invariant; the section is a placeholder wired for future).
2. **Budget headroom** — per-day / per-symbol / per-strategy bars
   showing `<remaining> / <max>`.
3. **Broker health** — per alias, "alive / stale / down" badge.
4. **Refresh** every 30 s via `withStates()`.

Mobile: single column at 700 px.

### HTTP APIs

- `GET /api/risk/state` — one payload with exposure + budgets +
  broker-health. Read-only. Install-token-gated on non-localhost.
- `GET /api/risk/budgets` — returns the current config.
- `POST /api/risk/budgets` — updates the config. Auth-gated on both
  localhost and non-localhost (write path).

### Tests (25)

- `tests/platform/test_risk_budget_module.py` (10) — record_fill /
  remaining_budget honest, day-slice UTC boundary, can_send_order
  logic for each scope, config load + save round-trip, missing
  config → defaults, reset_state, malformed jsonl skipped.
- `tests/platform/test_broker_health_module.py` (5) — 30-s cache,
  no-credentials returns friendly payload, password never in
  return, list_health_states matches list_aliases, clear_cache
  invalidates.
- `tests/platform/test_risk_page.py` (5) — page emits, has three
  sections, mobile media query, consumes withStates(), disclaimer.
- `tests/platform/test_risk_api.py` (5) — GET state / GET budgets /
  POST budgets, auth gate on non-localhost, scenario test (two
  orders drain daily budget → third blocked → clear-and-reset works).

## Scope (out)

- Reading `agent/risk/*` (D065 invariant).
- Real-time broker feed / positions API (paper stays flat by
  D065 invariant).
- Notifications on budget breach (F014 delivers the event; F012
  emits it into the bus).

## Legal

Adds claim entries:

- `risk_budget.can_send_order` — "3-tier max-loss cap enforced on
  every proposed live order".
- `risk_budget.remaining_budget` — "live headroom read from
  `risk_state.jsonl` (fill audit trail)".
- `broker_health.check_broker_health` — "broker connection probe
  with 30-second cache".

## UX

- `company/research/F012-user-journey.md` — the pre-trade check:
  "am I about to blow my budget? is my broker up?"
- `company/design/F012-mocks.md` — three-section dashboard, desktop
  + 375 px.

## Acceptance

- 25 new tests pass.
- Full suite green.
- Scenario test proves budget drain → next order blocked → clear +
  reset works.
- Broker-health probe respects 30 s cache (verified by test).
- `/risk` renders at 375 px.
- No import from `agent/live/*` or `agent/risk/*` (grep-verified).

## Files touched

New:
- `agent/platform/risk_budget.py`
- `agent/platform/broker_health.py`
- `tests/platform/test_risk_budget_module.py`
- `tests/platform/test_broker_health_module.py`
- `tests/platform/test_risk_page.py`
- `tests/platform/test_risk_api.py`
- `company/research/F012-user-journey.md`
- `company/design/F012-mocks.md`
- `company/qa/F012-verdict.md`
- Handoffs.

Edited:
- `agent/platform/pages.py` — `RISK_PAGE`
- `scripts/serve_platform.py` — 3 routes
- `company/legal/claim_register.md` — F012 entries
- `company/brand/copy.md` — risk UI strings
- `company/ledger/{company_state.json, decisions_log.md}`
