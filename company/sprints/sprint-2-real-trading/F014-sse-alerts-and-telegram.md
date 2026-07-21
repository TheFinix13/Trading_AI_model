# F014 — SSE alerts stream + Telegram bridge

- **Sprint:** sprint-2-real-trading
- **Priority:** P0
- **Lane:** Enhances F013.
- **Consumes:** F006 (auth), F007 (`platform.toml` bot_token), F011
  (kill_switches trip event), F012 (risk-budget breach event), F013
  (approval submitted event).
- **Consumed by:** future integrations subscribe to the bus.
- **Feature flags:** `auth: true` on SSE stream + config APIs →
  mandatory `security`.

## Problem statement

F013 gives the user a queue to look at. F014 gives the platform a
way to *poke* the user when something interesting happens (fill,
kill-switch trip, risk breach, approval submitted) without a
constant tab refresh.

Requirements:

- Server-Sent Events for browsers (`text/event-stream` on
  `/api/alerts/stream`).
- Telegram bridge for the away-from-keyboard case, reusing the
  existing `bot_token` in `platform.toml`.
- Event bus in-process (single-user install per D052 — no Redis).

## Scope (in)

### `agent/platform/alerts.py` (new — event bus)

Thread-safe pub/sub. In-process.

Public API:

```python
EVENT_TYPES: tuple[str, ...] = (
    "trade_fill", "stop_hit", "kill_switch_trip",
    "risk_budget_breach", "approval_submitted", "platform_down",
)

def publish(event_type: str, payload: dict,
            ts: float | None = None) -> None
def subscribe(callback) -> str  # returns subscription_id
def unsubscribe(subscription_id: str) -> bool
def recent(limit: int = 100) -> list[dict]
def reset() -> None  # test helper
```

Callbacks are called synchronously with the event dict. Exceptions
in a subscriber are logged and swallowed (never break other
subscribers).

Event shape:

```json
{
  "id": "urn-uuid-...",
  "type": "trade_fill",
  "ts": "2026-07-22T...",
  "payload": {...}
}
```

Ring buffer of the last 100 events in memory.

### `agent/platform/alerts_sse.py` (new — SSE endpoint)

Long-lived HTTP response with `text/event-stream`.

Public API:

```python
def sse_stream_response(handler) -> None
def format_event(event: dict) -> bytes  # SSE frame
```

Each subscriber gets a queue; the bus pushes events into the queue
and the SSE handler drains them. Client reconnect: last-event-id
header uses the ring buffer to catch up.

Auth-gated: `?token=` query param since browsers cannot add headers
to `EventSource`. Constant-time compared.

### `agent/platform/alerts_telegram.py` (new — Telegram bridge)

Subscribes to the bus on module import (opt-in via config).

Public API:

```python
def configure(bot_token: str, chat_id: str,
              per_event: dict[str, bool]) -> None
def load_config() -> dict  # from platform.toml [alerts.telegram]
def is_enabled() -> bool
def send(event: dict, client=None) -> bool
def start() -> str | None  # returns subscription_id; None if disabled
def stop() -> None
```

Sends via `httpx.post(TELEGRAM_API + "/sendMessage",
json={chat_id, text, parse_mode})` on each event whose type has
`per_event[type] == True`.

Config in `platform.toml`:

```toml
[alerts.telegram]
enabled = false
per_event = { trade_fill = true, stop_hit = true, kill_switch_trip = true,
              risk_budget_breach = true, approval_submitted = false,
              platform_down = true }
```

`bot_token` and `chat_id` are read from the existing `[telegram]`
table in `platform.toml` (F014 does not add a new secret).

### `ALERTS_PAGE` in `agent/platform/pages.py` (new)

Route: `/alerts`.

Layout:

- Client-side `EventSource("/api/alerts/stream?token=...")` — the
  page bootstraps the connection on load.
- Rolling list of recent events (last 100), most recent first.
- Filter chips per event type at the top.
- **Test-alert button** — fires `POST /api/alerts/test` which
  publishes a synthetic event.
- Consumes withStates() for the initial load.

Mobile: single column at 700 px.

### HTTP APIs

- `GET /api/alerts/stream` — SSE endpoint. Auth via `?token=` or
  session cookie (same as `/api/*` install gate). Long-lived.
- `GET /api/alerts/config` — returns Telegram routing config.
- `POST /api/alerts/config` — updates config. Auth-gated.
- `POST /api/alerts/test` — publishes a synthetic event
  (`{type: "trade_fill", payload: {test: True}}`). Auth-gated.

### Tests (20)

- `tests/platform/test_alerts_module.py` (7) — publish/subscribe,
  callback exception isolation, ring buffer bounds, event type
  validation, reset clears, `recent()` chronological.
- `tests/platform/test_alerts_sse_module.py` (5) — format_event
  produces a valid SSE frame with `id: ` + `event: ` + `data: `,
  handler drains the queue, disconnect cleans up, event serialisation
  survives dict payload, integration test connects EventSource-style
  and receives a published event.
- `tests/platform/test_alerts_telegram_module.py` (5) — httpx.post
  mocked, correct payload posted per event type, disabled config
  → no post, missing bot_token → no post, per-event filter
  respected.
- `tests/platform/test_alerts_page.py` (2) — page emits, has
  filter chips + test-alert button, consumes withStates().
- `tests/platform/test_alerts_api.py` (1) — config + test endpoint
  round-trip (auth-gated).

## Scope (out)

- Real Telegram bot calls in tests (all mocked).
- SMS / email channels (Telegram is enough; Sprint 3+ if needed).
- Multi-chat routing (single-user install; reuse F007's chat_id).
- WebSocket upgrade (SSE is sufficient — browsers all support it).

## Legal

Adds a claim entry:

- `alerts_telegram.load_config` — public "Telegram routing config"
  claim (which event types fan out to Telegram).

No user-facing legal warning (Telegram is opt-in in config).

## UX

- `company/research/F014-user-journey.md` — the "I want to know
  when a stop hits" journey.
- `company/design/F014-mocks.md` — /alerts page desktop + mobile.

## Acceptance

- 20 new tests pass, including SSE integration test.
- Full suite green.
- Telegram bridge test mocks `httpx.post` and asserts the correct
  payload shape.
- `/alerts` renders at 375 px.
- No real Telegram call executed by tests.
- No real SSE relay purchased (self-hosted stdlib SSE).

## Files touched

New:
- `agent/platform/alerts.py`
- `agent/platform/alerts_sse.py`
- `agent/platform/alerts_telegram.py`
- `tests/platform/test_alerts_module.py`
- `tests/platform/test_alerts_sse_module.py`
- `tests/platform/test_alerts_telegram_module.py`
- `tests/platform/test_alerts_page.py`
- `tests/platform/test_alerts_api.py`
- `company/research/F014-user-journey.md`
- `company/design/F014-mocks.md`
- `company/qa/F014-verdict.md`
- Handoffs.

Edited:
- `agent/platform/pages.py` — `ALERTS_PAGE`
- `agent/platform/config.py` — `[alerts.telegram]` block
- `scripts/serve_platform.py` — 4 routes
- `company/legal/claim_register.md` — F014 entries
- `company/brand/copy.md` — alerts UI strings
- `company/ledger/{company_state.json, decisions_log.md}`
