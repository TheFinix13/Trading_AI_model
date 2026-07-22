# F014 — User journey: `/alerts` + Telegram bridge

**Persona:** Rin (away-from-keyboard operator). He's fine with the
platform running unattended for hours but wants a push notification
the moment a stop-loss hits, a kill-switch trips, or a risk-budget
breach is imminent.

**Trigger:** Rin has enabled live-mode (F013). He wants a nightly
view of events on his phone -- the browser tab is closed -- and a
real-time list when he's at the desk.

## 1. Landing on `/alerts`

- Filter chips at the top (six event types).
- A "Send test alert" button.
- Connection indicator: "connected" (green) once EventSource
  attaches.
- Rolling list of events (newest first, up to 100).

Sprint 2 caveat pinned in the intro paragraph: "Sprint 2 does not
publish events from any live pathway; only the test button produces
events." Rin sees the mechanism working before it starts producing
real signals.

## 2. Configuring Telegram

Rin opens `platform.toml`, adds his bot_token + chat_id to
`[telegram]`, and enables `[alerts.telegram] enabled = true`. He
POSTs the new config via `/api/alerts/config` (or edits the file and
restarts). `load_config()` returns:

```json
{
  "enabled": true,
  "bot_token_configured": true,
  "chat_id_configured": true,
  "per_event": {"trade_fill": true, ...}
}
```

The raw token is NEVER in the response.

## 3. Firing a test alert

Rin clicks "Send test alert" on the /alerts page. Immediately:

- The event lands on the browser via SSE (`event: trade_fill` frame).
- The Telegram bridge posts to `https://api.telegram.org/bot<tkn>/sendMessage`
  with `{chat_id, text: "[trade_fill] <ts>\n  test: True\n  note: ..."}`.
- Rin's phone buzzes.

## 4. Filtering

Rin toggles the `stop_hit` chip off. Now stop-hit rows are hidden
from the browser list. The Telegram bridge still routes them per its
own config -- browser filtering is client-side only.

## 5. Reconnect

Rin's laptop sleeps for an hour. On wake, the EventSource
reconnects; the ring buffer of the last 100 events replays as
`initial_history` so Rin catches up without a page reload.

## 6. Handoff into future sprints

Sprint 2 ships the bus + wiring; F011 / F012 / F013 don't publish
events yet. That's D065 SCAFFOLDING invariant: when a future sprint
wires the squad's fill pipeline to the bus, Rin's `/alerts` page and
Telegram bridge start receiving real events without any code change
to F014.
