# F007 — MT5 broker connection wizard

- **Sprint:** sprint-1-access
- **Priority:** P0
- **Lane:** Broker Integrations (per D050)
- **Consumes:** F006 (`credentials.store_secret` / `retrieve_secret` /
  `list_keys` / `delete_secret`; auth gate on non-localhost `/api/broker/*`)
- **Consumed by:** F008 (broker step in onboarding wizard hands into
  this feature's flow)
- **Feature flags:** `auth: true` (guarded by F006 gate), `credentials: true`,
  `broker_connection: true` → mandatory `security` and `legal` stages per D048.

## Problem statement

A retail forex trader landing on the installed platform needs one way
to connect their MT5 account (Exness demo is the reference target).
That flow doesn't exist yet — `platform.toml` has ad-hoc broker config
but no wizard, no test-connection affordance, no encrypted storage
past this sprint. F007 delivers the wizard end-to-end.

## Goal

Multi-step web wizard at `/settings/broker`: choose account type →
enter credentials → test connection → save (encrypted). Sandbox / demo
is default; live requires typed confirmation and inline Legal warning.

## Scope (in)

### `agent/platform/broker_connection.py`

Public API:

- `is_mt5_available() -> bool` — returns True only on `sys.platform ==
  "win32"` where the `MetaTrader5` package can import. Everywhere else
  the wizard degrades to a "MT5 client only runs on Windows" affordance.
- `test_connection(login, password, server, timeout=10) -> dict` —
  `{success, error_code, error_message, account_type, account_number,
  balance_currency, server}`. When MT5 is not importable, returns
  `{"success": False, "error_code": None, "error_message": "MT5 not
  available on this platform", ...}` and never touches the network.
  Password is NEVER included in `error_message` or logged.
- `save_credentials(user_alias, login, password, server, account_type)
  -> bool` — encodes the whole tuple as JSON and stores via
  `credentials.store_secret(namespace="broker_mt5", key=user_alias,
  value=json.dumps(...))`. Alias validation enforced (see below).
- `load_credentials(user_alias) -> dict | None` — decrypts. **Server-side
  only**. Never returned via HTTP.
- `list_aliases() -> list[dict]` — returns `[{"alias", "account_type",
  "server", "login"}, ...]` — passwords absent by construction.
- `delete_credentials(user_alias) -> bool` — reverse of save.
- `ALLOWED_SERVERS` — module constant, allow-listed MT5 server
  patterns (`Exness-*`, `Demo-*`, `MetaQuotes-*`, `ICMarkets-*`, etc.).
  `test_connection` and `save_credentials` reject anything that doesn't
  match. Documented in Legal review.
- Rate-limiter — 5 `test_connection` attempts per minute per install
  token. Implementation via `collections.deque` + timestamps; state
  process-local (single-user model). Return `{"success": False,
  "error_code": 429, "error_message": "Too many attempts — wait a minute
  before retrying"}` when tripped.

### HTTP surface

- `POST /api/broker/test-connection` — body `{login, password, server}`,
  returns `test_connection()`. Password never echoed back. Rate-limited.
- `POST /api/broker/save` — body `{alias, login, password, server,
  account_type}`, returns `{"success": bool, "error"?: str}`.
- `GET /api/broker/list` — returns `list_aliases()`.
- `DELETE /api/broker/<alias>` — returns `{"success": bool}`.

All four gated by F006's install-token on non-localhost. Localhost
stays open for single-user dev per D052.

### `BROKER_WIZARD_PAGE` in `agent/platform/pages.py`

Multi-step form at `/settings/broker`:

1. **Step 1 — Choose account type.** Radio buttons: "Demo / Sandbox"
   (default, per D052), "Live account (real money)".
2. **Step 2 — Enter credentials.** Login (numeric), Password (`type=
   "password"`, `autocomplete="off"`, `spellcheck="false"`), Server
   (dropdown seeded from `ALLOWED_SERVERS`).
3. **Step 3 — Confirm live (if live).** Inline Legal warning from
   `company/legal/live-broker-warning.md`; user ticks "I understand
   this uses real money" AND types "LIVE" into a confirmation field.
4. **Step 4 — Test connection.** Calls `POST /api/broker/test-connection`.
   Uses F005 `withStates()` for the in-flight state.
5. **Step 5 — Save.** Alias field, POSTs `/api/broker/save`. On
   success, shows the fingerprint of the stored key + a "your password
   is encrypted at rest" affordance.

Includes step-back arrows (except from step 5). Aria-labels on every
form control. Mobile-friendly at 375 px viewport (F004 baked in).

### Tests

- `tests/security/test_broker_connection.py` — auth gate on `/api/broker/*`
  non-localhost, password-in-logs regression, allow-list enforcement for
  server URLs, rate-limit enforcement, DELETE authorisation.
- `tests/platform/test_broker_connection_module.py` — module smoke +
  no-write-of-password-to-log invariant.
- `tests/platform/test_broker_connection_api.py` — API contract tests
  (test-connection, save, list, delete).
- `tests/platform/test_broker_wizard_page.py` — page smoke: renders,
  form structure, F004 media-query, IP notice / disclaimer visible.

## Scope (out)

- Multi-broker (OANDA, MT4, IBKR) — Sprint 7+ backlog.
- Real broker orders — Sprint 5 gated by pen test.
- Automated MT5 install on macOS/Linux — MT5 client is Windows-only;
  we surface a friendly affordance and stop.
- Copy-trading — Sprint 7+.

## Legal review

- Draft `company/legal/live-broker-warning.md` — the inline warning
  users see when they pick "Live account" in step 1.
- Register every new public accessor in `claim_register.md`.
- Rolling constraint: `password` string never appears in any HTTP
  response body or log line — Security regression pins this.

## UX

- `company/research/F007-user-journey.md` — the retail user's wizard
  flow, sandbox-first framing.
- `company/design/F007-mocks.md` — step-by-step desktop + 375 px mocks.
- `company/brand/copy.md` — every wizard string sourced from copy.md.

## Acceptance

- All five security tests + all platform tests pass.
- `pytest -q` full suite green (974 baseline + F006 delta + F007 delta).
- BROKER_WIZARD_PAGE renders clean at 375 px.
- Password never appears in logs when running the wizard with fake
  credentials.
- Rate-limit trips on the sixth attempt within 60 s.
- Non-allowed server URL is rejected with a friendly error.

## Files touched

New:
- `agent/platform/broker_connection.py`
- `tests/security/test_broker_connection.py`
- `tests/platform/test_broker_connection_module.py`
- `tests/platform/test_broker_connection_api.py`
- `tests/platform/test_broker_wizard_page.py`
- `company/research/F007-user-journey.md`
- `company/design/F007-mocks.md`
- `company/legal/live-broker-warning.md`
- `company/legal/F007-broker-review.md`
- `company/qa/F007-verdict.md`
- Multiple handoffs under `company/handoffs/`.

Edited:
- `agent/platform/pages.py` — `BROKER_WIZARD_PAGE`.
- `scripts/serve_platform.py` — routes + APIs.
- `company/brand/copy.md`.
- `company/ledger/{company_state.json, decisions_log.md}`.
