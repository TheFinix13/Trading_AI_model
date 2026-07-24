# F023 — Legal + Security review (alerts durability JSONL sink + SSE stream cap)

**Verdict:** APPROVED — no new event types, no new secrets, no new
public copy; every F014/D100 rolling constraint verified preserved
below. Claims registered in-commit (register §F023 x2).

## Why this review fired

`security_relevant: true`: F023 touches the alerts bus (`alerts.py`),
the SSE transport (`alerts_sse.py`) and writes a new file to disk
(`<config_dir>/alerts_log.jsonl`). The alerts stack carries the
kill-switch/watchdog safety signal path, and the F014 reviews left
rolling constraints on tape that any change here must re-verify.

## What changed

1. **Opt-in JSONL sink (I010 durability gap).** `[alerts]
   jsonl_sink = true` (literal true only; default OFF) makes every
   `publish()` additionally append the event to
   `<config_dir>/alerts_log.jsonl`. Sink failures never block or fail
   `publish()` — one warning per process, then quiet. With the flag
   off (the default), behaviour is byte-identical to F014.
2. **Concurrent SSE stream cap (I010 resource gap).** `[alerts]
   max_sse_streams` (default 8) bounds concurrent
   `/api/alerts/stream` consumers. At the cap a NEW stream is refused
   with `429` + `Retry-After` BEFORE subscribing to the bus; existing
   streams are never evicted. Slot release is finally-guarded, so
   abrupt disconnects cannot leak capacity. The `/alerts` page now
   reconnects itself with bounded exponential backoff (2s → 60s cap)
   instead of the browser's tight default retry.

## Rolling constraints re-verified (F014 / F017 / D100 tape)

1. **Event-type whitelist (claim register §F014 alerts.py; D100
   extended it to seven with `watchdog_alert`).** PRESERVED — F023
   adds NO event type. `EVENT_TYPES` is untouched; the sink and the
   cap are transport-layer only.
2. **SSE wire format (register §F014 alerts_sse.py).** PRESERVED —
   `format_event` is untouched; frames still emit `id:` / `event:` /
   `data:` delimited by a blank line. The 429 refusal is an HTTP
   response issued INSTEAD of a stream, not a change to the stream
   format, so the "browser-compatible live stream" claim stands.
3. **Auth boundary.** PRESERVED — `alerts_sse` remains
   transport-only; the install-token gate on `/api/alerts/stream` is
   still enforced by the server handler BEFORE
   `sse_stream_response()` runs, so the cap check never becomes an
   unauthenticated probe surface (`_UNAUTHENTICATED_API_PATHS`
   untouched).
4. **Bot-token-never-in-payload (register §F014 alerts_telegram.py,
   ops split 2026-07-24).** PRESERVED — `alerts_telegram.py` is
   untouched. The sink stores only what the ring buffer already holds
   (event id/type/ts/payload); Telegram tokens and chat ids never ride
   bus payloads, so they can never land in the sink file.
5. **D065 SCAFFOLDING invariant.** PRESERVED — no live pathway gains
   a `publish()` call; publishers remain tests + the test-alert API.

## Security posture of the new file

- The sink lives under `<config_dir>` (same directory posture as
  `credentials.enc`), path derived through the existing
  `credentials._config_dir()` seam — no new location, no new
  permission surface, and the file inherits the operator's config-dir
  permissions.
- Content is exactly the bus events (no secrets by constraint 4).
- No retention/rotation policy — the file is operator-managed and the
  example config says so. This is a documented limitation, not a
  claim.

## Honesty rail

The sink is best-effort durability, NOT a guaranteed audit log (a
failed write warns once and delivery proceeds). Any future copy
claiming "every alert is durably recorded" is inaccurate under this
posture and requires a fresh Legal review — pinned as a rolling
constraint in claim register §F023.

## Tests pinning this review

`tests/platform/test_alerts_jsonl_sink.py` (default-off, literal-true
opt-in, restart survival, failure isolation + warn-once, config-dir
seam, config parsing) and `tests/platform/test_alerts_sse_module.py`
§TestStreamCap (429 + Retry-After at the cap, refuse-not-evict,
finally-guarded release incl. BrokenPipe, refusal-never-subscribes),
plus the `/alerts` page backoff pin in
`tests/platform/test_alerts_page.py`.
