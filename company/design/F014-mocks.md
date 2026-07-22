# F014 — Design mocks: `/alerts`

## Layout

Single column of rows on desktop and mobile. Six filter chips at the
top; test button + connection badge below.

```
+---------------------------------------+
| Alerts                                |
| Sprint 2 caveat prose...              |
|                                       |
| [ trade_fill ] [ stop_hit ] [ ... ]   |
| chips row (wraps on narrow viewports) |
|                                       |
| [Send test alert]  connected (green)  |
|                                       |
| +---------------------------------+   |
| | TRADE_FILL       2026-07-22...  |   |
| | payload JSON (mono)             |   |
| +---------------------------------+   |
| +---------------------------------+   |
| | KILL_SWITCH_TRIP 2026-07-22...  |   |
| | payload JSON (mono)             |   |
| +---------------------------------+   |
+---------------------------------------+
```

## Colour semantics

- Chips: `dim` when off, `--accent` when on.
- Connection badge: `--dim` when reconnecting, `--accent` when live.
- Event rows: neutral panel; the event TYPE is uppercase + bold.

## Copy strings

- **Intro:** "Live event stream (SSE). Filter by type below. Sprint
  2 caveat: Sprint 2 does not publish events from any live pathway
  -- only the 'Send test alert' button below produces events."
- **Empty state:** "No events yet. Try 'Send test alert'."
- **Reconnecting state:** "reconnecting..."

## Interaction

- Filter chips toggle inclusion in the rendered list (client-side).
- Test button hits `POST /api/alerts/test`; the event lands via SSE
  and populates the list (no page refresh).
- Ring buffer of last 100 events replays as `initial_history` when
  the EventSource reconnects.

## Mobile (700px)

- Filter chips wrap.
- Actions stack column-wise (button above connection badge).
- Event payload wraps with `white-space:pre-wrap; word-break:break-all`.
