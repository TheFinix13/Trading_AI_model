# F006 — UI mocks (design stage)

- **Feature:** F006 encrypted credential storage + install-scoped auth
- **Author:** UI Designer
- **Date:** 2026-07-21
- **Handoff in:** `company/handoffs/F006-ux_researcher-to-ui_designer.json`

F006 is mostly a backend feature (credentials + auth modules) — but two
UI surfaces still ship in this sprint:

## Surface 1 — Install fingerprint chip

A small pill in the top-right of the nav bar on **every** authenticated
page. Falls back to a neutral "Not configured" when
`/api/auth/status` returns `authenticated: false`.

```
┌────────────────────────────────────────────────────────────────────┐
│ Hub · v1 · v2 · HQ · Perf · Squad · Research    [🔒 a1b2c3d4…9z8y7x] │
└────────────────────────────────────────────────────────────────────┘
```

Design tokens:

- Font: `-apple-system` monospace tail (`font-family: ui-monospace,
  Menlo, monospace`) at 11 px.
- Border: `1px solid var(--border)`, `border-radius: 999px`, padding
  `2px 9px`.
- Colour: `var(--dim)` — quiet, informational, not attention-grabbing.
- Lock glyph: `🔒` (U+1F512). Alt: `[locked]` in a11y label.

Not-configured variant:

```
[⚠ Not configured yet — visit /onboarding]
```

Colour: `var(--amber)`.

## Surface 2 — `/api/auth/status` payload consumer

Any page's JS can read `/api/auth/status` and render the chip. F008's
onboarding page uses this to decide whether to redirect. `/hq` uses it
to render the chip.

No dedicated `/auth` page in F006 — the actual "generate a token" flow
lands in F008's welcome step.

## Mobile (375 px, per F004)

The fingerprint chip drops out of the nav row and lands under the
`<h1>` on `/hq` mobile view, retaining the same visual style. On other
pages it's optional (space-permitting) — falls to the mobile footer.

## Empty / error / loading states

- **Loading:** skeleton `.sk` chip using F005's `withStates()`.
- **Error:** the chip renders "Auth status unavailable" in
  `var(--amber)`. Retry silently in the background.
- **Empty:** "Not configured yet — visit /onboarding" (linked).

## Accessibility

- `aria-label="Install fingerprint. Blue Lock install identifier."`
- `role="status"` so screen-readers announce the change when it goes
  from configured to reset (and vice versa).
- Contrast: dim-on-panel `var(--dim)` at 4.6:1 vs `var(--panel)` — passes
  WCAG AA for non-large text.

## Brand copy sources (all in `company/brand/copy.md` §F006)

- "Install fingerprint" — label.
- "Not configured yet — visit /onboarding" — empty affordance.
- "Auth status unavailable" — error affordance.
- "Your install token is stored securely" — reassurance under the chip
  (only on `/hq`).
