# F004 — Mobile-responsive pass at 375 px viewport

- **Priority:** P0
- **Sprint:** Sprint 0 · Trust Foundation
- **Owner (build):** Frontend
- **Reviewers:** UI Designer, QA, CPO, CEO
- **Current stage:** `spec`
- **Written by:** CPO

## User story

> As a **trader who lives on their phone**, I want the platform to
> look and work correctly on my phone (375 px viewport — iPhone
> 12/13/14/15 mini / Pixel base width), so I can check on the
> squad between meetings without a laptop.

## Acceptance criteria

The feature is done when every route below renders correctly at
375 × 667 px (Chrome DevTools "iPhone SE" or real device):

| Route | Renders? | No horizontal scroll on landscape? | Interactive elements tap-friendly (≥ 44 × 44 px)? |
|---|---|---|---|
| `/` (hub) | ✅ required | ✅ required | ✅ required |
| `/v1` | ✅ required | ✅ required | ✅ required |
| `/v2` (both sim + LIVE modes) | ✅ required | ✅ required | ✅ required |
| `/hq` | ✅ required | ✅ required | ✅ required |
| `/performance` (F001) | ✅ required | ✅ required | ✅ required |
| `/players` + `/players/:id` (F002) | ✅ required | ✅ required | ✅ required |
| `/research` (F003) | ✅ required | ✅ required | ✅ required |

For each route, "renders correctly" means:

1. No horizontal scrollbar at 375 px.
2. All KPI tiles / cards stack to single-column below 700 px
   (breakpoint used consistently across the platform).
3. Text stays legible (font-size ≥ 12 px effective; no truncation
   that hides critical numbers).
4. Buttons and tap targets are ≥ 44 × 44 px.
5. Charts / SVGs reflow to full container width and don't overflow.
6. Tables become horizontally scrollable inside a
   `overflow-x: auto` container OR reflow to a card-per-row
   pattern (UI Designer picks per page).
7. Fixed-position elements (e.g. `#updated`) don't obscure
   content — either stick to a safe corner or become inline.
8. Nav (`_NAV`) becomes a wrap-friendly flex layout that doesn't
   force horizontal scroll.

## Non-goals

- **No** native mobile app.
- **No** touch-specific gestures (swipe cards, pull-to-refresh).
- **No** performance optimisation targeting cellular networks —
  the platform is already stdlib-only, so payload size is bounded.
- **No** tablet-specific breakpoint (768 px). Desktop and mobile
  breakpoints only for Sprint 0.
- **No** dark/light toggle — this sprint stays dark-only. That's a
  Sprint 4 polish concern.

## Dependencies

- **UI Designer:** provides responsive mocks for the 7 routes at
  375 px. Each mock names the specific CSS grid / flex adjustments
  needed.
- **Frontend Engineer:** applies the media-query changes. The
  canonical breakpoint is `@media (max-width: 700px)` per the
  existing HUB pattern; F004 formalises this as the platform-wide
  breakpoint.
- **QA:** the manual mobile check becomes part of every feature's
  DoD from Sprint 0 onwards.
- **F001, F002, F003, /hq:** all incoming P0 routes MUST land with
  their mobile mock included — F004 is not a retrofit sprint; it's
  a horizontal concern that gates every other feature. F004 spec
  exists to enforce this.

## Review checklist

| Reviewer | Check |
|---|---|
| UI Designer | Every route has a 375 px mock in `company/design/`; each mock lists the specific media-query adjustments. |
| Frontend Engineer | Every media query uses tokens (not hardcoded pixels beyond breakpoint literals); every new page ships with its mobile styling baked in, not deferred. |
| QA | Manual mobile check on 7 routes; results in `company/qa/F004-plan.md`; any horizontal-scroll bug at 375 px is a P0 defect. |
| CPO | F001/F002/F003 don't ship without their F004 requirements met — CPO enforces this as sprint owner. |

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| /v2 pitch page (SVG football field) is hard to make legible at 375 px. | UI Designer proposes: keep the pitch aspect ratio but let it become full-viewport-width; ticker becomes a bottom-drawer; player-cards stack below the pitch on mobile. Frontend explores; escalate to CTO if pitch SVG needs major restructure. |
| Existing pages have hardcoded desktop-specific widths that regress under a media-query pass. | QA runs regression on desktop (1440 × 900) after every mobile-focused change to catch drift. |
| Retrofit temptation — Frontend defers F004 to end of sprint and blows day 13. | CPO tracks day-by-day and refuses F001 signoff without its F004 check green. |

## Definition of shipped

Seven routes pass the 375 px manual check on a real phone (CEO's
personal device — friend-test compatible). QA plan closed with
"pass" verdict. No P0 mobile-layout bugs in the ledger.
