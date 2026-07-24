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

### F012 — `agent/platform/risk_budget.py` (Sprint 2)

Public accessors: `load_config() -> dict`, `save_config(payload) -> bool`,
`record_fill(symbol, strategy, pnl, ts=None) -> bool`,
`remaining_budget(scope="all", now=None) -> dict`,
`can_send_order(symbol, strategy, worst_case_loss, now=None) -> tuple[bool, str]`.

Public module constants: `DEFAULT_PER_DAY_MAX_LOSS`,
`DEFAULT_PER_SYMBOL_MAX_LOSS`, `DEFAULT_PER_STRATEGY_MAX_LOSS`,
`CONFIG_FILENAME`, `STATE_FILENAME`. Test-only helper marked
`# claim-exempt`: `reset_state`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `can_send_order` | `(bool, str)` | Third of four live-mode-off gates: True iff every per-day / per-symbol / per-strategy cap has enough headroom for the ask. | `risk_budget.can_send_order`. | Safety-control -- documented in F013's live-mode warning. |
| `remaining_budget` → `per_day` | `{cap, used, remaining}` | Today's UTC-day slice of realised loss vs configured per-day cap. | `risk_budget.remaining_budget`. | "Not investment advice" if surfaced in copy citing $-figures. |
| `remaining_budget` → `per_symbol` | `{symbol: {cap, used, remaining}}` | Per-symbol daily loss vs cap. | Same. | Same. |
| `remaining_budget` → `per_strategy` | `{strategy: {cap, used, remaining}}` | Per-source-agent daily loss vs cap. | Same. | Same. |
| `remaining_budget` → `per_symbol_default` | `float` | The default cap applied when a symbol has no explicit entry. | Same. | None -- meta. |
| `remaining_budget` → `per_strategy_default` | `float` | The default cap applied when a strategy has no explicit entry. | Same. | None -- meta. |
| `remaining_budget` → `as_of` | ISO-8601 str | Timestamp of the payload. | Same. | None -- meta. |
| `record_fill` | `bool` | Append a fill to `risk_state.jsonl`. Only losses (pnl < 0) count against the cap. | `risk_budget.record_fill`. | None -- state. |
| `load_config` / `save_config` | `dict` / `bool` | Read / atomic write of `<config_dir>/risk_budget.toml`. Missing / malformed → defaults. | `risk_budget.load_config`, `risk_budget.save_config`. | None -- configuration. |

Rolling constraint (Legal): any copy citing "3-tier max-loss cap"
MUST reference all three scopes (per-day / per-symbol / per-strategy)
verbatim -- collapsing to "daily loss limit" alone is inaccurate.

Asymmetric-cap constraint: `remaining_budget` records positive fills
but never restores headroom from a winning trade. Any future request
to make wins credit against the cap requires a Legal review because
it would materially change the safety-primitive claim.

### F012 — `agent/platform/broker_health.py` (Sprint 2)

Public accessors: `check_broker_health(user_alias, cache_ttl=None) -> dict`,
`is_broker_alive(user_alias) -> bool`,
`list_health_states() -> list[dict]`.

Public module constant: `CACHE_TTL_SECONDS`. Test-only helper marked
`# claim-exempt`: `clear_cache`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `check_broker_health` → `alive` | `bool` | Whether the last probe of this alias succeeded (or the cache says so if fresh). | `broker_health.check_broker_health`. | Live-broker warning if `account_type=="live"` shows. |
| `check_broker_health` → `reason` | `str` | Human-readable diagnostic. `"ok"` on success; `"no credentials"` when the alias isn't saved; MT5 error text otherwise. Password NEVER included. | Same. | Live-broker warning. |
| `check_broker_health` → `account_type` | `"demo"` \| `"live"` \| `"unknown"` \| None | Detected type from the probe. | Same. | Live-broker warning triggers when `"live"`. |
| `check_broker_health` → `server` | `str` \| None | MT5 server echoed back. | Same. | None. |
| `check_broker_health` → `checked_at` | ISO-8601 str | When the probe was recorded (cache-hit or fresh). | Same. | None. |
| `check_broker_health` → `cached` | `bool` | True iff this reading came from the 30-second cache. | Same. | None. |
| `is_broker_alive` | `bool` | Convenience wrapper. | `broker_health.is_broker_alive`. | Live-broker warning if the alias probes as `live`. |
| `list_health_states` | `list[dict]` | One row per configured alias; not-yet-probed aliases render `reason="not yet probed"`. | `broker_health.list_health_states`. | Same. |

Rolling constraint (Legal): the "30-second cache" claim is only
accurate while `CACHE_TTL_SECONDS = 30.0`. A future perf change that
raises the TTL must strike the claim from copy.

Password-never-surfaces constraint: `_sanitise_result` explicitly
whitelists the fields returned. A regression test in
`tests/platform/test_broker_health_module.py` pins that the raw
password does not appear in any field of the return payload.

### F013 — `agent/platform/approval_queue.py` (Sprint 2)

Public accessors: `submit(entry) -> str`,
`approve(approval_id, by="user") -> bool`,
`reject(approval_id, reason, by="user") -> bool`,
`timeout_reap(now=None) -> list[str]`,
`can_send_order(approval_id) -> bool`,
`get_entry(approval_id) -> dict | None`,
`list_entries(status="all", limit=100) -> list[dict]`,
`get_timeout_seconds() -> int`,
`set_timeout_seconds(seconds) -> None`,
`get_approved_ttl_seconds() -> int`,
`set_approved_ttl_seconds(seconds) -> None`,
`is_live_mode_enabled() -> bool`,
`set_live_mode(enabled) -> bool`,
`enable_ceremony(acknowledged, confirmation) -> tuple[bool, str]`,
`disable() -> bool`,
`can_send_live_order(entry, ...) -> tuple[bool, str]`.

Public module constants: `DEFAULT_TIMEOUT_SECONDS`,
`DEFAULT_APPROVED_TTL_SECONDS`, `STATUSES`, `AUDIT_FILENAME`,
`LIVE_MODE_NAMESPACE`, `LIVE_MODE_KEY`, `CONFIRMATION_PHRASE`.
Test-only helper marked `# claim-exempt`: `reset_state`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `is_live_mode_enabled` | `bool` | First of four live-mode-off gates. Default False. Any keyring error also returns False (fail-closed). | `approval_queue.is_live_mode_enabled`. | Live-mode warning renders when False -> True transition ceremony fires. |
| `set_live_mode` | `bool` | Persist the toggle. Trusts its `enabled` argument -- the enable-ceremony is the caller's guard. | `approval_queue.set_live_mode`. | Ceremony required on enable path (`/api/live-mode/enable`). |
| `enable_ceremony` | `(bool, str)` | Gate for `set_live_mode(True)` used by the HTTP API. True only when acknowledgement is True AND confirmation matches `ENABLE LIVE MODE` exactly. | `approval_queue.enable_ceremony`. | Verbatim `company/legal/live-mode-warning.md` rendered above the ceremony. |
| `disable` | `bool` | One-click OFF -- no ceremony (safety direction always frictionless). | `approval_queue.disable`. | None. |
| `submit` | `str` (approval_id) | Enqueue a proposal. Assigns id, validates payload, appends to JSONL audit. Sprint 2 does NOT call this from any live pathway (D065). | `approval_queue.submit`. | None -- internal endpoint gated by `[internal].token`. |
| `approve` | `bool` | Move pending -> approved. Idempotent (returns False on second call). Audit-logged. | `approval_queue.approve`. | Verbatim `company/legal/approval-queue-warning.md` renders above the pending list. |
| `reject` | `bool` | Move pending -> rejected with reason. Audit-logged. Rejected orders have zero market side-effect. | `approval_queue.reject`. | Same as approve. |
| `can_send_order` | `bool` | Fourth of four live-mode-off gates. True iff status == "approved". Auto-reaps stale pending AND stale approved (A005 freshness window) before answering. | `approval_queue.can_send_order`. | Composed into the invariant test. |
| `get_approved_ttl_seconds` / `set_approved_ttl_seconds` | `int` / None | A005 approved-freshness window (`[approvals] approved_ttl_seconds`, default 300 s). An `approved` entry past the window flips to `approval_expired` and every gate refuses it. | `approval_queue.get_approved_ttl_seconds`. | Freshness-window rolling constraint below. |
| `can_send_live_order` | `(bool, str)` | Composes ALL FOUR gates (live-mode + kill-switch + risk-budget + approval). The `test_live_mode_off_invariant` pin. | `approval_queue.can_send_live_order`. | Composed disclaimer of all four dependencies. |
| `timeout_reap` | `list[str]` | Expire stale pending entries (-> `timed_out`) AND stale approved entries (-> `approval_expired`, A005). Called under the hood by `can_send_order`, `list_entries`, and `_resolve` (so a late click can never approve an expired entry). | `approval_queue.timeout_reap`. | None -- state. |
| `list_entries` | `list[dict]` | Newest-first, optional status filter, `limit` cap. Returns copies (mutation-safe). | `approval_queue.list_entries`. | None -- state. |

Rolling constraint (Legal): the "5-minute timeout" claim is only
accurate while `DEFAULT_TIMEOUT_SECONDS == 300`. Any change (config
knob or default) must strike or update the claim wherever cited.

Freshness-window constraint (Legal, A005 2026-07-24): an approval is
only executable for `approved_ttl_seconds` (default 300 s) after the
click; past that it reads `approval_expired` with reason
`approved_ttl_expired` and `can_send_order` (hence
`can_send_live_order` and the F018 executor) refuses. Removing the
reap-in-`_resolve` call or the approved-TTL check would let an
hours-old approval fire an order -- that is a safety regression
pinned by `tests/security/test_live_mode_off_invariant.py`
(`TestStaleApprovalRefused`).

Ceremony-strictness constraint: `enable_ceremony` requires BOTH the
acknowledgement checkbox AND the exact confirmation phrase
`ENABLE LIVE MODE`. If either check is relaxed (e.g. case-insensitive
match, checkbox default true), that materially changes the safety
claim and requires a Legal review.

Fail-closed constraint: any keyring exception in
`is_live_mode_enabled` returns False. Removing the try/except would
allow a keyring outage to flip the default to True (unsafe) -- the
regression test in `tests/security/test_live_mode_off_invariant.py`
pins clean-install-is-off.

### F014 — `agent/platform/alerts.py` (Sprint 2)

Public accessors: `publish(event_type, payload, ts=None) -> dict`,
`subscribe(callback) -> str`,
`unsubscribe(subscription_id) -> bool`,
`recent(limit=100) -> list[dict]`.

Public module constants: `EVENT_TYPES`, `RING_BUFFER_CAPACITY`.
Test-only helper marked `# claim-exempt`: `reset`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `publish` | `dict` (event) | Push an event onto the in-process bus. Raises ValueError on unknown type or non-dict payload. Fires every subscriber synchronously; exceptions in one subscriber never break the others. Sprint 2 does NOT call this from any live pathway. | `alerts.publish`. | None -- transport. |
| `subscribe` / `unsubscribe` | `str` / `bool` | Register / remove a callback. Ids returned by subscribe are opaque tokens. | Same module. | None. |
| `recent` | `list[dict]` | Snapshot the ring buffer, newest first, up to `limit` entries. | Same. | None. |
| `EVENT_TYPES` | `tuple[str, ...]` | Whitelist of six event types the bus accepts. Adding a new type requires a Legal re-review (see rolling constraint). | Same. | None -- meta. |
| `RING_BUFFER_CAPACITY` | `int` (100) | Bounded ring buffer of most-recent events. Older events are dropped silently. | Same. | None -- meta. |

Rolling constraint (Legal): the seven event types
(`trade_fill`, `stop_hit`, `kill_switch_trip`, `risk_budget_breach`,
`approval_submitted`, `platform_down`, `watchdog_alert`) are the ONLY
event types this bus accepts. `watchdog_alert` was added in Sprint 2b
under this very constraint — re-review on tape at
`company/legal/F017-review.md` (D100). Adding a further event type
materially changes the alerts claim (e.g. "notifications on trade
fills") and requires a Legal re-review AND a per_event default in
`alerts_telegram`.

### F014 — `agent/platform/alerts_sse.py` (Sprint 2)

Public accessors:
`format_event(event) -> bytes`,
`sse_stream_response(handler, initial_history=None, heartbeat_seconds=15.0, max_seconds=None) -> None`.

Public module constants: `DEFAULT_HEARTBEAT_SECONDS`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `format_event` | `bytes` | Render an event dict as a valid SSE frame (`id: `, `event: `, `data: `). Malformed events fall back to safe defaults. | `alerts_sse.format_event`. | None -- transport. |
| `sse_stream_response` | None | Long-lived `text/event-stream` response. Auth is enforced by the caller (this module is transport-only). Broken pipes / connection resets clean up the subscription. | `alerts_sse.sse_stream_response`. | None. |
| `DEFAULT_HEARTBEAT_SECONDS` | `float` (15.0) | Idle-heartbeat interval that keeps proxies alive. | Same. | None -- meta. |

Rolling constraint (Legal): the "SSE frames" claim is only accurate
while `format_event` emits `id: `, `event: `, and `data: ` lines
delimited by a blank line (per the WHATWG SSE spec). Any wire-format
change requires the client (`ALERTS_PAGE` EventSource wiring) to
change with it and Legal to re-review the "browser-compatible live
stream" claim.

### F023 — `agent/platform/alerts.py` additions (Sprint 3: JSONL sink)

Public accessors: `configure_sink(enabled, path=None) -> None`,
`sink_is_enabled() -> bool`, `sink_path() -> Path`.

Public module constants: `SINK_FILENAME`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `configure_sink` | None | Toggle the opt-in JSONL sink (`[alerts] jsonl_sink`, literal `true` only; default OFF). Path override is a test seam. | `alerts.configure_sink`. | None -- transport config. |
| `sink_is_enabled` | `bool` | Whether the sink is currently on (default False -- memory-only F014 behaviour unchanged). | `alerts.sink_is_enabled`. | None. |
| `sink_path` | `Path` | Where the sink appends: `<config_dir>/alerts_log.jsonl` unless a test injected an override. | `alerts.sink_path`. | None. |
| `SINK_FILENAME` | `str` (`alerts_log.jsonl`) | The sink file name under the config dir. | Same. | None -- meta. |

Rolling constraint (Legal/Security, F023): the sink is best-effort
durability, NOT a guaranteed audit log — a sink write failure never
blocks or fails `publish()` (one warning per process, then quiet). Any
copy claiming "every alert is durably recorded" or similar is
inaccurate while this posture holds and requires a fresh Legal review.
The sink stores only what the bus already holds (event id/type/ts +
payload); Telegram bot tokens and chat ids never ride bus payloads, so
they can never land in the sink file.

### F023 — `agent/platform/alerts_sse.py` additions (Sprint 3: stream cap)

Public accessors: `set_max_streams(n) -> None`,
`get_max_streams() -> int`, `active_stream_count() -> int`.

Public module constants: `DEFAULT_MAX_STREAMS`, `RETRY_AFTER_SECONDS`.
Test-only helper marked `# claim-exempt`: `reset_streams_for_tests`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `set_max_streams` | None | Configure the concurrent-stream cap (`[alerts] max_sse_streams`); non-positive / non-numeric values are ignored so the cap never silently becomes unbounded. | `alerts_sse.set_max_streams`. | None -- transport config. |
| `get_max_streams` | `int` | The current cap (default 8). | `alerts_sse.get_max_streams`. | None. |
| `active_stream_count` | `int` | How many SSE streams are currently attached. | `alerts_sse.active_stream_count`. | None. |
| `DEFAULT_MAX_STREAMS` | `int` (8) | Default concurrent-stream cap. | Same. | None -- meta. |
| `RETRY_AFTER_SECONDS` | `int` (5) | `Retry-After` value on a 429 refusal. | Same. | None -- meta. |

Rolling constraint (Legal/Security, F023): past the cap a NEW stream
is refused with `429` + `Retry-After` — existing consumers are NEVER
evicted to admit a newcomer, and a refusal never subscribes to the
bus. Switching to an eviction policy would change the "live stream"
claim for already-connected clients and requires a fresh Legal review.

### F014 — `agent/platform/alerts_telegram.py` (Sprint 2; ops split 2026-07-24)

Public accessors:
`configure(bot_token, chat_id, per_event=None, enabled=True) -> None`,
`configure_ops(bot_token, chat_id, enabled=True) -> None`,
`load_config() -> dict`,
`is_enabled() -> bool`,
`ops_is_enabled() -> bool`,
`send(event, client=None) -> bool`,
`start(client=None) -> str | None`,
`stop() -> None`.

Public module constants: `TELEGRAM_API_BASE`, `OPS_EVENTS`,
`DUAL_ROUTE_EVENTS`. Test-only helpers marked `# claim-exempt`:
`reset`, `snapshot`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `configure` | None | Set the bridge config. Idempotent. Reuses the existing `[telegram]` bot_token / chat_id from `platform.toml` -- F014 does NOT add a new secret. | `alerts_telegram.configure`. | None. |
| `configure_ops` | None | Set the SEPARATE ops destination (`[alerts.telegram.ops]` -- its own bot_token + chat_id; CEO ops-split requirement 2026-07-24). Idempotent. | `alerts_telegram.configure_ops`. | None. |
| `load_config` | `dict` | Snapshot: `{enabled, bot_token_configured, chat_id_configured, per_event, ops}`. NEVER echoes the raw bot_token or chat_id (only boolean flags) -- for the ops block too. | `alerts_telegram.load_config`. | Bot-token-never-in-payload constraint. |
| `is_enabled` | `bool` | True iff enabled AND bot_token AND chat_id are all populated (fail-closed). | Same. | None. |
| `ops_is_enabled` | `bool` | Same fail-closed test for the ops destination (enabled AND ops bot_token AND ops chat_id). | Same. | None. |
| `send` | `bool` | Post a single event via httpx (mocked in tests), routed per the module matrix. Refuses when no destination is enabled, or the event's type is not in `per_event`. True when >= 1 destination accepted. | `alerts_telegram.send`. | None -- transport. |
| `start` / `stop` | `str \| None` / None | Attach / detach the bus subscription (attaches when EITHER destination is enabled). Idempotent. | Same. | None. |
| `TELEGRAM_API_BASE` | `str` | `https://api.telegram.org/bot` -- concatenated with the bot_token to form the sendMessage URL. | Same. | None -- meta. |
| `OPS_EVENTS` | `frozenset[str]` | Ops-class events (`watchdog_alert`) routed to the ops destination; FALLS BACK to primary when the ops block is absent/disabled (mis-channeled beats dropped). | Same. | None -- meta. |
| `DUAL_ROUTE_EVENTS` | `frozenset[str]` | Safety events (`kill_switch_trip`, `platform_down`) routed to BOTH destinations -- redundancy over deduplication. | Same. | None -- meta. |

Rolling constraint (Legal): `load_config()` returns
`bot_token_configured: bool` and `chat_id_configured: bool` -- NEVER
the raw string values. This pin EXTENDS to the `ops` sub-dict
(2026-07-24 ops split): `ops.bot_token_configured` /
`ops.chat_id_configured` are boolean flags only, and the ops token
never travels through `POST /api/alerts/config` (toml-managed). If a
future change echoes either token itself, that's a P0
secrets-in-transit regression and must strike the "Telegram routing
config" claim.

Fail-closed constraint: `is_enabled()` requires ALL of (enabled=True,
non-empty bot_token, non-empty chat_id); `ops_is_enabled()` applies
the identical rule to the ops block. Any leakage that would allow a
partially-configured bridge to fire would violate the
"user-controlled routing" claim.

Routing constraint (Legal, 2026-07-24 inline re-review): the routing
matrix is `OPS_EVENTS` -> ops (primary fallback), `DUAL_ROUTE_EVENTS`
-> both, everything else -> primary. The fallback direction is pinned
by test (`test_ops_event_falls_back_to_primary_when_ops_disabled`):
a disabled ops block must NEVER silently drop watchdog_alert. Any
change that lets an ops event drop when the ops block is
misconfigured is a safety regression and requires Legal re-review.

### F015 — `agent/platform/hq.py` (Org & Flow + HQ dashboard state)

Public accessors: `hq.hq_state(ledger_path) -> dict`,
`hq.org_state(ledger_path, handoffs_dir, handoff_limit) -> dict`.

Both read `company/ledger/company_state.json` (and, for `org_state`,
`company/handoffs/*.json`) and are strictly read-only. Missing /
malformed sources degrade to a shaped payload with
`unconfigured: true` — never a 500.

`hq_state()` fields (the `/api/hq/state` payload — internal company
dashboard, ledger-sourced):

| Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|
| `meta` | Company charter metadata (name, founded, mission, sprint id). | `hq.hq_state`. | None — internal dashboard; mission copy owned by Brand. |
| `roles` / `sprints` / `features` / `decisions` / `intake` / `experiments` / `blockers` | Ledger arrays passed through verbatim (decisions truncated to last 10 + `decisions_total`). | `hq.hq_state`. | None — internal state; any number promoted to marketing copy must cite the ledger entry. |
| `kpis` | KPI strip counters; recorded ledger values win, else derived at render (`_count_open_intake`, `_count_experiments_in_flight`, `_count_published_findings_30d`). | `hq.hq_state`. | None — internal metrics. |

`org_state()` fields (the `/api/hq/org` payload):

| Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|
| `tiers` | Roles grouped by tier (executive / design / engineering / business / executive-adjacent→"R&D"), each with `id`, `title`, `persona_name`, `active`, `current_task`, `reports_to`. | `hq.org_state` → `_group_roles_by_tier`. | Blue Lock IP notice covers persona names (same as F002). |
| `tiers[].roles[].reports_to` | Resolved report line: explicit ledger `reports_to` wins; tier default otherwise (design→cpo, engineering→cto, business→ceo, executive→ceo); CEO reports to nobody. | `_resolve_reports_to`. | None — org structure, not a performance claim. |
| `review_chain` | The 11 review-chain stages verbatim from `company/protocols/review-chain.md` (stage, owner, conditional, fires_when). | `_REVIEW_CHAIN_STAGES` module constant. | None — process description. |
| `handoffs` | Most recent N persona handoffs (`from_role`, `to_role`, `feature_id`, `timestamp`, `scope`, `verdict`, `file`) parsed from `company/handoffs/*.json`; malformed files skipped. | `_load_recent_handoffs`. | None — internal artefact metadata; notes bodies are NOT emitted. |
| `handoffs_total` / `roles_total` | Counts of parseable handoffs / ledger roles. | `hq.org_state`. | None — meta. |
| `generated_at` / `unconfigured` / `unconfigured_reason` | Payload timestamp + degradation flags. | `hq.org_state`. | None — meta. |

Rolling constraint (Legal): `org_state` deliberately emits handoff
METADATA only — the `notes` / `invariants_pinned` bodies of handoff
JSONs stay off the wire. Any future change that emits handoff notes
verbatim needs a Legal re-review (notes may reference unreleased
features or internal criticism). The review-chain stage list must
track `company/protocols/review-chain.md` — if the protocol gains or
drops a stage, `_REVIEW_CHAIN_STAGES` changes in the same commit.

### F017 — `agent/platform/watchdog.py` (Sprint 2b)

Public accessors: `watchdog.check_runtime_heartbeat(live_dir, now) -> dict`,
`watchdog.check_calendar_feed(cache_path, now) -> dict`,
`watchdog.check_broker_health(now) -> dict`,
`watchdog.check_risk_state(state_path, now) -> dict`,
`watchdog.check_intake_sla(intake_dir, now) -> dict`,
`watchdog.check_sprint_pulse(ledger_json_path, now) -> dict`,
`watchdog.check_ledger_drift(ledger_json_path, ledger_md_path, now) -> dict`,
`watchdog.run_check(check_id, ...) -> dict`,
`watchdog.run_checks(...) -> list[dict]`,
`watchdog.overall_status(results) -> str`,
`watchdog.publish_transitions(results, state_path, publisher) -> list[dict]`,
`watchdog.snapshot(...) -> dict`.

Public module constants: `CHECK_IDS`, `STATUSES`, `ALERT_EVENT_TYPE`,
`RUNTIME_WARN_SECONDS`, `RUNTIME_ALARM_SECONDS`,
`CALENDAR_WARN_SECONDS`, `CALENDAR_ALARM_SECONDS`,
`INTAKE_P0_ALARM_SECONDS`, `INTAKE_P1_WARN_SECONDS`,
`INTAKE_OPEN_WARN_SECONDS`, `SPRINT_QUIET_WARN_SECONDS`,
`FUTURE_SKEW_TOLERANCE_SECONDS`, `SNAPSHOT_CACHE_SECONDS`,
`STATE_FILENAME`, `REPO_ROOT`. Test-only helper marked
`# claim-exempt`: `reset_cache_for_tests`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `run_checks` / `run_check` | `list[dict]` / `dict` | The 7-check ops registry (`runtime_heartbeat`, `calendar_feed`, `broker_health`, `risk_state`, `intake_sla`, `sprint_pulse`, `ledger_drift`); each result is `{id, status: ok\|warn\|alarm\|na, detail, checked_at}`. Checks observe, never mutate; none may raise. | `watchdog.run_checks`. | None — ops state, not a performance claim. |
| `check_runtime_heartbeat` | `dict` | squad_live artefact freshness via `paper_loop.live_status`; warn > 5 min, alarm > 30 min, na when not configured. | `watchdog.check_runtime_heartbeat`. | None. |
| `check_calendar_feed` | `dict` | News cache `fetched_at` age; na absent, warn > 12 h, alarm > 48 h; corrupt cache alarms. | `watchdog.check_calendar_feed`. | None. |
| `check_broker_health` | `dict` | Reuses `broker_health.list_health_states()`; na when no aliases; warn when a probed alias is down. Never triggers a fresh probe. | `watchdog.check_broker_health`. | None. |
| `check_risk_state` | `dict` | `risk_state.jsonl` integrity (parseable, not future-dated); corruption alarms because it silently disables the F012 caps. | `watchdog.check_risk_state`. | None. |
| `check_intake_sla` | `dict` | Company-loop SLA: P0 untriaged > 4 h alarm, P1 untriaged > 7 d warn, any open item > 30 d warn. Emits item IDs + ages only — never intake body text. | `watchdog.check_intake_sla`. | Detail-string constraint (see F017 review). |
| `check_sprint_pulse` | `dict` | In-progress sprint with no ledger decision in 7 d → warn. | `watchdog.check_sprint_pulse`. | None. |
| `check_ledger_drift` | `dict` | Decision-count parity JSON vs MD; mismatch alarms (the Sprint-2-close drift bug, D076–D080). | `watchdog.check_ledger_drift`. | None. |
| `overall_status` | `str` | Worst status across the registry (na counts as ok). | `watchdog.overall_status`. | None — meta. |
| `publish_transitions` | `list[dict]` | State-change-only `watchdog_alert` publishing to the F014 bus; last-known state persists at `<config_dir>/watchdog_state.json`. Steady state publishes nothing. | `watchdog.publish_transitions`. | Transition-only constraint (see F017 review). |
| `snapshot` | `dict` | `{checks, overall, generated_at, cached}` with an in-process ~30 s cache; the `/api/watchdog/status` payload and the `/hq` strip's source. | `watchdog.snapshot`. | None. |

Rolling constraint (Legal): `watchdog_alert` payloads carry check id,
status, previous status, `recovered`, and a `detail` string built from
artefact metadata (ages, counts, IDs, filenames) ONLY. Piping file
contents into `detail` requires a fresh Legal review
(`company/legal/F017-review.md`).

Transition-only constraint: publishing on every poll instead of on
state changes kills the "alert stream you can trust not to nag" claim
and requires a Legal re-review — alert fatigue is a safety regression
for a trading product.

### F018 — `agent/platform/live_executor.py` (Sprint 2b)

Public accessors: `live_executor.Mt5OrderAdapter` (protocol),
`live_executor.FakeMt5OrderAdapter` (test double, exported for the
dogfood harness), `live_executor.RealMt5OrderAdapter` (Windows-only,
lazy MetaTrader5 import),
`live_executor.adapter_available() -> bool`,
`live_executor.load_executor_config(cfg=None) -> dict`,
`live_executor.is_enabled(cfg=None) -> bool`,
`live_executor.demo_guard(server, cfg=None) -> tuple[bool, str]`,
`live_executor.execute_approved(approval_id, adapter, cfg=None) -> dict`,
`live_executor.recent_executions(limit=20) -> list[dict]`,
`live_executor.executor_status(cfg=None) -> dict`.

Public module constants: `EXECUTIONS_FILENAME`,
`DEFAULT_MAX_VOLUME_LOTS`, `DEFAULT_ALLOWED_SERVER_PATTERNS`,
`EXECUTOR_STATES`. Test-only helper marked `# claim-exempt`:
`reset_state_for_tests`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `is_enabled` | `bool` | Gate #5. `[live_executor] enabled` in platform.toml; DEFAULT FALSE — a clean install refuses every execution. | `live_executor.is_enabled`. | Executor warning (`company/legal/executor-demo-warning.md`) renders on `/approvals`. |
| `demo_guard` | `(bool, str)` | DEMO-ONLY guard: requires the literal `demo_only = true` acknowledgement AND a connected-server name matching `allowed_server_patterns` (fnmatch, fail-closed on blank/missing/unmatched). Real-broker connections stay a hard NO (escalation.md §5). | `live_executor.demo_guard`. | Same warning. |
| `execute_approved` | `dict` | THE one caller of the four gates: re-runs `approval_queue.can_send_live_order` immediately before send (fresh, never cached), then demo guard, volume hard-cap, creds presence; single-use approvals; fill → `risk_budget.record_fill` + `trade_fill` alert; error → alert, NO auto-retry. Every attempt (refusals included) appends to `<config_dir>/executions.jsonl`. | `live_executor.execute_approved`. | Same warning + all four gate disclaimers compose. |
| `executor_status` | `dict` | `{enabled, demo_only_ack, allowed_server_patterns, max_volume_lots, broker_alias_configured, adapter_available, state: disabled\|not-on-windows\|ready, recent_executions}`. Never echoes credentials. | `live_executor.executor_status`. | None — state. |
| `recent_executions` | `list[dict]` | Last N rows of the executions audit JSONL, newest first. | `live_executor.recent_executions`. | None — state. |
| `load_executor_config` | `dict` | Normalised `[live_executor]` block (enabled, demo_only, patterns, max_volume_lots, broker_alias). | `live_executor.load_executor_config`. | None — meta. |
| `adapter_available` | `bool` | Whether MetaTrader5 is importable on this host (Windows-only package). | `live_executor.adapter_available`. | None — capability probe. |
| `Mt5OrderAdapter` / `RealMt5OrderAdapter` / `FakeMt5OrderAdapter` | protocol / impl / test double | The injectable MT5 seam: `connect`, `account_info`, `send_market_order`, `close_position`, `shutdown`. The real adapter imports MetaTrader5 lazily inside methods; credentials ride `broker_connection.load_credentials` and are never logged or echoed. | `live_executor`. | Same warning. |

Rolling constraint (Legal): the DEMO-ONLY guard is a safety claim.
Weakening it — accepting `demo_only` values other than literal true,
matching servers case-insensitively beyond the shipped patterns,
defaulting `enabled` to true, raising `max_volume_lots` default, or
caching the four-gate check across executions — requires a fresh
Legal review (`company/legal/F018-review.md`).

Single-use constraint: an approval that has been executed (or failed
execution) is consumed and can never fire a second order. Removing
the consumption marking would allow replay of a single human approval
into multiple orders — P0 regression.

### F021 — `agent/platform/players.py` additions (Sprint 3)

Public accessors added to the F002 module:
`players.form_guide(id, live_dir=None, n=20) -> dict | None`,
`players.gate_status(id, manifest_path=None) -> dict | None`,
`players.recent_decisions(id, live_dir=None, n=5) -> list | None`.

Public module constants: `MIN_FORM_SAMPLE` (= 5),
`FORM_WINDOW_DEFAULT` (= 20).

Provenance disclaimer (applies to every field below): shadow-paper
activity/quality metrics from the v2 squad's demo feed — NOT profit
performance. Every stat names its window explicitly
(`window_label`, e.g. "last 20 closed shadow-paper trades") and its
`sample_size`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `form_guide` | `tqs_series` | Rolling TQS values over the last-n closed shadow-paper trades (same rows `_stats_for_agent` counts), rendered as the sparkline. Quality metric, not profit. | `players.form_guide`. | Window label + sample_size in payload; page caption names the window. |
| `form_guide` | `win_rate_pct` | Rolling win-rate over the window. **Insufficient-sample rule (shared with F022): below `MIN_FORM_SAMPLE` (5) closed trades the value is `None` and the payload carries the literal note `insufficient sample (n=…)` — no percentage is ever rendered from a sub-5 sample.** | `players.form_guide`. | Same + the withheld-below-5 rule. |
| `form_guide` | `results` / `form` | W/L letters per close; `form` is the last-5 strip for the index cards. | `players.form_guide`. | Same. |
| `form_guide` | `net_pips_window`, `sample_size`, `window_label`, `insufficient_sample`, `min_sample`, `note` | Window bookkeeping — the honesty rails for everything above. | `players.form_guide`. | Same. |
| `gate_status` | `{status, reason, finding_url, finding_campaign, headline_stat}` | Current roster/gate state, display only. `benched` fires ONLY when the roster row's `finding_campaign` resolves to a PUBLISHED fail/dead verdict in the CPO manifest; `reason` and `headline_stat` are the manifest's own strings (never hardcoded prose), `finding_url` deep-links the published finding. Manifest missing/unpublished → honest `standby` fallback. | `players.gate_status`. | The negative is published copy already Legal-approved via the F003 manifest gate. |
| `recent_decisions` | `[{t, type, symbol, dir?, pnl_pips?, conviction?, exit_reason?, outcome?}]` | Last-n recorded rows with outcome fields (`win`/`loss` on closes). Extends the registered F002 `recent_activity` rows additively. | `players.recent_decisions`. | Same provenance as F002. |

Rolling constraint (Legal, shared F021/F022): the insufficient-sample
rule is a truthfulness claim — rendering any percentage from fewer
than `MIN_FORM_SAMPLE` closed trades, or lowering the constant,
requires a fresh Legal review.

### F020 — `agent/platform/highlights.py` (Sprint 3)

Public accessors: `highlights.match_report(day, live_dir=None) -> dict`,
`highlights.list_reports(n, live_dir=None) -> list[dict]`,
`highlights.trade_story(trade_id, live_dir=None) -> dict | None`,
`highlights.trade_id_for(close_row) -> str`.

Public module constants: `PROVENANCE_NOTE`, `QUIET_VOCAB`.

Provenance disclaimer (applies to EVERY field below): all numbers are
**shadow-paper activity/quality metrics** from the v2 squad's demo
feed — **NOT profit performance**. `PROVENANCE_NOTE` is echoed in
every payload and rendered as a banner on `/highlights`.

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `match_report` | `headline`, `timeline[].line`, `timeline[].pnl_pips`, `timeline[].r`, `timeline[].trade_id` | One day's narrative from recorded `events.jsonl` rows; deterministic template assembly, every number recomputable from the raw rows (test-pinned equality, not snapshot). Quiet days reuse the I002 `QUIET_VOCAB` phrase; missing tape → `empty=True`, never a fabricated day. | `highlights.match_report`. | PROVENANCE_NOTE in payload + page banner. |
| `match_report` | `full_time` (`shots`, `tackles`, `on_target`, `resolved`, `goals`, `misses`, `net_pips`, `net_r`, `mean_tqs`, `ticks_evaluated`) | Full-time stat line: counts of proposal / blocked / open / close / tick_summary rows and pip/R/TQS sums over closes. Activity + quality metrics only. | `highlights._full_time` via `match_report`. | Same. |
| `match_report` | `players[]` (`shots`, `tackled`, `opens`, `resolved`, `goals`, `net_pips`) | Per-agent involvement recomputed from the same rows; names via `players.roster_meta`. | `highlights._players_involved`. | Same. |
| `list_reports` | `[{day, quiet, headline, shots, goals, resolved, net_pips}]` | Newest-first index of match days present on tape; same recomputation as `match_report` per day. | `highlights.list_reports`. | Same. |
| `trade_story` | `{goal, pnl_pips, r, tqs, exit_reason, chapters[]}` | One closed trade retold (opening → shot → full time) by stitching the latest same-agent/same-symbol proposal and open rows at or before the close. All chapters are recorded evidence. | `highlights.trade_story`. | Same. |
| `trade_id_for` | `str` | Deterministic close-row id (`<agent>-<ts>-<sym>`) so click-through links stay stable. Not a number. | `highlights.trade_id_for`. | None — identifier. |

Rolling constraint (Legal): narrative strings are DETERMINISTIC
template assembly from recorded fields only — introducing generative
(LLM) retelling, or publishing any engagement/return-rate number for
the declared F020 hypothesis before its pre-registered experiment
reports, requires a fresh Legal review. Banned words ("ensemble",
"aggregator") stay out of every template string (Brand sweep pinned
by test).

### F022 — `agent/platform/leaderboard.py` (Sprint 3)

Public accessors: `leaderboard.standings(by, window_days, live_dir, now) -> dict`.

Public module constants: `PROVENANCE_NOTE`, `GROUPINGS`,
`WINDOWS_SUPPORTED`.

Provenance disclaimer (applies to EVERY field below): all numbers are
**internal squad standings on a demo feed** — shadow-paper
activity/quality metrics from the v2 squad, **NOT investment
performance**, and no comparison against any external benchmark is
implied. `PROVENANCE_NOTE` is echoed in every payload and rendered as
a banner on `/leaderboard`. Every payload names its computation
window (`window_label`, `window_days`) and its scope
(`total_closed`).

| Accessor | Return / Field | Human meaning | Code path | Disclaimer required? |
|---|---|---|---|---|
| `standings` | `rows[].closed_trades` / `rows[].wins` | Count of resolved `close` rows (numeric `pnl_pips`) per entity in the window — the same rows F002 `_stats_for_agent` counts as trades. Activity metric. | `leaderboard.standings`. | PROVENANCE_NOTE in payload + page banner. |
| `standings` | `rows[].cum_r` | Sum of recorded `r` across the entity's closes in the window (primary ranking key, descending). | `leaderboard.standings`. | Same. |
| `standings` | `rows[].mean_tqs` | Mean of recorded TQS across the entity's closes in the window (tie-break key); `None` when no close carries TQS. Quality metric, not profit. | `leaderboard.standings`. | Same. |
| `standings` | `rows[].win_rate_pct` | Fraction of the entity's windowed closes with `pnl_pips > 0`, 0–100. **Insufficient-sample rule (shared with F021): below `players.MIN_FORM_SAMPLE` (5) closed trades the value is `None` and the payload carries the literal note `insufficient sample (n=…)` — no percentage is ever rendered from a sub-5 sample.** | `leaderboard.standings`. | Same + the withheld-below-5 rule. |
| `standings` | `rows[].last_active` | Timestamp of the entity's most recent windowed close (verbatim from the recorded row). | `leaderboard.standings`. | None — recorded timestamp. |
| `standings` | `rows[].rank`, `rows[].entity`, `rows[].name`, `rows[].player_id`, `rows[].insufficient_sample`, `rows[].note` | Ordering + identity + honesty-rail bookkeeping. `player_id` deep-links the striker's `/players/:id` evidence page; ordering is deterministic (cum R desc, mean TQS tie-break, entity name for stability). | `leaderboard.standings`. | Blue Lock IP notice covers striker names (same as F002). |
| `standings` | `by`, `window_days`, `window_label`, `total_closed`, `min_sample`, `provenance`, `generated_at` | Payload meta: the grouping, the named window, the sample scope, and the shared F021/F022 sample floor. | `leaderboard.standings`. | None — meta / honesty rails. |

Rolling constraint (Legal, shared F021/F022 — same rule, same
constant): the insufficient-sample rule is a truthfulness claim.
Rendering any percentage from fewer than `players.MIN_FORM_SAMPLE`
closed trades, or lowering the constant, requires a fresh Legal
review.

Rolling constraint (Legal): rankings are single-install internal
standings. Any copy implying a comparison across users/installs or
against an external benchmark ("best squad", "top traders") is
inaccurate until the D115 auth migration ships cross-user ranking
under its own review — the "Internal squad standings" header framing
is load-bearing and pinned by test.

## Audit hook (Sprint 2 — F010 implementation)

Sprint 2's F010 ships `scripts/check_claim_register.py` +
`scripts/git-hooks/pre-commit` +
`scripts/install_git_hooks.py`. The script walks every
`agent/platform/*.py` via AST, cross-references this file, and
fails on any unregistered public claim. A CI-equivalent test at
`tests/platform/test_claim_register_audit.py` runs the audit
programmatically so an unregistered claim fails the suite even
without the hook installed.
