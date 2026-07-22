# F009 — User-journey memo (auth hardening)

- **Feature:** F009 — Auth hardening (rate limit + session expiry + token rotation)
- **Author:** UX Researcher
- **Date:** 2026-07-22

## Target segment

The **security-conscious operator**. A user who has installed
Blue Lock, generated their install token, connected their broker, and
now wants confidence that:

- A stolen token cannot be used forever (they can rotate it).
- A stolen token cannot be used at unlimited speed (the platform
  rate-limits them).
- A dormant session eventually goes stale (they will re-authenticate
  before an old session is used against them).

## Jobs-to-be-done

- **When my token might be compromised, I want to rotate it in one
  command so that only I have valid access again.**
- **When I forget my install for weeks, I want the platform to
  auto-invalidate the session so that a stale token cannot be reused
  by whoever finds my laptop.**
- **When I'm scripting the platform, I want rate limits to be sane
  defaults with a clear `Retry-After` header so my client can back off.**

## Content order + affordances

- Sprint 2 delivers the API surface only (`POST /api/auth/rotate`).
  A visual "Regenerate token" button lives in the `/settings/security`
  section slated for Sprint 3.
- Server responses on rate limit include `Retry-After` (integer
  seconds) so `curl` / SDK clients back off cleanly.
- Server responses on session expiry include a hint pointing at the
  rotation endpoint.

## Non-goals for this feature

- Multi-device sessions (single-user install per D052).
- Refresh tokens (single-user install = no OAuth flow).
- Rate-limit UI (Sprint 3 shows the recent-429 count if any).
- Rotation UI beyond a CLI-friendly endpoint (Sprint 3 wires the
  settings section).

## Accessibility

- The rotate response and expiry response follow the JSON pattern
  already established by F006 (`{error, hint, ...}`), so a
  screen-reader-friendly client renders them consistently.

## Adjacent needs NOT solved here

- **Password reset.** Single-user, no accounts. The rotation flow is
  the closest analogue.
- **Audit log of rotation events.** Sprint 4+ observability sprint.
- **Anomaly detection on rate-limit hits.** Sprint 4+.

## Handoff downstream

- Backend implements `rate_limiter.py`, adds session/rotation to
  `auth.py`, wires into `serve_platform.py`.
- Security reviews the composition (rate limit + expiry + rotation)
  as a single threat-model story.
- Legal audits the two new claim entries in `claim_register.md`.
- QA runs the 28+ new tests and confirms no plaintext-token-in-logs
  regression from Sprint 1.
