# F023 — Alerts durability (JSONL sink) + SSE stream cap

- **Sprint:** sprint-3-stickiness
- **Priority:** P1 (in-sprint) · Size **S**
- **Source:** I010 (audit A010, P2)
- **Consumes:** F014 alerts bus (`alerts.py`, `alerts_sse.py`)
- **Consumed by:** every bus producer/consumer, unchanged; ops
  forensics gains a durable trail
- **Feature flags:** `security_relevant: true` (resource-exhaustion
  surface on the SSE endpoint — Security review fires),
  `legal_relevant: false` (no new public claims; sink is a local
  file), `research_relevant: false`
- **Claims introduced:** NONE

## Problem statement

The F014 bus ring buffer is process-memory-only: a crash immediately
after a safety event (kill-switch trip) loses the bus's copy of the
evidence trail. And each `/api/alerts/stream` consumer holds a server
thread with no cap — a stuck or hostile client farm can exhaust the
server. Both halves are small, bounded fixes.

## Scope (in)

1. **Optional JSONL sink** (`alerts.py`): when `[alerts]
   jsonl_sink = true` (default **false** — behaviour change is
   opt-in), every `publish()` appends the event to
   `<config_dir>/alerts_log.jsonl` using the existing atomic-append
   pattern. Sink failures never block or fail `publish()` (bus
   semantics unchanged); a failed sink write logs a warning once per
   process. Documented durability boundary in the module docstring
   either way.
2. **SSE concurrent-stream cap** (`alerts_sse.py` +
   `serve_platform.py`): `[alerts] max_sse_streams` (default 8). At
   the cap, new stream requests are refused with `429` + `Retry-After`
   (refuse, NOT evict — an existing consumer's stream is never
   dropped to admit a newcomer). Stream teardown reliably decrements
   the counter (finally-guarded).
3. **`/alerts` page**: no UI change beyond the existing reconnect
   handling coping with a 429 (bounded backoff, matching the I010
   "reconnect cap" concern).

## Scope (out)

- No event replay/ack protocol; no external queue/broker.
- No change to event types, payload shapes, or the Telegram bridge
  (F014 Legal rolling constraints untouched).
- No retention/rotation policy for the sink file this sprint
  (documented as operator-managed; watchdog integration is a later
  candidate).

## Acceptance criteria

- With the sink on: publish → restart → the event is on disk; with
  it off (default): behaviour byte-identical to today.
- Sink write failure (read-only dir fixture) leaves `publish()`
  returning normally and consumers receiving the event.
- Stream N+1 past the cap gets 429; closing one stream admits the
  next; counter never leaks on abrupt disconnect.

## Test plan

`tests/platform/test_alerts_jsonl_sink.py` (default-off, opt-in
persistence, failure isolation, append format); extend
`test_alerts_sse*.py` (cap refusal, teardown decrement, abrupt-close
leak check, default cap). Target ≥ 14 tests.

## Files touched (expected)

Edited: `agent/platform/{alerts,alerts_sse,config}.py`,
`scripts/serve_platform.py`, `platform.toml.example`. No new modules.
