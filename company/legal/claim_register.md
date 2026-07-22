# Legal claim register

Every public field exposed by an `agent/platform/*.py` module has an
entry here. New public fields land with a matching entry in the same
commit. See `company/protocols/review-chain.md` §6.3 for the audit.

## Fields → code paths → disclaimers

Format:

| Module | Public accessor | Field | Human meaning | Code path (where computed) | Disclaimer required? |
|---|---|---|---|---|---|

### F001 — `agent/platform/performance.py`

Public accessor: `performance.get_state(log_root, live_dir) -> dict`.

| Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|
| `days_live` | Distinct UTC dates on which ≥ 1 trade closed. | `get_state` line 345 (set-comprehension over `merged`). | See `company/legal/disclaimers.md` §performance — "not investment advice". |
| `net_pips` | Sum of `pnl_pips` across every closed trade in scope. | `get_state` line 344 (`round(sum(...), 1)`). | Same as `days_live`. |
| `worst_dd_pips` | Deepest peak-to-trough draw-down on the time-ordered cumulative-pip curve. | `_worst_dd(curve)` at `performance.py:237`. | Same. |
| `win_rate_pct` | Fraction of closed trades with `pnl_pips > 0`, expressed 0-100. | `get_state` lines 349-350. | Same. |
| `sharpe_or_null` | Daily-return Sharpe of the pip-based series, or `None` when < `MIN_DAYS_FOR_SHARPE = 30`. | `_sharpe_or_null(daily)` at `performance.py:261`. | Same — plus the "need N more days" affordance on the page. |
| `sharpe_days_needed` | When Sharpe is null, integer count of additional daily returns needed to reach the floor. | `_sharpe_or_null` return line 279. | None — derived, non-claim. |
| `trades_total` | Count of `merged` trades. | `get_state` line 363. | Same as `days_live`. |
| `equity_curve` | List of `{ts, cum_pips}` in time order. | `_equity_curve(trades)` at `performance.py:224`. | Same. |
| `per_pair` | One row per FX pair present in scope; each row has trade count, net pips, win rate. | `_per_pair(trades)` at `performance.py:280`. | Same. |
| `source_hint` | Friendly string naming which data sources were used ("v1 live", "v2 shadow-paper", "combined view", "no data yet"). | `_source_hint(v1_count, v2_count)` at `performance.py:310`. | None — meta string, not a claim. |
| `v1_trades_count` | Number of v1 daily-log trades contributing to `merged`. | `get_state` line 367. | None — meta. |
| `v2_trades_count` | Number of v2 shadow-paper trades contributing. | `get_state` line 368. | None — meta. |
| `generated_at` | UTC ISO 8601 timestamp of the payload. | `_now_iso()` at `performance.py:90`. | None — meta. |

Rolling constraint (Legal): no `net_pips` or `win_rate_pct` may appear
in marketing copy outside `/performance` without a linked disclaimer.

### F002 — `agent/platform/players.py`

Public accessors: `players.list_state(live_dir) -> dict`,
`players.list_players(live_dir, bio_dir) -> list[dict]`,
`players.get_player(id_, live_dir) -> dict | None`,
`players.roster_meta() -> tuple[dict, ...]`,
`players.valid_ids() -> tuple[str, ...]`,
`players.normalize_id(raw) -> str | None`.

`list_players()` per-row fields (roster index card):

| Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|
| `id` | Canonical slug. | `list_players`. | None. |
| `name` | Display name (Blue Lock IP). | `list_players`. | IP notice. |
| `playstyle_tag` | Short badge string ("scoring line", etc.). | `list_players`. | Same. |
| `status` | `"active"` / `"standby"` / `"retired"`. | `list_players`. | None (state). |
| `tier` | Roster tier (e.g. `"S"`, `"A"`). | `list_players`. | None (state). |
| `symbols` | FX pairs assigned to this striker. | `list_players`. | None (state). |
| `signature_blurb` | One-line bio blurb. | `list_players`. | IP notice. |
| `proposals` | Count of proposal events for the agent. | `_stats_for_agent`. | Not-investment-advice. |
| `wins` | Count of proposals that closed with `pnl_pips > 0`. | `_stats_for_agent`. | Same. |
| `net_pips` | Sum of `pnl_pips` for the agent's proposals. | `_stats_for_agent`. | Same. |

`list_state()` per-row fields:

| Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|
| `id` | Canonical slug (matches roster bio filename). | `_load_bio` metadata. | None. |
| `name` | Display name (Blue Lock IP; parody usage governed by IP notice). | `_load_bio` metadata. | `company/legal/blue-lock-ip-notice.md` on every page. |
| `role` | One-liner ("scoring line", "playmaker", etc.) from the bio. | `_load_bio`. | Same IP notice. |
| `status` | `"active"`, `"standby"`, or `"retired"`. | `roster_meta()` static map. | None (state, not claim). |
| `agent_key` | Internal squad agent identifier (e.g. `A1_baseline`). | Static map in `roster_meta()`. | None. |
| `preview_stats` | Small subset of `_stats_for_agent` (goals, appearances, source_hint). | `_stats_for_agent` filtered. | See per-stat rows below. |

`get_player(id_)` payload extends `list_state` with:

| Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|
| `bio_html` | Bio prose rendered to HTML from `company/roster/players/<id>.md`. | `_parse_bio_markdown` at `players.py:236`. | IP notice. |
| `goals` | Count of `close` events with `pnl_pips > 0` for the agent. | `_stats_for_agent` at `players.py:346`. | "not investment advice" + IP notice. |
| `appearances` | Count of events attributed to the agent. | `_stats_for_agent`. | Same. |
| `net_pips` | Sum of `pnl_pips` for the agent's `close` events. | `_stats_for_agent`. | Same. |
| `win_rate_pct` | Wins ÷ total closes, 0-100. | `_stats_for_agent`. | Same. |
| `recent_activity` | Last N events for the agent. | `_recent_activity` at `players.py:414`. | Same. |
| `source_hint` | "no events yet" / "based on N events" / etc. | `_source_hint` at `players.py:448`. | None — meta. |
| `generated_at` | UTC ISO 8601. | `_now_iso` at `players.py:460`. | None — meta. |

Rolling constraint (Legal): no per-striker stat may appear in
marketing copy without both the "not investment advice" disclaimer
AND the Blue Lock IP notice.

### F003 — `agent/platform/research.py`

Public accessors: `research.get_state(research_root, manifest_path) -> dict`,
`research.load_manifest(path) -> dict`,
`research.list_all(research_root) -> list[dict]`,
`research.parse_report(path) -> dict | None`.

`get_state()` per-verdict fields:

| Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|
| `campaign_id` | Experiment/campaign folder id (e.g. `E011_...`). | `_campaign_id_from_path` at `research.py:210`. | None (source id). |
| `title` | Front-matter title from `REPORT.md`. | `parse_report` at `research.py:226`. | None (source string). |
| `verdict` | One of `alive_survivor` / `dead` / `fail` / `stopped` / `passing`. | `_classify_verdict` at `research.py:170`. | See "publication constraint" below. |
| `verdict_label` | Human-readable pill copy (from `brand/copy.md`). | `_decorate` at `research.py:313`. | Same. |
| `brand_summary` | Curated 1-2 sentence CPO summary (`publication_manifest.json`). | Manifest override. | Same. |
| `headline_stat` | Curated single-number stat surfaced next to the pill. | Manifest override. | Same. |
| `abstract` | First para of REPORT.md abstract, ≤ 320 chars. | `_extract_abstract` at `research.py:181`. | Anti-cherry-pick disclaimer must render on the page. |
| `date` | Date from front-matter or manifest. | `parse_report` / manifest. | None (source). |
| `source_path` | Relative sibling-repo path for provenance. | `parse_report`. | None (source). |

Publication constraint (Legal, D040 rolling): only campaigns explicitly
listed in `publication_manifest.json` are ever emitted. Verdicts of
kind `fail` / `dead` / `stopped` must not be dropped without an
equivalent alive entry — the receipt-trail ratio is public evidence.

Payload meta fields:

| Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|
| `verdicts` | List of decorated per-report rows. | `get_state`. | Anti-cherry-pick disclaimer. |
| `source_exists` | Whether the sibling research repo was found. | `get_state`. | None — meta. |
| `manifest_size` | Count of allow-listed campaigns. | `get_state`. | None — meta. |
| `source_hint` | "6 of 6 published" / "sibling repo missing" / etc. | `get_state`. | None. |
| `generated_at` | UTC ISO 8601. | `_now_iso` at `research.py:113`. | None. |

### F006 — `agent/platform/credentials.py` (Sprint 1)

Public accessors: `store_secret(namespace, key, value)`,
`retrieve_secret(namespace, key)`, `delete_secret(namespace, key)`,
`list_keys(namespace)`.

Internal setup / test helpers (no user-visible claim; marked
`# claim-exempt` at their def line): `encrypted_file_path`,
`set_config_dir`, `set_encrypted_file_passphrase`,
`is_keyring_available`, `force_fallback`. These configure the
storage backend but do not emit any field over HTTP.

Public fields returned:

| Accessor | Returned shape | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `store_secret` | `bool` (True on success). | Whether the write hit either the OS keychain or the encrypted-file fallback. | `credentials.store_secret`. | See F006 secrets-at-rest disclaimer in `company/legal/F006-secrets-at-rest.md`. |
| `retrieve_secret` | `str \| None`. | The stored secret **value** — MUST NEVER be logged, echoed, or returned via any HTTP response. | `credentials.retrieve_secret`. | Secrets-at-rest disclaimer. |
| `delete_secret` | `bool`. | Whether the delete succeeded. | `credentials.delete_secret`. | Same. |
| `list_keys` | `list[str]` — **keys only**, no values. | The known keys in a namespace. Values NEVER returned by this accessor. | `credentials.list_keys`. | Same. |

Non-public / never-emitted: the plaintext value itself. If the value
appears in a log line, response body, or an unrelated accessor's
output, that is a **claim-register violation** and Security should
open a P0 blocker.

### F006 — `agent/platform/auth.py` (Sprint 1)

Public accessors: `generate_install_token() -> str`,
`install_token_fingerprint(token) -> str`,
`load_install_token() -> str | None`,
`clear_install_token() -> bool`,
`is_install_configured() -> bool`,
`check_request_token(headers, query, cookies) -> bool`,
`auth_status() -> dict`.

Internal helpers exempt from the register (`# claim-exempt` inline):
`constant_time_equal`, `RedactingFilter`, `install_redacting_filter` --
these are auth-plumbing utilities that protect logs and never emit
their own claims over HTTP.

Public fields returned:

| Accessor | Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `generate_install_token` | `str` | Fresh 256-bit URL-safe install token. Stored via `credentials.store_secret`. | `auth.generate_install_token`. | Secrets-at-rest disclaimer. |
| `install_token_fingerprint` | `str` (first-8 + last-8 chars). | Display fingerprint the user records. Non-recoverable from fingerprint alone. | `auth.install_token_fingerprint`. | None — derived. |
| `load_install_token` | `str \| None` | Reads the stored token; never exposed via HTTP. | `auth.load_install_token`. | Secrets-at-rest disclaimer. |
| `clear_install_token` | `bool` | Reset the token (used by `/settings/reset-install`). | `auth.clear_install_token`. | Same. |
| `auth_status` → `authenticated` | `bool` | Whether the current request presents a valid token. | `auth.auth_status`. | None. |
| `auth_status` → `install_fingerprint` | `str \| None` | Fingerprint if configured, None otherwise. | `auth.auth_status`. | None. |
| `is_install_configured` | `bool` | True iff a stored install token exists in the F006 credentials layer. Callers use this to short-circuit the F009 session-expiry gate when running on the pre-F006 `platform.toml` fallback path. | `auth.is_install_configured`. | None -- state. |
| `check_request_token` | `bool` | Constant-time comparison of a request's presented token against the stored install token. Returns False on missing / mismatched / absent-config. Called by `scripts/serve_platform._install_gate_pass()`. | `auth.check_request_token`. | None -- security control. |

### F007 — `agent/platform/broker_connection.py` (Sprint 1)

Public accessors: `test_connection(login, password, server, timeout)`,
`save_credentials(user_alias, login, password, server, account_type)`,
`load_credentials(user_alias)`, `list_aliases()`,
`delete_credentials(user_alias)`, `is_mt5_available()`.

Test-only helper marked `# claim-exempt` inline: `reset_rate_limiter`.
Not user-visible; used in unit tests to reset internal state between
cases.

Public fields returned:

| Accessor | Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `test_connection` → `success` | `bool` | Whether the MT5 login attempt succeeded. | `broker_connection.test_connection`. | Live-broker warning in `company/legal/live-broker-warning.md`. |
| `test_connection` → `error_code` | `int \| None` | MT5 error code on failure. | Same. | None — mechanical. |
| `test_connection` → `error_message` | `str \| None` | Human-readable MT5 error. Password NEVER included. | Same. | Live-broker warning. |
| `test_connection` → `account_type` | `"demo"` / `"live"` / `"unknown"` | Detected from MT5 `account_info().trade_mode`. | Same. | Live-broker warning triggers when `live`. |
| `test_connection` → `account_number` | `int \| None` | The MT5 login the user typed (echoed back for confirmation). Not sensitive. | Same. | None. |
| `test_connection` → `balance_currency` | `str \| None` | 3-letter currency code from `account_info().currency`. | Same. | None. |
| `test_connection` → `server` | `str \| None` | Echo of the server the user chose. | Same. | None. |
| `save_credentials` | `bool` | Whether the write succeeded. Password stored via `credentials.store_secret` — never in this response. | Same. | Live-broker + secrets-at-rest. |
| `load_credentials` | `dict \| None` | Full credential bundle. **Server-side only**. NEVER returned via HTTP. | Same. | Secrets-at-rest. |
| `list_aliases` | `list[dict]` with `{alias, account_type, server, login}` — **no password**. | Aliases the user has saved. | Same. | None — passwords absent. |
| `delete_credentials` | `bool` | Whether the delete succeeded. | Same. | None. |
| `is_mt5_available` | `bool` | Whether the `MetaTrader5` package is importable on this platform. | Same. | None — meta. |

Rolling constraint (Legal): the string `password` MUST NEVER appear in
a log line, response body, or JSON payload emitted by broker_connection
or its HTTP wrappers. A regression test in `tests/security/` pins this.

### F008 — `agent/platform/onboarding.py` (Sprint 1)

Public accessors: `is_first_visit() -> bool`,
`is_setup_complete() -> bool`,
`mark_setup_complete() -> bool`,
`reset_install() -> bool`,
`get_onboarding_state() -> dict`,
`set_current_step(step) -> bool`,
`set_default_pairs(pairs) -> bool`,
`get_default_pairs() -> list[str]`,
`validate_passphrase(passphrase, keyring_available) -> tuple[bool, str]`.

Public fields returned:

| Accessor | Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `is_first_visit` | `bool` | True when no `install_token` exists in keyring/config. | `onboarding.is_first_visit`. | None — state. |
| `is_setup_complete` | `bool` | True once the user has completed the setup wizard. Cached in the F006 credentials layer under key `setup_complete`. | `onboarding.is_setup_complete`. | None — state. |
| `mark_setup_complete` | `bool` | Sets `setup_complete` flag in keyring. | `onboarding.mark_setup_complete`. | None. |
| `set_current_step` | `bool` | Persists the current wizard step id so a refresh returns to the same screen. Value validated against `_STEPS`. | `onboarding.set_current_step`. | None — state. |
| `set_default_pairs` | `bool` | Persists the FX pairs the user selected during onboarding. Values validated against `_ALLOWED_PAIRS`. | `onboarding.set_default_pairs`. | None — state. |
| `get_default_pairs` | `list[str]` | The FX pairs the user selected. Empty list = none chosen yet. | `onboarding.get_default_pairs`. | None — state. |
| `validate_passphrase` | `(bool, str)` | Rejects empty passphrases when the OS keychain is unavailable, and enforces a 12-character floor for the encrypted-file fallback. Second element is the reason. | `onboarding.validate_passphrase`. | None — security control. |
| `reset_install` | `bool` | Clears every keyring key under `namespace=bluelock`. | `onboarding.reset_install`. | Confirmation-required user-facing string uses `company/brand/copy.md` §F008. |
| `get_onboarding_state` → `step` | `str` | Current step id (e.g. `"welcome"`, `"passphrase"`, `"broker"`, `"pairs"`, `"confirm"`). | Same. | None — state. |
| `get_onboarding_state` → `completed` | `bool` | Whether setup is done. | Same. | None. |
| `get_onboarding_state` → `install_fingerprint` | `str \| None` | From `auth.install_token_fingerprint`. | Same. | None. |

Rolling constraint (Legal): the "By continuing you agree to…" text on
the welcome step must render verbatim from `company/legal/F008-onboarding-agreement.md`.

### F009 — `agent/platform/rate_limiter.py` (Sprint 2)

Public accessors: `check(token_key) -> tuple[bool, float]`,
`reset(token_key=None) -> None`,
`set_config(*, capacity, refill_per_sec, requests_per_minute) -> None`,
`get_config() -> dict`, `bucket_count() -> int`.

| Accessor | Field / return | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `check` | `(allowed: bool, retry_after: float)` | Whether this request is within the token-bucket budget for this install-token. Applied as the second gate on `/api/*` non-localhost. | `rate_limiter.check`. | None — security control. |
| `set_config` | side-effect (None) | Reconfigure bucket capacity / refill rate. Called at server start from `[rate_limit]` in `platform.toml`. | `rate_limiter.set_config`. | None. |
| `get_config` | `{capacity, refill_per_sec, requests_per_minute}` | Current rate-limit configuration. Cited by any future "we rate-limit at N req/min" copy. | `rate_limiter.get_config`. | None. |

Rolling constraint (Legal): any future marketing copy citing a
requests-per-minute number MUST reference `rate_limiter.get_config()`
as the source, not restate a hardcoded number.

### F009 — `agent/platform/auth.py` additions (Sprint 2)

Public accessors added: `record_session_activity()`,
`session_last_activity() -> float | None`,
`is_session_expired(now=None) -> bool`,
`clear_session_activity() -> bool`,
`rotate_install_token() -> str`,
`set_session_expiry_seconds(seconds) -> None`,
`get_session_expiry_seconds() -> int`.

| Accessor | Return | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `record_session_activity` | `bool` | Persist the current time as the last authenticated activity. Called by `_install_gate_pass()` after every successful install-token check. | `auth.record_session_activity`. | None — state. |
| `session_last_activity` | `float \| None` | The stored last-activity unix timestamp, or None. | `auth.session_last_activity`. | None — state. |
| `is_session_expired` | `bool` | True iff `now - last_activity > session_expiry_seconds`. Missing activity counts as expired (defense-in-depth). | `auth.is_session_expired`. | None — security control. |
| `rotate_install_token` | `str` | Generate a fresh token and invalidate the old. Refreshes session activity. Raises RuntimeError if no install token exists yet. | `auth.rotate_install_token`. | Secrets-at-rest disclaimer (F006 applies). |
| `get_session_expiry_seconds` | `int` | Current expiry window. Cited by any future session-length copy. | `auth.get_session_expiry_seconds`. | None. |

Rolling constraint (Legal): any future session-length copy MUST
reference `[session] expiry_days` in `platform.toml` (surfaced by
`get_session_expiry_seconds`), not a hardcoded 7-day figure.

### F011 — `agent/platform/kill_switches.py` (Sprint 2)

Public accessors: `kill_dir()`, `is_killed(symbol=None) -> bool`,
`list_killed() -> list[dict]`.

Public module constants: `KILL_DIR_ENV`, `DEFAULT_KILL_DIRNAME`,
`SUPPORTED_SYMBOLS`, `GLOBAL_KEY`. Test-only helper marked
`# claim-exempt` inline: `reset_cache_for_tests`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `kill_dir` | `Path` | Current kill-flag directory. Defaults to `<config_dir>/kill`; env var `BLUELOCK_KILL_DIR` overrides. | `kill_switches.kill_dir`. | None -- filesystem path. |
| `is_killed(None)` | `bool` | True iff the global kill flag exists. | `kill_switches.is_killed`. | Safety-control claim; documented in F013's live-mode warning. |
| `is_killed("EURUSD")` | `bool` | True iff the global kill OR the EURUSD per-symbol flag exists. | Same. | Same. |
| `list_killed` → `scope` | `"GLOBAL"` \| supported symbol | The active kill scopes, global-first then symbols in `SUPPORTED_SYMBOLS` order. | `kill_switches.list_killed`. | Safety-control state; surfaces in `/settings/kill-switches`. |
| `list_killed` → `reason` | `str` | Operator-supplied reason (max 200 chars), scrubbed of trailing whitespace. | `kill_switch_admin.activate_kill` -> flag file. | None -- operator-authored text. |
| `list_killed` → `activated_at` | ISO-8601 str | When the flag was written. | Same. | None. |
| `list_killed` → `by` | `str` | Who activated the kill (default `"user"`). | Same. | None. |

Rolling constraint (Legal): the "kill-switch is active" copy in any
future UI or Telegram alert MUST cite the scope value verbatim (never
paraphrase "GLOBAL" as "everything" without also citing the reason
string).

### F011 — `agent/platform/kill_switch_admin.py` (Sprint 2)

Public accessors: `activate_kill(symbol=None, reason="", by="user") -> bool`,
`clear_kill(symbol=None) -> bool`,
`recent_events(limit=20) -> list[dict]`,
`events_log_path() -> Path`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `activate_kill` | `bool` (True) | Create the flag file for the scope. Raises `ValueError` on unknown symbol. Idempotent (re-activate updates reason). | `kill_switch_admin.activate_kill`. | Safety-control -- documented in F013's live-mode warning. |
| `clear_kill` | `bool` (True) | Remove the flag file for the scope. Idempotent (clear-of-empty still audit-logs a no-op). | `kill_switch_admin.clear_kill`. | Same. |
| `recent_events` → `ts` | ISO-8601 str | When the audit entry was appended. | `kill_switch_admin._append_event`. | None. |
| `recent_events` → `action` | `"activate"` \| `"clear"` | The operator action. | Same. | None. |
| `recent_events` → `scope` | `"GLOBAL"` \| supported symbol | The scope acted on. | Same. | Same as `list_killed → scope`. |
| `recent_events` → `reason` | `str` | Reason for activate; `""` or `"(no-op)"` for clear. | Same. | None -- operator-authored text. |
| `recent_events` → `by` | `str` | Operator identifier. | Same. | None. |
| `events_log_path` | `Path` | Path to `<config_dir>/kill_events.jsonl`. | `kill_switch_admin.events_log_path`. | None. |

Rolling constraint (Legal): the phrase "kill switches with hot-reload"
is only accurate to cite in marketing / documentation while
`kill_switches._read_state` continues to stat-check the directory on
every call. Any future perf optimisation that removes hot-reload must
strike the claim from copy.

## Audit hook (Sprint 2 — F010 implementation)

Sprint 2's F010 ships `scripts/check_claim_register.py` +
`scripts/git-hooks/pre-commit` +
`scripts/install_git_hooks.py`. The script walks every
`agent/platform/*.py` via AST, cross-references this file, and
fails on any unregistered public claim. A CI-equivalent test at
`tests/platform/test_claim_register_audit.py` runs the audit
programmatically so an unregistered claim fails the suite even
without the hook installed.
