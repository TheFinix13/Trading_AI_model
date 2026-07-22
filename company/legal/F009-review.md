# F009 — Legal review (rate limit + session expiry + token rotation)

- **Feature:** F009
- **Reviewer:** Legal
- **Date:** 2026-07-22
- **Verdict:** **pass**

## Claim review

Two new public claims register with `company/legal/claim_register.md`:

### Rate-limit protection

- **Claim:** "60 requests / minute per install-token by default on
  non-localhost `/api/*`."
- **Code path:** `agent/platform/rate_limiter.check()` returning
  `(False, retry_after)` when the token-bucket is drained. Applied in
  `scripts/serve_platform.py::_install_gate_pass()` before every
  authenticated `/api/*` request.
- **Disclaimer required:** No — this is a security control, not a
  performance claim. No dollar figure / return figure attached.

### Session expiry

- **Claim:** "Session expires 7 days after the last authenticated
  request. Default configurable via `[session] expiry_days` in
  `platform.toml`."
- **Code path:** `agent/platform/auth.is_session_expired()`. Applied
  in `_install_gate_pass()` before every authenticated `/api/*`
  request; the `POST /api/auth/rotate` route stays reachable even
  when the session is expired (recovery path).
- **Disclaimer required:** No.

### Token rotation

- **Claim:** "Users may rotate their install token at any time via
  `POST /api/auth/rotate`; the old token is invalidated
  atomically."
- **Code path:** `agent/platform/auth.rotate_install_token()`
  wrapped by the `/api/auth/rotate` route.
- **Disclaimer required:** No.

## Constraint check

- ✅ No performance / return / revenue claim attached to any F009
  surface.
- ✅ No third-party name usage.
- ✅ No new personal data collected (rotation returns the token
  once to the same caller who authorised the rotation).
- ✅ RedactingFilter (F006) survives rotation — a regression test in
  `tests/security/test_token_rotation.py::test_rotate_logs_only_
  fingerprint` pins that the rotated plaintext token never appears
  in a log line.

## Rolling constraints

- Any future "we rate-limit at N req/min" copy must reference
  `agent/platform/rate_limiter.get_config()` as the source of
  truth, not restate a hardcoded number.
- Any future session-length copy must reference the
  `[session] expiry_days` config path, not a hardcoded 7-day figure.

## Verdict

**Pass.** F009 does not introduce a public performance claim, does
not collect user data, and does not name any third party. The
two new security controls are appropriate defence-in-depth
additions to the F006 install-token gate. Signoff proceeds to CEO.
