# F009 — QA verdict (auth hardening)

- **Feature:** F009
- **Reviewer:** QA
- **Date:** 2026-07-22
- **Verdict:** **pass**

## Tests

| Suite | Path | Count |
|---|---|---|
| Rate limiter | `tests/security/test_rate_limiter.py` | 14 |
| Session expiry | `tests/security/test_session_expiry.py` | 9 |
| Token rotation | `tests/security/test_token_rotation.py` | 6 |
| **F009 total** | — | **29** |
| Full platform suite | `pytest -q` | 1287 passed |

Spec said 5+5+5 = 15 minimum; we shipped 29 to cover branch coverage
on refill / retry-after / config validation and the log-scrubbing
regression on rotation.

## Manual verification

- Cold install → `generate_install_token()` records initial session
  activity (verified through `test_generation_records_activity`
  chain in test_session_expiry). First `/api/*` request after
  generation is not rejected as expired.
- Rate-limit response: `429 Too Many Requests` with a
  `Retry-After` header carrying an integer >=1 s. Verified by
  eye-balling the response headers in an ad-hoc `curl` loop.
- Rotation: old token no longer authorises; new token authorises;
  ancient session-activity is refreshed on rotation (verified by
  `test_rotate_refreshes_session_activity`).

## Regression coverage

- Sprint 1 F006 `RedactingFilter` still active on `agent.platform` /
  `""` root loggers (unchanged).
- `test_rotate_logs_only_fingerprint` pins that the rotated
  plaintext token never appears in a log line.
- `platform.toml` fallback token still works (Sprint 0 backwards-
  compat via D052); the pre-existing `TestInstallTokenGate::
  test_platform_toml_fallback_accepted` remained green after
  session-expiry was scoped to `is_install_configured()` only.

## Handoff

Legal review (F009-review.md) passed before this verdict per D048.
CEO signoff is next.
