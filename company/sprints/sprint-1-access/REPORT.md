# Sprint 1 (Access) — Report

**Dates:** 2026-07-21 (single wall-clock day, honest-review flag)
**Target:** 2026-07-21 → ~2026-08-04, 11–13 day honest review
**Verdict:** **COMPLETE**
**Features shipped:** 3 / 3 (F006, F007, F008)

## Features shipped

| Id | Title | Route(s) | Backend module | Tests added | Commits |
|---|---|---|---|---|---|
| F006 | Encrypted credential storage + install-scoped auth | `/api/auth/status` + gate on `/api/*` non-localhost | `agent/platform/credentials.py`, `agent/platform/auth.py` | 117 | `fd7c142`, `48cee00` |
| F007 | MT5 broker connection wizard | `/settings/broker` + `/api/broker/*` | `agent/platform/broker_connection.py` | 89 | `e4f5b5e`, `e36faab` |
| F008 | First-time setup / onboarding flow | `/onboarding` + `/settings/reset-install` + `/api/onboarding/*` + first-visit redirect gate | `agent/platform/onboarding.py` | 79 | `d990f54`, + close-out |

## Test counts

| Layer | Before | After | Delta |
|---|---|---|---|
| Full suite (`pytest -q`) | 974 | 1259 | +285 |
| `tests/security/*` | 0 | 132 | +132 |
| `tests/platform/*` new API/module/page | 0 | 111 | +111 |
| Everything else | 974 | 1016 | +42 (docs/protocol tests) |

Security suite is populated for the first time this sprint. Sprint 0
had no `tests/security/` directory; the mandatory-security-tests rule
from D048 arrived as part of this sprint.

## Handoffs written

| Feature | Handoffs |
|---|---|
| F006 | 8 (cpo→ux, ux→ui, ui→cto, cto-review, backend-build, security-review, qa→legal, legal→ceo) |
| F007 | 9 (cpo→ux, ux→ui, ui→frontend, frontend-build, cto-review, backend-build, security-review, qa→legal, legal→ceo) |
| F008 | 7 (cpo→ux, ux→ui, ui→frontend, cto-review, backend-build, security-review, qa→legal, legal→ceo) |

Sprint-1-retro from Sprint 0 also on tape:
`company/handoffs/sprint-1-retro-cto-to-cpo.json`.

## Blockers surfaced

**None.** No `[BLOCKER][SPEND]`, no `[BLOCKER][ARCH]`, no
`[BLOCKER][TEST]`. Sprint ran to completion inside the given lane
structure.

## Security posture

Threat model exercised in this sprint (in order of criticality):

- **Secret-at-rest.** Broker password + install token both live in
  the OS keychain, with a Fernet-encrypted file fallback keyed by
  PBKDF2-SHA256-200k against a per-install salt. Pinned by
  `tests/security/test_credentials.py` (40 tests).
- **Log leakage.** `auth.RedactingFilter` mounted at server start,
  scrubs URL-safe blobs ≥ 24 chars + explicit `password=` / `token=`
  key-values + JSON `password` fields before formatting. Pinned by
  `tests/security/test_auth.py::TestRedactingFilter` (part of 52
  auth-security tests).
- **Access control.** F006 install-token gate on `/api/*`
  non-localhost. `X-Bluelock-Token` / `Authorization: Bearer` /
  cookie / `?token=` all accepted; constant-time compare via
  `hmac.compare_digest`. Pinned by
  `tests/platform/test_auth_api.py::TestInstallTokenGate` (13 tests).
- **Server allow-list.** F007 refuses to save credentials for a
  server outside `ALLOWED_SERVERS` (12 broker prefixes). Pinned by
  `tests/security/test_broker_connection.py::TestServerAllowList`.
- **Rate limit.** F007 `test_connection` allows 5/min per process.
  Pinned by `TestRateLimit::*`.
- **First-visit gate.** F008 HTML routes redirect to `/onboarding`
  when setup incomplete. Opt-in on `make_handler`; `main()` flips
  it on for non-localhost binds.
- **Reset flow.** F008 `reset_install` sweeps both `bluelock` and
  `broker_mt5` namespaces; verified empty by `list_keys` after.

Controls deferred (Sprint 2+):

- **Rate limit per install token.** Currently rate limit is
  process-wide; a per-token bucket lands with the multi-broker work.
- **Session expiry.** Install tokens don't rotate. Rotation lands
  when we introduce a real refresh cycle (Sprint 5+).
- **Automated Legal claim-register audit hook.** Registered in
  §6.3 of `review-chain.md` but hook script deferred to Sprint 2.

## Retro amendments landed FIRST

Per D047, four protocol improvements landed before feature work
began (commit `635c9bd`):

1. **§3.5 F005-first serialisation.** Shared UI primitives land
   first in the sprint.
2. **§4.2 Spec-lock validation.** Build stage diffs spec vs. on-disk
   state before starting; documents drift as `[SPEC-EXTENSION]`.
3. **§5.5 `_BASE_CSS_VERSION` tag.** Constant added in
   `agent/platform/pages.py`, pinned by
   `tests/platform/test_pages_shared_states.py::TestBaseCssVersion`.
4. **§6.3 Automated Legal claim-register audit.** New
   `company/legal/claim_register.md` seeded with F001/F002/F003
   fields; F006/F007/F008 fields registered at build time.

## Deviations from the spec

None as `[SPEC-EXTENSION]` decisions. Two intentional adjustments,
noted in the relevant handoffs but not requiring a spec-extension:

- The server field in `BROKER_WIZARD_PAGE` was originally sketched
  as a `<select>`; we shipped it as an `<input>` backed by a
  `<datalist>` of allow-listed prefixes. The user's exact server
  string is rarely one of the prefixes verbatim (e.g. `Exness-MT5Trial7`
  vs. prefix `Exness-`), so we let them type the full string with
  autocomplete assistance. Allow-list is still enforced server-side.
- The F008 first-visit redirect gate was originally sketched as
  always-on. We made it opt-in via `enforce_onboarding_gate` on
  `make_handler`, defaulting off, so Sprint 0 unit tests remain
  unchanged. `main()` flips it on for non-localhost binds. This is
  a UX gate, not an access-control gate; auth still lives in F006.

## HQ dashboard state at close

- `sprints[0]` (Trust Foundation): COMPLETE (was already so at
  sprint start).
- `sprints[1]` (Access): COMPLETE, actual_end 2026-07-21,
  feature_ids [F006, F007, F008].
- `features[]`: F006/F007/F008 each `current_stage: ship`, full
  10-stage history on tape.
- KPIs: `features_shipped_sprint_1: 3`, `features_total_sprint_1: 3`,
  `sprint_verdicts` carries the sprint's honest-review flag.

## Retro suggestions for Sprint 2 (Real-Trading)

1. **Trade approval mode.** Before Sprint 2 wires the live-trade
   path to real broker accounts, add a "review before send" mode
   where the platform surfaces the pending order for user
   confirmation. Ties into F007's live-broker warning as the moral
   layer.
2. **Risk UI parity.** `/performance` shows post-trade stats;
   Sprint 2 needs pre-trade risk (exposure, margin usage, worst-case
   loss on this order). Extend `agent/risk/*` to expose those
   without touching the live-path modules.
3. **Alerts.** F008 gets us onto the platform. Sprint 2 needs a
   way to tell the user "your trade closed / your stop hit / your
   platform is down" without them refreshing the tab. Cheapest
   version: server-sent events on `/api/alerts/stream`.
4. **Automate the claim-register audit.** Ship the hook script
   deferred from this sprint so §6.3 is enforced, not vibes-based.
5. **Sprint-length calibration.** The 1-day compression here is
   an artefact of the Executor persona owning every lane. A real
   3-persona split with independent scheduling would take longer.
   Sprint 2 should either continue with a single-Executor pattern
   (and adjust day_target down) or split for real (and expect
   day_target more like 11-13).

## Verdict: COMPLETE

All success criteria from the sprint brief met:

- [x] 3 P0 features shipped, all with mandatory security tests green.
- [x] Auth gate deployed on `/api/*` routes for non-localhost binds.
- [x] No plaintext credentials on disk, in logs, or in git.
- [x] Onboarding flow works end-to-end from clean install
      (cold-install cycle via `/settings/reset-install`).
- [x] Mobile pass on all new surfaces (`@media (max-width: 700px)`
      block in `_BROKER_CSS` + `_ONBOARDING_CSS`).
- [x] 974 → 1259 tests passing, security suite populated.
- [x] Ledger reflects COMPLETE, HQ dashboard shows 3/3 in ship column.
- [x] Zero commits off `product`.
- [x] Zero spend triggered.
- [x] No Cursor attribution anywhere.
