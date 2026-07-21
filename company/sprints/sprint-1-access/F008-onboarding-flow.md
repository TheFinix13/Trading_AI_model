# F008 — First-time setup / onboarding flow

- **Sprint:** sprint-1-access
- **Priority:** P0
- **Lane:** Onboarding UX (per D050)
- **Consumes:** F006 (auth check, install-token generation, passphrase
  fallback), F007 (broker step jumps into F007's `/api/broker/test-
  connection`).
- **Consumed by:** none this sprint — F008 is the sprint's
  user-facing culmination.
- **Feature flags:** `auth: true` (guarded by F006), `credentials: true`
  (passphrase step), `first_visit_redirect: true` → mandatory `security`
  and `legal` stages per D048.

## Problem statement

A user who installs the platform for the first time currently sees the
existing hub page with routes to `/performance`, `/players`, `/research`
— all of which are read-only surfaces. There is no journey from
"installed" to "connected to my broker and seeing my own data".

## Goal

Multi-step onboarding at `/onboarding` walks the user from "hello" to
"broker connected". First visit redirects. `/settings/reset-install`
returns to onboarding for testing / recovery.

## Scope (in)

### `agent/platform/onboarding.py`

Public API:

- `is_first_visit() -> bool` — returns True when no `install_token`
  exists in the keyring / config store. Called by every route handler
  (except `/healthz`, `/onboarding`, `/settings/reset-install`, and
  `/api/auth/status`) to decide whether to redirect.
- `mark_setup_complete() -> bool` — writes a `setup_complete=True`
  flag to keyring (namespace `bluelock`, key `setup_complete`).
- `reset_install() -> bool` — clears every key in the `bluelock` and
  `broker_mt5` namespaces (via `credentials.delete_secret`). Used by
  the `/settings/reset-install` route.
- `get_onboarding_state() -> dict` — returns `{"step", "completed",
  "install_fingerprint"}`. Consumed by the wizard's UI to know where
  to resume if the user reloads mid-flow.
- `set_current_step(step) -> bool` — persists the current step ("welcome",
  "passphrase", "broker", "pairs", "confirm") to keyring so a reload
  survives.

State stored in keyring, NEVER in the git-tracked `platform.toml`.

### `ONBOARDING_PAGE` in `agent/platform/pages.py`

5-step wizard:

1. **Welcome** — brand copy from `company/brand/copy.md` §F008; legal
   pass-through text ("By continuing you agree to…") from
   `company/legal/F008-onboarding-agreement.md`.
2. **Passphrase** — optional user passphrase for the encrypted-file
   fallback (used only when the OS keychain is unavailable). Empty is
   allowed — the wizard warns that credentials will fall back to
   plaintext-refused-and-degrade if keychain is missing. Passphrase
   strength check enforced (≥ 12 chars OR keyring available).
3. **Broker** — embeds F007's wizard steps as a sub-flow. On success,
   returns here.
4. **Default pairs** — checkbox grid: EURUSD (default on), GBPUSD, USDCAD.
5. **Confirm** — recap + "Complete setup" button that calls
   `POST /api/onboarding/complete`.

Every step uses F005 `withStates()` for in-flight state and 375 px
media query for mobile (F004).

### HTTP surface

- `GET /onboarding` — page.
- `GET /settings/reset-install` — confirmation page ("This clears your
  install. Continue?"). On POST-confirm, calls `onboarding.reset_install()`,
  redirects to `/onboarding`.
- `POST /onboarding/passphrase` — accepts / validates passphrase, stores
  hash (never plaintext) via `credentials.store_secret`.
- `POST /onboarding/complete` — calls `mark_setup_complete()`.
- `GET /api/onboarding/state` — returns `get_onboarding_state()`.
- **First-visit redirect JS** in `_BASE_CSS` / every page's shell —
  when `/api/onboarding/state` returns `completed=False`, JS redirects
  to `/onboarding`. Server-side redirect also enforced (belt + braces).

### Tests

- `tests/security/test_onboarding.py` — auth-bypass (hitting `/hq`
  before setup redirects to `/onboarding`), passphrase strength
  (empty rejected UNLESS keyring available; short rejected), reset
  flow doesn't leak previous state.
- `tests/platform/test_onboarding_module.py` — module smoke.
- `tests/platform/test_onboarding_api.py` — API contract.
- `tests/platform/test_onboarding_page.py` — page smoke: 5 steps,
  mobile media-query, disclaimer visible.

## Scope (out)

- Multi-user onboarding (D052 defers).
- Native mobile app onboarding (deferred).
- Onboarding video / tour v2 (Sprint 6 F040).

## Legal review

- Draft `company/legal/F008-onboarding-agreement.md` — the "By
  continuing you agree to…" copy on the welcome step.
- Confirm no personal data collected beyond what F007 already handles
  (broker login + password).

## UX

- `company/research/F008-user-journey.md` — first-user journey memo.
- `company/design/F008-mocks.md` — all 5 steps, desktop + 375 px.
- `company/brand/copy.md` — welcome + step titles + confirmation.

## Acceptance

- All three security tests pass.
- `pytest -q` full suite green (974 baseline + F006 + F007 + F008
  delta).
- Cold-install cycle (via `--reset-install`) drops the user at
  `/onboarding` and lets them finish setup end-to-end without
  hitting a 500 or a dead-end.
- Every step renders at 375 px.
- Reset flow doesn't leak any prior credentials.

## Files touched

New:
- `agent/platform/onboarding.py`
- `tests/security/test_onboarding.py`
- `tests/platform/test_onboarding_module.py`
- `tests/platform/test_onboarding_api.py`
- `tests/platform/test_onboarding_page.py`
- `company/research/F008-user-journey.md`
- `company/design/F008-mocks.md`
- `company/legal/F008-onboarding-agreement.md`
- `company/legal/F008-review.md`
- `company/qa/F008-verdict.md`
- Multiple handoffs.

Edited:
- `agent/platform/pages.py` — `ONBOARDING_PAGE` + first-visit-redirect JS.
- `scripts/serve_platform.py` — routes.
- `company/brand/copy.md`.
- `company/ledger/{company_state.json, decisions_log.md}`.
