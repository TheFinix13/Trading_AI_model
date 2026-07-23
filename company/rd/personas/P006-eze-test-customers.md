---
id: P006
name: Amaka & Chidi Eze
archetype: test customer pair (fake billing-ready profiles)
goals:
  - Stand in for real paying customers in future payment-flow tests
  - Exercise two-people-one-household edge cases (shared device, separate accounts)
risk_tolerance: low
devices:
  - Shared iPad
  - Chidi's Android phone
tests:
  - onboarding
  - broker
  - kill_switch
fake_profile:
  amaka:
    full_name: "Amaka Eze (TEST CUSTOMER — NOT REAL)"
    email: "amaka.test@example.invalid"
    billing_address: "1 Test Way, Example City, EX 00000"
    card_last4: "0000"
    card_token: "tok_test_amaka_DO_NOT_CHARGE"
  chidi:
    full_name: "Chidi Eze (TEST CUSTOMER — NOT REAL)"
    email: "chidi.test@example.invalid"
    billing_address: "1 Test Way, Example City, EX 00000"
    card_last4: "4242"
    card_token: "tok_test_chidi_DO_NOT_CHARGE"
---

# P006 — Amaka & Chidi Eze (test customer pair)

There is no payment flow yet (see `company/strategy/sellability-gaps.md`),
but when one lands it must be tested with customer records that are
unambiguously fake. The Eze household is that record: two profiles,
`.invalid` emails (RFC 2606 — can never resolve), placeholder card
tokens, and names that literally say TEST CUSTOMER.

Until payments exist their journeys reuse the customer basics —
onboarding, broker wizard failure paths with fake credentials, and the
kill-switch round-trip — as a couple sharing one device, which is a
session-handling edge case the platform will eventually need to face.
