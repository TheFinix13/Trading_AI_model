# F006 — Encrypted credential storage + install-scoped auth

- **Sprint:** sprint-1-access
- **Priority:** P0
- **Lane:** Auth Developer (per D050)
- **Consumes:** none (foundation feature for F007 + F008)
- **Consumed by:** F007 (credential storage), F008 (auth check on onboarding redirect)
- **Feature flags:** `auth: true`, `credentials: true` → mandatory `security` and `legal` stages per D048.

## Problem statement

Sprint 0 shipped seven public routes with no auth surface. The
pre-existing `platform.toml` `auth_token` (used by the deployed VM)
was retained but not exercised at the feature layer. Sprint 1 adds
credentials to the platform (broker passwords, install tokens) and
those cannot live in `platform.toml` — a committed file in a Git repo
is not an at-rest store.

## Goal

Give the single-user installation (per D052) a secure home for
secrets and a token-based check for its own HTTP surface. Two backend
modules; zero rotation of the deployed VM's existing token.

## Scope (in)

### `agent/platform/credentials.py`

Thin wrapper over the `keyring` library (already in `requirements.txt`
after this sprint's first commit). Public API:

- `store_secret(namespace, key, value)` — attempts the OS keychain
  first; on `keyring.errors.NoKeyringError` (headless Linux, sandbox
  without a keyring backend), falls back to an encrypted file at
  `<config_dir>/credentials.enc` using a user-supplied passphrase and
  `cryptography.fernet.Fernet`. Returns `True` on success. Never logs
  the `value`.
- `retrieve_secret(namespace, key) -> Optional[str]` — reverse.
- `delete_secret(namespace, key) -> bool` — reverse.
- `list_keys(namespace) -> list[str]` — returns known keys; values
  never returned.

### `agent/platform/auth.py`

Install-scoped token generation and validation:

- `generate_install_token() -> str` — first-time setup. Generates a
  URL-safe 256-bit token (`secrets.token_urlsafe(32)`), stores it via
  `credentials.store_secret(namespace="bluelock", key="install_token")`.
  Also generates a display fingerprint (first 8 + last 8 chars of the
  token, joined by `…`) that the user records for their records.
- `install_token_fingerprint(token) -> str` — pure function; useful for
  UI display and tests.
- `load_install_token() -> str | None` — reads from keyring; never
  exposed via HTTP.
- `clear_install_token() -> bool` — used by `/settings/reset-install`.
- `auth_status() -> dict` — returns `{"authenticated": bool, "install_fingerprint": str | None}`.
- `check_request_token(header_value, cookie_value) -> bool` —
  constant-time compare against the stored install token; returns
  False if none stored. Backwards-compat: also accepts the
  `platform.toml` `auth_token` fallback (documented rotation path in
  D052).

Plus a **redaction filter** for the Python logging module. `RedactingFilter`
scrubs any string matching known token/password patterns from log
records before they hit stdout/stderr. Installed at
`serve_platform.main()` initialisation.

### HTTP surface (via `scripts/serve_platform.py`)

- `GET /api/auth/status` — returns `auth.auth_status()`. Always
  reachable (no auth gate); intentionally leaks only whether the
  install is configured + the fingerprint.
- **Auth gate** on `/api/*` routes when binding **non-localhost**.
  `127.0.0.1` stays open. New `X-Bluelock-Token` header supported
  alongside the existing `?token=`, `Authorization: Bearer`, and
  cookie paths. Existing `platform.toml` `auth_token` remains the
  documented fallback; install-token stored in keyring takes
  precedence when both are present.
- Redaction filter mounted on the platform's root logger so any
  accidental log of a secret is scrubbed.

### Tests (per D048)

- `tests/security/__init__.py` — empty marker.
- `tests/security/test_credentials.py` — auth-bypass, storage-at-rest
  (no plaintext in encrypted-file fallback), input fuzz (empty /
  whitespace / control chars / path-traversal / oversized), log-scrubber
  regression.
- `tests/security/test_auth.py` — token generation entropy,
  fingerprint stability, constant-time compare, expired-session /
  replay / malformed-token negative tests, backwards-compat with
  `platform.toml` fallback.

## Scope (out)

- No user database / multi-tenancy (D052; deferred to Sprint 5).
- No password reset / email verification (D052).
- No rotation of the deployed VM's `platform.toml` `auth_token` —
  install-token is ADDITIVE, not a replacement.
- No functional changes to Sprint 0 shipped modules
  (`performance.py`, `players.py`, `research.py`, `hq.py`); only their
  `/api/*` routes gain the auth gate via `serve_platform.py`.

## Non-goals

- Hardware token (YubiKey) support — Sprint 5+.
- OAuth / SSO — Sprint 5+.
- Signed cookies / JWTs — Sprint 2+ if session pattern emerges.

## Legal review

- Add F006 secrets-at-rest disclaimer at
  `company/legal/F006-secrets-at-rest.md` — one page: "your MT5
  password lives in the OS keychain on your machine; the platform
  server never sees it in plaintext except when actively testing a
  connection".
- Register every new public accessor in `company/legal/claim_register.md`
  (seeded during retro-amendment commit).

## UX

- UX Researcher memo `company/research/F006-user-journey.md` — why
  single-user is right for the target audience (a retail forex trader
  with one MT5 demo account).
- UI Designer mock `company/design/F006-mocks.md` — install-fingerprint
  display and the "reset install" affordance.
- Brand copy updates `company/brand/copy.md` — security-related strings
  (fingerprint label, reset warning, "token stored securely" affordance).

## Acceptance

- All four `tests/security/test_credentials.py` + `test_auth.py` test
  groups pass.
- `pytest -q` full suite green (971 baseline + 3 BASE_CSS + F006 delta).
- No secrets in `git ls-files` output (grep for `token`, `password`).
- No plaintext token in `platform.toml` beyond the existing pre-Sprint-1
  fallback.
- Redaction filter regression test passes.

## Files touched

New:
- `agent/platform/credentials.py`
- `agent/platform/auth.py`
- `tests/security/__init__.py`
- `tests/security/test_credentials.py`
- `tests/security/test_auth.py`
- `tests/platform/test_credentials_module.py` (module smoke)
- `tests/platform/test_auth_module.py` (module smoke)
- `tests/platform/test_auth_api.py` (`/api/auth/status`)
- `company/research/F006-user-journey.md`
- `company/design/F006-mocks.md`
- `company/legal/F006-secrets-at-rest.md`
- `company/qa/F006-verdict.md`
- Multiple handoffs under `company/handoffs/`.

Edited:
- `scripts/serve_platform.py` — `/api/auth/status` route + auth gate on
  `/api/*` non-localhost + redaction-filter mount.
- `agent/platform/pages.py` — none (all UI ships with F008).
- `company/brand/copy.md` — security strings.
- `company/ledger/{company_state.json, decisions_log.md}`.
