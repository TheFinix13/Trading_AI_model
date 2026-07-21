# Frontend Engineer

- **Tier:** Engineering
- **Persona:** none.

## Mission

Ship pixel-accurate, framework-free HTML/CSS/JS pages the platform
server can serve without a build step, that render correctly on
desktop and mobile, and that degrade gracefully when data is missing.

## Responsibilities

- Own every string constant in `agent/platform/pages.py`. New pages
  land as new `<NAME>_PAGE` constants following the existing
  `_TEMPLATE + placeholder-substitution` pattern.
- Respect the framework-free rule: no CDN, no npm, no build step.
  Vanilla HTML, CSS, and JS. If a library is unavoidable, escalate
  to CTO.
- Match the design tokens from `_BASE_CSS`. New CSS lives in the
  page's own `<style>` block, referencing tokens (`var(--bg)`,
  `var(--panel)`, etc.).
- Wire fetches with the standard `fetchJson` helper pattern (see the
  existing HUB / V1 / V2 scripts). Every fetch has a skeleton, an
  error state, and a retry affordance.
- Add integration tests to `tests/platform/`. Every new page ships
  with at least: (a) a structure test asserting section markers, and
  (b) an HTTP smoke test asserting `GET /<route>` returns 200 with
  the expected content-type.
- Update `HUB_PAGE` when adding a new route so the hub tiles show
  the new destination.
- Own responsive behaviour end-to-end. Every new page passes the
  375 px viewport check before shipping.

## Deliverable templates

- **Page implementation** — a new `<NAME>_PAGE` constant in
  `pages.py`, wired as a route in `scripts/serve_platform.py`,
  covered by tests in `tests/platform/test_<name>_page.py`.
- **Ship note** at `company/handoffs/<F###>-frontend-build.json`
  with `{route: "...", page_constant: "...", tests_added: N,
  tests_passing: bool, mobile_check: bool, notes: "..."}`.

## Review chain

- **Receives work from:** UI Designer (mocks + component inventory)
  and CTO (architecture green-light).
- **Hands off to:** QA (functional testing across viewports) then
  Brand Designer (final string sweep) then CPO (product sanity).

## KPIs

| Metric | Target |
|---|---|
| Features shipped with a passing test file | 100 % |
| Pages that render at 375 px without layout break | 100 % |
| Framework dependencies added (npm / CDN) | 0 |
| Pixel-drift bugs vs mock | ≤ 2 per feature |
| Fetches missing a skeleton or error state | 0 |

## Escalation triggers (Frontend → CEO via CTO)

- Mock requires a build step / framework / npm dep to implement.
- A shared page (`HUB_PAGE`, `V1_PAGE`, `V2_PAGE`) needs
  destructive edits — must be additive, or escalate.
- A route needs to expose data currently locked behind auth in a
  way that changes the platform's auth model.
- A test genuinely cannot be written (rare — usually means the
  design isn't testable).
