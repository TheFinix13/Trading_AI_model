# F007 -- Live broker warning (verbatim)

Legal review: 2026-07-21 (Sprint 1, F007 Broker Integrations lane).

The text below is served verbatim by `GET /api/broker/live-warning` and
rendered inside the F007 wizard's "You picked a live account" step. It
must appear before the user is allowed to check the acknowledgement box
and type `LIVE`.

## Verbatim warning text

> **You are about to connect a LIVE MetaTrader 5 account.**
>
> Live accounts trade with real money. Blue Lock Trading Co. is a
> single-user hobbyist trading platform. It is not a regulated broker,
> financial adviser, or investment product. Nothing this platform does
> constitutes financial advice.
>
> The Blue Lock v1 agent and the multi-agent squad can and do place
> orders on whatever broker account you connect. Losses on a live
> account are real, permanent, and your sole responsibility.
>
> Before continuing:
>
> - Confirm the MT5 login and server below match the LIVE account you
>   intend to use. If in doubt, click Back and pick Demo / Sandbox.
> - Confirm the broker's own risk disclosures (leverage, margin, spread,
>   swap) -- Blue Lock does not restate them.
> - Confirm you have set a maximum-loss stop on the broker side. The
>   platform's risk controls (`agent/risk/*`) are an additional layer,
>   not a replacement for broker-side limits.
>
> If any of those is not true, click Back. You can always come back
> once you are certain.

## Compliance notes (internal, not shown to user)

- The warning does not solicit trading, does not project returns, and
  does not compare Blue Lock to any product it is not.
- The reference to "single-user hobbyist trading platform" pins the
  legal frame CEO ratified in Sprint 0 (`decisions_log.md` D019).
- The last paragraph names the user as the sole responsible party and
  points to the broker's own risk disclosures rather than restating
  them -- avoids the accidental "we are a regulated adviser" impression.

## Change control

Any edit to the verbatim block above must:

1. Re-run `tests/platform/test_broker_api.py::TestLiveWarningEndpoint`.
2. Re-run the wizard end-to-end on desktop + mobile.
3. Land as a new `D###` decision entry linking to the change diff.

Version: v1.0 (2026-07-21).
