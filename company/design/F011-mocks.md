# F011 — /settings/kill-switches mocks

Visual system: `_BASE_CSS` v1.0.0 palette
(`--panel`, `--border`, `--red`, `--dim`, `--fg`). No new tokens; no
`_BASE_CSS_VERSION` bump.

## Desktop (>= 700 px)

```
+------------------------------------------------------------+
| [Hub] [v1] [v2] [HQ] [Perf] [Squad] [Research]             |  <- _NAV
| Kill switches                                              |  <- h1
| Halt live orders globally or per-symbol. ...               |  <- .ks-lead
| +------------------------------------------------------+   |
| | reason textarea (60 px tall, resize vertical)        |   |  <- .ks-reason
| +------------------------------------------------------+   |
|                                                            |
| +------------+ +------------+ +------------+ +------------+|
| | GLOBAL     | | EURUSD     | | GBPUSD     | | USDCAD     ||
| | inert      | | inert      | | inert      | | inert      ||
| | [Activate] | | [Activate] | | [Activate] | | [Activate] ||
| +------------+ +------------+ +------------+ +------------+|
| +------------+ +------------+                              |
| | USDJPY     | | USDCHF     |                              |
| | inert      | | inert      |                              |
| | [Activate] | | [Activate] |                              |
| +------------+ +------------+                              |
|                                                            |
| status: "Activated EURUSD"                                 |  <- .ks-result (aria-live)
|                                                            |
| Recent events                                              |
|   2026-07-22T14:03Z  ACTIVATE  EURUSD -- spread jump ...   |
|   2026-07-22T14:00Z  CLEAR     EURUSD -- (no-op)  by user  |
+------------------------------------------------------------+
```

Active cells shift to a red-tinted background (`rgba(248,81,73,.10)`)
with a red border and the header colour flipped to `var(--red)`. The
action button flips to *Clear* with a neutral background (transparent
+ border) so the destructive-looking red is reserved for *Activate*.

## Mobile (375 px)

```
+------------------------------+
| [Hub] [v1] [v2] [HQ]  ...    |
| Kill switches                |
| Halt live orders...          |
| +--------------------------+ |
| | reason textarea          | |
| +--------------------------+ |
| +--------------------------+ |
| | GLOBAL                   | |
| | inert                    | |
| | [Activate]               | |
| +--------------------------+ |
| +--------------------------+ |
| | EURUSD                   | |
| | ACTIVE -- spread jump    | |
| | [Clear]                  | |
| +--------------------------+ |
| +--------------------------+ |
| | GBPUSD                   | |
| | inert                    | |
| | [Activate]               | |
| +--------------------------+ |
| ...                          |
| Recent events                |
+------------------------------+
```

Media query at `max-width: 700px` collapses `grid-template-columns`
from `repeat(auto-fit,minmax(180px,1fr))` to `1fr`. All other tokens
stay identical; the visual hierarchy scales cleanly.

## Copy strings (loaded via `company/brand/copy.md`)

- Page title: **Kill switches**
- Subtitle: *Halt live orders globally or per-symbol. Activating a
  switch creates a flag file the future live-order pathway will
  honour as the second of the four safety checks (kill → risk →
  approval, all after live-mode is enabled). Sprint 2 ships the
  switch, not the wiring — toggling it here is safe.*
- Activate button: **Activate kill**
- Clear button: **Clear**
- Empty audit hint: *No events yet.*
- Empty-reason rejection: *Reason is required when activating.*

## Interaction contract

- Click *Activate* on an inert cell:
  1. If reason empty → status message + refuse.
  2. Else POST `/api/kill-switches/activate` with `{symbol, reason}`
     (or `{reason}` for GLOBAL).
  3. On 200 + `{ok: true}` → clear textarea, refetch state, re-render.
  4. On 400 / 401 / 500 → surface the error in `.ks-result`.

- Click *Clear* on an active cell:
  1. No reason required.
  2. POST `/api/kill-switches/clear` with `{symbol}` (empty body for GLOBAL).
  3. Same success / error handling.

- Every render calls `withStates()` so a network glitch shows the
  standard skeleton + retry affordance rather than an infinite
  spinner.

## Not shown / out of scope

- No "confirm dialog" -- the click IS the confirm (activate needs a
  typed reason; clear is one-click intentionally so panic-recovery
  stays fast).
- No colour beyond the _BASE_CSS red — the visual weight is enough.
- No animation on state flip (matches the Sprint-0 minimalist
  aesthetic).
