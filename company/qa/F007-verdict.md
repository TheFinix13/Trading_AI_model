# F007 -- QA verdict

_Sprint 1, Broker Integrations lane, 2026-07-21._

## Summary verdict: PASS

- Tests added this feature: 89 (52 module/API + 21 wizard page + 16
  security).
- Full suite before F007: 1091 tests passing.
- Full suite after F007: 1180 tests passing (+89).
- Security suite specific to F007: `tests/security/test_broker_connection.py`
  green.

## Acceptance-criteria coverage

| Criterion | Test |
|-----------|------|
| Password never leaves the client except during the two POSTs | `test_broker_api.py::TestSaveEndpoint::test_save_round_trips` + `TestTestConnectionEndpoint::test_test_connection_short_circuits_when_mt5_unavailable` |
| Password never renders back into the DOM | `test_broker_wizard_page.py::TestPasswordFieldSafety::test_password_is_never_defaulted_in_html` |
| Password field carries `type=password` + `autocomplete=off` + `spellcheck=false` | `test_broker_wizard_page.py::TestPasswordFieldSafety::test_password_input_has_password_type` |
| Demo pre-selected by default | `test_broker_wizard_page.py::TestAccountTypeDefaults::test_demo_radio_selected_by_default` |
| Live requires checkbox + typed LIVE + Legal warning body | `test_broker_wizard_page.py::TestLiveConfirmationGate::*` |
| Server allow-list enforced at save-time | `test_broker_api.py::TestSaveEndpoint::test_save_rejects_disallowed_server` + `test_broker_connection.py::TestServerAllowList::*` |
| Rate limit on `test_connection` | `test_broker_connection.py::TestRateLimit::*` |
| Non-localhost install-token gate on `/api/broker/*` | `test_broker_api.py::TestBrokerGate::*` |
| Delete-only-your-own-alias invariant pinned | `test_broker_connection.py::TestDeleteAuthorisation::*` |
| Wizard renders on mobile (375px) | `test_broker_wizard_page.py::TestMobileCare::test_media_query_for_narrow_viewports` |

## Notes for the Security stage

- No real credentials in code, tests, docstrings, or handoff artefacts.
- Tests never surface a real MT5 login; the module short-circuits on
  macOS / Linux and the tests exploit that fact rather than mocking
  the SDK.
- `broker_connection.reset_rate_limiter()` is exposed for tests only;
  it does not leak into any user-facing surface.

## Rolling constraint

- Any new field emitted by `broker_connection.py` (test-connection
  result, list-aliases row) must gain a `claim_register.md` entry
  before merge.

## Verdict

Ship: yes. Legal signoff required next on the verbatim `live-broker-warning.md`.
