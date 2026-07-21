# F009 — Auth hardening: rate limit + session expiry + token rotation

- **Sprint:** sprint-2-real-trading
- **Priority:** P0
- **Lane:** Sprint 1 carry-over (D062) — resolves the three deferred
  security controls flagged in Sprint 1's REPORT §Security posture.
- **Consumes:** F006 (`auth.py`, `credentials.py`) and F006's
  install-token gate on `/api/*` non-localhost.
- **Consumed by:** F013 (live-mode toggle, approval APIs need
  rate-limiting + session freshness).
- **Feature flags:** `auth: true`, `credentials: true` → mandatory
  `security` review per D048.

## Problem statement

Sprint 1 shipped install-token auth but left three controls open:

1. **No per-token rate limit.** F007's `test_connection` rate-limits
   itself, but every other `/api/*` route is uncapped. An adversary
   with a stolen token could burst-hit the platform.
2. **No session expiry.** Install tokens never rotate. A token stolen
   once is stolen forever.
3. **No rotation path.** Even if the user knows their token is
   compromised, there is no `POST /api/auth/rotate` endpoint.

F009 closes all three.

## Scope (in)

### `agent/platform/rate_limiter.py` (new)

Token-bucket, per install-token, on every `/api/*` non-localhost request.

Public API:

```python
def check(token_key: str) -> tuple[bool, float]
    # Returns (allowed, retry_after_seconds).
    # retry_after_seconds is 0.0 when allowed.

def reset(token_key: str | None = None) -> None
    # Test helper. None clears every bucket.

def set_config(*, capacity: int, refill_per_sec: float) -> None
    # Called at server startup from platform.toml [rate_limit].
```

Config in `platform.toml`:

```toml
[rate_limit]
requests_per_minute = 60
burst = 60
```

Default: 60 req/min per install-token. Any 61st request in the same
window returns `429 Too Many Requests` with `Retry-After: <secs>`
header. Bucket state is in-memory (per-process, single-user install).

### `agent/platform/auth.py` (edited — additive)

Adds:

```python
SESSION_EXPIRY_SECONDS: int = 7 * 24 * 3600  # 7 days default
SESSION_ACTIVITY_KEY: str = "session_last_activity"

def record_session_activity() -> None
def session_last_activity() -> float | None
def is_session_expired(now: float | None = None) -> bool
def clear_session_activity() -> bool
def rotate_install_token() -> str  # generates new, invalidates old
def set_session_expiry_seconds(seconds: int) -> None  # test helper + config
```

Every authenticated request calls `record_session_activity()` (called
by `_install_gate_authorized` in `serve_platform.py`). When
`time.time() - session_last_activity() > SESSION_EXPIRY_SECONDS`, the
next authenticated request is rejected with `401` and body
`{"error": "session expired", "hint": "rotate your token"}`.

Rotation:

- `POST /api/auth/rotate` — requires a currently-valid install-token.
  On success: generates a new token via `generate_install_token()`
  (which overwrites the stored one), returns the new plaintext in the
  response body once (the caller displays it and stores it).
- Server-side triggers: passphrase change (future), user request via
  `/settings/security` (a new page section — F009 ships the API; the
  UI section lives in Sprint 3 stickiness).

Config in `platform.toml`:

```toml
[session]
expiry_days = 7
```

### `scripts/serve_platform.py` (edited)

- On startup: reads `[rate_limit]` + `[session]` from `platform.toml`
  via `agent/platform/config.py`, calls `rate_limiter.set_config(...)`
  and `auth.set_session_expiry_seconds(...)`.
- In `_install_gate_authorized`: after token match, call
  `rate_limiter.check(fingerprint)`. On `False`, `429 + Retry-After`.
  On success, call `auth.record_session_activity()`. On expired,
  reject with 401 as above.
- New route: `POST /api/auth/rotate`.

Localhost stays open per D052 — rate limiter + session expiry only
apply when `enforce_install_token=True`.

### Tests

- `tests/security/test_rate_limiter.py` (5) — bucket refill honest,
  429 fires on over-burst, per-token isolation (two tokens don't
  share a bucket), retry-after monotonic, reset clears state.
- `tests/security/test_session_expiry.py` (5) — activity recorded
  on each authorized hit, expiry after configured seconds, expired
  request → 401, clear resets, non-token activity ignored.
- `tests/security/test_token_rotation.py` (5) — rotate generates a
  new token, old token no longer authorises, new token authorises,
  rotate without prior token fails cleanly, rotate response body
  is a well-formed token.
- Regression: `tests/security/test_auth.py::TestRedactingFilter`
  keeps passing (no-plaintext-token-in-logs invariant from Sprint 1
  survives).

## Scope (out)

- Refresh-token model (not applicable — single-user install).
- Multi-token multi-device (Sprint 5+ compliance work).
- Rate limits on localhost (single-user dev stays open per D052).

## Legal

Adds two claim entries to `company/legal/claim_register.md`:

- `rate_limiter.check` — public rate-limit protection claim
  ("60 requests/minute per install-token by default").
- `auth.is_session_expired` — public session-expiry claim
  ("session expires 7 days after last authenticated request").

Both entries link to the module's public accessor + config surface.
No new user-facing legal warning (rate-limit and session-expiry are
infrastructural). Legal review handoff written BEFORE QA per D048.

## UX

- `company/research/F009-user-journey.md` — the security-conscious
  operator's journey; token rotation surfaced as a "regenerate my
  token" flow (API only in this sprint, UI section in Sprint 3).
- No design-mocks needed (no UI surface).

## Acceptance

- All 15 new tests pass.
- Full suite green (baseline + delta).
- Rate limit + session expiry only fire on non-localhost binds.
- Rotation endpoint returns a token that satisfies
  `auth._is_well_formed()`.
- No plaintext token in any log line, including in the rotation flow.

## Files touched

New:
- `agent/platform/rate_limiter.py`
- `tests/security/test_rate_limiter.py`
- `tests/security/test_session_expiry.py`
- `tests/security/test_token_rotation.py`
- `company/research/F009-user-journey.md`
- `company/legal/F009-review.md`
- `company/qa/F009-verdict.md`
- Handoffs.

Edited:
- `agent/platform/auth.py` — session/rotation additions
- `agent/platform/config.py` — new `[rate_limit]` + `[session]` blocks
- `scripts/serve_platform.py` — wire rate limiter + session recorder +
  rotation endpoint
- `company/legal/claim_register.md` — F009 entries
- `company/ledger/{company_state.json, decisions_log.md}`
