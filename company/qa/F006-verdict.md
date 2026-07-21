# F006 — QA verdict

- **Sprint:** sprint-1-access
- **Feature:** F006 encrypted credential storage + install-scoped auth
- **Author:** QA
- **Date:** 2026-07-21
- **Verdict:** **pass**

## Test count

| Suite | Pre-F006 | Post-F006 | Delta |
|---|---|---|---|
| `tests/platform/` (existing) | 351 | 351 | 0 |
| `tests/platform/test_credentials_module.py` | 0 | 6 | +6 |
| `tests/platform/test_auth_module.py` | 0 | 6 | +6 |
| `tests/platform/test_auth_api.py` | 0 | 13 | +13 |
| `tests/security/test_credentials.py` (new) | 0 | 40 | +40 |
| `tests/security/test_auth.py` (new) | 0 | 52 | +52 |
| **Total (F006-scope)** | 351 | 468 | **+117** |
| **Full test suite** | 974 | 1091 | **+117** |

`python -m pytest tests/` returns `1091 passed`; every F006-scope
module is green.

## Coverage against acceptance criteria

- ✅ Malformed / empty / control-char / oversized inputs rejected by
  `store_secret` / `retrieve_secret` / `delete_secret`.
- ✅ Encrypted-file fallback holds no plaintext of stored value
  (byte-search regression test).
- ✅ Wrong passphrase → `retrieve_secret` returns `None` (fails
  safely, does not raise).
- ✅ Install token has ≥ 32 chars, URL-safe alphabet, ≥ 20 unique on
  20 draws (entropy).
- ✅ Constant-time compare — length-mismatch handled, `None`-safe.
- ✅ Fingerprint reveals first 8 + last 8 only, ellipsis in middle.
- ✅ `/api/auth/status` reachable without token; never emits the raw
  token; shape stable.
- ✅ `/api/*` non-localhost blocked without token (except
  `/api/auth/status`); presenting via header / cookie / query / Bearer
  all unlock.
- ✅ Legacy `platform.toml` `auth_token` still accepted as a fallback.
- ✅ Log-scrubber (`RedactingFilter`) regression: install token, MT5
  password, `token=`/`password=`/`secret=` key-values all scrubbed
  from log records.
- ✅ Idempotent filter mount (repeated `install_redacting_filter` calls
  replace the filter rather than stacking).
- ✅ `list_keys` never returns values; `__index__` reserved key
  hidden from listings.

## Manual dogfood

Not exercised in this stage (F008 wizard is where the end-to-end
onboarding walkthrough happens). Backend + API surface fully covered
by automated tests.

## Notes for Security stage

Threat model in `company/legal/F006-secrets-at-rest.md` (Legal drafted
after receiving Security's threat inputs). All rows in the table have
a mitigation on tape and a test that pins it.
