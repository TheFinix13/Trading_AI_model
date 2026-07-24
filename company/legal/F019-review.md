# F019 — Legal review (broker-wizard recovery copy + missing-broker chip)

**Verdict:** APPROVED — no new claims; Brand copy sweep clean.

## Why this review fired

The F019 spec flags `legal_relevant: true`: it changes user-facing
copy on a public first-run surface (the broker wizard failure path)
and adds a new state chip to the onboarding completion screen and the
`/` hub. Per review-chain stage 8, publicly reachable copy changes get
a Legal pass with a Brand pre-sweep.

## Copy reviewed

1. **Non-Windows failure message**
   (`broker_connection._MT5_UNAVAILABLE_MESSAGE`): states the
   constraint ("MetaTrader 5 (MT5) -- the Windows-only trading
   terminal this platform connects through"), then BOTH recovery
   routes: Windows machine/VM (with the setup-guide path,
   `docs/RUNBOOK_demo_launch.md`) and finish-now-connect-later
   (`Settings > Broker`, `/settings/broker`). MT5 is explained in one
   clause; no unexplained jargon. No promise of trading outcomes, no
   performance language.
2. **Missing-broker chip** (onboarding completion + `/` hub):
   "Broker not connected yet — trading stays paused until a broker
   account is linked." Truthful state description; the word "paused"
   is accurate because no broker connection means no orders can be
   placed on any path. Links only to the in-product wizard.

## Brand sweep (banned words)

Neither new string contains "ensemble" or "aggregator". Tone matches
the plain-English register `company/brand/error_copy.md` uses.

## Claims check

No numbers, no performance-shaped fields, no new public accessors.
The chip reads the existing `broker_connected` boolean (F008,
registered). The I004 internal-token seam moves WHERE a config file is
read from; the fail-closed refusal is unchanged and no new field is
emitted — nothing to register.

## Rolling constraint

The failure copy's two recovery routes are load-bearing for the I003
closure: the dogfood cast asserts the substrings
`connect your broker later` and `/settings/broker`. Any future copy
edit must keep an actionable recovery path (both routes or better)
or re-open I003.

— Legal, 2026-07-24 (Sprint 3, F019)
