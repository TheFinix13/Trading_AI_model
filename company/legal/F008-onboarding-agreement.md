# F008 -- Onboarding agreement (verbatim)

Legal review: 2026-07-21 (Sprint 1, F008 Onboarding UX lane).

The paragraph below is rendered verbatim inside the Welcome step of
`ONBOARDING_PAGE`. It is the only "By continuing you agree to..." text
the user has to acknowledge before proceeding. There is no separate
click-through EULA; single-user hobbyist install per D052.

## Verbatim agreement text

> By continuing you agree that Blue Lock Trading Co. is not a
> regulated broker or investment adviser, that nothing this
> platform outputs is financial advice, and that any losses
> incurred through connected broker accounts are your
> responsibility.

## Compliance notes (internal, not shown to user)

- Frames Blue Lock as a hobbyist platform (D019, D052 continuity).
- Explicitly names the user as the sole responsible party for
  losses on any connected broker account -- ties into F007's
  live-broker warning without duplicating it.
- Deliberately does NOT restate regulatory jurisdictions; the
  broker's own disclosures cover that.
- Deliberately does NOT collect any additional personal data during
  onboarding -- the only inputs are the fallback passphrase (never
  transmitted) + broker login/password (F007) + default pair choice.

## Change control

Any edit to the verbatim block above must:

1. Re-run `tests/platform/test_onboarding_page.py::TestLegalAgreement`.
2. Land as a new `D###` decision entry linking to the change diff.
3. Trigger a CPO re-review before the change ships.

Version: v1.0 (2026-07-21).
