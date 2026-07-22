# F014 — QA verdict

**Verdict:** GREEN — ready for merge.

## Coverage

| Layer                  | Tests | File |
|------------------------|------:|------|
| Module (alerts bus)    | 10 | `tests/platform/test_alerts_module.py` |
| Module (alerts_sse)    |  5 | `tests/platform/test_alerts_sse_module.py` |
| Module (alerts_telegram) |  8 | `tests/platform/test_alerts_telegram_module.py` |
| Page (/alerts)         |  7 | `tests/platform/test_alerts_page.py` |
| API                    |  5 | `tests/platform/test_alerts_api.py` |
| **Total**              | **35** | — |

Spec asked for 20; shipped 35.

## What was verified

- **Publish/subscribe:** every subscriber receives every event;
  exceptions in one subscriber DO NOT break the others (test-pinned).
- **Ring buffer bounded:** capacity 100; oldest events fall off
  silently.
- **Newest-first ordering** in `recent()`.
- **Thread-safety:** 4 concurrent publishers land 200 events; buffer
  caps at 100.
- **Event-type validation:** unknown types raise ValueError.
- **Payload validation:** non-dict payloads raise ValueError.
- **SSE frame shape:** `id:` + `event:` + `data:` + blank line
  (WHATWG spec).
- **SSE data line is JSON** — carries id, type, ts, payload.
- **SSE live delivery:** stream response opens, receives events
  published mid-flight, drains cleanly on disconnect.
- **SSE cleanup:** on connection close, subscription is unregistered
  (test proves no ghost subscriber remains).
- **Telegram bridge (mocked httpx):** correct payload posted; per-event
  filter respected; disabled config -> no post; missing bot_token
  -> no post; missing chat_id -> no post.
- **`load_config()` never echoes raw bot_token / chat_id** -- only
  `bot_token_configured: bool` and `chat_id_configured: bool` flags.
- **Bridge fail-closed:** `is_enabled()` returns True only when ALL
  of enabled/token/chat_id are populated.
- **API endpoints:** GET `/api/alerts/config`, POST `/api/alerts/config`,
  POST `/api/alerts/test`, GET `/api/alerts/recent`, SSE
  `/api/alerts/stream`.
- **Auth gate on writes:** POST `/api/alerts/config` returns 401 when
  install-token enforcement is on.
- **`/alerts` page renders:** filter chips for all six event types +
  test button + EventSource wiring + mobile 700px collapse.
- **Restricted-directory quarantine:** none of alerts.py,
  alerts_sse.py, alerts_telegram.py imports from `agent/live`,
  `agent/risk`, or `agent/squad`. Grep-verified.
- **NO real Telegram call:** every `send()` test uses the fake client
  fixture (`_FakeClient`).

## Sprint 2 caveat check

- No live pathway in Sprint 2 publishes events. The only publishers
  in the shipped code are the test-alert API endpoint and the tests
  themselves. Grep-verified.

## Sprint suite delta

Full suite pre-F014: 1447 passed.
Full suite post-F014: **1482 passed** (+35).

## Deferred / not in scope

- Real Telegram routing testing (needs a real bot; deferred).
- SMS / email channels.
- WebSocket upgrade (SSE is sufficient).

## Sign-off

QA → CPO: **APPROVED**.
