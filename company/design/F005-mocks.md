# F005 — UI mocks (loading skeletons + friendly error states)

- **Feature:** F005 — Loading skeletons + friendly error-state recovery
- **Owner:** UI Designer (with Brand Designer on copy)
- **Related spec:** `../sprints/sprint-0-trust-foundation/F005-loading-skeletons-error-states.md`

## Component inventory

Three reusable states, one CSS class family (`.sk*`), one JS helper
(`withStates`). Composition happens at the caller site.

### 1. Loading skeleton

ASCII wireframe (KPI-tile + chart layout — the F001 baseline):

```
+-------------------------------------------------+
|  [====]                                          |  <- .sk .sk-line .short
+-------------------------------------------------+
|                                                 |
|  +------+  +------+  +------+                   |
|  | [==] |  | [==] |  | [==] |                   |  <- .sk-tile x 3
|  | [==] |  | [==] |  | [==] |                   |     with two .sk-line
|  +------+  +------+  +------+                   |
|                                                 |
|  +---------------------------------------+      |
|  |                                       |      |
|  |             .sk-chart                 |      |  <- 220px tall chart placeholder
|  |     (subtle .accent shimmer pass)     |      |     with linear-gradient shimmer
|  |                                       |      |
|  +---------------------------------------+      |
+-------------------------------------------------+
```

Dimensions match the final content exactly — no layout shift when
data lands:

| Element | Skeleton size | Final content |
|---|---|---|
| Section header line | 40 % width × 12 px | h3 line |
| KPI tile | 180+ min-width, 72 px min-height | KPI tile |
| Chart placeholder | 220 px tall, 100 % width | Equity SVG |
| Row line | 100 % × 12 px | Table row |

Animation: `@keyframes shimmer` sweeps a 200 px gradient from left to
right every 1.4 s. Reduced-motion users (via `prefers-reduced-motion`
in a future pass) can opt out; Sprint 0 ships without the
media-query for scope reasons — logged as `[SPEC-EXTENSION]` if
adopted mid-build.

### 2. Error state

```
+-------------------------------------------------+
| Server-restart amber left border                |
|                                                 |
|  Couldn't reach the platform server — it might  |  <- .sk-error .msg
|  be restarting. Try again in a moment.          |
|                                                 |
|  [ Try again ]                                  |  <- .sk-error .retry
|                                                 |
+-------------------------------------------------+
```

Copy source: `company/brand/error_copy.md` `server_restarting` key.
Retry button reruns the same fetch (single-attempt, per F005 non-goal
of exponential-backoff).

### 3. Empty state

```
+-------------------------------------------------+
| Dim (grey) left border — NOT an error           |
|                                                 |
|  No shadow-paper data yet — the squad is still  |  <- context-specific empty copy
|  warming up. Come back after the first H4       |     from F001 / F002 / F003
|  bar close.                                     |
|                                                 |
|  [ Try again ]  (optional, only when data may   |
|                  appear later)                  |
+-------------------------------------------------+
```

Empty is NOT an error. Distinct left-border colour so a user glances
and knows the fetch succeeded but the data is legitimately absent.

## Mobile (375 px) variants

At 375 px:

- KPI tile grid collapses to a single-column stack; each tile is
  full-width.
- Chart placeholder keeps 220 px height, 100 % width — no horizontal
  scroll.
- Error / empty states retain the left-border style (still 3 px);
  the retry button becomes full-width via `.sk-error .retry { width:
  100% }` in the per-page CSS override. Sprint 0 leaves this to the
  consuming page rather than baking into `_SKELETON_CSS` (avoids
  forcing a full-width button on desktop).

## Component library implementation

Shipped in `agent/platform/pages.py` as three constants:

- `_SKELETON_CSS` — the animation + `.sk*` class family. Injected
  into every page's `<style>` block that consumes `withStates()`.
- `_ERROR_COPY_JS` — the `CANONICAL_ERROR_COPY` and
  `DEFAULT_ERROR_MAP` objects. Mirror of
  `company/brand/error_copy.md`.
- `_WITH_STATES_JS` — the `withStates(box, fetcher, renderer, opts)`
  helper plus `classifyFetchOutcome`, `renderErrorState`,
  `renderEmptyState`.

Consumers stitch them together at page-template time:

```python
_MY_PAGE = f"""...
<style>{_BASE_CSS}
{_SKELETON_CSS}
...my page-specific CSS...
</style>
...
<script>
{_ERROR_COPY_JS}
{_WITH_STATES_JS}
async function refresh() {{
  withStates(document.getElementById("box"),
             () => fetchJson("/api/thing"),
             (data, box) => box.innerHTML = ...);
}}
</script>
...
"""
```

## Accessibility notes

- Skeleton chart carries `role="progressbar"` and
  `aria-label="Loading"` so screen readers announce "loading" during
  the wait.
- Skeleton lines have `aria-hidden="true"` — they're decorative.
- Retry button is a native `<button type="button">` — full keyboard
  and screen-reader support with zero extra JS.
- Error / empty copy uses full sentences, not shorthand — screen
  readers pronounce them cleanly.

## What we deliberately did NOT do

- No animated SVG shimmers (CSS `@keyframes` only, per F005 non-goal).
- No third-party skeleton library. Zero dependencies.
- No exponential-backoff retry logic (out of Sprint 0 scope).
- No toast / snackbar. Errors show in-place.
- No dark/light mode switch (dark-only for Sprint 0).
