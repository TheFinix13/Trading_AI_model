# F005 — Loading skeletons + friendly error-state recovery

- **Priority:** P0
- **Sprint:** Sprint 0 · Trust Foundation
- **Owner (build):** Frontend
- **Reviewers:** UI Designer, Brand Designer, QA, CPO, CEO
- **Current stage:** `spec`
- **Written by:** CPO

## User story

> As a **first-time visitor to the platform**, I want the page to
> feel *alive* while it loads, and if something goes wrong I want
> a friendly message with a retry button — not a blank div or a
> mysterious `undefined`, so I don't bounce.

Research consistently shows skeleton screens are perceived ~30 %
faster than spinners. This is a **perceived-quality** feature.

## Acceptance criteria

The feature is done when EVERY `fetch()` call across the platform
has:

1. A **loading state** — either a shimmering skeleton placeholder
   (preferred for content areas: KPI tiles, cards, tables) or an
   inline three-dot pulser (for footer / secondary elements).
2. An **error state** — a human-readable message ("Couldn't load
   the squad's last events — the platform server might be
   restarting") with a **retry button** that re-triggers the same
   fetch.
3. An **empty state** — distinct from the error state, used when
   the fetch succeeded but returned zero relevant rows
   ("No trades yet — the squad is watching the market"). Empty
   states have their own copy, not "no data".

Concrete surfaces to cover in Sprint 0:

| Page | Fetches covered |
|---|---|
| `/` (hub) | `/api/v1/status`, `/api/v2/live/status`, `/api/v2/live/events`, `/healthz` |
| `/v1` | `/api/v1/status` |
| `/v2` (sim) | `/api/v2/matches`, `/api/v2/match/:id/*` |
| `/v2` (LIVE) | `/api/v2/live/*` |
| `/hq` | `/api/hq/state` |
| `/performance` (F001) | `/api/performance` |
| `/players/:id` (F002) | `/api/players/:id` |
| `/research` (F003) | `/api/research` |

## Non-goals

- **No** full retry-with-exponential-backoff logic. One retry
  button click = one retry attempt. Multi-retry is a Sprint 3+
  polish concern.
- **No** offline-first / service-worker caching.
- **No** optimistic UI (rendering assumed data while waiting).
- **No** toast / snackbar library. Errors show in-place next to
  the section that failed.
- **No** animated shimmer via SVG or canvas. CSS `@keyframes` on
  a subtle background gradient is enough.

## Dependencies

- **UI Designer:** produces skeleton mocks for the reusable
  components (KPI tile, card, table row, chart, ticker item).
  Skeleton uses only `--panel` + a slightly-lighter shade —
  no new colours.
- **Brand Designer:** authors the friendly-error copy library at
  `company/brand/error_copy.md`. Standard phrasings for common
  failures: "server restarting", "no data yet", "temporary
  glitch". Never "Error 500" or "undefined" or a stack trace.
- **Frontend Engineer:** implements the skeleton + error patterns
  as reusable helpers in the shared JS (in `pages.py`'s script
  blocks). Every existing `fetchJson()` call is upgraded.
- **QA:** the error-state check becomes part of every feature's
  QA plan from Sprint 0 onwards — disconnect the data source and
  verify the error state fires with a retry.

## Review checklist

| Reviewer | Check |
|---|---|
| UI Designer | Skeleton mocks exist for each reusable component; skeleton dimensions match final content dimensions (no layout shift when data lands). |
| Brand Designer | Every error-state string is stranger-friendly; the retry button is labelled clearly ("Try again" not "Retry"); empty-state copy is distinct from error-state copy. |
| Frontend Engineer | No `fetch()` remains in the codebase without loading + error + empty state; a helper (`withStates()` or similar) is introduced to make the pattern hard to forget. |
| QA | Every P0 feature's QA plan includes: (a) skeleton visible during network throttling, (b) error state visible when backend stopped, (c) retry button re-fires the fetch, (d) empty state visible when data source returns empty. |

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| F005 is retrofit-heavy — touching every fetch across every page invites conflicts with F001/F002/F003 as they're being built. | F005 is treated as horizontal: F001/F002/F003 ship WITH their skeleton + error state, using F005's helper; F005 doesn't retrofit after the fact. Order: F005 helper drops first (day 3), other features consume it. |
| Skeleton dimensions drift from final content → layout shift when data lands. | UI Designer's mocks pin exact skeleton sizes to the KPI tile / card / row containers, not to the content inside them. |
| Different fetches need subtly different error copy → inconsistency. | Brand's `error_copy.md` provides 5–7 canonical phrasings; every fetch picks the closest match. New copy needs Brand review. |

## Definition of shipped

`company/brand/error_copy.md` published; a shared `withStates()`
helper exists in `pages.py` and is used by every fetch; QA
regression run demonstrates skeleton + error + empty state on every
route; no `fetch()` in the codebase without these states.
