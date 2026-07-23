# Sellability gaps — what stands between today and "functional and sellable"

- **Date:** 2026-07-23
- **Authors:** CEO / CPO / Finance personas (D095)
- **Status:** living document — re-baseline at every sprint close
- **Companion:** `company/sprints/sprint-0-trust-foundation/BACKLOG.md`
  (Sprints 1–6 placeholders), `company/rd/intake/` (I003, I004)

## Honesty preamble

Today's state: a single-install, demo-MT5, localhost-first platform
with 1,540 green tests, four live-order safety gates that nothing is
wired to, one published research finding, and zero users who are not
also the CEO. That is a strong foundation and **not a sellable
product**. This memo lists every gap we know about, maps each to the
existing backlog where covered, and flags what is on NO backlog at
all — those flags are the real risk.

A numbering caveat up front: the backlog's placeholder F-numbers
(planned F006 "user accounts", etc.) diverged from what the executed
sprints actually shipped (actual F006 = install-token gate, F007 =
broker wizard, ... F016 = dogfood cast). Mappings below cite the
backlog sprint, not the stale placeholder IDs.

## The gap list

### 1. Multi-user accounts (install-token → real auth)

**Today:** one install token per deployment (F006/F009 as shipped:
token gate, rotation, session expiry, rate limit). There is no
concept of two users, no sign-up, no per-user data isolation — the
config dir IS the user.
**Backlog coverage:** planned in the Sprint 1 placeholder ("real
accounts, per-user data") but the executed sprint-1 consciously
shipped single-install access instead (D052 localhost-open). Sprint 5
adds 2FA on top of whatever auth exists.
**Verdict: PARTIALLY COVERED — needs its own charter.** The
install-token → real-auth migration (accounts, password reset,
per-user config-dir namespacing) is a bigger lift than the Sprint 1
placeholder implies and nothing currently schedules it.

### 2. Hosting or packaged installer

**Today:** `scripts/serve_platform.py` on localhost or the demo
Windows VM, run by hand. No installer, no container image, no update
channel. I004 (internal token pinned to repo-root `platform.toml`) is
this gap in miniature — the code still assumes it runs from a source
checkout.
**Backlog coverage:** Sprint 1 lists "DevOps (public hosting)" as a
standby-role activation; Sprint 4 has the status page (F027-planned).
**Verdict: NOT MEANINGFULLY COVERED.** No backlog item delivers "a
customer can run this without git". Packaging (installer or hosted
multi-tenant) needs a dedicated sprint; I004 folds into it.

### 3. Payments / licensing

**Today:** nothing. No pricing, no billing, no license enforcement.
The P006 test-customer pair (fake billing profiles) exists so the
flow can be dogfooded the day it lands.
**Backlog coverage:** Sprint 6 (pricing tiers, billing
infrastructure, trial + upgrade flow).
**Verdict: COVERED, LATE BY DESIGN.** Correctly sequenced after
compliance; no action now beyond keeping Sprint 6 real.

### 4. 30–90 day live shadow track record

**Today:** paper/replay evidence only. The `/performance` and
`/research` surfaces are honest about provenance, but a buyer will
ask "show me it running on a live feed for a quarter" and we cannot.
**Backlog coverage:** NONE — and it **cannot be sprinted**. This is
calendar time: 30–90 days of demo-MT5 shadow operation with the
existing kill/risk/approval gates on, logged and untouched.
**Verdict: NOT COVERED — start the clock.** The single cheapest
action in this memo: the sooner the shadow loop runs unattended on
the VM, the sooner the track-record window closes. Every week of
delay is a week added to the earliest possible sale date.

### 5. Support channel

**Today:** none. A stuck user has no path (I003 shows what a dead end
looks like at the first screen).
**Backlog coverage:** Sprint 4's planned "recovery paths / contact
support" item, Sprint 3's community forum, Support role activating in
Sprint 6.
**Verdict: PARTIALLY COVERED.** A minimal channel (support email +
in-product link on error states) is cheap and should ride along with
any Sprint 3/4 work rather than waiting for Sprint 6.

### 6. Legal claim signoff

**Today:** the claim register + pre-commit audit is live and green
(17 modules audited) — internally strong. But no external counsel has
reviewed the public claims, disclaimers, or ToS; there IS no ToS.
**Backlog coverage:** Sprint 5 is compliance-titled but its items are
technical (2FA, audit log, GDPR flows); external legal review and
terms-of-service are not listed anywhere.
**Verdict: NOT COVERED — flag.** Add "external legal review + ToS /
risk-disclosure pack" to the Sprint 5 charter when it opens. Selling
a trading product without this is not a growth hack, it's a lawsuit.

### 7. Penetration test before real money

**Today:** internal security reviews on tape per feature; no external
pen test.
**Backlog coverage:** Sprint 5 (external pen test before Sprint 6
launches paid tiers) — correctly gated.
**Verdict: COVERED.** Keep the ordering invariant: no paid tier, no
real-money enablement, before the pen-test report is on tape.

### 8. Live-order wiring sprint

**Today:** the four gates exist and are composition-tested
(`live_mode_enabled` AND `not is_killed` AND `can_send_order`
risk AND approval) — but **no pathway calls them**. D065's
scaffolding invariant was the right call for Sprint 2; it also means
the product's core promise ("it trades") is not yet wired even for
demo accounts.
**Backlog coverage:** NONE. Sprint 2 explicitly excluded it; no later
sprint picks it up.
**Verdict: NOT COVERED — the biggest product gap on this list.**
Needs its own charter with the safety hierarchy (escalation.md §5)
driving the gate order: demo-MT5 wiring first, shadow mode (gap 4)
running through it, real-broker wiring only after pen test (gap 7)
and legal signoff (gap 6).

## Priority reading (Finance persona)

Ranked by "blocks a sale the longest":

1. **Live-order wiring** (gap 8) — without it there is no product
   claim, only a dashboard.
2. **Shadow track record** (gap 4) — calendar-constrained; start
   now, runs in parallel with everything.
3. **Multi-user auth** (gap 1) — every other commercial feature
   (billing, support, GDPR) assumes it exists.

Gaps 2, 5, 6 are real but can trail those three; gaps 3 and 7 are
correctly sequenced already.

## The separate business/product-docs repo question

**Question (CEO):** should `company/` move to its own repo as the
business grows?

**Recommendation: DEFER until product #2 exists.** Grounds:

- `company/` is functionally coupled to the platform code today:
  the claim-register pre-commit audit walks `agent/platform/*.py`
  against `company/legal/claim_register.md`, and `/hq` + `/api/hq/org`
  read `company/ledger/company_state.json` and `company/handoffs/`
  at request time. Splitting the repo breaks both unless we build a
  sync mechanism — cost with no current benefit.
- Cross-product canonical protocols already have a home outside this
  repo (brain-box). Nothing is trapped here that a second product
  would need.
- The forcing function for a split is a second product wanting to
  share the company layer. When that exists, split along the seam
  that has by then proven natural.

Logged as a **parked decision** under D095 — revisit at product #2
kickoff or at Sprint 6 (whichever first).
