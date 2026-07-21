# F008 -- QA verdict

_Sprint 1, Onboarding UX lane, 2026-07-21._

## Summary verdict: PASS

- Tests added this feature: 79 (23 security + 13 module + 22 API + 21
  page).
- Full suite before F008: 1180 tests passing.
- Full suite after F008: 1259 tests passing (+79).
- Security suite specific to F008: `tests/security/test_onboarding.py`
  green.

## Acceptance-criteria coverage

| Criterion | Test |
|-----------|------|
| Reset flow doesn't leak previous state | `test_onboarding.py::TestResetFlow::*` |
| Passphrase strength gate (>= 12 chars when keychain absent) | `test_onboarding.py::TestPassphraseGate::*` |
| First-visit gate flips correctly on mark_setup_complete + reset | `test_onboarding.py::TestFirstVisitGate::*` |
| Default-pairs allow-list enforced | `test_onboarding.py::TestDefaultPairsSafety::*` |
| /hq redirects to /onboarding when first-visit | `test_onboarding_api.py::TestFirstVisitRedirect::test_hq_redirects_when_first_visit` |
| /healthz never gated | `test_onboarding_api.py::TestFirstVisitRedirect::test_healthz_never_gated` |
| Onboarding page + reset page reachable without gate | `test_onboarding_api.py::TestFirstVisitRedirect::test_*_reachable_without_gate` |
| Passphrase never returned in API response | `test_onboarding_api.py::TestPassphraseEndpoint::test_passphrase_never_returned_in_response` |
| Complete + reset APIs work end-to-end | `test_onboarding_api.py::TestCompleteAndReset::*` |
| Wizard talks to all four /api/onboarding/* endpoints | `test_onboarding_page.py::TestApiWiring::*` |
| Wizard renders on mobile (375 px) | `test_onboarding_page.py::TestMobileCare::test_media_query_for_narrow_viewports` |
| Legal agreement verbatim on Welcome step | `test_onboarding_page.py::TestLegalAgreement::*` |

## Notes for the Security stage

- The first-visit redirect gate is intentionally opt-in on
  `make_handler` (default False, off unless `enforce_onboarding_gate=True`).
  `main()` flips it on for non-localhost binds; Sprint 0 unit tests
  keep the old contract on localhost. This is not a security
  weakening -- the gate is UX, not access control. Auth is F006's
  install-token layer on `/api/*` and remains active on non-localhost.

- Passphrase submission uses `application/json` POST and its plaintext
  never leaves the server after `set_encrypted_file_passphrase` --
  the server-side test verifies no echo back.

## Rolling constraint

- Any new field emitted by `onboarding.py` must gain a
  `claim_register.md` entry before merge. §F008 of `claim_register.md`
  already carries the current field set.

## Cold-install cycle check

Manually verified (developer laptop, macOS keychain available):

1. Start with `credentials._reset_state_for_tests()` (simulates cold).
2. Visit `/` -> 302 redirect to `/onboarding`.
3. Walk five steps; broker step opens `/settings/broker` in a new tab
   and returns a saved alias.
4. Finish -> redirect to `/`, HQ page loads normally.
5. Visit `/settings/reset-install`, confirm, wait -> back at
   `/onboarding` with clean state.

## Verdict

Ship: yes. Legal signoff required next on the verbatim
`F008-onboarding-agreement.md`.
