# Brand error-copy library

Canonical friendly-error phrasings for every user-facing fetch on the
platform. Referenced by F005's shared `withStates()` helper in
`agent/platform/pages.py` and by every page that renders errors
inline.

Rule of thumb: an error state must (a) tell the user what happened in
one sentence, (b) tell them it isn't their fault, (c) offer a next
action ("Try again"). Never show a stack trace, a status code, or the
word "undefined".

## Canonical phrasings

Every phrasing has a **key** (used by the JS helper), a **user-facing
message**, and an **example situation** so future contributors know
when to pick which.

### `server_restarting`

**Message:** "Couldn't reach the platform server — it might be
restarting. Try again in a moment."

**Situation:** Fetch threw a network error (server not running,
connection reset), or HTTP 502 / 503.

### `temporary_glitch`

**Message:** "Something didn't come through this time. That's usually
a hiccup — one more try often works."

**Situation:** HTTP 5xx that isn't a restart signal (500, 504), or a
JSON parse error on the response body.

### `unauthorized`

**Message:** "This view is protected — add a token to the URL
(`?token=…`) or ask the operator for one."

**Situation:** HTTP 401. Never expose the auth-token itself; the
"add a token" phrasing tells the operator what to do without leaking
the current one.

### `not_configured`

**Message:** "Not set up on this server yet. The operator can point
this page at the data by reading the runbook."

**Situation:** Backend returned 200 but with `unconfigured=True` in
the payload (matches the /hq degradation path).

### `no_data_yet`

**Message (default):** "No data yet — the squad is watching the
market. Come back after the next H4 bar close."

**Message (with context):** Passed through by the caller when the
empty state needs to reference a specific surface — see
`empty_state_variants` below.

**Situation:** Fetch succeeded, response was well-shaped, but the
relevant array was empty (no trades, no proposals, no verdicts).

### `unknown_route`

**Message:** "That page doesn't exist. Check the URL, or head back
to the hub."

**Situation:** HTTP 404 on a page route (not an API — see
`api_not_found` below).

### `api_not_found`

**Message:** "The data we need isn't available on this server. The
page will keep what it has and try again."

**Situation:** HTTP 404 on an API endpoint (e.g. live dir not
created yet, replay cache missing).

### `stale_data`

**Message:** "The numbers you're seeing haven't updated in a while —
the backing data source may be paused. The page will keep trying."

**Situation:** Fetch succeeded but the payload's `generated_at` is
much older than expected (e.g. > 60 minutes for live data).

## Empty-state variants (distinct from errors)

Empty states are NOT errors. They fire when the fetch succeeded and
the data is legitimately empty. Copy is context-specific:

### F001 — /performance

**No trades yet:** "No shadow-paper data yet — the squad is still
warming up. Come back after the first H4 bar close."

**Not enough for Sharpe:** "Sharpe: n/a — need N more daily returns."
(N calculated at render-time by the frontend.)

### F002 — /players/:id

**Retired player, no activity:** "This striker has retired. The
'Evolution history' below records their run."

**Standby player, no activity:** "This striker is on standby — off
by default, kept in the roster for record-keeping."

**Active player, no recent trades:** "No trades on the tape for
this striker yet — see 'Playstyle' for how they read a market."

### F003 — /research

**No verdicts published:** "No research verdicts published yet.
This page updates when the CPO promotes a completed campaign from
the research repo."

**Research repo missing:** "Research repo not configured on this
server. See `docs/RUNBOOK_demo_launch.md` §7b for setup."

### /hq (existing)

**No blockers:** "No blockers. Company is executing."

**No decisions logged yet:** "No decisions yet. This is a very new
company."

## Button labels (retry actions)

Consistent across every error state:

- Primary action: **"Try again"**
- Secondary action (rare): **"Go to hub"** (only when the current
  page is broken beyond retrying, e.g. 404 on a page route)

## What NOT to say

Banned phrases in error states (regressions caught in QA):

- "Error 500" (or any raw HTTP code — friendly phrasing wraps it)
- "undefined", "null", "NaN" (raw JS values)
- "Failed to fetch" (raw browser error text)
- "Something went wrong" (too vague — pick one of the canonical
  phrasings above)
- "Please contact support" (no support channel exists in Sprint 0)
- "Refresh the page" (retry button re-runs the same fetch; a full
  page refresh should never be the required action)
- Any stack trace, file path, or line number

## For engineers: how `withStates()` picks a phrasing

The shared helper in `pages.py` takes an optional `errorMap` object
that lets callers override the default keys. The default mapping is:

```js
{
  "network": "server_restarting",
  "http_5xx": "temporary_glitch",
  "http_401": "unauthorized",
  "http_404": "api_not_found",
  "json_parse": "temporary_glitch",
  "unconfigured": "not_configured"
}
```

Pages that want a page-specific override pass a partial map:

```js
withStates(box, () => fetchJson("/api/players/isagi"), renderPlayer, {
  errorCopy: {"http_404": "unknown_route"}
});
```

Copy text is looked up from this file's `CANONICAL` object embedded
in the JS at page-render time (see `_ERROR_COPY_JS` in `pages.py`).
